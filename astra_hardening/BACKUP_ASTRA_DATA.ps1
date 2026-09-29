$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$container = 'myshka-astra'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$app = $null
try {
    $raw = docker inspect $container 2>$null | ConvertFrom-Json
    if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
        $app = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
} catch {}
if(-not $app){ throw 'ASTRA container not found.' }

$destRoot = Join-Path $app 'data-backups'
$dest = Join-Path $destRoot ("astra-data-" + $stamp)
New-Item -ItemType Directory -Path $dest -Force | Out-Null

Write-Host '=== ASTRA SQLITE BACKUP ===' -ForegroundColor Cyan
Write-Host ("Destination: " + $dest)

$py = @'
import glob, json, os, shutil, sqlite3, time
srcs = sorted(set(glob.glob("/data/*.sqlite3") + glob.glob("/data/*.sqlite") + glob.glob("/data/*.db")))
out = "/tmp/astra_sqlite_backup"
shutil.rmtree(out, ignore_errors=True)
os.makedirs(out, exist_ok=True)
manifest = {"created_at": time.time(), "files": []}
for src in srcs:
    name = os.path.basename(src)
    dst = os.path.join(out, name)
    try:
        s = sqlite3.connect(src, timeout=10)
        d = sqlite3.connect(dst, timeout=10)
        with d:
            s.backup(d)
        q = d.execute("PRAGMA quick_check").fetchone()[0]
        d.close(); s.close()
        if str(q).lower() != "ok":
            raise RuntimeError("quick_check=" + str(q))
        manifest["files"].append({"name": name, "status": "ok", "bytes": os.path.getsize(dst)})
    except Exception as exc:
        manifest["files"].append({"name": name, "status": "error", "error": type(exc).__name__ + ": " + str(exc)})
with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print(json.dumps(manifest, ensure_ascii=False))
'@

$out = docker exec $container python -c $py
if($LASTEXITCODE -ne 0){ throw 'Container SQLite backup failed.' }
Write-Host $out

docker cp ($container + ':/tmp/astra_sqlite_backup/.') $dest
if($LASTEXITCODE -ne 0){ throw 'docker cp backup failed.' }

$manifest = Join-Path $dest 'manifest.json'
if(-not (Test-Path $manifest)){ throw 'Backup manifest missing.' }
$j = Get-Content $manifest -Raw | ConvertFrom-Json
$bad = @($j.files | Where-Object { $_.status -ne 'ok' })
if($bad.Count -gt 0){
    Write-Warning 'Some SQLite files could not be backed up:'
    $bad | Format-Table -AutoSize
    throw 'Backup incomplete.'
}

Write-Host ''
Write-Host ("BACKUP_OK · " + $j.files.Count + " SQLite DB(s)") -ForegroundColor Green
Write-Host ("Path: " + $dest) -ForegroundColor Green
