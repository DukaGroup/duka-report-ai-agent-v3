# SQL Server integration

SQL Server is implemented using `pymssql`. Enter each source's `SQLSERVER_HOST`, `SQLSERVER_PORT`, `SQLSERVER_USER`, `SQLSERVER_PASSWORD`, and `SQLSERVER_DATABASE` in **Data sources → Add source**. The other fields are the database display name, type, and optional description. **Configure connection** edits existing SQL Server sources; blank fields keep saved values. The database type cannot be changed on an existing source. Saved settings are applied immediately without restarting the container.

Connection credentials are encrypted with Fernet in the separate `source_credentials` table. The key is `/data/source-credentials.key`, created with mode 0600 inside the private data volume. The API returns only configuration presence booleans, not saved values or ciphertext. Validation errors exclude submitted input values, and logs/audit events exclude credentials. Each source has its own connection settings. Keep backups of the data volume/key together; a missing or unreadable key fails closed for sources relying on stored credentials. An explicitly configured environment connection does not depend on that key. Volume encryption does not protect against an attacker who already has access to both the database and key.

SQL settings in the project-root `.env` are authoritative when configured, taking precedence over form-saved credentials and container variables. Docker mounts the file read-only at `/run/duka.env`. The backend parses it with interpolation disabled and resolves it before connection checks/queries. If SQL environment settings are absent, per-source encrypted credentials remain supported. After editing the file, use `docker compose up -d --force-recreate`; this also handles editors that replace the file inode. Never put credentials in datasets, query files, chat, or Git. Other database types remain placeholders.

Use a dedicated SQL Server login granted SELECT on only the reporting tables/views it needs. The driver requests `read_only=True`, but this is a routing hint, not write-permission enforcement. Transport encryption defaults to `require`; the driver and server TLS/certificate behavior should be validated for your deployment. Login and queries time out after 15 seconds by default. Raw driver messages are never returned or logged by this connector.

Add or configure a SQL Server source under **Data sources**, test its connection, define a dataset with an approved query key, enable it, and grant access to each relevant member (including administrators). The admin overview shows whether each environment variable is set, status, last check time, and sanitized errors. Enabled means the script is available; the source status indicates the last connection result.

## Automatic reporting from chat

Once the source is configured, administrators can immediately ask the assistant to discover tables and create reports. Manual dataset definitions are optional. The tools invoke backend Python scripts (`database_tools.py` and `connectors.py`), with credentials resolved privately by the connector registry. Members need a source-level grant, managed through **Qasja te burimi**. This grant permits discovery/reading of all tables available to the source's SQL login, so restrict that login or reporting views as appropriate. Dataset-only grants do not give database-wide access.

The assistant uses `list_sources` → `list_tables` (paginated, with optional all/table/view and name-fragment filters) → `describe_table` → `query_database`/`create_database_report`. Schema discovery reads SQL Server metadata views, including foreign keys. Queries are structural plans validated by Pydantic and compiled by Python; no arbitrary SQL, connection strings, file access or shell commands are accepted. The compiler verifies column references, quotes identifiers, and binds filter values. It supports up to four joined tables, WHERE filters, date buckets, grouping, sorting, numeric aggregates and bounded reads. The model must account for join cardinality and business definitions; generated interpretation still needs review.

Example structural query (the model builds it after inspecting actual tables):

```json
{
  "tables": [{"schema": "dbo", "name": "Sales", "alias": "s"}],
  "select": [{"column": "s.Date", "alias": "month", "bucket": "month"}],
  "metrics": [{"function": "sum", "column": "s.Amount", "alias": "revenue"}],
  "filters": [{"column": "s.Date", "operator": "gte", "value": "2026-01-01"}],
  "group_by": ["month"],
  "order_by": [{"column": "month", "direction": "asc"}],
  "limit": 100
}
```

A query reads one extra row to detect a limited preview. Preview results are explicitly marked `truncated`; reports reject them to prevent partial sums being presented as complete totals. Aggregate metrics run against the full filtered SQL data before the result limit is applied. Report snapshots include the normalized query and output column types; decimal precision is preserved. SQL Server 2012 or later is required for the metadata pagination/date bucket functions. Advanced calculations outside the structural tool can still use curated backend query scripts below.

## Approved backend scripts

`backend/queries/<query_key>.sql` and `<query_key>.json` form a script pair. Docker mounts the directory read-only into the container so scripts can be deployed without rebuilding the image. After modifying a schema, disable/re-enable its dataset to synchronize parameter/column schemas. The query catalog is reloaded on requests. Keep the SQL directory accessible only to trusted operators.

The bundled `connection_check` reads `SELECT 1`. `database_catalog` reads table/view column metadata with the parameter `{"schema_name":"dbo"}`. Neither provides business performance figures. Grant schema metadata access deliberately. Large schemas may exceed the result limit; add a narrower catalog query for those databases.

For example, **after adapting this to your actual tables**, deploy `sales_summary.sql`:

```sql
SELECT sale_date AS sale_date, SUM(net_amount) AS revenue, COUNT(*) AS orders
FROM reporting.sales
WHERE sale_date >= %(start_date)s AND sale_date < %(end_date)s
GROUP BY sale_date
ORDER BY sale_date;
```

And `sales_summary.json`:

```json
{
  "name": "Sales summary",
  "description": "Daily revenue and orders for a date range (end date exclusive).",
  "parameters_schema": {
    "type": "object",
    "properties": {
      "start_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
      "end_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}
    },
    "required": ["start_date", "end_date"],
    "additionalProperties": false
  },
  "columns_schema": [
    {"name": "sale_date", "type": "date"},
    {"name": "revenue", "type": "decimal"},
    {"name": "orders", "type": "integer"}
  ]
}
```

This example is documentation, not an installed query against invented tables. Parameters are bound by the driver; never interpolate values into SQL. Only one SELECT is allowed, with no batches, SELECT INTO, DDL, DML, EXEC, or remote query functions. The conservative script check can reject otherwise valid queries containing reserved words; adapt aliases if needed. Server-enforced SELECT permissions remain mandatory. Use aggregation queries for large data and include row/tenant filtering in approved scripts or views as appropriate for your users.

## Model and report workflow

The assistant lists authorized datasets and their parameter/column schemas, asks for missing parameters, fetches rows, analyzes results, and can call `create_report` to save a report. Tool arguments cannot contain a host, password, connection string, SQL text, or arbitrary destination. No connection configuration is sent to the model. Authorized schema metadata and query results are sent to the user's subscription when they request analysis.

Reports use the same granted datasets and parameter validation as chat. They fetch once, record an immutable snapshot, compute numeric totals, and generate structured output using the subscription. SQL decimals become exact strings; declare those columns as `decimal`/`numeric`/`money` in the manifest so backend summaries include them without float conversion. Empty data blocks generation. Results exceeding 500 rows, 100 columns, or 100 KB are rejected instead of silently truncated. Reports are available as Markdown, JSON, and source CSV; PDF/Excel are not implemented.

## Other connectors

`backend/app/connectors.py` defines:

```python
class ReportConnector(Protocol):
    async def fetch(self, query_key: str, parameters: dict[str, Any]) -> list[dict[str, Any]]: ...
```

Additional implementations must load credentials from server-side secrets, use SELECT-only accounts and timeouts, map query keys to fixed queries, bind parameters, enforce row/tenant authorization, and return bounded JSON-compatible rows.

Register the connector during FastAPI lifespan:

```python
app.state.connectors.register(source_id, connector)
```

Add their connection checks, script catalogs and enable logic before enabling them in the UI. Keep parameter schemas self-contained and disallow remote references.

Both chat tools and report creation verify the current user's dataset grant before using the registry. Reports fetch data once and generate against that immutable snapshot. Use registered aggregation queries for large databases and compute important figures in Python/database code.

Automated tests cover bound parameters, credential redaction, access grants, script validation, result bounds, decimal conversion, old-volume migration, and model-driven report persistence using a protocol fixture. A live SQL Server connection cannot be verified until actual connection variables and database tables are supplied.

## Connection versus query errors

A successful SELECT 1 confirms connectivity, not the usability of every view. SQL error 208 identifies an unavailable object/dependency; 207 identifies an unavailable column. Driver diagnostics are classified and sanitized. A query error preserves the connected status and is displayed separately; model tools receive the safe category and numeric code. Use a working base table or repair the view definition/permissions in SQL Server. No credentials or raw driver text are exposed.
