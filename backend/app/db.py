"""Application metadata only. Business databases will use separate connectors."""

import json
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

    def initialize(self):
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript((Path(__file__).parent / "schema.sql").read_text())
            columns = {row[1] for row in c.execute("PRAGMA table_info(data_sources)")}
            for name in ("last_error", "checked_at"):
                if name not in columns:
                    c.execute(f"ALTER TABLE data_sources ADD COLUMN {name} TEXT")
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
