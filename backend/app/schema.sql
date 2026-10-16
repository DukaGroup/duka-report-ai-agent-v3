CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_migrations VALUES(1, strftime('%Y-%m-%dT%H:%M:%SZ','now'));
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL COLLATE NOCASE,
    name TEXT NOT NULL, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('devs','president','manager')), active INTEGER NOT NULL DEFAULT 1,
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
CREATE TABLE IF NOT EXISTS model_preferences (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK(provider IN ('chatgpt','claude'))
);
CREATE TABLE IF NOT EXISTS conversation_provider_threads (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK(provider IN ('chatgpt','claude')),
    thread_id TEXT NOT NULL,
    PRIMARY KEY(conversation_id,provider)
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('completed','streaming','failed','interrupted')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,created_at);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    name TEXT NOT NULL, extension TEXT NOT NULL, size INTEGER NOT NULL,
    purpose TEXT NOT NULL CHECK(purpose IN ('analysis','template')), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message_attachments (
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    attachment_id TEXT NOT NULL REFERENCES attachments(id),
    PRIMARY KEY(message_id,attachment_id)
);
CREATE INDEX IF NOT EXISTS attachments_conversation ON attachments(conversation_id);
CREATE TABLE IF NOT EXISTS data_sources (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'not_configured',
    created_at TEXT NOT NULL, last_error TEXT, checked_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1, credential_profile TEXT NOT NULL DEFAULT 'legacy'
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
CREATE INDEX IF NOT EXISTS reports_conversation ON reports(conversation_id);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY, actor_id TEXT REFERENCES users(id), action TEXT NOT NULL,
    target_id TEXT, detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traffic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
    direction TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL,
    correlation_id TEXT, user_id TEXT, bytes INTEGER NOT NULL DEFAULT 0,
    duration_ms REAL, detail_json TEXT NOT NULL DEFAULT '{}', payload_json TEXT,
    payload_truncated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS traffic_direction ON traffic_events(direction,id);
CREATE TABLE IF NOT EXISTS calculation_runs (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    provenance_json TEXT NOT NULL, inputs_json TEXT NOT NULL, result_json TEXT NOT NULL,
    created_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status='complete')
);
CREATE INDEX IF NOT EXISTS calculation_owner ON calculation_runs(user_id,conversation_id);

CREATE TABLE IF NOT EXISTS conversation_settings (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    reasoning_effort TEXT
);
CREATE TABLE IF NOT EXISTS report_settings (
    report_id TEXT PRIMARY KEY REFERENCES reports(id) ON DELETE CASCADE,
    reasoning_effort TEXT
);
CREATE TABLE IF NOT EXISTS message_revisions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    previous_content TEXT NOT NULL,
    assistant_content TEXT NOT NULL,
    assistant_status TEXT NOT NULL,
    attachment_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_branches (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    fork_message_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS archived_calculations (
    calculation_id TEXT PRIMARY KEY REFERENCES calculation_runs(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES conversation_branches(id) ON DELETE CASCADE
);
