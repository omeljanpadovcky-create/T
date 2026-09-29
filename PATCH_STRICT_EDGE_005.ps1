$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "============================================"
Write-Host " MYSHKA / ASTRA - STRICT EDGE BUFFER +0.05%"
Write-Host "============================================"
Write-Host ""

# Find the active ASTRA project.
$project = Get-Location
if (-not (Test-Path (Join-Path $project "api.py")) -or -not (Test-Path (Join-Path $project "edge.py"))) {
    try {
        $raw = docker inspect myshka-astra 2>$null | ConvertFrom-Json
        if ($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir') {
            $project = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
        }
    } catch {}
}

$apiPath = Join-Path $project "api.py"
$edgePath = Join-Path $project "edge.py"

if (-not (Test-Path $apiPath)) { throw "api.py not found. Start this script from the ASTRA project folder." }
if (-not (Test-Path $edgePath)) { throw "edge.py not found. Start this script from the ASTRA project folder." }

Set-Location $project
Write-Host "[OK] Project: $project"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$apiBackup = Join-Path $project ("api_before_strict_edge_005_" + $stamp + ".py")
$edgeBackup = Join-Path $project ("edge_before_strict_edge_005_" + $stamp + ".py")
Copy-Item $apiPath $apiBackup -Force
Copy-Item $edgePath $edgeBackup -Force
Write-Host "[OK] Backups created."

$utf8 = New-Object System.Text.UTF8Encoding($false)

# 1) edge.py: caller-selectable minimum NET edge.
$edgeLines = [System.Collections.Generic.List[string]](Get-Content $edgePath)
$checkStart = -1
for ($i=0; $i -lt $edgeLines.Count; $i++) {
    if ($edgeLines[$i] -match '^def\s+check_edge\s*\(') { $checkStart = $i; break }
}
if ($checkStart -lt 0) { throw "def check_edge(...) not found in edge.py" }

$signatureEnd = -1
for ($i=$checkStart; $i -lt [Math]::Min($edgeLines.Count,$checkStart+40); $i++) {
    if ($edgeLines[$i] -match '^\)\s*->\s*EdgeResult\s*:') { $signatureEnd = $i; break }
}
if ($signatureEnd -lt 0) { throw "check_edge signature end not found in edge.py" }

$alreadyParam = $false
for ($i=$checkStart; $i -le $signatureEnd; $i++) {
    if ($edgeLines[$i] -match 'min_net_edge_pct') { $alreadyParam = $true; break }
}
if (-not $alreadyParam) {
    $edgeLines.Insert($signatureEnd, '    min_net_edge_pct: float = 0.0,')
    Write-Host "[OK] edge.py: added min_net_edge_pct parameter."
}

$passedFound = $false
for ($i=$checkStart; $i -lt $edgeLines.Count; $i++) {
    if ($edgeLines[$i] -match 'passed\s*=\s*net_edge\s*>\s*0\s*,') {
        $edgeLines[$i] = $edgeLines[$i] -replace 'passed\s*=\s*net_edge\s*>\s*0\s*,','passed=net_edge > min_net_edge_pct,'
        $passedFound = $true
        break
    }
    if ($edgeLines[$i] -match 'passed\s*=\s*net_edge\s*>\s*min_net_edge_pct\s*,') {
        $passedFound = $true
        break
    }
}
if (-not $passedFound) { throw "EDGE passed=net_edge > 0 line not found." }
[System.IO.File]::WriteAllLines($edgePath, $edgeLines, $utf8)

# 2) api.py: only STRICT 4/4 gets the +0.05% buffer.
$apiLines = [System.Collections.Generic.List[string]](Get-Content $apiPath)
$marker = "MYSHKA_STRICT_EDGE_BUFFER_005"
$hasMarker = ($apiLines | Select-String -SimpleMatch $marker) -ne $null

if (-not $hasMarker) {
    $callIndex = -1
    for ($i=0; $i -lt $apiLines.Count; $i++) {
        if ($apiLines[$i] -match '^\s*edge\s*=\s*check_edge\(') { $callIndex = $i; break }
    }
    if ($callIndex -lt 0) { throw "edge = check_edge(...) call not found in api.py" }

    $call = $apiLines[$callIndex]
    if ($call -notmatch '\)\s*$') { throw 'check_edge call is multiline; patch aborted safely.' }

    $indent = [regex]::Match($call,'^\s*').Value
    $block = @(
        ($indent + '# ' + $marker),
        ($indent + 'strict_4of4 = ('),
        ($indent + '    (sig.direction == "LONG" and sig.ema_fast > sig.ema_slow and sig.structure == "UP" and 52.0 <= sig.rsi <= 72.0 and sig.volume_ratio >= 0.60)'),
        ($indent + '    or'),
        ($indent + '    (sig.direction == "SHORT" and sig.ema_fast < sig.ema_slow and sig.structure == "DOWN" and 28.0 <= sig.rsi <= 48.0 and sig.volume_ratio >= 0.60)'),
        ($indent + ')'),
        ($indent + 'strict_edge_min = 0.05 if strict_4of4 else 0.0')
    )

    for ($j=$block.Count-1; $j -ge 0; $j--) { $apiLines.Insert($callIndex, $block[$j]) }
    $callIndex += $block.Count
    $call = $apiLines[$callIndex]
    $apiLines[$callIndex] = $call -replace '\)\s*$', ', min_net_edge_pct=strict_edge_min)'
    [System.IO.File]::WriteAllLines($apiPath, $apiLines, $utf8)
    Write-Host "[OK] api.py: STRICT 4/4 requires NET EDGE > +0.05%."
    Write-Host "[OK] api.py: TRAIN 3/4 keeps NET EDGE > 0.00%."
} else {
    Write-Host "[OK] api.py already has STRICT EDGE +0.05% patch."
}

Write-Host ""
Write-Host "[TEST] Python syntax..."
python -m py_compile edge.py api.py
if ($LASTEXITCODE -ne 0) {
    Copy-Item $edgeBackup $edgePath -Force
    Copy-Item $apiBackup $apiPath -Force
    throw "Python compile failed. Original files restored."
}
Write-Host "[OK] Python syntax valid."

Write-Host ""
Write-Host "[BUILD] Rebuilding ASTRA..."
docker compose up -d --build astra
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Docker rebuild failed. Source backups are:"
    Write-Warning $edgeBackup
    Write-Warning $apiBackup
    exit 1
}

Start-Sleep -Seconds 5
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8088/health" -TimeoutSec 10
    Write-Host "[OK] ASTRA health: $($health.status)"
} catch {
    Write-Warning "ASTRA did not answer /health yet. Check: docker logs --tail 80 myshka-astra"
}

Write-Host ""
Write-Host "DONE"
Write-Host "STRICT 4/4: Net Edge must be > +0.05%"
Write-Host "TRAIN 3/4 : Net Edge must be >  0.00%"
Write-Host ""
Write-Host "Backups:"
Write-Host "  $edgeBackup"
Write-Host "  $apiBackup"
