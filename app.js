const numberFormat = new Intl.NumberFormat("ko-KR");

function formatDate(value) {
  return `${value.slice(0, 4)}.${value.slice(4, 6)}.${value.slice(6, 8)}`;
}

function renderMatches(matches) {
  const body = document.querySelector("#results-body");
  body.replaceChildren(
    ...matches.map((match) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td><strong>${match.name}</strong><small>${match.ticker}</small></td>
        <td><span class="market ${match.market.toLowerCase()}">${match.market}</span></td>
        <td>${formatDate(match.limit_date)}</td>
        <td>${formatDate(match.signal_date)}</td>
        <td>${numberFormat.format(match.limit_close)}원</td>
        <td>${numberFormat.format(match.signal_close)}원</td>
        <td class="gap">+${match.gap_pct.toFixed(2)}%</td>
        <td>${numberFormat.format(match.volume)}</td>`;
      return row;
    }),
  );
}

async function loadResults() {
  const response = await fetch("reports/latest.json", { cache: "no-store" });
  if (!response.ok) throw new Error("결과 파일을 불러오지 못했습니다.");
  const data = await response.json();
  document.querySelector("#as-of").textContent = `${formatDate(data.as_of)} 확정 일봉 기준`;
  document.querySelector("#match-count").textContent = `${data.matches.length}종목`;
  document.querySelector("#criteria-list").replaceChildren(
    ...data.criteria.map((criterion) => {
      const item = document.createElement("li");
      item.textContent = criterion;
      return item;
    }),
  );

  if (data.matches.length) {
    renderMatches(data.matches);
    document.querySelector("#table-wrap").hidden = false;
  } else {
    document.querySelector("#empty-state").hidden = false;
  }
}

loadResults().catch((error) => {
  document.querySelector("#as-of").textContent = "데이터를 불러오지 못했습니다";
  document.querySelector("#empty-state").hidden = false;
  document.querySelector("#empty-state").innerHTML = `<strong>결과를 표시할 수 없습니다.</strong><p>${error.message}</p>`;
});
