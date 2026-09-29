$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$app = $null
try {
    $raw = docker inspect myshka-astra 2>$null | ConvertFrom-Json
    if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
        $app = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
} catch {}
if(-not $app){ throw 'ASTRA project not found.' }

$test = Join-Path $app 'selftest_hardening.py'
if(-not (Test-Path $test)){ throw 'selftest_hardening.py not installed.' }

Write-Host '=== ASTRA SAFE CHAOS TESTS ===' -ForegroundColor Cyan
Write-Host 'Simulation only: real Bybit/Ollama/n8n/Docker services are NOT interrupted.'
& python $test
if($LASTEXITCODE -ne 0){ throw 'Safe chaos tests failed.' }
Write-Host 'SAFE_CHAOS_OK' -ForegroundColor Green
