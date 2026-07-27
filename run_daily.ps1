$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReportPath = Join-Path $ProjectRoot "reports\latest.md"
$LogPath = Join-Path $ProjectRoot "reports\last-run.log"

Set-Location $ProjectRoot
python .\scanner.py --out $ReportPath *>&1 | Tee-Object -FilePath $LogPath

$Content = Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8
$MatchCount = ([regex]::Matches($Content, '^\| .+ \| (KOSPI|KOSDAQ) \|', 'Multiline')).Count
$Title = "Korea stock pattern scanner"
$Message = if ($MatchCount -eq 0) { "No matching stocks today. See reports\latest.md." } else { "$MatchCount matching stocks found. See reports\latest.md." }

try {
    Add-Type -AssemblyName System.Windows.Forms
    $Notification = New-Object System.Windows.Forms.NotifyIcon
    $Notification.Icon = [System.Drawing.SystemIcons]::Information
    $Notification.BalloonTipTitle = $Title
    $Notification.BalloonTipText = $Message
    $Notification.Visible = $true
    $Notification.ShowBalloonTip(10000)
    Start-Sleep -Seconds 3
    $Notification.Dispose()
} catch {
    Write-Host "$Title - $Message"
}
