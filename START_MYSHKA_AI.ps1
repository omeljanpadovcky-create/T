# Crypto Myshka local AI launcher - ASCII-only for Windows PowerShell 5.1
# No real trades are placed. Images are sent only to local Ollama.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Model = 'qwen2.5vl:3b'
$env:MYSHKA_VISION_MODEL = $Model
$env:MYSHKA_OLLAMA_URL = 'http://127.0.0.1:11434'

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host 'Ollama is missing. Install it from https://ollama.com/download/windows' -ForegroundColor Yellow
    exit 1
}
if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host 'Python 3.10+ is required: https://www.python.org/downloads/windows/' -ForegroundColor Yellow
    exit 1
}
try {
    $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
} catch {
    Write-Host 'Starting Ollama...' -ForegroundColor Cyan
    Start-Process -FilePath (Get-Command ollama).Source -ArgumentList 'serve' -WindowStyle Minimized
    Start-Sleep -Seconds 4
    try {
        $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
    } catch {
        Write-Host 'Ollama did not respond. Run ollama serve in another PowerShell window.' -ForegroundColor Red
        exit 1
    }
}
$installed = @($tags.models | ForEach-Object { $_.name })
if ($installed -notcontains $Model) {
    Write-Host "Vision model $Model is not installed (download may require several GB)." -ForegroundColor Yellow
    $answer = Read-Host 'Download the vision model now? (Y/N)'
    if ($answer -notin @('Y','y')) {
        Write-Host "Run: ollama pull $Model" -ForegroundColor Yellow
        exit 1
    }
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) { exit 1 }
}
Write-Host 'Starting Crypto Myshka Fast Analysis...' -ForegroundColor Green
Write-Host 'The local server will open the browser when ready.' -ForegroundColor Cyan
Write-Host 'Upload a chart screenshot to analyze it with local JEV.' -ForegroundColor Green
Write-Host 'Press Ctrl+C to stop. No real orders are placed.' -ForegroundColor Gray
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 (Join-Path $Root 'crypto_myshka\local_chart_server.py')
} else {
    & python (Join-Path $Root 'crypto_myshka\local_chart_server.py')
}
