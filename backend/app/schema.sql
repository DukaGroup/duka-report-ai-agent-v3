CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_migrations VALUES(1, strftime('%Y-%m-%dT%H:%M:%SZ','now'));
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL COLLATE NOCASE,
    name TEXT NOT NULL, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','member')), active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL,
    model TEXT, provider_thread_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(user_id,updated_at);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('completed','streaming','failed','interrupted')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,created_at);
CREATE TABLE IF NOT EXISTS data_sources (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'not_configured',
    created_at TEXT NOT NULL, last_error TEXT, checked_at TEXT
);
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY, source_id TEXT REFERENCES data_sources(id), name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', query_key TEXT, parameters_schema_json TEXT NOT NULL DEFAULT '{}',
    columns_schema_json TEXT NOT NULL DEFAULT '[]', enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_credentials (
    source_id TEXT PRIMARY KEY REFERENCES data_sources(id) ON DELETE CASCADE,
    ciphertext TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_grants (
    source_id TEXT NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY(source_id,user_id)
);
CREATE TABLE IF NOT EXISTS dataset_grants (
    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY(dataset_id,user_id)
);
CREATE TABLE IF NOT EXISTS dataset_snapshots (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
    dataset_id TEXT REFERENCES datasets(id), provenance_json TEXT NOT NULL,
    rows_json TEXT NOT NULL, captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_templates (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
    sections_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    template_id TEXT NOT NULL REFERENCES report_templates(id),
    snapshot_id TEXT REFERENCES dataset_snapshots(id), title TEXT NOT NULL,
    instructions TEXT NOT NULL, model TEXT, parameters_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','blocked')),
    content_json TEXT, error TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    stage TEXT, deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS reports_owner ON reports(user_id,created_at);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY, actor_id TEXT REFERENCES users(id), action TEXT NOT NULL,
    target_id TEXT, detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
