import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import ValidationError

from app.config import Settings
from app.connectors import DatabaseUnavailable, QueryCatalog, SQLServerConnector, SourceNotConfigured
from app.db import Database


class Driver:
    def __init__(self, rows=None, error=None):
        self.rows = rows or [{"connected": 1}]
        self.error = error
        self.options = None
        self.executed = None
        self.closed = self.rolled_back = False

    def connect(self, **options):
        self.options = options
        if self.error:
            raise RuntimeError(self.error)
        return self

    def cursor(self):
        return self

    def execute(self, sql, parameters):
        self.executed = (sql, parameters)

    def fetchmany(self, count):
        start = getattr(self, "position", 0)
        batch = self.rows[start : start + count]
        self.position = start + len(batch)
        return batch

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def connector(driver):
    settings = Settings(
        env_file=None,
        sqlserver_host="private-host",
        sqlserver_user="private-login",
        sqlserver_password="private-password",
        sqlserver_database="private-database",
        query_dir=Path("backend/queries").resolve(),
    )
    return SQLServerConnector(settings, QueryCatalog(settings.query_dir), driver)


async def test_sqlserver_bound_parameters_read_intent_and_exact_decimal_results():
    driver = Driver([{"revenue": Decimal("1234567890123.45"), "day": date(2026, 10, 1)}])
    db = connector(driver)
    value = "dbo'; DROP TABLE sales; --"
    rows = await db.fetch("database_catalog", {"schema_name": value})
    assert value not in driver.executed[0]
    assert driver.executed[1] == {"schema_name": value}
    assert driver.options["read_only"] is True
    assert driver.options["encryption"] == "require"
    # Login stays short; a running query gets the separate, longer limit.
    assert driver.options["login_timeout"] == 15
    assert driver.options["timeout"] == 600
    assert driver.closed and driver.rolled_back
    assert rows == [{"revenue": "1234567890123.45", "day": "2026-10-01"}]


async def test_missing_or_invalid_parameters_never_open_connection():
    driver = Driver()
    db = connector(driver)
    with pytest.raises(ValidationError):
        await db.fetch("database_catalog", {})
    with pytest.raises(ValidationError):
        await db.fetch("database_catalog", {"schema_name": "dbo", "sql": "SELECT *"})
    with pytest.raises(SourceNotConfigured):
        await db.fetch("../config", {})
    assert driver.options is None
    db.settings.sqlserver_password = ""
    with pytest.raises(SourceNotConfigured, match="SQLSERVER_PASSWORD"):
        await db.check()
    assert driver.options is None


async def test_driver_errors_never_disclose_connection_secrets():
    db = connector(
        Driver(error="18456 Login failed for private-login on private-host; private-password private-database")
    )
    with pytest.raises(DatabaseUnavailable) as error:
        await db.check()
    assert "authentication failed" in str(error.value)
    assert "private-" not in str(error.value)
    assert "private-" not in repr(db.settings)


async def test_schema_counts_are_paginated_and_table_schema_filter_is_bound():
    driver=Driver([{'schema_name':'sales','table_count':50,'view_count':3},{'schema_name':'archive','table_count':20,'view_count':1}])
    result=await connector(driver).schemas(limit=1)
    assert result['schemas']==[{'schema_name':'sales','table_count':50,'view_count':3}] and result['next_offset']==1
    assert 'GROUP BY TABLE_SCHEMA' in driver.executed[0] and driver.executed[1]=={'offset':0,'size':2}
    driver=Driver([{'schema_name':'sales','name':'Orders','kind':'BASE TABLE'}])
    attack="sales'; DROP TABLE Orders; --"
    await connector(driver).tables(schema=attack,name_contains='Orders')
    assert attack not in driver.executed[0] and driver.executed[1]['schema']==attack


async def test_large_results_are_rejected_without_silent_truncation():
    driver = Driver([{"value": 1}] * 501)
    with pytest.raises(DatabaseUnavailable, match="row limit"):
        await connector(driver).fetch("connection_check", {})
    assert driver.closed and driver.rolled_back


def test_catalog_rejects_writes_batches_and_invalid_schema(tmp_path):
    catalog = QueryCatalog(tmp_path)
    (tmp_path / "bad.json").write_text(json.dumps({"parameters_schema": {"type": "object", "properties": {}}}))
    for sql in ("DELETE FROM sales", "SELECT * INTO copy FROM sales", "SELECT 1; DROP TABLE sales"):
        (tmp_path / "bad.sql").write_text(sql)
        with pytest.raises(SourceNotConfigured):
            catalog.load("bad")
    (tmp_path / "bad.sql").write_text("SELECT 1")
    (tmp_path / "bad.json").write_text('{"parameters_schema":{"type":"invalid"}}')
    assert catalog.list()[0]["error"] == "Query files are invalid."


def test_existing_application_volume_migrates_without_losing_sources(tmp_path):
    db = Database(tmp_path / "old.sqlite3")
    db.execute(
        "CREATE TABLE data_sources(id TEXT PRIMARY KEY,name TEXT,kind TEXT,description TEXT,status TEXT,created_at TEXT)"
    )
    db.execute("INSERT INTO data_sources VALUES('existing','Existing source','sqlserver','','not_configured','old')")
    db.initialize()
    db.initialize()
    row = db.one("SELECT * FROM data_sources WHERE id='existing'")
    assert row["name"] == "Existing source" and row["last_error"] is None and row["checked_at"] is None
    assert db.one("SELECT version FROM schema_migrations WHERE version=2")
