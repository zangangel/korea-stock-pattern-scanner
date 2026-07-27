from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

import pandas as pd


DATE_FMT = "%Y%m%d"
LIMIT_UP_RATIO = 1.295
MARCAP_URL = "https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet"


@dataclass(frozen=True)
class PatternMatch:
    ticker: str
    name: str
    market: str
    limit_date: pd.Timestamp
    signal_date: pd.Timestamp
    limit_close: int
    signal_close: int
    gap_pct: float
    volume: int


def parse_yyyymmdd(value: str) -> dt.date:
    return dt.datetime.strptime(value, DATE_FMT).date()


def yyyymmdd(value: dt.date | pd.Timestamp) -> str:
    if isinstance(value, pd.Timestamp):
        value = value.date()
    return value.strftime(DATE_FMT)


def ensure_year_data(year: int, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"marcap-{year}.parquet"
    if not path.exists():
        print(f"[INFO] downloading marcap {year} data", flush=True)
        urlretrieve(MARCAP_URL.format(year=year), path)
    return path


def load_marcap_window(as_of: dt.date, lookback_days: int, cache_dir: Path) -> pd.DataFrame:
    start = as_of - dt.timedelta(days=lookback_days)
    frames = []
    for year in range(start.year, as_of.year + 1):
        path = ensure_year_data(year, cache_dir)
        frames.append(pd.read_parquet(path))

    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"])
    mask = (df["Date"].dt.date >= start) & (df["Date"].dt.date <= as_of)
    df = df.loc[mask].copy()
    df = df[df["Market"].isin(["KOSPI", "KOSDAQ"])]
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    return df.sort_values(["Code", "Date"])


def scan_market(
    as_of: dt.date,
    lookback_days: int = 30,
    max_tickers: int | None = None,
    min_market_cap: int = 0,
    cache_dir: Path = Path(".cache/marcap"),
) -> tuple[list[PatternMatch], dt.date]:
    df = load_marcap_window(as_of, lookback_days, cache_dir)
    if df.empty:
        raise RuntimeError("No marcap rows were found for the requested date window.")

    latest = pd.Timestamp(df["Date"].max()).date()
    if min_market_cap > 0:
        latest_caps = df[df["Date"].dt.date == latest][["Code", "Marcap"]]
        keep = set(latest_caps[latest_caps["Marcap"].fillna(0) >= min_market_cap]["Code"])
        df = df[df["Code"].isin(keep)]

    results: list[PatternMatch] = []
    groups = list(df.groupby("Code", sort=False))
    if max_tickers is not None:
        groups = groups[:max_tickers]

    for ticker, history in groups:
        history = history.sort_values("Date").copy()
        if len(history) < 5:
            continue

        history["PrevClose"] = history["Close"].shift(1)
        history["LimitUp"] = history["Close"] >= history["PrevClose"] * LIMIT_UP_RATIO

        # The alert is generated after the third post-limit candle has closed.
        i = len(history) - 4
        if i < 1 or not bool(history.iloc[i]["LimitUp"]):
            continue

        limit_row = history.iloc[i]
        d1, d2, d3 = history.iloc[i + 1], history.iloc[i + 2], history.iloc[i + 3]
        limit_close = int(limit_row["Close"])

        bearish_bullish_bearish = (
            int(d1["Close"]) < int(d1["Open"])
            and int(d2["Close"]) > int(d2["Open"])
            and int(d3["Close"]) < int(d3["Open"])
        )
        above_limit_close = all(int(row["Close"]) > limit_close for row in (d1, d2, d3))
        if not (bearish_bullish_bearish and above_limit_close):
            continue

        signal_close = int(d3["Close"])
        results.append(
            PatternMatch(
                ticker=ticker,
                name=str(d3["Name"]),
                market=str(d3["Market"]),
                limit_date=pd.Timestamp(limit_row["Date"]),
                signal_date=pd.Timestamp(d3["Date"]),
                limit_close=limit_close,
                signal_close=signal_close,
                gap_pct=(signal_close / limit_close - 1.0) * 100,
                volume=int(d3["Volume"]),
            )
        )

    return sorted(results, key=lambda item: (item.gap_pct, item.volume), reverse=True), latest


def render_report(matches: list[PatternMatch], latest: dt.date) -> str:
    latest_label = yyyymmdd(latest)
    lines = [
        f"# 상한가 이후 음봉+양봉+음봉 관심 종목 ({latest_label} 확정 일봉 기준)",
        "",
        "조건: 상한가 다음 3거래일이 음봉, 양봉, 음봉이며 세 날 모두 상한가 당일 종가 위에서 마감.",
        "주의: 이 결과는 매매 추천이 아니라 영상 기법을 데이터로 필터링한 관심 종목 목록입니다.",
        "",
    ]

    if not matches:
        lines.append("오늘 조건에 맞는 종목이 없습니다.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| 종목 | 시장 | 코드 | 상한가일 | 신호일 | 상한가 종가 | 신호 종가 | 괴리율 | 신호일 거래량 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in matches:
        lines.append(
            f"| {item.name} | {item.market} | {item.ticker} | {yyyymmdd(item.limit_date)} | "
            f"{yyyymmdd(item.signal_date)} | {item.limit_close:,} | {item.signal_close:,} | "
            f"{item.gap_pct:.2f}% | {item.volume:,} |"
        )
    return "\n".join(lines) + "\n"


def render_json(matches: list[PatternMatch], latest: dt.date) -> str:
    """Return the same scan result in a format the web dashboard can read."""
    payload = {
        "as_of": yyyymmdd(latest),
        "strategy": "상한가 이후 음봉-양봉-음봉",
        "criteria": [
            "상한가 당일 종가가 전일 종가 대비 29.5% 이상 상승",
            "이후 3거래일이 음봉, 양봉, 음봉 순서",
            "세 거래일 모두 상한가 당일 종가보다 높게 마감",
        ],
        "matches": [
            {
                "ticker": item.ticker,
                "name": item.name,
                "market": item.market,
                "limit_date": yyyymmdd(item.limit_date),
                "signal_date": yyyymmdd(item.signal_date),
                "limit_close": item.limit_close,
                "signal_close": item.signal_close,
                "gap_pct": round(item.gap_pct, 2),
                "volume": item.volume,
            }
            for item in matches
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="상한가 이후 음봉+양봉+음봉 패턴 스캐너")
    parser.add_argument("--date", help="조회 기준일 YYYYMMDD. 생략하면 오늘 날짜를 사용합니다.")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-tickers", type=int)
    parser.add_argument("--min-market-cap", type=int, default=0, help="최소 시가총액(원). 0이면 전체 검색")
    parser.add_argument("--cache-dir", default=".cache/marcap")
    parser.add_argument("--out", default="reports/latest.md")
    parser.add_argument("--json-out", default="reports/latest.json")
    args = parser.parse_args()

    as_of = parse_yyyymmdd(args.date) if args.date else dt.date.today()
    matches, latest = scan_market(
        as_of=as_of,
        lookback_days=args.lookback_days,
        max_tickers=args.max_tickers,
        min_market_cap=args.min_market_cap,
        cache_dir=Path(args.cache_dir),
    )
    report = render_report(matches, latest)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    json_out_path = Path(args.json_out)
    json_out_path.parent.mkdir(parents=True, exist_ok=True)
    json_out_path.write_text(render_json(matches, latest), encoding="utf-8")
    print(report)
    print(f"Saved: {out_path.resolve()}")
    print(f"Saved: {json_out_path.resolve()}")


if __name__ == "__main__":
    main()
