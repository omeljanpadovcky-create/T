from pathlib import Path
import re, sys

MARKER="MYSHKA_NEWS_INTELLIGENCE_SHADOW_V1"

def _after(s,pattern,addition,label):
    m=re.search(pattern,s,flags=re.MULTILINE)
    if not m: raise RuntimeError(label+" not found")
    return s[:m.end()]+addition+s[m.end():]

def patch_api(path: Path):
    s=path.read_text(encoding="utf-8-sig")
    compile(s,str(path),"exec")
    if MARKER in s:
        print("[OK] News Intelligence SHADOW V1 already present")
        return

    fwd_re=(r"^from \.forward_experiment_lab import init as forward_experiment_init, "
            r"status as forward_experiment_status, report as forward_experiment_report, "
            r"recent as forward_experiment_recent, observe_results as forward_experiment_observe\n")
    if not re.search(fwd_re,s,flags=re.MULTILINE):
        raise RuntimeError("Forward Experiment Lab import not found")

    imports=(
        "from .news_analyzer import start as news_intelligence_start, status as news_intelligence_status, "
        "report as news_intelligence_report, refresh_now as news_intelligence_refresh\n"
        "from .news_outcomes import init as news_outcomes_init, status as news_outcomes_status, "
        "report as news_outcomes_report, observe_results as news_outcomes_observe\n"
    )
    s=_after(s,fwd_re,imports,"Forward Experiment import")

    s=_after(
        s,r"^[ \t]+forward_experiment_init\(\)\n",
        f"    # {MARKER}\n    news_intelligence_start()\n    news_outcomes_init()\n",
        "Forward Experiment startup",
    )

    s=_after(
        s,r'^[ \t]+"forward_experiment_lab":\s*forward_experiment_status\(\),\n',
        f'        # {MARKER}\n        "news_intelligence": news_intelligence_status(),\n'
        '        "news_intelligence_outcomes": news_outcomes_status(),\n',
        "Forward Experiment health",
    )

    endpoints=(
        f'# {MARKER}\n'
        '@app.get("/news-intelligence/status")\n'
        'def news_intelligence_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return {"status":"ok","analyzer":news_intelligence_status(),"outcomes":news_outcomes_status()}\n\n\n'
        '@app.get("/news-intelligence/report")\n'
        'def news_intelligence_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return {"status":"ok","mode":"NEWS_INTELLIGENCE_SHADOW","analyzer":news_intelligence_report(),"outcomes":news_outcomes_report(),'
        '"changes_trading_decisions":False,"changes_paper_execution":False,"live_execution":False}\n\n\n'
        '@app.post("/news-intelligence/refresh-now")\n'
        'def news_intelligence_refresh_api(limit: int = 2, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return news_intelligence_refresh(limit=limit)\n\n\n'
    )
    anchor='@app.get("/forward-experiments/status")\n'
    if anchor not in s: raise RuntimeError("Forward Experiment endpoint anchor not found")
    s=s.replace(anchor,endpoints+anchor,1)

    s=_after(
        s,r"^[ \t]+forward_experiment_observe\(results\)\n",
        f"        # {MARKER}: cached News Intelligence SHADOW only\n"
        "        news_outcomes_observe(results)\n",
        "Forward Experiment observer",
    )

    compile(s,str(path),"exec")
    path.write_text(s,encoding="utf-8")
    print("[OK] api.py patched: News Intelligence SHADOW V1")

def main():
    if len(sys.argv)!=2: raise SystemExit("usage: patch_news_intelligence.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve()/"api.py")

if __name__=="__main__": main()
