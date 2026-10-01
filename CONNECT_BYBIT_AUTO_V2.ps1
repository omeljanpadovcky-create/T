$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$env:COMPOSE_ANSI='never'

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - BYBIT ENV AUTO-DETECT V2 ' -ForegroundColor Yellow
Write-Host ' READ-ONLY PRIVATE PREFLIGHT - NO ORDERS - DRY_RUN ONLY ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$inspect = docker inspect myshka-astra 2>$null | ConvertFrom-Json
if(-not $inspect){ throw 'myshka-astra container not found.' }
$wd = $inspect[0].Config.Labels.'com.docker.compose.project.working_dir'
if(-not $wd -or -not (Test-Path $wd)){ throw 'ASTRA project folder not found.' }
Set-Location $wd

$envMain = Join-Path $wd '.env'
$envArmed = Join-Path $wd '.env.live-armed'
if(-not (Test-Path $envMain)){ throw '.env not found.' }
if(-not (Test-Path $envArmed)){ throw '.env.live-armed not found.' }

$armedText = Get-Content $envArmed -Raw
if($armedText -notmatch '(?m)^FREQTRADE__DRY_RUN=true\s*$'){ throw 'HARD STOP: FREQTRADE__DRY_RUN must be true.' }
if($armedText -notmatch '(?m)^ASTRA_LIVE_EXECUTION=false\s*$'){ throw 'HARD STOP: ASTRA_LIVE_EXECUTION must be false.' }
if($armedText -notmatch '(?m)^ASTRA_LIVE_KILL_SWITCH=true\s*$'){ throw 'HARD STOP: ASTRA_LIVE_KILL_SWITCH must be true.' }

Write-Host ''
Write-Host 'Paste the Bybit API credentials LOCALLY.' -ForegroundColor Cyan
Write-Host 'Do not paste them into chat.' -ForegroundColor Yellow
$keySec = Read-Host 'Bybit API KEY' -AsSecureString
$secretSec = Read-Host 'Bybit API SECRET' -AsSecureString

function Reveal-Secure([Security.SecureString]$s){
  $p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
  try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($p) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p) }
}
$key = Reveal-Secure $keySec
$secret = Reveal-Secure $secretSec
if([string]::IsNullOrWhiteSpace($key) -or [string]::IsNullOrWhiteSpace($secret)){ throw 'Key/secret cannot be empty.' }

Write-Host '[1/5] Auto-detecting Bybit environment...'
$py=@'
import os,time,hmac,hashlib,json,urllib.request,urllib.error

key=os.getenv("TMP_BYBIT_KEY","")
secret=os.getenv("TMP_BYBIT_SECRET","")
recv="5000"

targets=[
 ("mainnet-global","https://api.bybit.com"),
 ("mainnet-demo","https://api-demo.bybit.com"),
 ("testnet","https://api-testnet.bybit.com"),
 ("mainnet-eu","https://api.bybit.eu"),
 ("mainnet-tr","https://api.bybit.tr"),
 ("mainnet-kz","https://api.bybit.kz"),
 ("mainnet-georgia","https://api.bybitgeorgia.ge"),
 ("mainnet-ae","https://api.bybit.ae"),
 ("mainnet-id","https://api.bybit.id"),
]

def call(base):
    ts=str(int(time.time()*1000))
    payload=ts+key+recv
    sig=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest()
    req=urllib.request.Request(
      base+"/v5/user/query-api",
      headers={
        "X-BAPI-API-KEY":key,
        "X-BAPI-TIMESTAMP":ts,
        "X-BAPI-RECV-WINDOW":recv,
        "X-BAPI-SIGN":sig,
      }
    )
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:return json.loads(e.read().decode())
        except:return {"retCode":e.code,"retMsg":str(e)}
    except Exception as e:
        return {"retCode":-1,"retMsg":f"{type(e).__name__}: {e}"}

rows=[]
matched=None
for name,base in targets:
    d=call(base)
    rows.append({"name":name,"base":base,"retCode":d.get("retCode"),"retMsg":d.get("retMsg")})
    if d.get("retCode")==0 and matched is None:
        matched={"name":name,"base":base,"result":d.get("result") or {}}

print(json.dumps({"matched":matched,"probes":rows},ensure_ascii=False))
'@

$env:TMP_BYBIT_KEY=$key
$env:TMP_BYBIT_SECRET=$secret
try{
  $raw=$py | docker exec -e TMP_BYBIT_KEY -e TMP_BYBIT_SECRET -i myshka-astra python -
}finally{
  Remove-Item Env:TMP_BYBIT_KEY -ErrorAction SilentlyContinue
  Remove-Item Env:TMP_BYBIT_SECRET -ErrorAction SilentlyContinue
}
$det=$raw | ConvertFrom-Json

if(-not $det.matched){
  Write-Host ''
  Write-Host 'No Bybit environment accepted this key.' -ForegroundColor Red
  foreach($p in $det.probes){
    Write-Host ($p.name+': '+$p.retCode+' '+$p.retMsg)
  }
  Write-Host ''
  Write-Host 'Interpretation:' -ForegroundColor Yellow
  Write-Host '  10003 = key/environment mismatch or invalid key'
  Write-Host '  10004 = signature/secret mismatch or non-HMAC key'
  throw 'Bybit key auto-detect failed.'
}

$name=[string]$det.matched.name
$base=[string]$det.matched.base
$res=$det.matched.result

Write-Host ('[OK] Key matched: '+$name+' -> '+$base) -ForegroundColor Green

if($name -notin @('mainnet-global','testnet')){
  Write-Host ('Matched environment: '+$name) -ForegroundColor Yellow
  Write-Host 'This connector only auto-configures global mainnet or testnet.' -ForegroundColor Yellow
  Write-Host 'No files changed.' -ForegroundColor Yellow
  exit 0
}

$readOnly=$res.readOnly
$perms=$res.permissions
$contract=@()
$deriv=@()
if($perms){
  if($perms.ContractTrade){$contract=@($perms.ContractTrade)}
  if($perms.Derivatives){$deriv=@($perms.Derivatives)}
}
$tradeCapable=($readOnly -eq 0 -and ((($contract -contains 'Order') -and ($contract -contains 'Position')) -or ($deriv -contains 'DerivativesTrade')))

Write-Host ('[2/5] readOnly='+$readOnly+' trade-capable='+$tradeCapable)

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $wd ('backup-before-bybit-auto-v2-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item $envMain (Join-Path $backup '.env') -Force
Copy-Item $envArmed (Join-Path $backup '.env.live-armed') -Force

$secretFile=Join-Path $wd '.env.bybit.local'
$overlay=Join-Path $wd 'compose.bybit-mainnet.yaml'
if(Test-Path $secretFile){Copy-Item $secretFile (Join-Path $backup '.env.bybit.local') -Force}
if(Test-Path $overlay){Copy-Item $overlay (Join-Path $backup 'compose.bybit-mainnet.yaml') -Force}

$sandbox = if($name -eq 'testnet'){'true'}else{'false'}

Write-Host '[3/5] Writing local Freqtrade Bybit env...'
@(
  'FREQTRADE__EXCHANGE__NAME=bybit'
  ('FREQTRADE__EXCHANGE__SANDBOX='+$sandbox)
  ('FREQTRADE__EXCHANGE__KEY='+$key)
  ('FREQTRADE__EXCHANGE__SECRET='+$secret)
) | Set-Content $secretFile -Encoding ASCII
try{(Get-Item $secretFile).Attributes=(Get-Item $secretFile).Attributes -bor [IO.FileAttributes]::Hidden}catch{}

@'
services:
  freqtrade:
    env_file:
      - .env.bybit.local
'@ | Set-Content $overlay -Encoding ASCII

$mainLines=Get-Content $envMain
$mainLines=@($mainLines | Where-Object {$_ -notmatch '^COMPOSE_FILE=' -and $_ -notmatch '^COMPOSE_PATH_SEPARATOR='})
$baseFiles=@()
$cfgLabel=$inspect[0].Config.Labels.'com.docker.compose.project.config_files'
if($cfgLabel){
  foreach($f in ($cfgLabel -split ',')){
    $n=[IO.Path]::GetFileName($f.Trim())
    if($n -and $baseFiles -notcontains $n){$baseFiles += $n}
  }
}
if($baseFiles.Count -eq 0){
  if(Test-Path (Join-Path $wd 'docker-compose.yml')){$baseFiles += 'docker-compose.yml'}
}
if($baseFiles -notcontains 'compose.bybit-mainnet.yaml'){$baseFiles += 'compose.bybit-mainnet.yaml'}
$mainLines += 'COMPOSE_PATH_SEPARATOR=;'
$mainLines += ('COMPOSE_FILE='+($baseFiles -join ';'))
$mainLines | Set-Content $envMain -Encoding ASCII

Write-Host '[4/5] Recreating Freqtrade + ASTRA; DRY_RUN remains ON...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker compose --ansi never up -d --force-recreate freqtrade astra
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'Docker recreate failed.'}

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
  $pong=$ping | docker exec -i myshka-astra python - 2>&1
  $prc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($prc -eq 0 -and (($pong -join [Environment]::NewLine) -match '200')){$ftReady=$true}
  if($astraReady -and $ftReady){break}
}
if(-not $astraReady){throw 'ASTRA not healthy.'}
if(-not $ftReady){throw 'Freqtrade API not ready.'}

Write-Host '[5/5] Verifying paper-only execution...'
$check=@'
import os,json,base64,urllib.request
base=os.getenv("FREQTRADE_BASE_URL","http://freqtrade:8080").rstrip("/")
u=os.getenv("FREQTRADE_USERNAME","")
p=os.getenv("FREQTRADE_PASSWORD","")
basic=base64.b64encode(f"{u}:{p}".encode()).decode()
q=urllib.request.Request(base+"/api/v1/token/login",headers={"Authorization":"Basic "+basic},method="POST")
with urllib.request.urlopen(q,timeout=8) as r:
    tok=json.loads(r.read().decode())["access_token"]
q=urllib.request.Request(base+"/api/v1/show_config",headers={"Authorization":"Bearer "+tok})
with urllib.request.urlopen(q,timeout=8) as r:
    c=json.loads(r.read().decode())
print(json.dumps({
 "dry_run":c.get("dry_run"),
 "exchange":c.get("exchange"),
 "trading_mode":c.get("trading_mode"),
 "margin_mode":c.get("margin_mode"),
 "max_open_trades":c.get("max_open_trades"),
 "stoploss_on_exchange":(c.get("order_types") or {}).get("stoploss_on_exchange"),
}))
'@
$fcRaw=$check | docker exec -i myshka-astra python -
$fc=$fcRaw | ConvertFrom-Json

if($fc.dry_run -ne $true){throw 'HARD STOP: Freqtrade is not DRY_RUN.'}
if([string]$fc.exchange -ne 'bybit'){throw 'HARD STOP: exchange is not bybit.'}

$key=$null
$secret=$null
Remove-Variable keySec,secretSec -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - BYBIT AUTO-DETECT V2 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Matched environment: '+$name)
Write-Host ('Bybit endpoint: '+$base)
Write-Host ('readOnly: '+$readOnly)
Write-Host ('Trade-capable permission: '+$tradeCapable)
Write-Host ('Freqtrade exchange: '+$fc.exchange)
Write-Host ('FREQTRADE DRY_RUN: '+$fc.dry_run)
Write-Host ('trading_mode: '+$fc.trading_mode)
Write-Host ('margin_mode: '+$fc.margin_mode)
Write-Host ('max_open_trades: '+$fc.max_open_trades)
Write-Host ('stoploss_on_exchange: '+$fc.stoploss_on_exchange)
Write-Host 'REAL MONEY EXECUTION: OFF'
Write-Host 'ASTRA KILL SWITCH: ON'
Write-Host ('Backup: '+$backup)
