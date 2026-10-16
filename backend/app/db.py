"""Application metadata only. Business databases will use separate connectors."""

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate_roles(self):
        # SQLite CHECK constraints require a table rebuild. Disable FK actions
        # outside the transaction so sessions, grants and history retain IDs.
        with sqlite3.connect(self.path, timeout=15) as c:
            table = c.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()
            if not table or "'admin'" not in table[0]:
                return
            c.execute("PRAGMA foreign_keys=OFF")
            try:
                c.execute("BEGIN IMMEDIATE")
                c.execute("CREATE TABLE users_new (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL COLLATE NOCASE, name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('devs','president','manager')), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)")
                c.execute("INSERT INTO users_new SELECT id,email,name,password_hash,CASE role WHEN 'admin' THEN 'devs' WHEN 'member' THEN 'manager' ELSE role END,active,created_at FROM users")
                c.execute("DROP TABLE users")
                c.execute("ALTER TABLE users_new RENAME TO users")
                if c.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("Role migration would break existing references.")
                c.commit()
            except BaseException:
                c.rollback()
                raise
            finally:
                c.execute("PRAGMA foreign_keys=ON")

    def initialize(self):
        self.migrate_roles()
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript((Path(__file__).parent / "schema.sql").read_text())
            traffic_columns = {row[1] for row in c.execute('PRAGMA table_info(traffic_events)')}
            if 'payload_json' not in traffic_columns:
                c.execute('ALTER TABLE traffic_events ADD COLUMN payload_json TEXT')
            if 'payload_truncated' not in traffic_columns:
                c.execute('ALTER TABLE traffic_events ADD COLUMN payload_truncated INTEGER NOT NULL DEFAULT 0')
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(10,?)',(now(),))
            columns = {row[1] for row in c.execute("PRAGMA table_info(data_sources)")}
            for name in ("last_error", "checked_at"):
                if name not in columns:
                    c.execute(f"ALTER TABLE data_sources ADD COLUMN {name} TEXT")
            if "enabled" not in columns:
                c.execute("ALTER TABLE data_sources ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
            if "credential_profile" not in columns:
                c.execute("ALTER TABLE data_sources ADD COLUMN credential_profile TEXT NOT NULL DEFAULT 'legacy'")
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(9,?)", (now(),))
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(2,?)", (now(),))
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(3,?)", (now(),))
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(4,?)", (now(),))
            report_columns = {row[1] for row in c.execute("PRAGMA table_info(reports)")}
            if "stage" not in report_columns:
                c.execute("ALTER TABLE reports ADD COLUMN stage TEXT")
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(5,?)", (now(),))
            if "deleted_at" not in report_columns:
                c.execute("ALTER TABLE reports ADD COLUMN deleted_at TEXT")
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(6,?)", (now(),))
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(7,?)", (now(),))
            if not c.execute("SELECT 1 FROM schema_migrations WHERE version=8").fetchone():
                # Old provider rollouts contain the removed per-turn style text.
                # Rebuild their model context from original local messages once;
                # conversations, uploads, report snapshots and exports stay intact.
                c.execute("UPDATE conversations SET provider_thread_id=NULL")
                c.execute("INSERT INTO schema_migrations VALUES(8,?)", (now(),))
            c.execute("UPDATE messages SET status='interrupted' WHERE status='streaming'")
            c.execute(
                "UPDATE reports SET status='failed', error='Application restarted during generation.' WHERE status IN ('queued','running')"
            )
            templates = [
                ("executive", "Executive overview", "Key performance, changes, findings, and next steps."),
                ("sales", "Sales performance", "Revenue, sales trends, leading products, and opportunities."),
                ("operations", "Operations brief", "Operational performance, exceptions, and recommended actions."),
            ]
            for identifier, title, description in templates:
                c.execute(
                    "INSERT OR IGNORE INTO report_templates(id,name,description,sections_json) VALUES(?,?,?,?)",
                    (
                        identifier,
                        title,
                        description,
                        json.dumps(["Overview", "Findings", "Recommendations", "Data limitations"]),
                    ),
                )

    def one(self, sql, params=()):
        with self.connect() as c:
            row = c.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql, params=()):
        with self.connect() as c:
            return [dict(row) for row in c.execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        with self.connect() as c:
            return c.execute(sql, params).rowcount

    def audit(self, actor, action, target=None, detail=None):
        self.execute(
            "INSERT INTO audit_events(id,actor_id,action,target_id,detail_json,created_at) VALUES(?,?,?,?,?,?)",
            (uid(), actor, action, target, json.dumps(detail or {}), now()),
        )

    def archive_chat_branch(self, c, conversation_id, target, messages):
        """Called inside the accepted retry transaction, before removing its tail."""
        branch_id = uid()
        attachments = [dict(r) for r in c.execute(
            "SELECT ma.* FROM message_attachments ma JOIN messages m ON m.id=ma.message_id WHERE m.conversation_id=?", (conversation_id,))]
        revisions = [dict(r) for r in c.execute("SELECT * FROM message_revisions WHERE conversation_id=?", (conversation_id,))]
        reports = [r[0] for r in c.execute("SELECT id FROM reports WHERE conversation_id=? AND created_at>=?", (conversation_id, target["created_at"]))]
        calculations = [r[0] for r in c.execute("SELECT id FROM calculation_runs WHERE conversation_id=? AND created_at>=? AND id NOT IN (SELECT calculation_id FROM archived_calculations)", (conversation_id, target["created_at"]))]
        c.execute("INSERT INTO conversation_branches VALUES(?,?,?,?,?)", (
            branch_id, conversation_id, target["id"],
            json.dumps({"messages": messages, "attachments": attachments, "revisions": revisions,
                        "report_ids": reports, "calculation_ids": calculations}, ensure_ascii=False), now()))
        # Saved reports keep their snapshots and exports in the Reports library.
        c.execute("UPDATE reports SET conversation_id=NULL WHERE conversation_id=? AND created_at>=?", (conversation_id, target["created_at"]))
        c.executemany("INSERT INTO archived_calculations VALUES(?,?)", [(identifier, branch_id) for identifier in calculations])
        return branch_id

    def delete_conversation(self, conversation_id, user_id):
        """Detach saved reports before deleting chat history, in one transaction."""
        with self.connect() as c:
            if not c.execute(
                "SELECT id FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)
            ).fetchone():
                return False
            c.execute("UPDATE reports SET conversation_id=NULL WHERE conversation_id=?", (conversation_id,))
            c.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id))
            return True

    def empty_report_trash(self, user_id, directory):
        """Purge only this user's trash, preserving any still-referenced snapshots."""
        with self.connect() as connection:
            # Serialize restore/delete against the exact set whose files are removed.
            connection.execute("BEGIN IMMEDIATE")
            reports = connection.execute(
                "SELECT id,snapshot_id,status FROM reports WHERE user_id=? AND deleted_at IS NOT NULL",
                (user_id,),
            ).fetchall()
            if any(report["status"] in ("queued", "running") for report in reports):
                raise ValueError("Stop reports in the trash before emptying it.")
            for report in reports:
                identifier = report["id"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
                    raise ValueError("Invalid saved report identifier.")
                # Remove cached exports first. On a filesystem failure the SQL
                # transaction rolls back, and snapshots can recreate removed caches.
                for path in [directory / (identifier + ".xlsx"), directory / (identifier + ".tmp"), *directory.glob(identifier + ".*.tmp")]:
                    path.unlink(missing_ok=True)
            connection.execute("DELETE FROM reports WHERE user_id=? AND deleted_at IS NOT NULL", (user_id,))
            for snapshot_id in {report["snapshot_id"] for report in reports if report["snapshot_id"]}:
                connection.execute(
                    "DELETE FROM dataset_snapshots WHERE id=? AND user_id=? AND NOT EXISTS(SELECT 1 FROM reports WHERE snapshot_id=?)",
                    (snapshot_id, user_id, snapshot_id),
                )
            connection.execute(
                "INSERT INTO audit_events(id,actor_id,action,target_id,detail_json,created_at) VALUES(?,?,?,NULL,?,?)",
                (uid(), user_id, "report.trash_emptied", json.dumps({"deleted_count": len(reports)}), now()),
            )
            return len(reports)
