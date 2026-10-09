# Crypto Myshka local AI: one PowerShell command, isolated copy, no secrets.
# Installs nothing without confirmation. Does not modify an existing T repository.
param(
    [switch]$SkipDownload,
    [string]$PythonExe = ''
)
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
function Refresh-SessionPath {
    # winget installers update user/machine PATH on disk, not in an existing PS session.
    $machine = [Environment]::GetEnvironmentVariable('Path','Machine')
    $user = [Environment]::GetEnvironmentVariable('Path','User')
    $segments = @($env:Path, $machine, $user) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $env:Path = $segments -join ';'
}
function Lookup-Python {
    Refresh-SessionPath
    $candidates = New-Object 'System.Collections.Generic.List[string]'

    # Search installed interpreters directly, without trusting Windows Store app aliases.
    $baseDirs = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        (Join-Path $env:ProgramFiles 'Python'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links')
    )
    if ($env:ProgramFiles) {
        $baseDirs += $env:ProgramFiles
    }
    foreach ($base in $baseDirs) {
        if (-not (Test-Path -LiteralPath $base -PathType Container)) { continue }
        if ($base -eq $env:ProgramFiles) {
            $dirs = @(Get-ChildItem -LiteralPath $base -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue)
        } else {
            $dirs = @(Get-ChildItem -LiteralPath $base -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)
        }
        foreach ($dir in $dirs) {
            $exe = Join-Path $dir.FullName 'python.exe'
            if (Test-Path -LiteralPath $exe -PathType Leaf) { $candidates.Add($exe) }
        }
        $direct = Join-Path $base 'python.exe'
        if (Test-Path -LiteralPath $direct -PathType Leaf) { $candidates.Add($direct) }
    }
    # Python's official installer registers its real executable even when
    # Windows PATH and the py launcher were not refreshed yet.
    foreach ($hive in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        if (-not (Test-Path -LiteralPath $hive)) { continue }
        foreach ($version in @(Get-ChildItem -LiteralPath $hive -ErrorAction SilentlyContinue)) {
            $install = Join-Path $version.PSPath 'InstallPath'
            if (-not (Test-Path -LiteralPath $install)) { continue }
            try {
                $key = Get-Item -LiteralPath $install -ErrorAction Stop
                $registered = $key.GetValue('ExecutablePath')
                if ($registered) { $candidates.Add([string]$registered) }
                $folder = $key.GetValue('')
                if ($folder) { $candidates.Add((Join-Path ([string]$folder) 'python.exe')) }
            } catch { }
        }
    }
    foreach ($alias in @('python.exe', 'python3.exe')) {
        foreach ($command in @(Get-Command $alias -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $candidates.Add([string]$command.Source) }
        }
    }
    foreach ($exe in @($candidates | Select-Object -Unique)) {
        try {
            # WindowsApps aliases may be executable stubs; actual interpreter must
            # pass both the version test AND return a real executable path.
            $out = & $exe -c 'import sys; print(sys.executable if sys.version_info >= (3,10) else "")' 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $resolved = ([string]($out | Select-Object -First 1)).Trim()
                if ($resolved -and (Test-Path -LiteralPath $resolved -PathType Leaf)) { return $resolved }
            }
        } catch { }
    }
    foreach ($launcher in @('py.exe','py')) {
        $command = Get-Command $launcher -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        foreach ($selector in @('-3.12','-3')) {
            try {
                $out = & $command.Source $selector -c 'import sys; print(sys.executable if sys.version_info >= (3,10) else "")' 2>$null
                if ($LASTEXITCODE -eq 0 -and $out) {
                    $resolved = ([string]($out | Select-Object -First 1)).Trim()
                    if ($resolved -and (Test-Path -LiteralPath $resolved -PathType Leaf)) { return $resolved }
                }
            } catch { }
        }
    }
    return $null
}
function Lookup-Ollama {
    Refresh-SessionPath
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
    if ($PythonExe) {
        if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
            Fail ('Specified Python executable does not exist: ' + $PythonExe)
        }
        try {
            $pythonVersion = & $PythonExe -c 'import sys; print(sys.version_info.major, sys.version_info.minor)' 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $pythonVersion) {
                Fail ('Specified Python executable cannot run: ' + $PythonExe)
            }
            $versionParts = ([string]$pythonVersion).Trim().Split(' ')
            if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 10)) {
                Fail ('Python 3.10+ required; got ' + $pythonVersion)
            }
            Write-Host ('Using explicit Python: ' + $PythonExe) -ForegroundColor Green
            return $PythonExe
        } catch {
            Fail ('Unable to launch specified Python executable: ' + $_.Exception.Message)
        }
    }
    $found = Lookup-Python
    if ($found) { return $found }
    Write-Host 'Python 3.10+ not found.' -ForegroundColor Yellow
    $ans = Read-Host 'Install Python 3.12 with winget? Y/N'
    if ($ans -notin @('Y','y')) { Fail 'Install Python 3.12 from https://www.python.org/downloads/windows/ and retry.' }
    $wg = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $wg) { Fail 'winget not available. Install Python manually and retry.' }
    # winget sometimes returns a nonzero code when Python is already installed
    # or the Store repository times out. Always re-check for the interpreter.
    $exitCode = 1
    try {
        & $wg.Source install --exact --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
        $exitCode = $LASTEXITCODE
    } catch {
        Write-Host ('winget reported: ' + $_.Exception.Message) -ForegroundColor Yellow
    }
    Refresh-SessionPath
    $found = Lookup-Python
    if ($found) {
        if ($exitCode -ne 0) {
            Write-Host ('winget returned ' + $exitCode + ', but an installed Python was found. Continuing.') -ForegroundColor Yellow
        }
        return $found
    }
    Write-Host ('winget exit code: ' + $exitCode) -ForegroundColor Yellow
    Write-Host 'Python diagnostics (send only the output, no API keys):' -ForegroundColor Cyan
    try { & $wg.Source list --id Python.Python.3.12 --exact --accept-source-agreements } catch {}
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) { try { & $launcher.Source -0p } catch {} }
    Fail 'Python is still not available. Install Python 3.12 from https://www.python.org/downloads/windows/ (check Add python.exe to PATH), then reopen PowerShell and rerun.'
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
    Refresh-SessionPath
    $found = Lookup-Ollama
    if (-not $found) { Fail 'Ollama installer finished, but executable is not yet visible. Reopen PowerShell and rerun the command.' }
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
