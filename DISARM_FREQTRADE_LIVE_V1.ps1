param(
  [switch]$KeepFreqtradeLive
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - DISARM LIVE V1 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=$null
try {
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
} catch {}
if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback '.env.live-armed')){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}

Set-Location $app
if(-not (Test-Path '.env.live-armed')){throw '.env.live-armed not found.'}

function Set-EnvKey {
  param([string[]]$Lines,[string]$Key,[string]$Value)
  $filtered=@($Lines | Where-Object {$_ -notmatch ('^'+[regex]::Escape($Key)+'=')})
  return @($filtered + ($Key+'='+$Value))
}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item '.env.live-armed' ('.env.live-armed.before-disarm-'+$stamp) -Force

$lines=Get-Content '.env.live-armed'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_EXECUTION' 'false'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_CONFIRM' 'NOT_ARMED'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_KILL_SWITCH' 'true'
$lines=Set-EnvKey $lines 'ASTRA_FREQTRADE_DRYRUN_AUTO' 'false'

if(-not $KeepFreqtradeLive){
  $lines=Set-EnvKey $lines 'FREQTRADE__DRY_RUN' 'true'
  $lines=Set-EnvKey $lines 'ASTRA_FREQTRADE_DRYRUN_AUTO' 'true'
}

$lines | Set-Content '.env.live-armed' -Encoding ASCII

if($KeepFreqtradeLive){
  docker compose up -d --build --force-recreate astra | Out-Host
} else {
  docker compose up -d --build --force-recreate freqtrade astra | Out-Host
}
if($LASTEXITCODE -ne 0){throw 'Docker recreate failed.'}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' LIVE DISARMED ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'ASTRA live execution: FALSE'
Write-Host 'Kill switch: TRUE'
if($KeepFreqtradeLive){
  Write-Host 'Freqtrade mode: unchanged'
} else {
  Write-Host 'Freqtrade dry_run: TRUE'
  Write-Host 'Dry-run bridge auto: TRUE'
}
