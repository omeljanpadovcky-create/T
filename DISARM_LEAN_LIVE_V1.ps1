$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - DISARM LEAN LIVE V1 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=$null
try{
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
}catch{}
if(-not $app){throw 'ASTRA project folder not found.'}
Set-Location $app

function Set-EnvKey {
  param([string[]]$Lines,[string]$Key,[string]$Value)
  $filtered=@($Lines | Where-Object {$_ -notmatch ('^'+[regex]::Escape($Key)+'=')})
  return @($filtered + ($Key+'='+$Value))
}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item '.env.live-armed' ('.env.live-armed.before-lean-disarm-'+$stamp) -Force

$lines=Get-Content '.env.live-armed'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_EXECUTION_MODE' 'DRY_RUN'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_EXECUTION' 'false'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_CONFIRM' 'NOT_ARMED'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_KILL_SWITCH' 'true'
$lines=Set-EnvKey $lines 'FREQTRADE__DRY_RUN' 'true'
$lines=Set-EnvKey $lines 'ASTRA_FREQTRADE_DRYRUN_AUTO' 'false'
$lines | Set-Content '.env.live-armed' -Encoding ASCII

$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker compose --ansi never up -d --build --force-recreate freqtrade astra
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'Docker recreate failed.'}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' LEAN LIVE DISARMED ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'FastTrack backend: DRY_RUN'
Write-Host 'Freqtrade dry_run: TRUE'
Write-Host 'ASTRA LIVE: FALSE'
Write-Host 'Kill switch: TRUE'
Write-Host 'Legacy dry-run auto router: FALSE'
