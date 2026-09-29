param(
    [Parameter(Mandatory=$true)]
    [string]$BackupPath,
    [string]$Confirm = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if($Confirm -ne 'RESTORE'){
    throw 'Restore blocked. Re-run with -Confirm RESTORE'
}
$BackupPath = (Resolve-Path $BackupPath).Path
$manifestPath = Join-Path $BackupPath 'manifest.json'
if(-not (Test-Path $manifestPath)){ throw 'manifest.json not found in backup folder.' }

$j = Get-Content $manifestPath -Raw | ConvertFrom-Json
$files = @($j.files | Where-Object { $_.status -eq 'ok' })
if($files.Count -eq 0){ throw 'Backup contains no valid SQLite files.' }

Write-Host '=== ASTRA SQLITE RESTORE ===' -ForegroundColor Yellow
Write-Host ("Source: " + $BackupPath)
Write-Host ("DB files: " + $files.Count)

# Validate host backup before touching the container.
foreach($f in $files){
    $p = Join-Path $BackupPath $f.name
    if(-not (Test-Path $p)){ throw ("Backup file missing: " + $f.name) }
    $check = & python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA quick_check').fetchone()[0]); c.close()" $p
    if(($check | Out-String).Trim().ToLower() -ne 'ok'){
        throw ("Host backup integrity failed: " + $f.name)
    }
}
Write-Host '[OK] Host backup integrity verified.' -ForegroundColor Green

$container = 'myshka-astra'
$app = $null
try {
    $raw = docker inspect $container 2>$null | ConvertFrom-Json
    if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
        $app = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
} catch {}
if(-not $app){ throw 'ASTRA container/project not found.' }

Push-Location $app
try {
    docker compose stop astra
    if($LASTEXITCODE -ne 0){ throw 'Could not stop ASTRA service.' }

    foreach($f in $files){
        docker cp (Join-Path $BackupPath $f.name) ($container + ':/data/' + $f.name)
        if($LASTEXITCODE -ne 0){ throw ("docker cp restore failed: " + $f.name) }
    }

    # Service container is stopped, so use a one-shot compose container that mounts
    # the same /data volume to clear stale WAL/SHM files and verify restored DBs.
    docker compose run --rm --no-deps --entrypoint sh astra -lc "rm -f /data/*-wal /data/*-shm"
    if($LASTEXITCODE -ne 0){ throw 'Could not clear SQLite WAL/SHM sidecars.' }

    foreach($f in $files){
        $db = "/data/" + $f.name
        $q = docker compose run --rm --no-deps --entrypoint python astra -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA quick_check').fetchone()[0]); c.close()" $db
        if(($q | Out-String).Trim().ToLower() -ne 'ok'){
            throw ("Container DB integrity failed after restore: " + $f.name)
        }
    }

    docker compose up -d --force-recreate astra
    if($LASTEXITCODE -ne 0){ throw 'ASTRA restart failed after restore.' }
} finally {
    Pop-Location
}

$health = $null
for($i=0;$i -lt 30;$i++){
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 3
        if($health.status -eq 'ok'){ break }
    } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'Restore completed but ASTRA health check failed.' }

Write-Host ''
Write-Host 'RESTORE_OK · ASTRA health: ok' -ForegroundColor Green
