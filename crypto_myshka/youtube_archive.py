"""Incremental, provenance-aware archive of public trading YouTube videos.

Archive video links and concise extracted facts, NEVER copyrighted video files.
Revisit recent uploads, then crawl older pages in rotating batches. Unavailable
videos remain previously archived but are not described as fully analysed.
Trading screenshots and unverified influencer win rates are not market data.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from yt_dlp import YoutubeDL

try:
    from video_gemini import (
        analyze_public_youtube as gemini_analyze,
        available as gemini_available,
        MAX_PER_RUN as GEMINI_MAX_PER_RUN,
        DAILY_VIDEO_BUDGET as GEMINI_DAILY_BUDGET,
        UNSIZED_RESERVATION as GEMINI_UNSIZED_RESERVATION,
    )
except ImportError:
    from crypto_myshka.video_gemini import (
        analyze_public_youtube as gemini_analyze,
        available as gemini_available,
        MAX_PER_RUN as GEMINI_MAX_PER_RUN,
        DAILY_VIDEO_BUDGET as GEMINI_DAILY_BUDGET,
        UNSIZED_RESERVATION as GEMINI_UNSIZED_RESERVATION,
    )

try:
    from video_jev import summarize as jev_summarize, API_KEY as JEV_KEY, ENABLED as JEV_ENABLED
except ImportError:
    from crypto_myshka.video_jev import summarize as jev_summarize, API_KEY as JEV_KEY, ENABLED as JEV_ENABLED

try:
    from youtube_analysts import (
        CHANNELS, INSTRUMENT_RE, TIMEFRAME_RE, INDICATOR_RE,
        classify, normalize,
    )
except ImportError:
    from crypto_myshka.youtube_analysts import (
        CHANNELS, INSTRUMENT_RE, TIMEFRAME_RE, INDICATOR_RE,
        classify, normalize,
    )

ROOT = Path(__file__).resolve().parent
ARCHIVE_FILE = ROOT / "data" / "youtube_archive.json"
SOURCE_FILE = ROOT / "data" / "youtube_analysts.json"
SECTIONS = ("videos", "streams", "shorts")
RECENT_COUNT = max(5, min(30, int(os.getenv("VIDEO_ARCHIVE_RECENT", "12"))))
BACKFILL_PAGE = max(10, min(100, int(os.getenv("VIDEO_ARCHIVE_PAGE", "45"))))
DETAIL_LIMIT = max(0, min(12, int(os.getenv("VIDEO_ARCHIVE_DETAILS", "5"))))
MAX_ENTRIES = max(50, min(12000, int(os.getenv("VIDEO_ARCHIVE_MAX_ENTRIES", "5000"))))
JEV_MAX_PER_RUN = max(0, min(5, int(os.getenv("YOUTUBE_JEV_MAX_PER_RUN", "2"))))
_jev_used = 0
VID_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT = "https://www.youtube.com/watch?v="
ISOTIME = lambda: datetime.now(timezone.utc).isoformat()


def load(path: Path, fallback: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except (OSError, ValueError, TypeError):
        return fallback


def safe_text(value: Any, limit: int = 240) -> str:
    return normalize(str(value or ""))[:limit]


def make_entry(video_id: str, channel: dict, kind: str, title: str = "",
               upload_date: Any = None, duration: Any = None) -> dict:
    if not VID_ID.fullmatch(video_id):
        raise ValueError("Invalid YouTube video ID")
    date = str(upload_date or "")
    if not re.fullmatch(r"\d{8}", date):
        date = None
    seconds = duration if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None
    return {
        "id": video_id,
        "channel_id": channel["id"],
        "channel_name": channel["name"],
        "channel_handle": channel.get("handle"),
        "kind": kind,
        "title": safe_text(title, 260) or "Назва недоступна",
        "url": YT + video_id,
        "thumbnail": "https://i.ytimg.com/vi/" + video_id + "/hqdefault.jpg",
        "upload_date": date,
        "duration_seconds": int(seconds) if seconds and seconds >= 0 else None,
        "indexed_at": ISOTIME(),
        "details_checked_at": None,
        "content_status": "metadata_only",
        "caption_status": "not_checked",
        "analysis": classify(title),
        "video_reviewed": False,
        "market_quotes_verified": False,
        "gemini": {"status": "not_analyzed", "reason": "Gemini has not been called"},
        "jev": {"status": "not_analyzed", "reason": "Only metadata have been collected"},
    }


def merge_entry(previous: dict, new: dict) -> dict:
    """Keep enriched historical records, but use fresh index titles/dates."""
    output = dict(previous)
    for k in ("title", "upload_date", "duration_seconds", "thumbnail", "channel_name", "channel_handle"):
        if new.get(k) not in (None, "", "Назва недоступна"):
            output[k] = new[k]
    output["last_seen_index_at"] = ISOTIME()
    return output


def list_segment(channel: dict, section: str, start: int, count: int) -> list[dict]:
    if section not in SECTIONS:
        raise ValueError("Unsupported section")
    options = {
        "quiet": True, "no_warnings": True, "ignoreerrors": True,
        "extract_flat": "in_playlist", "skip_download": True,
        "playliststart": max(1, start),
        "playlistend": max(1, start) + count - 1,
        "socket_timeout": 12, "retries": 1,
    }
    address = f'https://www.youtube.com/{channel["handle"]}/{section}'
    with YoutubeDL(options) as ydl:
        listing = ydl.extract_info(address, download=False) or {}
    entries = []
    for item in (listing.get("entries") or []):
        if not isinstance(item, dict):
            continue
        vid = str(item.get("id") or "")
        if not VID_ID.fullmatch(vid):
            continue
        entries.append({
            "id": vid, "title": item.get("title"),
            "upload_date": item.get("upload_date"),
            "duration": item.get("duration"),
        })
    return entries


def extract_captions(details: dict) -> dict:
    """Scan available public json3 subtitle text; STORE ONLY short excerpts/facts."""
    tracks = details.get("subtitles") or details.get("automatic_captions") or {}
    for language in ("uk", "ru", "en", "en-US", "uk-UA", "ru-RU"):
        formats = tracks.get(language) or []
        item = next((f for f in formats if isinstance(f, dict)
                     and f.get("ext") == "json3" and f.get("url")), None)
        if item is None:
            continue
        try:
            res = requests.get(item["url"], timeout=12,
                               headers={"User-Agent": "Mozilla/5.0"}, stream=True)
            res.raise_for_status()
            payload = bytearray()
            for chunk in res.iter_content(chunk_size=32768):
                payload.extend(chunk)
                if len(payload) > 2_000_000:
                    raise ValueError("Subtitle source exceeds 2MB limit")
            entries = json.loads(payload.decode("utf-8")).get("events") or []
            segments = []
            for item in entries[:18000]:
                if not isinstance(item, dict):
                    continue
                snippets = item.get("segs") or []
                for seg in snippets:
                    if isinstance(seg, dict) and seg.get("utf8"):
                        segments.append(str(seg["utf8"]))
            # In-memory transcript supports rule-based extraction over the entire
            # available caption track; no full transcript stored/re-published.
            full_text = normalize(" ".join(segments))
            return {
                "status": "available" if full_text else "empty",
                "language": language,
                "full_text": full_text[:175_000],
                "truncated": len(full_text) > 175_000 or len(entries) > 18000,
                "events_processed": min(len(entries), 18000),
            }
        except (ValueError, OSError, requests.RequestException, UnicodeError):
            continue
    return {"status": "unavailable", "language": None, "full_text": "",
            "truncated": False, "events_processed": 0}


def facts_from_text(title: str, description: str, captions: dict) -> dict:
    full = safe_text(title, 260) + " " + safe_text(description, 1700) + " " + str(captions.get("full_text") or "")
    pairs = list(dict.fromkeys(re.sub(r"\s+", " ", s.upper()).strip().replace("_", "/").replace("-", "/")
                               for s in INSTRUMENT_RE.findall(full)))[:15]
    timeframes = list(dict.fromkeys(s.upper() for s in TIMEFRAME_RE.findall(full)))[:10]
    indicators = list(dict.fromkeys(s.upper() for s in INDICATOR_RE.findall(full)))[:15]
    # For claim classification only, sample the accessible transcript evenly to
    # avoid implying that a title alone constitutes a full video review.
    subtitle = str(captions.get("full_text") or "")
    spread = subtitle[:700] + " " + subtitle[len(subtitle)//2:len(subtitle)//2+550] + " " + subtitle[-550:]
    context = classify(title, description, spread)
    context["mentioned_instruments"] = pairs
    context["mentioned_timeframes"] = timeframes
    context["mentioned_indicators"] = indicators
    context["content_excerpt"] = safe_text(subtitle[:280], 280) if captions.get("status") == "available" else ""
    context["source_evidence"] = (
        "Доступні субтитри: пошук згадок у тексті" if captions.get("status") == "available"
        else "Лише назва й опис, зміст кадрів не перевірено"
    )
    context["verified_chart_patterns"] = False
    context["executed_trades_verified"] = False
    return context


def enrich(video: dict) -> dict:
    options = {"quiet": True, "no_warnings": True, "skip_download": True,
               "socket_timeout": 15, "retries": 1, "ignoreerrors": False}
    output = dict(video)
    output["details_checked_at"] = ISOTIME()
    try:
        with YoutubeDL(options) as ydl:
            details = ydl.extract_info(video["url"], download=False) or {}
        if not isinstance(details, dict) or not details.get("id"):
            raise ValueError("Video details unavailable")
        title = safe_text(details.get("title") or output.get("title"), 260)
        description = safe_text(details.get("description"), 1600)
        captions = extract_captions(details)
        output["title"] = title
        date = str(details.get("upload_date") or output.get("upload_date") or "")
        output["upload_date"] = date if re.fullmatch(r"\d{8}", date) else None
        output["caption_status"] = captions["status"]
        output["caption_language"] = captions.get("language")
        output["caption_events_processed"] = captions.get("events_processed", 0)
        output["captions_truncated"] = captions.get("truncated", False)
        output["analysis"] = facts_from_text(title, description, captions)
        global _jev_used
        if captions["status"] == "available" and JEV_ENABLED and JEV_KEY and _jev_used < JEV_MAX_PER_RUN:
            _jev_used += 1
            output["jev"] = jev_summarize(
                title=title, description=description,
                subtitles=captions["full_text"],
                instruments=output["analysis"]["mentioned_instruments"],
                indicators=output["analysis"]["mentioned_indicators"],
            )
        else:
            output["jev"] = {
                "status":"not_analyzed",
                "reason": ("No public captions" if captions["status"] != "available" else
                           "JEV key missing, disabled, or per-run budget reached"),
            }
        output["content_status"] = ("captions_scanned" if captions["status"] == "available"
                                    else "title_description_only")
        output["video_reviewed"] = False  # Audio/video was NOT sampled.
        output.pop("details_error", None)
    except Exception as exc:
        output["details_error"] = safe_text(type(exc).__name__ + ": " + str(exc), 180)
        output["content_status"] = output.get("content_status") or "metadata_only"
        output["caption_status"] = output.get("caption_status") or "unavailable"
    return output


def seed_older_records(entries: dict, source: dict) -> int:
    """Preserve genuine records gathered by the earlier 8-video collector."""
    known = {x["id"]: x for x in CHANNELS if x.get("confirmed")}
    seeded = 0
    for channel in (source.get("channels") or []):
        selected = known.get(channel.get("id")) if isinstance(channel, dict) else None
        if not selected:
            continue
        for item in (channel.get("videos") or []):
            if not isinstance(item, dict) or item.get("sample_only"):
                continue
            vid = str(item.get("id") or "")
            if not VID_ID.fullmatch(vid) or vid in entries:
                continue
            entry = make_entry(vid, selected, "videos", item.get("title", ""), item.get("upload_date"))
            entry["analysis"] = item.get("analysis") if isinstance(item.get("analysis"), dict) else entry["analysis"]
            entry["content_status"] = "legacy_metadata_only"
            entries[vid] = entry
            seeded += 1
    return seeded


def run_gemini_video_batch(existing: dict, previous: dict, processor=gemini_analyze,
                           *, enabled: bool = True) -> dict:
    """Process video directly: does not depend on subtitles or yt-dlp details.

    Persist conservative UTC daily processing budget. Retry failing videos
    on a future day, not every run. A disabled API never marks them analyzed.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    old_budget = previous.get("gemini_budget") or {}
    if not isinstance(old_budget, dict) or old_budget.get("utc_date") != today:
        budget = {"utc_date": today, "reserved_seconds": 0, "requests_attempted": 0}
    else:
        budget = {
            "utc_date": today,
            "reserved_seconds": max(0, int(old_budget.get("reserved_seconds") or 0)),
            "requests_attempted": max(0, int(old_budget.get("requests_attempted") or 0)),
        }
    if not enabled or GEMINI_MAX_PER_RUN <= 0:
        return budget
    used = 0
    # Prioritize affordable Shorts, then recent videos, then long replays.
    # Never guarantee full archive analysis or exceed configured free-tier cap.
    priority = {"shorts": 0, "videos": 1, "streams": 2}
    due = sorted(existing.values(), key=lambda v: (
        priority.get(v.get("kind"), 3),
        -(int(v.get("upload_date")) if str(v.get("upload_date") or "").isdigit() else 0),
        str(v.get("id") or ""),
    ))
    for entry in due:
        if used >= GEMINI_MAX_PER_RUN:
            break
        if not VID_ID.fullmatch(str(entry.get("id") or "")):  # checked by archive IDs
            continue
        info = entry.get("gemini") or {}
        if isinstance(info, dict) and info.get("status") == "gemini_video_summary":
            continue
        # Wait 24 hours between failed attempts (provider quota, access errors).
        checked = entry.get("gemini_checked_at")
        if isinstance(checked, str):
            try:
                if datetime.fromisoformat(checked.replace("Z", "+00:00")).date().isoformat() == today:
                    continue
            except ValueError:
                pass
        duration = entry.get("duration_seconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
            seconds = max(1, int(duration))
        else:
            seconds = 120 if entry.get("kind") == "shorts" else GEMINI_UNSIZED_RESERVATION
        if seconds > GEMINI_DAILY_BUDGET or budget["reserved_seconds"] + seconds > GEMINI_DAILY_BUDGET:
            continue
        budget["reserved_seconds"] += seconds
        budget["requests_attempted"] += 1
        used += 1
        entry["gemini_checked_at"] = datetime.now(timezone.utc).isoformat()
        try:
            result = processor(str(entry["id"]), title=str(entry.get("title") or ""))
            if not isinstance(result, dict):
                result = {"status": "unavailable", "reason": "Non-object Gemini response"}
        except Exception as exc:
            result = {"status": "unavailable", "error_type": type(exc).__name__}
        entry["gemini"] = result
        if result.get("status") == "gemini_video_summary":
            entry["content_status"] = "gemini_video_analyzed"
            entry["ai_video_processed"] = True
            # This remains an unverified model interpretation, not a verified trade.
            entry["market_quotes_verified"] = False
            entry["video_reviewed"] = False
        if result.get("http_status") in (401, 402, 429):
            # Stop after a key/quota/billing error, do not repeatedly query it.
            break
    return budget


def build(previous: dict, seed: dict, fetcher=list_segment, detailer=enrich,
          include_enrichment: bool = True,
          gemini_processor=gemini_analyze, use_gemini: bool | None = None) -> dict:
    existing = {str(x.get("id")): dict(x) for x in previous.get("videos") or []
                if isinstance(x, dict) and VID_ID.fullmatch(str(x.get("id") or ""))}
    seeded = seed_older_records(existing, seed)
    progress = previous.get("progress") if isinstance(previous.get("progress"), dict) else {}
    progress = dict(progress)
    errors = []
    newly_found = 0
    scans = 0
    for channel in CHANNELS:
        if not channel.get("confirmed") or not channel.get("handle"):
            continue
        for kind in SECTIONS:
            key = channel["id"] + ":" + kind
            data = dict(progress.get(key) or {})
            if data.get("backfill_complete"):
                # The leading page still refreshes for new uploads; older pages
                # are retained, without falsely assuming removed/private coverage.
                chunks = [(1, RECENT_COUNT, False)]
            else:
                cursor = max(1, int(data.get("next_start") or 1))
                chunks = [(1, RECENT_COUNT, False)]
                if cursor <= 1:
                    chunks.append((RECENT_COUNT + 1, BACKFILL_PAGE, True))
                else:
                    chunks.append((cursor, BACKFILL_PAGE, True))
            data["last_attempt"] = ISOTIME()
            good = 0
            for offset, amount, backfill in chunks:
                scans += 1
                try:
                    found = fetcher(channel, kind, offset, amount)
                except Exception as exc:
                    errors.append({"channel":channel["id"], "section":kind,
                                   "error":safe_text(type(exc).__name__ + ": " + str(exc), 190)})
                    data["status"] = "access_unavailable"
                    continue
                good += 1
                for row in found:
                    vid = str(row.get("id") or "")
                    if not VID_ID.fullmatch(vid):
                        continue
                    candidate = make_entry(vid, channel, kind, row.get("title"),
                                           row.get("upload_date"), row.get("duration"))
                    if vid in existing:
                        existing[vid] = merge_entry(existing[vid], candidate)
                    else:
                        existing[vid] = candidate
                        newly_found += 1
                if backfill:
                    data["next_start"] = offset + len(found)
                    if len(found) < amount:
                        data["backfill_complete"] = bool(found or existing)
                    else:
                        data["backfill_complete"] = False
                data["last_successful_scan"] = ISOTIME()
            if good:
                data["status"] = "ok"
            progress[key] = data

    if include_enrichment:
        # Retry previously inaccessible videos on later runs but never claim
        # their metadata confirms the underlying chart.
        due = [v for v in existing.values() if
               v.get("content_status") in ("metadata_only", "legacy_metadata_only")
               and not v.get("details_checked_at")]
        due.sort(key=lambda v: (v.get("upload_date") or "", v["id"]), reverse=True)
        for item in due[:DETAIL_LIMIT]:
            existing[item["id"]] = detailer(item)

    gemini_budget = run_gemini_video_batch(
        existing, previous, gemini_processor,
        enabled=(gemini_available() if use_gemini is None else use_gemini)
                and include_enrichment,
    )

    # Keep a deterministic bounded published JSON file, while recording count;
    # once the configured safety maximum is reached, output is explicitly partial.
    ordered = sorted(existing.values(),key=lambda v: (v.get("upload_date") or "",
                       v.get("indexed_at") or "",v["id"]),reverse=True)
    cutoff = len(ordered) > MAX_ENTRIES
    ordered = ordered[:MAX_ENTRIES]
    return {
        "version": 1,
        "updated_at": ISOTIME(),
        "status": "partial_or_growing" if errors or not all(
            (progress.get(ch["id"]+":"+kind) or {}).get("backfill_complete")
            for ch in CHANNELS if ch.get("confirmed") for kind in SECTIONS
        ) or cutoff else "accessible_backfill_scanned",
        "scope": "Publicly accessible videos, stream replays and shorts from configured channels",
        "all_videos_guaranteed": False,
        "videos_copied_or_hosted": False,
        "full_video_content_reviewed": False,
        "market_quotes_verified": False,
        "video_count": len(ordered),
        "gemini_analyzed_count": sum(1 for row in ordered if (row.get("gemini") or {}).get("status") == "gemini_video_summary"),
        "gemini_configured": gemini_available(),
        "gemini_mode": "direct_public_youtube_video_understanding",
        "gemini_budget": gemini_budget,
        "newly_discovered": newly_found,
        "legacy_entries_seeded": seeded,
        "scan_calls": scans,
        "errors": errors[:30],
        "progress": progress,
        "channels": [{k:v for k,v in c.items() if k in ("id","name","handle","url")} for c in CHANNELS
                     if c.get("confirmed")],
        "videos": ordered,
    }


def main() -> None:
    old = load(ARCHIVE_FILE, {"videos": [], "progress": {}})
    source = load(SOURCE_FILE, {"channels": []})
    archive = build(old, source)
    ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ARCHIVE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(archive, ensure_ascii=False, separators=(",", ":"))+"\n", encoding="utf-8")
    temporary.replace(ARCHIVE_FILE)
    print(json.dumps({"indexed": archive["video_count"],
                      "new": archive["newly_discovered"],
                      "gemini_connected":archive["gemini_configured"],
                      "gemini_video_summaries":archive["gemini_analyzed_count"],
                      "errors": len(archive["errors"]),
                      "status": archive["status"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
