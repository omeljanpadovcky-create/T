# Crypto Myshka local AI: one PowerShell command, isolated copy, no secrets.
# Installs nothing without confirmation. Does not modify an existing T repository.
param([switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$HomeDir = Join-Path $env:LOCALAPPDATA 'CryptoMyshka-Easy'
$BaseUrl = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/'
$Model = 'qwen2.5vl:3b'
$env:MYSHKA_VISION_MODEL = $Model
$env:MYSHKA_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:PYTHONUTF8 = '1'

function Fail($message) {
    Write-Host ('ERROR: ' + $message) -ForegroundColor Red
    throw $message
}
function Lookup-Python {
    foreach ($exe in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'),
        'python.exe'
    )) {
        try {
            $resolved = (Get-Command $exe -ErrorAction Stop).Source
            $out = & $resolved -c 'import sys; print(sys.executable if sys.version_info >= (3,10) else "")' 2>$null
            if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path $out.Trim())) { return $out.Trim() }
        } catch {}
    }
    try {
        $py = (Get-Command py.exe -ErrorAction Stop).Source
        $out = & $py -3 -c 'import sys; print(sys.executable if sys.version_info >= (3,10) else "")' 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path $out.Trim())) { return $out.Trim() }
    } catch {}
    return $null
}
function Lookup-Ollama {
    $found = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    foreach ($exe in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
        (Join-Path $env:ProgramFiles 'Ollama\ollama.exe')
    )) {
        if (Test-Path $exe) { return $exe }
    }
    return $null
}
function Get-OllamaTags {
    try {
        return Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
    } catch { return $null }
}
function Ensure-Python {
    $found = Lookup-Python
    if ($found) { return $found }
    Write-Host 'Python 3.10+ not found.' -ForegroundColor Yellow
    $ans = Read-Host 'Install Python 3.12 with winget? Y/N'
    if ($ans -notin @('Y','y')) { Fail 'Install Python 3.12 from https://www.python.org/downloads/windows/ and retry.' }
    $wg = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $wg) { Fail 'winget not available. Install Python manually and retry.' }
    & $wg.Source install --exact --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { Fail 'Python installer failed. Check winget output above.' }
    $found = Lookup-Python
    if (-not $found) { Fail 'Python installed but Windows terminal cannot find it yet. Reopen PowerShell and rerun the same command.' }
    return $found
}
function Ensure-Ollama {
    $found = Lookup-Ollama
    if ($found) { return $found }
    Write-Host 'Ollama is needed to analyze chart screenshots locally.' -ForegroundColor Yellow
    $ans = Read-Host 'Install Ollama from winget? Y/N'
    if ($ans -notin @('Y','y')) { Fail 'Install https://ollama.com/download/windows/ and rerun.' }
    $wg = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $wg) { Fail 'winget not found. Install Ollama manually and retry.' }
    & $wg.Source install --exact --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { Fail 'Ollama installation failed. Check winget output.' }
    $found = Lookup-Ollama
    if (-not $found) { Fail 'Ollama installed but executable is not visible yet. Reopen PowerShell and rerun.' }
    return $found
}

Write-Host ''
Write-Host '================ Crypto Myshka AI ================' -ForegroundColor Cyan
Write-Host 'Separate local install. Research-only; NO REAL TRADES.' -ForegroundColor Yellow
Write-Host 'GitHub Pages does NOT run the AI. This starts your own server.' -ForegroundColor Yellow
Write-Host ''

$Python = Ensure-Python
$OllamaExe = Ensure-Ollama
Write-Host ('Python: ' + $Python) -ForegroundColor Green
Write-Host ('Ollama: ' + $OllamaExe) -ForegroundColor Green

if (-not $SkipDownload) {
    $Files = @(
        'myshka-app.html',
        'myshka.webmanifest',
        'myshka-sw.js',
        'app/myshka.js',
        'app/myshka.css',
        'app/myshka-icon.svg',
        'crypto_myshka/local_chart_server.py',
        'crypto_myshka/data/youtube_live.json',
        'crypto_myshka/data/pair_reports.json',
        'crypto_myshka/data/youtube_analysts.json'
    )
    Write-Host 'Downloading the latest public application files...' -ForegroundColor Cyan
    foreach ($rel in $Files) {
        $dest = Join-Path $HomeDir $rel.Replace('/', [IO.Path]::DirectorySeparatorChar)
        $dir = Split-Path -Parent $dest
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $temporary = $dest + '.tmp'
        try {
            Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + $rel) -OutFile $temporary -TimeoutSec 40
            Move-Item -LiteralPath $temporary -Destination $dest -Force
        } catch {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            if (-not (Test-Path -LiteralPath $dest)) { Fail ('Cannot download required file: ' + $rel) }
            Write-Host ('Using last saved copy: ' + $rel) -ForegroundColor Yellow
        }
    }
}

$main = Join-Path $HomeDir 'crypto_myshka\local_chart_server.py'
if (-not (Test-Path -LiteralPath $main)) { Fail 'AI server was not downloaded.' }
$tags = Get-OllamaTags
if (-not $tags) {
    Write-Host 'Starting local Ollama server...' -ForegroundColor Cyan
    Start-Process -FilePath $OllamaExe -ArgumentList 'serve' -WindowStyle Minimized
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 2
        $tags = Get-OllamaTags
        if ($tags) { break }
    }
    if (-not $tags) { Fail 'Ollama does not respond on port 11434. Check Windows firewall and Ollama.' }
}

$names = @($tags.models | ForEach-Object { $_.name })
if ($names -notcontains $Model) {
    Write-Host ('Vision model ' + $Model + ' is not downloaded. It needs several GB and may run slowly on older PCs.') -ForegroundColor Yellow
    $answer = Read-Host 'Download vision model now? Y/N'
    if ($answer -notin @('Y','y')) { Fail ('To enable the model later run: ollama pull ' + $Model) }
    & $OllamaExe pull $Model
    if ($LASTEXITCODE -ne 0) { Fail 'Vision model download failed. Run the same command again.' }
}

# Only one listener on this port, never kill other processes or touch another repository.
$port = 18765
try {
    $existing = Invoke-RestMethod -Uri ('http://127.0.0.1:'+$port+'/api/chart-health') -TimeoutSec 2
    if ($existing.ready) {
        Write-Host 'Local JEV is already running; opening its browser page.' -ForegroundColor Green
        Start-Process ('http://127.0.0.1:'+$port+'/myshka-app.html#analysis')
        return
    }
    Fail 'Port 18765 already serves another app or an unhealthy JEV. Stop the old server and retry.'
} catch {
    if ($_.Exception.Message -like '*already serves*') { throw }
}
Write-Host ''
Write-Host 'Starting LOCAL JEV. Keep this window open.' -ForegroundColor Green
Write-Host 'Open http://127.0.0.1:18765/myshka-app.html#analysis' -ForegroundColor Green
Write-Host 'Do NOT use the GitHub Pages link for local screenshot analysis.' -ForegroundColor Yellow
Write-Host 'Press Ctrl+C to stop. No broker orders are sent.' -ForegroundColor Cyan
Push-Location $HomeDir
try {
    & $Python $main
} finally {
    Pop-Location
}
