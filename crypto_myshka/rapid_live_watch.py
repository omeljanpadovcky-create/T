"""Fast local LIVE observer: begin per-channel checks every 15 seconds.

Runs on an always-on user's own Windows PC/server. It is intentionally separate
from GitHub Actions and previous trading/analysis modules. Networking, YouTube
challenge screens, capture and vision may take longer than 15 seconds; no
overlapping task is started for a busy channel.

Public claims are NOT independently verified trades; never place orders.
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from youtube_analysts import CHANNELS
from pair_reports import update_from_live
from live_monitor import (
    AI_AVAILABLE, API_KEY, CAPTURE_INTERVAL, OUT, choose_stream_url,
    capture, get_stream, load, now, save, transcribe, vision,
)

DEFAULT_SECONDS = 15


def scan_channel(channel: dict) -> tuple[dict, dict | None]:
    started = now()
    row = {
        "id": channel["id"],
        "name": channel["name"],
        "handle": channel.get("handle"),
        "url": channel.get("url"),
        "live_page": (
            "https://www.youtube.com/" + channel["handle"] + "/live"
            if channel.get("handle") else None
        ),
        "checked_at": started,
        "status": "checking",
        "live": False,
        "stream": None,
    }
    if not channel.get("confirmed"):
        row["status"] = "source_unverified"
        return row, None

    stream, err = get_stream(channel)
    row["checked_at"] = now()
    if stream:
        row["status"] = "LIVE"
        row["live"] = True
        row["stream"] = {k: v for k, v in stream.items() if k != "_formats"}
        return row, stream
    if err and err.startswith("youtube_access_blocked"):
        row["status"] = "access_blocked"
    elif err:
        row["status"] = "check_error"
    else:
        row["status"] = "not_detected"
    if err:
        row["error"] = err
    return row, None


def inspect_frame(channel_id: str, channel_name: str, stream: dict) -> tuple[str, dict | None]:
    if not AI_AVAILABLE:
        return "requires_OPENAI_API_KEY_or_local_OLLAMA", None
    video_url = choose_stream_url(stream.get("_formats") or [])
    if not video_url:
        return "media_unavailable", None
    try:
        with TemporaryDirectory(prefix="crypto-myshka-live-") as folder:
            frame, audio = capture(video_url, Path(folder))
            if not frame:
                return "frame_unavailable", None
            spoken = transcribe(audio) if API_KEY else ""
            analysis = vision(frame, spoken)
            from pair_jev import analyze as jev_explain
            analysis["jev"] = jev_explain(analysis)
        return "visual_claim_reviewed", {
            "observed_at": now(),
            "channel_id": channel_id,
            "channel_name": channel_name,
            "video_id": stream["video_id"],
            "url": stream["url"],
            "claim_only": True,
            "independently_verified": False,
            "data_source": "public_live_frame_and_optional_audio",
            "observation": analysis,
        }
    except Exception as exc:
        return "analysis_unavailable: " + str(exc)[:120], None


def safe_result(future: Future, channel: dict) -> tuple[dict, dict | None]:
    try:
        return future.result()
    except Exception as exc:
        return ({
            "id": channel["id"], "name": channel["name"],
            "handle": channel.get("handle"), "url": channel.get("url"),
            "status": "check_error", "live": False,
            "checked_at": now(), "error": str(exc)[:140], "stream": None,
        }, None)


def watch(interval: int = DEFAULT_SECONDS, once: bool = False) -> None:
    # "Every 15 seconds" means a check is SCHEDULED for each eligible channel
    # every 15 seconds. Timeouts or access challenges may prevent completion.
    interval = max(15, interval)
    previous = load()
    observed = list(previous.get("observations") or [])[-100:]
    channel_by_id = {c["id"]: c for c in CHANNELS}
    states: dict[str, dict] = {
        c["id"]: {
            "id": c["id"], "name": c["name"], "handle": c.get("handle"),
            "url": c.get("url"), "live": False, "checked_at": None,
            "status": "checking" if c.get("confirmed") else "source_unverified",
            "stream": None,
        }
        for c in CHANNELS
    }
    checks: dict[str, Future] = {}
    frame_jobs: dict[str, Future] = {}
    last_capture_at: dict[str, float] = {}
    next_tick = time.monotonic()

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="myshka-live") as pool, \
         ThreadPoolExecutor(max_workers=2, thread_name_prefix="myshka-frame") as frames:
        try:
            while True:
                tick = time.monotonic()
                if tick < next_tick:
                    time.sleep(next_tick - tick)
                next_tick += interval
                if time.monotonic() >= next_tick:
                    # Do not create a burst of overlapping checks after stalls.
                    next_tick = time.monotonic() + interval

                for channel in CHANNELS:
                    key = channel["id"]
                    f = checks.get(key)
                    if f and f.done():
                        row, stream = safe_result(f, channel)
                        del checks[key]
                        old = states[key]
                        row["last_visual_check"] = old.get("last_visual_check")
                        row["observation_status"] = old.get("observation_status")
                        states[key] = row

                        pending_frame = frame_jobs.get(key)
                        eligible = (
                            stream and AI_AVAILABLE
                            and (pending_frame is None or pending_frame.done())
                            and time.monotonic() - last_capture_at.get(key, 0) >= CAPTURE_INTERVAL
                        )
                        if eligible:
                            last_capture_at[key] = time.monotonic()
                            row["last_visual_check"] = now()
                            row["observation_status"] = "frame_queued"
                            frame_jobs[key] = frames.submit(
                                inspect_frame, key, channel["name"], stream
                            )
                        elif stream and not AI_AVAILABLE:
                            row["observation_status"] = "requires_OPENAI_API_KEY_or_local_OLLAMA"

                    frame_future = frame_jobs.get(key)
                    if frame_future and frame_future.done():
                        del frame_jobs[key]
                        try:
                            status, event = frame_future.result()
                        except Exception as exc:
                            status, event = "analysis_unavailable: " + str(exc)[:120], None
                        states[key]["observation_status"] = status
                        if event:
                            observed.append(event)
                            observed = observed[-100:]

                    if channel.get("confirmed") and key not in checks:
                        checks[key] = pool.submit(scan_channel, channel)
                        states[key]["scan_pending"] = True
                    else:
                        states[key]["scan_pending"] = key in checks

                # Status reported only for recently CONFIRMED live streams. Never
                # use a stale positive result as a present-tense "LIVE" claim.
                current_time = time.time()
                rows = []
                for ch in CHANNELS:
                    row = dict(states[ch["id"]])
                    if row.get("checked_at"):
                        try:
                            observed_at = datetime.fromisoformat(row["checked_at"]).timestamp()
                            if current_time - observed_at > 75 and row.get("status") == "LIVE":
                                row.update(status="stale", live=False)
                        except ValueError:
                            row.update(status="stale", live=False)
                    rows.append(row)

                output = {
                    "version": 2,
                    "updated_at": now(),
                    "mode": "LOCAL LIVE watch; read-only",
                    "polling": "Each known channel check initiated every 15 seconds when previous call is done",
                    "scan_interval_seconds": interval,
                    "capture_interval_seconds": CAPTURE_INTERVAL,
                    "channels": rows,
                    "observations": observed,
                    "live_count": sum(x.get("live") is True for x in rows),
                    "ai_enabled": AI_AVAILABLE,
                    "ai_provider": "openai" if API_KEY else "local_ollama" if AI_AVAILABLE else "none",
                    "auto_trade": False,
                    "final_signal": "SKIP",
                    "notice": (
                        "Timed scan attempts are not a guarantee of 15-second market coverage. "
                        "A stream screenshot is not a verified fill or win-rate."
                    ),
                }
                save(output)
                try:
                    update_from_live(output)
                except Exception as exc:
                    print("Pair report generation failed:", str(exc)[:180], flush=True)
                print(
                    now(),
                    "| LIVE", output["live_count"],
                    "| waiting", sum(not f.done() for f in checks.values()),
                    "| vision", "enabled" if AI_AVAILABLE else "disabled",
                    "| 15s scan scheduled", flush=True,
                )
                if once:
                    return
        except KeyboardInterrupt:
            print("Local LIVE observer stopped. No trades executed.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=15, help="Seconds between local scan starts (minimum 15)")
    parser.add_argument("--once", action="store_true", help="Start one scan cycle for debugging")
    args = parser.parse_args()
    watch(args.interval, args.once)


if __name__ == "__main__":
    main()
