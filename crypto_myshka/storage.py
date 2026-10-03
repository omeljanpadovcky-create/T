from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ROOT = Path(__file__).resolve().parent
SCHEMA = ROOT / "db" / "schema.sql"


def enabled() -> bool:
    return bool(DATABASE_URL)


def _connect():
    import psycopg
    return psycopg.connect(DATABASE_URL)


def ensure_schema() -> bool:
    if not enabled():
        return False
    sql = SCHEMA.read_text(encoding="utf-8")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    return True


def sync_feed(payload: dict) -> int:
    if not enabled():
        return 0
    from psycopg.types.json import Jsonb

    ensure_schema()
    items = payload.get("items") or []
    market = payload.get("market") or {}
    generated_at = payload.get("generated_at") or datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        with conn.cursor() as cur:
            for x in items:
                cur.execute(
                    """
                    INSERT INTO materials
                      (id, source, mode, risk, knowledge, title, summary, url, published_at, payload, updated_at)
                    VALUES
                      (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                    ON CONFLICT (id) DO UPDATE SET
                      source=EXCLUDED.source,
                      mode=EXCLUDED.mode,
                      risk=EXCLUDED.risk,
                      knowledge=EXCLUDED.knowledge,
                      title=EXCLUDED.title,
                      summary=EXCLUDED.summary,
                      url=EXCLUDED.url,
                      published_at=EXCLUDED.published_at,
                      payload=EXCLUDED.payload,
                      updated_at=now()
                    """,
                    (
                        x.get("id"), x.get("source"), x.get("mode"), x.get("risk"),
                        bool(x.get("knowledge")), x.get("title"), x.get("summary"),
                        x.get("url"), x.get("published_at"), Jsonb(x),
                    ),
                )

            cur.execute(
                """
                INSERT INTO market_snapshots (captured_at, payload)
                VALUES (%s, %s)
                ON CONFLICT (captured_at) DO NOTHING
                """,
                (generated_at, Jsonb(market)),
            )
        conn.commit()
    return len(items)


def sync_news(payload: dict) -> int:
    if not enabled():
        return 0
    from psycopg.types.json import Jsonb

    ensure_schema()
    items = payload.get("items") or []
    with _connect() as conn:
        with conn.cursor() as cur:
            for x in items:
                cur.execute(
                    """
                    INSERT INTO news_events
                      (id, title, summary, url, published_at, impact, source_count, payload, updated_at)
                    VALUES
                      (%s,%s,%s,%s,%s,%s,%s,%s,now())
                    ON CONFLICT (id) DO UPDATE SET
                      title=EXCLUDED.title,
                      summary=EXCLUDED.summary,
                      url=EXCLUDED.url,
                      published_at=EXCLUDED.published_at,
                      impact=EXCLUDED.impact,
                      source_count=EXCLUDED.source_count,
                      payload=EXCLUDED.payload,
                      updated_at=now()
                    """,
                    (
                        x.get("id"), x.get("title"), x.get("summary"), x.get("url"),
                        x.get("published_at"), x.get("impact"), x.get("source_count"),
                        Jsonb(x),
                    ),
                )
                ai = x.get("jev_ai")
                if ai:
                    cur.execute(
                        """
                        INSERT INTO jev_analyses
                          (event_id, engine, analysis_level, payload, updated_at)
                        VALUES (%s,%s,%s,%s,now())
                        ON CONFLICT (event_id) DO UPDATE SET
                          engine=EXCLUDED.engine,
                          analysis_level=EXCLUDED.analysis_level,
                          payload=EXCLUDED.payload,
                          updated_at=now()
                        """,
                        (
                            x.get("id"), x.get("analysis_engine"),
                            x.get("analysis_level"), Jsonb(ai),
                        ),
                    )
        conn.commit()
    return len(items)


def sync_archive(payload: dict) -> int:
    if not enabled():
        return 0
    from psycopg.types.json import Jsonb

    ensure_schema()
    posts = payload.get("posts") or []
    with _connect() as conn:
        with conn.cursor() as cur:
            for p in posts:
                cur.execute(
                    """
                    INSERT INTO telegram_posts
                      (channel, post_id, item_id, text, url, published_at, payload, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,now())
                    ON CONFLICT (channel, post_id) DO UPDATE SET
                      item_id=EXCLUDED.item_id,
                      text=EXCLUDED.text,
                      url=EXCLUDED.url,
                      published_at=EXCLUDED.published_at,
                      payload=EXCLUDED.payload,
                      updated_at=now()
                    """,
                    (
                        p.get("channel"), p.get("post_id"), p.get("id"), p.get("text"),
                        p.get("url"), p.get("published_at"), Jsonb(p),
                    ),
                )
        conn.commit()
    return len(posts)
