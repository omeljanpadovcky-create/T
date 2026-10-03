CREATE TABLE IF NOT EXISTS materials (
  id text PRIMARY KEY,
  source text NOT NULL,
  mode text,
  risk integer,
  knowledge boolean NOT NULL DEFAULT false,
  title text NOT NULL,
  summary text,
  url text,
  published_at timestamptz,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS materials_source_url_uq
  ON materials(source, url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS materials_published_idx ON materials(published_at DESC);
CREATE INDEX IF NOT EXISTS materials_source_idx ON materials(source);
CREATE INDEX IF NOT EXISTS materials_search_idx ON materials
  USING gin (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(summary,'')));

CREATE TABLE IF NOT EXISTS news_events (
  id text PRIMARY KEY,
  title text NOT NULL,
  summary text,
  url text,
  published_at timestamptz,
  impact integer,
  source_count integer,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS news_published_idx ON news_events(published_at DESC);
CREATE INDEX IF NOT EXISTS news_impact_idx ON news_events(impact DESC);
CREATE INDEX IF NOT EXISTS news_search_idx ON news_events
  USING gin (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(summary,'')));

CREATE TABLE IF NOT EXISTS jev_analyses (
  event_id text PRIMARY KEY REFERENCES news_events(id) ON DELETE CASCADE,
  engine text,
  analysis_level text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS telegram_posts (
  channel text NOT NULL,
  post_id bigint NOT NULL,
  item_id text,
  text text,
  url text,
  published_at timestamptz,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(channel, post_id)
);

CREATE INDEX IF NOT EXISTS telegram_published_idx ON telegram_posts(published_at DESC);
CREATE INDEX IF NOT EXISTS telegram_search_idx ON telegram_posts
  USING gin (to_tsvector('simple', coalesce(text,'')));

CREATE TABLE IF NOT EXISTS market_snapshots (
  captured_at timestamptz PRIMARY KEY,
  payload jsonb NOT NULL
);
