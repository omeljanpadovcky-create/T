$ErrorActionPreference = 'Stop'
$repo = 'omeljanpadovcky-create/T'

function Read-PlainSecret([string]$label) {
    $secure = Read-Host $label -AsSecureString
    if ($secure.Length -eq 0) { return '' }
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host 'GitHub CLI (gh) не знайдено.' -ForegroundColor Yellow
    Write-Host 'Встанови один раз: winget install --id GitHub.cli' -ForegroundColor Cyan
    exit 1
}

gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Увійди в GitHub CLI. Відкриється стандартний login:' -ForegroundColor Yellow
    gh auth login
}

$items = @(
    @{ Name='TELEGRAM_BOT_TOKEN'; Label='Telegram Bot Token' },
    @{ Name='TELEGRAM_CHAT_ID'; Label='Telegram Chat ID' },

    @{ Name='BYBIT_API_KEY'; Label='Bybit API Key' },
    @{ Name='BYBIT_API_SECRET'; Label='Bybit API Secret' },

    @{ Name='BITGET_API_KEY'; Label='Bitget API Key' },
    @{ Name='BITGET_API_SECRET'; Label='Bitget API Secret' },
    @{ Name='BITGET_API_PASSPHRASE'; Label='Bitget API Passphrase' },

    @{ Name='GATE_API_KEY'; Label='Gate API Key' },
    @{ Name='GATE_API_SECRET'; Label='Gate API Secret' },

    @{ Name='OKX_API_KEY'; Label='OKX API Key' },
    @{ Name='OKX_API_SECRET'; Label='OKX API Secret' },
    @{ Name='OKX_API_PASSPHRASE'; Label='OKX API Passphrase' },

    @{ Name='KUCOIN_API_KEY'; Label='KuCoin API Key' },
    @{ Name='KUCOIN_API_SECRET'; Label='KuCoin API Secret' },
    @{ Name='KUCOIN_API_PASSPHRASE'; Label='KuCoin API Passphrase' },

    @{ Name='MEXC_API_KEY'; Label='MEXC API Key' },
    @{ Name='MEXC_API_SECRET'; Label='MEXC API Secret' },
    @{ Name='HTX_API_KEY'; Label='HTX API Key' },
    @{ Name='HTX_API_SECRET'; Label='HTX API Secret' },
    @{ Name='BINGX_API_KEY'; Label='BingX API Key' },
    @{ Name='BINGX_API_SECRET'; Label='BingX API Secret' },
    @{ Name='COINEX_API_KEY'; Label='CoinEx API Key' },
    @{ Name='COINEX_API_SECRET'; Label='CoinEx API Secret' },
    @{ Name='WHITEBIT_API_KEY'; Label='WhiteBIT API Key' },
    @{ Name='WHITEBIT_API_SECRET'; Label='WhiteBIT API Secret' },
    @{ Name='LBANK_API_KEY'; Label='LBank API Key' },
    @{ Name='LBANK_API_SECRET'; Label='LBank API Secret' },
    @{ Name='COINW_API_KEY'; Label='CoinW API Key' },
    @{ Name='COINW_API_SECRET'; Label='CoinW API Secret' },
    @{ Name='TOOBIT_API_KEY'; Label='Toobit API Key' },
    @{ Name='TOOBIT_API_SECRET'; Label='Toobit API Secret' },
    @{ Name='BITUNIX_API_KEY'; Label='Bitunix API Key' },
    @{ Name='BITUNIX_API_SECRET'; Label='Bitunix API Secret' },
    @{ Name='WEEX_API_KEY'; Label='WEEX API Key' },
    @{ Name='WEEX_API_SECRET'; Label='WEEX API Secret' },
    @{ Name='DIGIFINEX_API_KEY'; Label='DigiFinex API Key' },
    @{ Name='DIGIFINEX_API_SECRET'; Label='DigiFinex API Secret' },
    @{ Name='BITMART_API_KEY'; Label='BitMart API Key' },
    @{ Name='BITMART_API_SECRET'; Label='BitMart API Secret' }
)

Write-Host ''
Write-Host 'MYSHKA — завантаження API-ключів у GitHub Secrets' -ForegroundColor Cyan
Write-Host 'Enter на порожньому полі = пропустити. Значення на екрані не показуються.' -ForegroundColor DarkGray
Write-Host ''

foreach ($item in $items) {
    $value = Read-PlainSecret "$($item.Label) (Enter = пропустити)"
    if ([string]::IsNullOrWhiteSpace($value)) {
        Write-Host "Пропущено: $($item.Name)" -ForegroundColor DarkGray
        continue
    }

    $value | gh secret set $item.Name -R $repo
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Збережено: $($item.Name)" -ForegroundColor Green
    } else {
        Write-Host "Помилка: $($item.Name)" -ForegroundColor Red
    }

    $value = $null
}

Write-Host ''
Write-Host 'Готово. Ключі збережені як GitHub Actions Secrets і не потрапили в репозиторій.' -ForegroundColor Green
Write-Host 'MYSHKA Cloud підхопить підтримувані ключі на наступному запуску.' -ForegroundColor Cyan
