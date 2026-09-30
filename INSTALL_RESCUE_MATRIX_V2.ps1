$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host 'MYSHKA / ASTRA - RESCUE MATRIX V2 · FORWARD SHADOW' -ForegroundColor Cyan

$bundleCommit='fa3073078aa413009498d8daf46e1f6f0b17a8c1'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$bundleCommit

$app=$null
try {
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
} catch {}
if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'api.py')){$app=$fallback}
}
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){throw 'ASTRA project folder not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-rescue-v2-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','index.html','rescue_matrix.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}

$tmp=Join-Path $env:TEMP 'myshka_rescue_v2'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$files=@{
  'rescue_matrix.py'='/astra_rescue_matrix/rescue_matrix.py'
  'patch_rescue_matrix.py'='/astra_rescue_matrix/patch_rescue_matrix.py'
  'selftest_rescue_matrix.py'='/astra_rescue_matrix/selftest_rescue_matrix.py'
  'index.html'='/index.html'
}
foreach($name in $files.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri ($root+$files[$name]) -OutFile (Join-Path $tmp $name)
}

$py=@((Join-Path $tmp 'rescue_matrix.py'),(Join-Path $tmp 'patch_rescue_matrix.py'),(Join-Path $tmp 'selftest_rescue_matrix.py'))
& python -m py_compile @py
if($LASTEXITCODE -ne 0){throw 'Rescue V2 compile failed. ASTRA unchanged.'}

$pkg=Join-Path $tmp 'rescuepkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
Copy-Item (Join-Path $tmp 'rescue_matrix.py') (Join-Path $pkg 'rescue_matrix.py') -Force
Copy-Item (Join-Path $tmp 'selftest_rescue_matrix.py') (Join-Path $pkg 'selftest_rescue_matrix.py') -Force
Push-Location $tmp
try {
  & python -m rescuepkg.selftest_rescue_matrix
  if($LASTEXITCODE -ne 0){throw 'Rescue V2 self-test failed. ASTRA unchanged.'}
} finally {Pop-Location}

try {
  Copy-Item (Join-Path $tmp 'rescue_matrix.py') (Join-Path $app 'rescue_matrix.py') -Force
  Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force
  & python (Join-Path $tmp 'patch_rescue_matrix.py') $app
  if($LASTEXITCODE -ne 0){throw 'API patch failed.'}
  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'rescue_matrix.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
    docker compose up -d --build --force-recreate astra
    if($LASTEXITCODE -ne 0){throw 'ASTRA rebuild failed.'}
  } finally {Pop-Location}
  docker cp (Join-Path $tmp 'index.html') 'myshka-astra:/data/myshka_dashboard.html'
  if($LASTEXITCODE -ne 0){throw 'Dashboard publish failed.'}
} catch {
  foreach($name in @('api.py','index.html','rescue_matrix.py')){
    $b=Join-Path $backup $name
    $dst=Join-Path $app $name
    if(Test-Path $b){Copy-Item $b $dst -Force}
  }
  throw
}

Write-Host ''
Write-Host 'READY - RESCUE MATRIX V2 INSTALLED' -ForegroundColor Green
Write-Host 'Mode: FORWARD SHADOW ONLY'
Write-Host 'Anchor: JEV APPROVE x TECH 3/4'
Write-Host 'Positive + toxic clusters: ON'
Write-Host 'WATCH + new-forward confirmation: ON'
Write-Host 'Auto gate: OFF'
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
