$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING='utf-8'

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FOCUSED JEV DIAGNOSTIC V2 ' -ForegroundColor Yellow
Write-Host ' READ ONLY ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=$null
try{
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
}catch{}
if(-not $app){throw 'ASTRA project folder not found.'}

$out=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_JEV_FOCUSED_V2.txt'
$api=Join-Path $app 'api.py'
$jev=Join-Path $app 'jev.py'
$sig=Join-Path $app 'signals.py'
if(-not (Test-Path $api) -or -not (Test-Path $jev)){throw 'api.py or jev.py missing.'}

$buf=New-Object System.Collections.Generic.List[string]
$buf.Add('=== API.PY _evaluate_request 1350-1450 ===')
$apiLines=Get-Content $api -Encoding UTF8
for($i=1349;$i -lt [Math]::Min(1450,$apiLines.Count);$i++){
  $buf.Add(('{0,5}: {1}' -f ($i+1),$apiLines[$i]))
}

$buf.Add('')
$buf.Add('=== JEV.PY FULL ===')
$jevLines=Get-Content $jev -Encoding UTF8
for($i=0;$i -lt $jevLines.Count;$i++){
  $buf.Add(('{0,5}: {1}' -f ($i+1),$jevLines[$i]))
}

if(Test-Path $sig){
  $buf.Add('')
  $buf.Add('=== SIGNALS.PY FULL ===')
  $sigLines=Get-Content $sig -Encoding UTF8
  for($i=0;$i -lt $sigLines.Count;$i++){
    $buf.Add(('{0,5}: {1}' -f ($i+1),$sigLines[$i]))
  }
}

$buf.Add('')
$buf.Add('=== RUNTIME ===')
try{
  $token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } | ForEach-Object { $_.Substring($_.IndexOf('=')+1) } | Select-Object -First 1)
  if($token){
    $h=@{'X-MYSHKA-TOKEN'=$token}
    $ctl=Invoke-RestMethod 'http://127.0.0.1:8088/control/status' -Headers $h -TimeoutSec 8
    $buf.Add(('ollama_enabled={0}' -f $ctl.runtime.ollama_enabled))
    $buf.Add(('auto_scan={0}' -f $ctl.runtime.auto_scan))
    $buf.Add(('paused={0}' -f $ctl.runtime.paused))
    $buf.Add(('kill_switch={0}' -f $ctl.runtime.kill_switch))
  }
}catch{
  $buf.Add(('control_status_error='+$_.Exception.Message))
}

$buf | Set-Content $out -Encoding UTF8

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - FOCUSED JEV DIAGNOSTIC V2 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Saved: '+$out)
Write-Host 'Files changed: NO'
Write-Host 'Docker rebuild: NO'
Write-Host 'LIVE changed: NO'
