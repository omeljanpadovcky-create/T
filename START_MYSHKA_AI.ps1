# Run from a local clone of github.com/omeljanpadovcky-create/T
# Start only local AI analysis; does not place orders or send images to Telegram.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Model = 'qwen2.5vl:3b'
$env:MYSHKA_VISION_MODEL = $Model
$env:MYSHKA_OLLAMA_URL = 'http://127.0.0.1:11434'

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host 'Ollama не встановлена. Встанови з https://ollama.com/download/windows' -ForegroundColor Yellow
    exit 1
}
if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host 'Потрібен Python 3.10+ з https://python.org/downloads' -ForegroundColor Yellow
    exit 1
}
try {
    $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
} catch {
    Write-Host 'Запускаю Ollama...' -ForegroundColor Cyan
    Start-Process -FilePath (Get-Command ollama).Source -ArgumentList 'serve' -WindowStyle Minimized
    Start-Sleep -Seconds 4
    try {
        $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
    } catch {
        Write-Host 'Ollama не відповідає. Запусти ollama serve в іншому PowerShell.' -ForegroundColor Red
        exit 1
    }
}
$installed = @($tags.models | ForEach-Object { $_.name })
if ($installed -notcontains $Model) {
    Write-Host "Модель $Model ще не встановлена (кілька ГБ)." -ForegroundColor Yellow
    $answer = Read-Host 'Завантажити її зараз? (Y/N)'
    if ($answer -notin @('Y','y','Так','так')) {
        Write-Host "Виконай: ollama pull $Model" -ForegroundColor Yellow
        exit 1
    }
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) { exit 1 }
}
Write-Host 'Відкриваю Crypto Myshka Fast Analysis...' -ForegroundColor Green
Write-Host 'Локальний сервер сам відкриє браузер, коли буде готовий.' -ForegroundColor Cyan
Write-Host 'Завантаж фото: JEV проаналізує його локально через Ollama.' -ForegroundColor Green
Write-Host 'Ctrl+C зупиняє локальний сервер. Реальних угод не відкриває.' -ForegroundColor Gray
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 (Join-Path $Root 'crypto_myshka\local_chart_server.py')
} else {
    & python (Join-Path $Root 'crypto_myshka\local_chart_server.py')
}
