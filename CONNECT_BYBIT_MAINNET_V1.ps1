$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$env:COMPOSE_ANSI='never'

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - CONNECT BYBIT MAINNET V1 ' -ForegroundColor Yellow
Write-Host ' PRIVATE API PREFLIGHT - NO ORDERS - DRY_RUN STAYS ON ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

# Locate project from running ASTRA container.
$inspect = docker inspect myshka-astra 2>$null | ConvertFrom-Json
if(-not $inspect){ throw 'myshka-astra container not found.' }
$wd = $inspect[0].Config.Labels.'com.docker.compose.project.working_dir'
if(-not $wd -or -not (Test-Path $wd)){ throw 'ASTRA project folder not found.' }
Set-Location $wd

$envMain = Join-Path $wd '.env'
$envArmed = Join-Path $wd '.env.live-armed'
if(-not (Test-Path $envMain)){ throw '.env not found.' }
if(-not (Test-Path $envArmed)){ throw '.env.live-armed not found.' }

# Safety: do not run this connector while live execution is armed.
$armedText = Get-Content $envArmed -Raw
if($armedText -notmatch '(?m)^FREQTRADE__DRY_RUN=true\s*$'){ throw 'HARD STOP: FREQTRADE__DRY_RUN must be true for connection preflight.' }
if($armedText -notmatch '(?m)^ASTRA_LIVE_EXECUTION=false\s*$'){ throw 'HARD STOP: ASTRA_LIVE_EXECUTION must be false.' }
if($armedText -notmatch '(?m)^ASTRA_LIVE_KILL_SWITCH=true\s*$'){ throw 'HARD STOP: ASTRA_LIVE_KILL_SWITCH must be true.' }

# Prompt locally. Nothing is sent to ChatGPT/GitHub.
Write-Host ''
Write-Host 'Paste the BYBIT MAINNET API credentials locally.' -ForegroundColor Cyan
Write-Host 'Do NOT use a key with Withdrawal permission.' -ForegroundColor Yellow
$keySec = Read-Host 'Bybit API KEY' -AsSecureString
$secretSec = Read-Host 'Bybit API SECRET' -AsSecureString

function Reveal-Secure([Security.SecureString]$s){
  $p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
  try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($p) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p) }
}
$key = Reveal-Secure $keySec
$secret = Reveal-Secure $secretSec
if([string]::IsNullOrWhiteSpace($key) -or [string]::IsNullOrWhiteSpace($secret)){
  throw 'API key/secret cannot be empty.'
}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $wd ('backup-before-bybit-mainnet-connect-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item $envMain (Join-Path $backup '.env') -Force
Copy-Item $envArmed (Join-Path $backup '.env.live-armed') -Force

$secretFile=Join-Path $wd '.env.bybit.local'
$overlay=Join-Path $wd 'compose.bybit-mainnet.yaml'
if(Test-Path $secretFile){ Copy-Item $secretFile (Join-Path $backup '.env.bybit.local') -Force }
if(Test-Path $overlay){ Copy-Item $overlay (Join-Path $backup 'compose.bybit-mainnet.yaml') -Force }

Write-Host '[1/6] Writing local Bybit secret file...'
@(
  'FREQTRADE__EXCHANGE__NAME=bybit'
  'FREQTRADE__EXCHANGE__SANDBOX=false'
  ('FREQTRADE__EXCHANGE__KEY='+$key)
  ('FREQTRADE__EXCHANGE__SECRET='+$secret)
) | Set-Content $secretFile -Encoding ASCII

# Hide from casual Explorer view; no secret is printed.
try { (Get-Item $secretFile).Attributes = (Get-Item $secretFile).Attributes -bor [IO.FileAttributes]::Hidden } catch {}
Write-Host '[OK] Credentials stored locally; values not printed.' -ForegroundColor Green

Write-Host '[2/6] Creating compose overlay for Freqtrade only...'
@'
services:
  freqtrade:
    env_file:
      - .env.bybit.local
'@ | Set-Content $overlay -Encoding ASCII

# Make the overlay part of every future "docker compose" invocation in this project.
$mainLines=Get-Content $envMain
$mainLines=@($mainLines | Where-Object {$_ -notmatch '^COMPOSE_FILE=' -and $_ -notmatch '^COMPOSE_PATH_SEPARATOR='})
$baseFiles=@()
$cfgLabel=$inspect[0].Config.Labels.'com.docker.compose.project.config_files'
if($cfgLabel){
  foreach($f in ($cfgLabel -split ',')){
    $name=[IO.Path]::GetFileName($f.Trim())
    if($name -and $baseFiles -notcontains $name){ $baseFiles += $name }
  }
}
if($baseFiles.Count -eq 0){
  if(Test-Path (Join-Path $wd 'docker-compose.yml')){$baseFiles += 'docker-compose.yml'}
  elseif(Test-Path (Join-Path $wd 'compose.yaml')){$baseFiles += 'compose.yaml'}
}
if($baseFiles -notcontains 'compose.bybit-mainnet.yaml'){ $baseFiles += 'compose.bybit-mainnet.yaml' }
$mainLines += 'COMPOSE_PATH_SEPARATOR=;'
$mainLines += ('COMPOSE_FILE='+($baseFiles -join ';'))
$mainLines | Set-Content $envMain -Encoding ASCII
Write-Host ('[OK] COMPOSE_FILE='+($baseFiles -join ';')) -ForegroundColor Green

Write-Host '[3/6] Verifying effective compose without exposing secret values...'
$cfg = docker compose config --format json | ConvertFrom-Json
$ft = $cfg.services.freqtrade
if(-not $ft){ throw 'Freqtrade service missing from compose config.' }
$ftEnv=$ft.environment
if(-not $ftEnv){ throw 'Freqtrade environment missing.' }
if([string]::IsNullOrWhiteSpace([string]$ftEnv.FREQTRADE__EXCHANGE__KEY)){ throw 'Bybit API key did not reach Freqtrade compose environment.' }
if([string]::IsNullOrWhiteSpace([string]$ftEnv.FREQTRADE__EXCHANGE__SECRET)){ throw 'Bybit API secret did not reach Freqtrade compose environment.' }
Write-Host '[OK] Bybit credentials are wired into Freqtrade.' -ForegroundColor Green

Write-Host '[4/6] Recreating Freqtrade + ASTRA with DRY_RUN still ON...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker compose --ansi never up -d --force-recreate freqtrade astra
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){ throw 'Docker recreate failed.' }

# Wait for ASTRA + Freqtrade API.
$astraReady=$false
$ftReady=$false
for($i=0;$i -lt 60;$i++){
  Start-Sleep -Seconds 2
  try{
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
    if($h.status -eq 'ok'){$astraReady=$true}
  }catch{}
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  $ping='import urllib.request; print(urllib.request.urlopen("http://freqtrade:8080/api/v1/ping",timeout=3).status)'
  $p=$ping | docker exec -i myshka-astra python - 2>&1
  $prc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($prc -eq 0 -and (($p -join [Environment]::NewLine) -match '200')){$ftReady=$true}
  if($astraReady -and $ftReady){break}
}
if(-not $astraReady){throw 'ASTRA did not become healthy.'}
if(-not $ftReady){throw 'Freqtrade API did not become ready.'}
Write-Host '[OK] ASTRA + Freqtrade ready.' -ForegroundColor Green

Write-Host '[5/6] Bybit private API preflight (read-only request; NO ORDER)...'
$py=@'
import os,time,hmac,hashlib,json,urllib.request,urllib.error

key=os.getenv("FREQTRADE__EXCHANGE__KEY","")
secret=os.getenv("FREQTRADE__EXCHANGE__SECRET","")
if not key or not secret:
    print(json.dumps({"ok":False,"reason":"missing_env_credentials"}))
    raise SystemExit(0)

BASE="https://api.bybit.com"
RECV="5000"

def signed_get(path, query=""):
    ts=str(int(time.time()*1000))
    payload=ts+key+RECV+query
    sig=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest()
    url=BASE+path+("?" + query if query else "")
    req=urllib.request.Request(url,headers={
        "X-BAPI-API-KEY":key,
        "X-BAPI-TIMESTAMP":ts,
        "X-BAPI-RECV-WINDOW":RECV,
        "X-BAPI-SIGN":sig,
    })
    try:
        with urllib.request.urlopen(req,timeout=12) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:return json.loads(e.read().decode())
        except:return {"retCode":e.code,"retMsg":str(e)}
    except Exception as e:
        return {"retCode":-1,"retMsg":f"{type(e).__name__}: {e}"}

api=signed_get("/v5/user/query-api")
acct=signed_get("/v5/account/info")

res=api.get("result") or {}
perms=res.get("permissions") or {}
contract=perms.get("ContractTrade") or []
deriv=perms.get("Derivatives") or []
trade_capable=(int(res.get("readOnly",1))==0 and (
    ("Order" in contract and "Position" in contract) or
    ("DerivativesTrade" in deriv)
))
out={
    "ok": api.get("retCode")==0 and acct.get("retCode")==0,
    "api_retCode":api.get("retCode"),
    "api_retMsg":api.get("retMsg"),
    "account_retCode":acct.get("retCode"),
    "account_retMsg":acct.get("retMsg"),
    "readOnly":res.get("readOnly"),
    "trade_capable_permission":trade_capable,
    "contract_trade_permissions":contract,
    "derivatives_permissions":deriv,
    "ip_bind_count":len(res.get("ips") or []),
    "uta":res.get("uta"),
    "account": {
        "unifiedMarginStatus":(acct.get("result") or {}).get("unifiedMarginStatus"),
        "marginMode":(acct.get("result") or {}).get("marginMode"),
    }
}
print(json.dumps(out,ensure_ascii=False))
'@
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
$out=$py | docker exec -i freqtrade python -
$prc=$LASTEXITCODE
$ErrorActionPreference=$old
if($prc -ne 0){throw 'Bybit private preflight could not run.'}
$bp=$out | ConvertFrom-Json
if(-not $bp.ok){
  Write-Host ($out -join [Environment]::NewLine)
  throw 'Bybit private API preflight failed.'
}
Write-Host ('[OK] Bybit authenticated. readOnly='+$bp.readOnly+' tradePermission='+$bp.trade_capable_permission+' IP-bind-count='+$bp.ip_bind_count) -ForegroundColor Green

Write-Host '[6/6] Verifying Freqtrade remains paper-only...'
$check=@'
import os,json,base64,urllib.request
base=os.getenv("FREQTRADE_BASE_URL","http://freqtrade:8080").rstrip("/")
u=os.getenv("FREQTRADE_USERNAME","")
p=os.getenv("FREQTRADE_PASSWORD","")
basic=base64.b64encode(f"{u}:{p}".encode()).decode()
req=urllib.request.Request(base+"/api/v1/token/login",headers={"Authorization":"Basic "+basic},method="POST")
with urllib.request.urlopen(req,timeout=8) as r:
    tok=json.loads(r.read().decode())["access_token"]
req=urllib.request.Request(base+"/api/v1/show_config",headers={"Authorization":"Bearer "+tok})
with urllib.request.urlopen(req,timeout=8) as r:
    c=json.loads(r.read().decode())
print(json.dumps({
    "dry_run":c.get("dry_run"),
    "exchange":c.get("exchange"),
    "trading_mode":c.get("trading_mode"),
    "margin_mode":c.get("margin_mode"),
    "max_open_trades":c.get("max_open_trades"),
    "stoploss":c.get("stoploss"),
    "order_types":c.get("order_types"),
}))
'@
$fcRaw=$check | docker exec -i myshka-astra python -
$fc=$fcRaw | ConvertFrom-Json
if($fc.dry_run -ne $true){throw 'HARD STOP: Freqtrade is no longer DRY_RUN.'}
if([string]$fc.exchange -ne 'bybit'){throw 'HARD STOP: exchange is not bybit.'}
if([string]$fc.trading_mode -ne 'futures'){throw 'HARD STOP: trading_mode is not futures.'}
if([string]$fc.margin_mode -ne 'isolated'){throw 'HARD STOP: margin_mode is not isolated.'}
if([int]$fc.max_open_trades -ne 1){throw 'HARD STOP: max_open_trades is not 1.'}
if($fc.order_types.stoploss_on_exchange -ne $true){throw 'HARD STOP: stoploss_on_exchange is not true.'}

# Clear plaintext variables from this PowerShell process.
$key=$null
$secret=$null
Remove-Variable keySec,secretSec -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - BYBIT MAINNET CONNECTED V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Private API auth: OK')
Write-Host ('Trade-capable permission: '+$bp.trade_capable_permission)
Write-Host ('IP restrictions configured: '+([bool]($bp.ip_bind_count -gt 0)))
Write-Host ('Account marginMode: '+$bp.account.marginMode)
Write-Host ('Freqtrade exchange: '+$fc.exchange)
Write-Host ('Freqtrade mode: '+$fc.trading_mode+' / '+$fc.margin_mode)
Write-Host ('max_open_trades: '+$fc.max_open_trades)
Write-Host ('stoploss: '+$fc.stoploss)
Write-Host ('stoploss_on_exchange: '+$fc.order_types.stoploss_on_exchange)
Write-Host 'REAL MONEY EXECUTION: OFF'
Write-Host 'FREQTRADE DRY_RUN: TRUE'
Write-Host 'ASTRA KILL SWITCH: ON'
Write-Host ('Local secret file: '+$secretFile)
Write-Host ('Backup: '+$backup)
