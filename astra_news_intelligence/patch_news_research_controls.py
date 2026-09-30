from pathlib import Path
import re, sys

MARKER="MYSHKA_NEWS_RESEARCH_CONTROLS_V1"

def _after(s,pattern,addition,label):
    m=re.search(pattern,s,flags=re.MULTILINE)
    if not m: raise RuntimeError(label+" not found")
    return s[:m.end()]+addition+s[m.end():]

def patch_api(path: Path):
    s=path.read_text(encoding="utf-8-sig")
    compile(s,str(path),"exec")
    if MARKER in s:
        print("[OK] News Research Controls already present")
        return

    news_out_re=(
        r"^from \.news_outcomes import init as news_outcomes_init, status as news_outcomes_status, "
        r"report as news_outcomes_report, observe_results as news_outcomes_observe\n"
    )
    if not re.search(news_out_re,s,flags=re.MULTILINE):
        raise RuntimeError("News Outcomes import not found. Install News Intelligence first.")

    imports=(
        "from .news_research_controls import status as news_research_status, "
        "news_quality_report, story_report as news_story_report, "
        "live_readiness_report\n"
    )
    s=_after(s,news_out_re,imports,"News Outcomes import")

    # Add diagnostic status to /health if the News Outcomes line exists.
    health_re=r'^[ \t]+"news_intelligence_outcomes":\s*news_outcomes_status\(\),\n'
    if re.search(health_re,s,flags=re.MULTILINE):
        s=_after(
            s,health_re,
            f'        # {MARKER}\n        "news_research_controls": news_research_status(),\n',
            "News Outcomes health",
        )

    endpoints=(
        f'# {MARKER}\n'
        '@app.get("/news-research/quality")\n'
        'def news_research_quality_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return news_quality_report()\n\n\n'
        '@app.get("/news-research/stories")\n'
        'def news_research_stories_api(limit: int = 30, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return news_story_report(limit=limit)\n\n\n'
        '@app.get("/live-readiness/status")\n'
        'def live_readiness_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return news_research_status()\n\n\n'
        '@app.get("/live-readiness/report")\n'
        'def live_readiness_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return live_readiness_report()\n\n\n'
    )
    anchor='@app.get("/news-intelligence/status")\n'
    if anchor not in s:
        anchor='@app.get("/forward-experiments/status")\n'
    if anchor not in s:
        raise RuntimeError("API endpoint insertion point not found")
    s=s.replace(anchor,endpoints+anchor,1)

    compile(s,str(path),"exec")
    path.write_text(s,encoding="utf-8")
    print("[OK] api.py patched: News Research Controls + Live Readiness")

def main():
    if len(sys.argv)!=2:
        raise SystemExit("usage: patch_news_research_controls.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve()/"api.py")

if __name__=="__main__":
    main()
