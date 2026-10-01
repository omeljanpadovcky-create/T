#!/usr/bin/env python3
from __future__ import annotations
import csv, json, os, re, shutil, subprocess, sys, time, urllib.parse
from pathlib import Path

URLS = [
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=HhwP43LLqUw%2FqQl7FNYh%2Fw%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=1TF3sRrklDbGrpj2yOOkhw%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=E%2FZElx9T1WhI8YQkvUc4AQ%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=4PeZ4JI3nDbPCg2HvZFQHQ%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=USziyeD8XwgurpqzAG6WAw%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=ZVyiBTgen0NW7ciUQ1fS8A%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=lcq%2FGJGxgQH5uqCLJCjD7g%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=CSSIcV3UbgANg03c0xCq2Q%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=zKBsbcATbI1jKx3PRVN9aw%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=0%2B5wiEDPDXkmSj3szEi3hQ%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=S5KzhaWIwliZsKou%2Brkn6w%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=8VflwRnauljOpgmRXUIAzQ%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=FI5d%2BryNY9DRW2eQxRSLPw%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=rxq3%2BykubqVlz9sm%2B4WYpw%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=x0a%2FUGinj3Wn3ztown9%2Fsg%3D%3D&profileDay=30&copyFrom=CTIndex",
"https://www.bybit.com/uk-UA/copyTrade/trade-center/detail?leaderMark=KacRNvEbxDUse5WA%2Fy5tPg%3D%3D&profileDay=30&copyFrom=CTIndex",
]

OUT = Path.home()/"Downloads"/"BYBIT_MASTER_COMPARE"
OUT.mkdir(parents=True, exist_ok=True)

def make_driver():
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    profile_dir = (Path.home()/".myshka"/"bybit-toptraders-browser").resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    opts = Options()
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--start-maximized")
    return webdriver.Edge(options=opts)

def lines_of(text:str):
    return [re.sub(r"\s+"," ",x).strip() for x in text.splitlines() if re.sub(r"\s+"," ",x).strip()]

def pct(s):
    if not s: return None
    m=re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*%",s)
    return float(m.group(1).replace(",",".")) if m else None

def num(s):
    if not s: return None
    m=re.search(r"([+-]?\d[\d,]*(?:\.\d+)?)",s)
    if not m: return None
    try:return float(m.group(1).replace(",",""))
    except:return None

def find_after(lines, labels, max_ahead=4):
    labs=[x.lower() for x in labels]
    for i,ln in enumerate(lines):
        ll=ln.lower()
        if any(l in ll for l in labs):
            # same line value
            tail=ln
            for lab in labels:
                pos=ll.find(lab.lower())
                if pos>=0:
                    tail=ln[pos+len(lab):].strip(" :")
                    break
            if tail and tail!=ln:
                return tail
            for j in range(i+1,min(len(lines),i+1+max_ahead)):
                if lines[j]:
                    return lines[j]
    return None

def extract_name(driver, lines):
    # Prefer visible headings.
    try:
        for sel in ("h1","h2","h3"):
            for el in driver.find_elements("css selector",sel):
                t=re.sub(r"\s+"," ",(el.text or "")).strip()
                if 2 <= len(t) <= 60 and t.lower() not in {"statistics","trades","followers","статистика","угоди"}:
                    return t
    except: pass
    ranks={"cadet","bronze","silver","gold","кадет","бронза","срібло","золото","vip 1","vip 2","vip 3","vip 4","vip 5"}
    for i,ln in enumerate(lines):
        if ln.lower() in ranks and i>0:
            for j in range(i-1,max(-1,i-5),-1):
                c=lines[j]
                if 1<len(c)<=60 and c.lower() not in {"in","ua"}:
                    return c
    return ""

def history_cut(text):
    markers=[
      "Past trades initiated by trader","Past Trades","Trade History","Trading History",
      "Минулі угоди, ініційовані трейдером","Минулі угоди","Історія угод"
    ]
    low=text.lower(); cuts=[]
    for m in markers:
        k=low.find(m.lower())
        if k>=0: cuts.append(k)
    return min(cuts) if cuts else len(text)

def parse_open_positions(text):
    cur=text[:history_cut(text)]
    lines=lines_of(cur)
    out=[]; seen=set()
    side_pat=r"(?:LONG|SHORT|ЛОНГ|ШОРТ)"
    for i,ln in enumerate(lines):
        u=ln.upper()
        m=re.search(r"([^\s|]{1,24}?)(USDT|USDC)\s*"+side_pat,u,re.I)
        if not m: continue
        raw=m.group(0)
        sm=re.search(side_pat,raw,re.I)
        side=sm.group(0).upper() if sm else ""
        side="SHORT" if side in {"SHORT","ШОРТ"} else "LONG"
        base=m.group(1).strip(" -_/|:")
        quote=m.group(2).upper()
        pair=(base.upper() if base.isascii() else base)+"/"+quote
        win=" | ".join(lines[i:min(len(lines),i+6)])
        lev=None; pnl=None
        lm=re.search(r"(\d+(?:\.\d+)?)\s*[xX]",win)
        if lm:
            try: lev=float(lm.group(1))
            except: pass
        pm=re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*%",win)
        if pm:
            try: pnl=float(pm.group(1).replace(",","."))
            except: pass
        k=(pair,side)
        if k not in seen:
            seen.add(k); out.append({"pair":pair,"side":side,"leverage":lev,"pnl_pct":pnl})
    return out

def detect_tags(lines):
    known=[
      "High Frequency","High Leverage","Winning Streak","Veteran","Highest ROI","Automated Strategy",
      "Висока частотність","Високе кредитне плече","Вдала серія","Бувалий","Найвища ROI","Автоматизована стратегія",
      "Short-term Trading","Короткострокова торгівля","Money Maker","Money-мейкер"
    ]
    found=[]
    joined="\n".join(lines).lower()
    for t in known:
        if t.lower() in joined and t not in found: found.append(t)
    return found

def get_leader_mark(url):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    return q.get("leaderMark",[""])[0]

def main():
    driver=make_driver()
    rows=[]
    try:
        for idx,url in enumerate(URLS,1):
            print(f"[{idx}/{len(URLS)}] opening profile...")
            driver.get(url)
            time.sleep(4.5)
            body=driver.find_element("tag name","body").text
            lines=lines_of(body)
            name=extract_name(driver,lines) or f"profile-{idx}"

            rec={
              "index":idx,
              "name":name,
              "leader_mark":get_leader_mark(url),
              "url":url,
              "followers":num(find_after(lines,["Follower(s)","Followers","Підписник(и)","Підписники"])),
              "trading_days":num(find_after(lines,["Trading Days","Торгові дні"])),
              "stability_index":num(find_after(lines,["Stability Index","Індекс стабільності"])),
              "aum_usdt":num(find_after(lines,["Assets Under Management","AUM","Активи в управл.","Активи в управл"])),
              "total_assets_usdt":num(find_after(lines,["Total Assets","Загалом активів"])),
              "profit_share_pct":pct(find_after(lines,["Profit Sharing","Profit Share","Частка прибутку"])),
              "roi_30d_pct":pct(find_after(lines,["ROI"])),
              "win_rate_pct":pct(find_after(lines,["Win Rate","% успішних угод","Успішних угод"])),
              "max_drawdown_30d_pct":pct(find_after(lines,["Max. Drawdown","Max Drawdown","Макс. просідання","Просадка"])),
              "master_pnl":num(find_after(lines,["Master Trader's P&L","Master's P&L","P&L майстер-трейдера"])),
              "follower_pnl":num(find_after(lines,["Follower's P&L","Followers' P&L","P&L підписників"])),
              "tags":detect_tags(lines),
              "open_positions":parse_open_positions(body),
            }
            rows.append(rec)
            (OUT/f"{idx:02d}_{re.sub(r'[^A-Za-z0-9_.-]+','_',name)[:50]}.txt").write_text(body,encoding="utf-8")
            print("   ",name,"ROI=",rec["roi_30d_pct"],"MDD=",rec["max_drawdown_30d_pct"],"open=",len(rec["open_positions"]))
    finally:
        driver.quit()

    jpath=OUT/"bybit_master_compare.json"
    cpath=OUT/"bybit_master_compare.csv"
    jpath.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    fields=["index","name","followers","trading_days","stability_index","aum_usdt","total_assets_usdt","profit_share_pct","roi_30d_pct","win_rate_pct","max_drawdown_30d_pct","master_pnl","follower_pnl","tags","open_positions","leader_mark","url"]
    with cpath.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            rr=dict(r)
            rr["tags"]=" | ".join(rr["tags"])
            rr["open_positions"]=" | ".join(f"{p['pair']} {p['side']} lev={p.get('leverage')} pnl={p.get('pnl_pct')}" for p in rr["open_positions"])
            w.writerow(rr)

    zbase = Path.home()/"Downloads"/"BYBIT_MASTER_COMPARE"
    zpath = shutil.make_archive(str(zbase), "zip", root_dir=OUT)

    print("\nDONE")
    print(jpath)
    print(cpath)
    print(zpath)
    print("\nPaste this summary back to ChatGPT:")
    for r in rows:
        print(json.dumps({
          "name":r["name"],"followers":r["followers"],"trading_days":r["trading_days"],
          "stability":r["stability_index"],"aum":r["aum_usdt"],"assets":r["total_assets_usdt"],
          "roi30":r["roi_30d_pct"],"win":r["win_rate_pct"],"mdd30":r["max_drawdown_30d_pct"],
          "tags":r["tags"],"open":r["open_positions"]
        },ensure_ascii=False))

if __name__=="__main__":
    main()
