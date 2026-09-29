$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "============================================"
Write-Host " MYSHKA / ASTRA - STRICT EDGE BUFFER +0.05%"
Write-Host "============================================"
Write-Host ""

# Find the active ASTRA project.
$project = Get-Location
if (-not (Test-Path (Join-Path $project "api.py"))) {
    try {
        $raw = docker inspect myshka-astra 2>$null | ConvertFrom-Json
        if ($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir') {
            $project = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
        }
    } catch {}
}

$apiPath = Join-Path $project "api.py"
if (-not (Test-Path $apiPath)) {
    throw "api.py not found. Start ASTRA first or run this script from the ASTRA project folder."
}

Set-Location $project
Write-Host "[OK] Project: $project"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$apiBackup = Join-Path $project ("api_before_strict_edge_005_" + $stamp + ".py")
Copy-Item $apiPath $apiBackup -Force
Write-Host "[OK] Backup: $apiBackup"

$utf8 = New-Object System.Text.UTF8Encoding($false)
$apiLines = [System.Collections.Generic.List[string]](Get-Content $apiPath)
$marker = "MYSHKA_STRICT_EDGE_BUFFER_005"

$hasMarker = ($apiLines | Select-String -SimpleMatch $marker) -ne $null
if (-not $hasMarker) {
    $callIndex = -1
    for ($i=0; $i -lt $apiLines.Count; $i++) {
        if ($apiLines[$i] -match '^\s*edge\s*=\s*check_edge\(') {
            $callIndex = $i
            break
        }
    }
    if ($callIndex -lt 0) {
        throw "edge = check_edge(...) call not found in api.py"
    }

    # v9.7 currently uses a one-line check_edge(...) call. Abort safely if source changed.
    if ($apiLines[$callIndex] -notmatch '\)\s*$') {
        throw "check_edge call is multiline/changed; patch aborted safely."
    }

    $indent = [regex]::Match($apiLines[$callIndex], '^\s*').Value
    $block = @(
        ($indent + '# ' + $marker),
        ($indent + 'strict_4of4 = ('),
        ($indent + '    (sig.direction == "LONG" and sig.ema_fast > sig.ema_slow and sig.structure == "UP" and 52.0 <= sig.rsi <= 72.0 and sig.volume_ratio >= 0.60)'),
        ($indent + '    or'),
        ($indent + '    (sig.direction == "SHORT" and sig.ema_fast < sig.ema_slow and sig.structure == "DOWN" and 28.0 <= sig.rsi <= 48.0 and sig.volume_ratio >= 0.60)'),
        ($indent + ')'),
        ($indent + 'if strict_4of4 and edge is not None and edge.net_edge_pct <= 0.05:'),
        ($indent + '    # MYSHKA_STRICT_EDGE_PAYLOAD_V2'),
        ($indent + '    edge_payload = _clean(edge.as_dict())'),
        ($indent + '    if not isinstance(edge_payload, dict):'),
        ($indent + '        edge_payload = {}'),
        ($indent + '    edge_payload["passed"] = False'),
        ($indent + '    edge_payload["reason"] = "strict_edge_buffer"'),
        ($indent + '    edge_payload["min_required_net_edge_pct"] = 0.05'),
        ($indent + '    training_meta["strict_edge_min_pct"] = 0.05'),
        ($indent + '    return {'),
        ($indent + '        "action": "DROP", "reason": "strict_edge_buffer", "pair": req.pair,'),
        ($indent + '        "signal": _clean(sig.as_dict()), "edge": edge_payload,'),
        ($indent + '        "training": training_meta,'),
        ($indent + '    }')
    )

    $insertAt = $callIndex + 1
    for ($j=$block.Count-1; $j -ge 0; $j--) {
        $apiLines.Insert($insertAt, $block[$j])
    }

    [System.IO.File]::WriteAllLines($apiPath, $apiLines, $utf8)
    Write-Host "[OK] api.py: STRICT 4/4 now requires Net Edge > +0.05%."
    Write-Host "[OK] TRAIN 3/4 keeps the existing EDGE rule."
} else {
    Write-Host "[OK] STRICT EDGE +0.05% patch already present."
}

Write-Host ""
Write-Host "[TEST] Python syntax..."
python -m py_compile api.py
if ($LASTEXITCODE -ne 0) {
    Copy-Item $apiBackup $apiPath -Force
    throw "Python compile failed. Original api.py restored."
}
Write-Host "[OK] Python syntax valid."

Write-Host ""
Write-Host "[BUILD] Rebuilding ASTRA..."
docker compose up -d --build astra
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Docker rebuild failed. Source backup:"
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
Write-Host "TRAIN 3/4 : existing EDGE rule is unchanged"
Write-Host ""
