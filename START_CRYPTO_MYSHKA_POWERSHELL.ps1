# CryptoMyshka LIVE - Windows PowerShell one-time setup and 15s local watcher.
# Uses a separate folder under LocalAppData. Does not change GitHub or existing folders.
param(
    [ValidateRange(15,3600)]
    [int]$FrameInterval = 60,
    [switch]$Refresh
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}

function Find-UsablePython {
    $candidatePaths = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe')
    )
    foreach ($candidate in $candidatePaths) {
        if (Test-Path -LiteralPath $candidate) {
            try {
                $version = & $candidate -c 'import sys; print(sys.version_info.major,sys.version_info.minor)' 2>$null
                if ($LASTEXITCODE -eq 0 -and $version) { return $candidate }
            } catch {}
        }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($selector in @('-3.12','-3')) {
            try {
                $resolved = & $py.Source $selector -c 'import sys; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved.Trim())) {
                    return $resolved.Trim()
                }
            } catch {}
        }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        try {
            $resolved = & $python.Source -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved.Trim())) {
                return $resolved.Trim()
            }
        } catch {}
    }
    return $null
}

function Ensure-Python {
    $found = Find-UsablePython
    if ($found) { return $found }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Python is not installed and winget is missing. Install Python 3.12 from https://www.python.org/downloads/windows/ and start again.'
    }
    Write-Host '[1/5] Python missing. Installing Python 3.12 using winget ...' -ForegroundColor Cyan
    & $winget.Source install --exact --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw 'winget could not install Python. Install Python 3.12 manually and run this command again.'
    }
    $found = Find-UsablePython
    if (-not $found) {
        throw 'Python was installed, but not detected in this terminal. Close PowerShell, reopen it and run the same command again.'
    }
    return $found
}

function Download-Project([string]$projectFolder, [bool]$replaceExisting) {
    if ((Test-Path -LiteralPath (Join-Path $projectFolder 'crypto_myshka\rapid_live_watch.py')) -and (-not $replaceExisting)) {
        Write-Host '[2/5] Reusing the previously downloaded project. No files were replaced.' -ForegroundColor DarkCyan
        return
    }
    if ((Test-Path -LiteralPath $projectFolder) -and $replaceExisting) {
        # Preserve old folders and snapshots. Never delete an existing project.
        $projectFolder = $projectFolder + '-updated-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
        $script:activeProject = $projectFolder
        Write-Host ('Keeping the older copy; new files go into ' + $projectFolder) -ForegroundColor Yellow
    } elseif (Test-Path -LiteralPath $projectFolder) {
        throw ('The project destination exists but is incomplete: ' + $projectFolder + '. Rename this folder and retry.')
    }
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('myshka-' + [Guid]::NewGuid().ToString('N'))
    $archive = $tempRoot + '.zip'
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    try {
        Write-Host '[2/5] Downloading the public GitHub repository (first setup only) ...' -ForegroundColor Cyan
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/omeljanpadovcky-create/T/archive/refs/heads/main.zip' -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $tempRoot -Force
        $downloaded = Join-Path $tempRoot 'T-main'
        if (-not (Test-Path -LiteralPath (Join-Path $downloaded 'crypto_myshka\rapid_live_watch.py'))) {
            throw 'The downloaded archive has no rapid LIVE watcher. Please check the GitHub repository.'
        }
        Move-Item -LiteralPath $downloaded -Destination $projectFolder
    } finally {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Find-FreePort {
    foreach ($port in 8765..8775) {
        $listener = $null
        try {
            $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
            $listener.Start()
            return $port
        } catch {
        } finally {
            if ($listener) { $listener.Stop() }
        }
    }
    throw 'Could not find a free local dashboard port between 8765 and 8775.'
}

Write-Host ''
Write-Host 'CryptoMyshka LIVE | local YouTube check every 15 seconds' -ForegroundColor Green
Write-Host 'Read-only monitor. No real-money trades. Press Ctrl+C to stop.' -ForegroundColor Yellow
Write-Host ''
Write-Host '[1/5] Checking Python ...' -ForegroundColor Cyan
$python = Ensure-Python

$installRoot = Join-Path $env:LOCALAPPDATA 'CryptoMyshka-LIVE'
New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
$project = Join-Path $installRoot 'project'
$script:activeProject = $project
Download-Project $project ([bool]$Refresh)
$project = $script:activeProject

$venvFolder = Join-Path $installRoot '.venv'
$venvPython = Join-Path $venvFolder 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host '[3/5] Creating a private Python environment ...' -ForegroundColor Cyan
    & $python -m venv $venvFolder
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
} else {
    Write-Host '[3/5] Existing Python environment found.' -ForegroundColor DarkCyan
}

Write-Host '[4/5] Installing dependencies: yt-dlp, requests and ffmpeg ...' -ForegroundColor Cyan
& $venvPython -m pip install --disable-pip-version-check requests==2.32.5 yt-dlp imageio-ffmpeg
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

$env:LIVE_CAPTURE_INTERVAL = [string]$FrameInterval
$env:PYTHONUTF8 = '1'
if (-not $env:OPENAI_API_KEY -and -not $env:MYSHKA_OLLAMA_URL) {
    Write-Host ''
    Write-Host 'No vision AI is configured: only LIVE detection will run.' -ForegroundColor Yellow
    Write-Host 'For optional chart reading, configure local Ollama or an OpenAI API key.' -ForegroundColor Yellow
}
Write-Host ('LIVE checks: 15 seconds | optional vision frame interval: ' + $FrameInterval + ' seconds') -ForegroundColor Green
Write-Host 'Note: YouTube can block unattended extraction; results may be UNKNOWN.' -ForegroundColor Yellow

$port = Find-FreePort
$dashboard = 'http://127.0.0.1:' + $port + '/youtube-analysts.html#liveMonitor'
$serverArguments = '-m http.server {0} --bind 127.0.0.1 --directory "{1}"' -f $port, $project

Write-Host '[5/5] Starting local dashboard and continuous watcher ...' -ForegroundColor Cyan
$server = Start-Process -FilePath $venvPython -ArgumentList $serverArguments -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Seconds 2
    Write-Host ('Dashboard: ' + $dashboard) -ForegroundColor Green
    Start-Process $dashboard
    Push-Location $project
    try {
        & $venvPython 'crypto_myshka\rapid_live_watch.py' --interval 15
    } finally {
        Pop-Location
    }
} finally {
    if ($server -and (-not $server.HasExited)) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}
