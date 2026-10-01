param(
  [string]$Root = "$HOME\Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL"
)

$ErrorActionPreference = "Stop"

$configPy = Join-Path $Root "config.py"
$ftConfig = Join-Path $Root "freqtrade_user_data\config.json"

if (!(Test-Path $configPy)) { throw "config.py not found: $configPy" }
if (!(Test-Path $ftConfig)) { throw "Freqtrade config not found: $ftConfig" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $configPy "$configPy.before-any-coin-$stamp.bak" -Force
Copy-Item $ftConfig "$ftConfig.before-any-coin-$stamp.bak" -Force

# ASTRA: keep the universe dynamic and remove the 10M turnover floor.
# This does NOT hardcode coin names. Any eligible Bybit USDT perpetual can enter
# the ranked universe; TOP_N only caps simultaneous scan load.
$s = Get-Content $configPy -Raw

$s = [regex]::Replace(
  $s,
  'DYNAMIC_UNIVERSE_TOP_N:\s*int\s*=\s*field\(default_factory=lambda:\s*max\(3,\s*min\(30,\s*int\(os\.getenv\("DYNAMIC_UNIVERSE_TOP_N",\s*"15"\)\)\)\)\)',
  'DYNAMIC_UNIVERSE_TOP_N: int = field(default_factory=lambda: max(3, min(30, int(os.getenv("DYNAMIC_UNIVERSE_TOP_N", "30")))))'
)

$s = [regex]::Replace(
  $s,
  'DYNAMIC_UNIVERSE_MIN_TURNOVER_USDT:\s*float\s*=\s*field\(default_factory=lambda:\s*float\(os\.getenv\("DYNAMIC_UNIVERSE_MIN_TURNOVER_USDT",\s*"10000000"\)\)\)',
  'DYNAMIC_UNIVERSE_MIN_TURNOVER_USDT: float = field(default_factory=lambda: float(os.getenv("DYNAMIC_UNIVERSE_MIN_TURNOVER_USDT", "0")))'
)

Set-Content -Path $configPy -Value $s -Encoding UTF8

# Freqtrade: remove BTC/ETH/SOL-only StaticPairList.
# Leading VolumePairList ignores pair_whitelist and builds from active markets
# matching stake currency, ranked by 24h quote volume.
$j = Get-Content $ftConfig -Raw | ConvertFrom-Json

$j.exchange.pair_whitelist = @()
$j.pairlists = @(
  [pscustomobject]@{
    method = "VolumePairList"
    number_assets = 30
    sort_key = "quoteVolume"
    min_value = 0
    refresh_period = 900
  },
  [pscustomobject]@{
    method = "PrecisionFilter"
  }
)

$j | ConvertTo-Json -Depth 100 | Set-Content -Path $ftConfig -Encoding UTF8

Write-Host ""
Write-Host "[OK] ASTRA dynamic universe: TOP-30, no hardcoded coin restriction" -ForegroundColor Green
Write-Host "[OK] ASTRA min turnover floor: 0" -ForegroundColor Green
Write-Host "[OK] Freqtrade: VolumePairList TOP-30, Static BTC/ETH/SOL whitelist removed" -ForegroundColor Green
Write-Host "[SAFE] No API keys changed. Live execution not enabled." -ForegroundColor Yellow
Write-Host ""

# Restart only if containers exist.
$names = @(docker ps -a --format "{{.Names}}")
if ($names -contains "myshka-astra") {
  docker restart myshka-astra | Out-Null
  Write-Host "[OK] restarted myshka-astra"
}
if ($names -contains "freqtrade") {
  docker restart freqtrade | Out-Null
  Write-Host "[OK] restarted freqtrade"
}

Write-Host ""
Write-Host "Open the dashboard and press Ctrl+F5. After the first scan, Universe should be > 3 if Bybit ticker discovery is healthy." -ForegroundColor Cyan
