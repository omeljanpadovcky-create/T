$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$dir=Join-Path $PSScriptRoot 'p2p_radar'
$venv=Join-Path $dir '.venv'
$python=Join-Path $venv 'Scripts\python.exe'
if(-not (Test-Path $python)){
  Write-Host '[MYSHKA] Creating Python environment...' -ForegroundColor Cyan
  py -3 -m venv $venv
}
& $python -m pip install --disable-pip-version-check -q -r (Join-Path $dir 'requirements.txt')
if(-not (Test-Path (Join-Path $dir '.env'))){
  Copy-Item (Join-Path $dir '.env.example') (Join-Path $dir '.env') -Force
  Write-Host '[MYSHKA] Created p2p_radar\.env. Existing root .env is also reused.' -ForegroundColor Yellow
}
Write-Host '=====================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA P2P RADAR - SCAN ONLY / NO AUTO-TRADING' -ForegroundColor Yellow
Write-Host ' Ctrl+C stops the scanner.' -ForegroundColor DarkGray
Write-Host '=====================================================' -ForegroundColor Cyan
& $python (Join-Path $dir 'radar.py')
