-- src/auto_reply/store/migrations_sql/0001_initial.sql
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads_seen (
  thread_id TEXT PRIMARY KEY,
  last_msg_id TEXT,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  customer_msg TEXT NOT NULL,
  draft_text TEXT NOT NULL,
  intent TEXT NOT NULL,
  sensitive INTEGER NOT NULL DEFAULT 0,
  confidence REAL,
  context_json TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  auto_sent INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS drafts_status_idx ON drafts(status);
CREATE INDEX IF NOT EXISTS drafts_thread_idx ON drafts(thread_id);

CREATE TABLE IF NOT EXISTS sent_replies (
  draft_id INTEGER PRIMARY KEY REFERENCES drafts(id),
  final_text TEXT NOT NULL,
  edit_distance REAL NOT NULL DEFAULT 0.0,
  sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  draft_id INTEGER NOT NULL REFERENCES drafts(id),
  thumb INTEGER,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS training_labels (
  draft_id INTEGER PRIMARY KEY REFERENCES drafts(id),
  label INTEGER NOT NULL,
  source TEXT NOT NULL,
  features_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_id TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0.0,
  purpose TEXT NOT NULL,
  draft_id INTEGER,
  at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS cost_log_at_idx ON cost_log(at);
CREATE INDEX IF NOT EXISTS cost_log_purpose_idx ON cost_log(purpose);

CREATE TABLE IF NOT EXISTS wiki_index (
  product_id TEXT NOT NULL,
  chunk_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  embedding BLOB NOT NULL,
  PRIMARY KEY (product_id, chunk_id)
);
