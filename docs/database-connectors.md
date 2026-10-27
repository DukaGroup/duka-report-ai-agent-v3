# SQL Server integration

SQL Server is implemented using `pymssql`. Enter each connection's `SQLSERVER_HOST`, `SQLSERVER_PORT`, `SQLSERVER_USER`, and `SQLSERVER_PASSWORD` in **Burimet e të dhënave → Shto lidhje**. `SQLSERVER_DATABASE` is optional; blank means server-wide discovery. The display name identifies the connection; type and description are separate fields. **Configure connection** edits existing SQL Server sources; blank fields keep saved values. An existing source can switch between SQL Server and SAP HANA by supplying the correct new SQL port. Saved settings are applied immediately without restarting the backend.

Production connection credentials are saved in **`/var/lib/duka-agent/runtime.env`**, selected by the native service's `ENV_FILE`. Local development uses the ignored project-root `.env`. Each form-configured source uses a stable `DUKA_CONNECTION_<ID>_` prefix; APIs show only configuration-presence flags and the prefix. The private file uses locks, literal quoting and an fsynced recovery journal. Keep production ownership `duka:duka`, mode `600`, and back it up with the full private data directory.

Legacy Fernet-encrypted rows migrate to this environment file on startup; `source_credentials` then stores only the marker `env`. Retain `/var/lib/duka-agent/source-credentials.key` for old-backup recovery. Named/generic environment sources and independent form-saved profiles stay distinct. Blank fields retain saved values. Deleting a saved connection removes its managed profile; disconnecting retains it. After manual production file changes, restart `duka-agent`. Neither credentials nor environment-file access is given to the model.

Connection updates use a shared partial-update contract: blank or omitted fields retain their existing private values, including environment-backed profiles and saved TLS/CA settings. Only entered values are replaced; a new connection still needs complete credentials. `PATCH /api/admin/sources/{id}` accepts individual fields without requiring name/type again. Set `discover_databases: true` to explicitly remove a default database; an empty database field on an update keeps it. The same rules apply to every connection instance of both supported drivers.

## SAP HANA

SAP HANA uses `hdbcli`, not `pymssql`. Select **SAP HANA**, provide `HANA_HOST`, the actual `HANA_PORT`, `HANA_USER`, `HANA_PASSWORD`, and optionally the tenant `HANA_DATABASE`. Existing SQL Server sources can change type, with an explicit new SQL port required. HANA TLS and certificate validation default to true; the form exposes both options. HANA Cloud normally uses 443 and its direct tenant endpoint; on-premise SQL ports depend on instance and tenant. A Business One company schema is not a tenant database name.

Tenant discovery uses `SYS.M_DATABASE` and, if permitted, `SYS_DATABASES.M_DATABASES`; unavailable catalog permissions are disclosed. Every returned tenant is checked for actual access, and its business schemas are discovered using `SYS.TABLES`/`SYS.VIEWS`. A tenant-only login can discover its own visible schemas without SYSTEMDB access. For tenants unreachable through one endpoint, add separate connections. The structured query compiler emits HANA identifiers, date expressions and positional parameters. Both preview and complete Excel queries preserve the existing grants and export-limit checks. Legacy SQL Server query scripts are rejected for HANA. `discover_sales` recognizes SAP Business One invoice/credit tables when present; other SAP schemas use generic discovery rather than guessed table names.

Use a dedicated SQL Server login granted SELECT on only the reporting tables/views it needs. The driver requests `read_only=True`, but this is a routing hint, not write-permission enforcement. Transport encryption defaults to `require`; the driver and server TLS/certificate behavior should be validated for your deployment. Login and queries time out after 15 seconds by default. Raw driver messages are never returned or logged by this connector.

Add or configure a SQL Server source under **Data sources**, test its connection, define a dataset with an approved query key, enable it, and assign access to the relevant Managers. Devs and President have automatic access. The admin overview shows whether each environment variable is set, status, last check time, and sanitized errors. Enabled means the script is available; the source status indicates the last connection result.

## Automatic reporting from chat

Once the source is configured, administrators can immediately ask the assistant to discover tables and create reports. Manual dataset definitions are optional. The tools invoke backend Python scripts (`database_tools.py` and `connectors.py`), with credentials resolved privately by the connector registry. Managers need explicit database/company selections, managed through **Zgjidh qasjen** (also opened from **Qasja te burimi**). These selections restrict discovery and reads within the source SQL login's permissions. Pre-existing source-wide grants retain their original meaning until explicitly replaced; the compatibility PUT endpoint no longer creates new broad grants. Dataset-only grants do not give database-wide access.

The assistant uses `discover_databases` (all granted sources and accessible online business databases) → `list_tables` (paginated, with optional all/table/view and name-fragment filters) → `describe_table` → `query_database`/`create_database_report`. Pass the inventoried `source_id` and `database` to table discovery, descriptions, previews and report tools. Schema discovery reads SQL Server metadata views, including foreign keys. Supplementary report analyses may use different sources/databases, with provenance preserved in the snapshot and Excel source headings. Catalog discovery uses master independently of the configured business database; system databases are not exposed for business queries. Queries are structural plans validated by Pydantic and compiled by Python; no arbitrary SQL, connection strings, file access or shell commands are accepted. The compiler verifies column references, quotes identifiers, and binds filter values. It supports up to four joined tables, WHERE filters, date buckets, grouping, sorting, numeric aggregates and bounded reads. The model must account for join cardinality and business definitions; generated interpretation still needs review.

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

`backend/queries/<query_key>.sql` and `<query_key>.json` form a script pair. The native service reads that directory through `REPORT_QUERY_DIR`. Deploy script changes as a trusted operator; the restricted backend service has read access but cannot alter the application tree. After modifying a schema, disable/re-enable its dataset to synchronize parameter/column schemas. The query catalog is reloaded on requests. Keep the SQL directory accessible only to trusted operators.

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

ChatGPT and Claude use the same generic `calculate_data` workflow. The model investigates real metadata and evidence, writes its own `calculate(tables)` Python, and chooses every business formula, date rule, exclusion, sign, join, classification and currency treatment. The backend retrieves the model-selected complete query/attachment inputs, checks authorization, validates and isolates execution, and captures the exact outputs. It does not implement business calculations or automatically sum numeric columns. Query aggregates run only as specified in the model's structural query plan.

For SAP FI identity discovery, the optional `inspect_sap_context(source_id, database, schema)` reads raw T001/T000 metadata without choosing companies or calculating amounts. Other schemas/engines use the same general discovery and structural query tools. Neither company names nor client numbers establish production scope; the model must investigate actual evidence. No company, account list or historical cutoff is built into the generic calculation runner.

The model returns concise summary/control datasets alongside complete detail. Chat previews are bounded, but calculation inputs and captured outputs include all matching rows within configured resource limits; failure never publishes a partial result. The backend provides counts, schemas and hashes for transport/audit, not accounting totals. Financial code uses exact Decimal helpers with explicit rounding. A successful script proves execution, not the accuracy of the model's business interpretation.

When Excel is requested, `create_calculation_report` selects named datasets from that exact run without querying again or changing formulas. The model also writes the workbook presentation script. Grants are rechecked at capture/export; excluded raw inputs remain private audit evidence and are stripped from model context/public exports. Calculating alone creates no report. Saved reports survive conversation deletion.

Fixed balance tools and direct `balance_reconciliation` report inputs are retired and cannot execute. Older chats receive recovery instructions: `create_database_report` with `CALCULATE_DATA` plus a newline and the JSON plan runs the same model-authored workflow; `EXPORT_CALCULATION` exports the resulting ID. No thread/history reset is required. Legacy balance rendering/validation remains solely to read previously saved snapshots.

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

## HANA certificate verification

The driver now explicitly uses OpenSSL and the system CA bundle. If SAP HANA uses an internal/private CA, obtain the trusted root and intermediate public certificates from the SAP/database administrator or hosting provider. Configure the chain in **Konfiguro lidhjen → Certifikata CA e besuar** (`HANA_TLS_CA_CERTIFICATE`). An optional `HANA_TLS_SERVER_NAME` identifies the verified DNS identity in the certificate when the TCP host is an IP/alias. Neither setting disables TLS verification. Certificate values remain in the source's private environment profile; the native backend creates a private combined trust bundle under `/var/lib/duka-agent/tls`, outside model workspaces. The browser receives configuration-presence flags only.

Do not trust a certificate solely because an unverified connection presented it. No certificate is fetched or trusted automatically. An expired certificate must be renewed on the HANA server. The admin panel distinguishes expiration, hostname mismatch, and general certificate verification errors without revealing raw driver diagnostics. See [SAP server certificate authentication](https://help.sap.com/docs/HANA_CLOUD_DATABASE/f1b440ded6144a54ada97ff95dac7adf/a95754380f4c4c05b728524f9cd652e3.html).

## Large SAP catalog discovery

Use `discover_databases` → `list_schemas` for connection/structure checks. `list_schemas` returns paginated schema names and table/view counts through server-side aggregation. Then use `list_tables` with a returned `schema` and optional `name_contains` to inspect relevant table groups. Both SQL Server and HANA bind the schema/name filters; source grants and selected-database checks remain in force. Full table catalogs remain paginated and available when needed.

HANA `discover_sales` filters OINV/INV1/ORIN/RIN1 names inside `SYS.TABLES`, pages all matching schemas, and reads their real columns. It does not enumerate unrelated SAP tables. No matches means these Business One tables were not found, not that a tenant has no sales data. Other SAP deployments require generic schema/table discovery and their actual accounting definitions. These changes affect metadata discovery only; complete report reads and breakdowns retain their existing guarantees.

## Member access boundaries

Devs and President have automatic access to all registered SQL Server/HANA sources and their databases/companies. President is a business role, not a user/system administrator. New Managers receive database/company assignments in the add-member form; existing members can be edited with **Zgjidh qasjen**. Grants are saved atomically with account creation. `source_access_policies` marks granular policies and `database_grants` stores selected databases plus server-verified company scope definitions. Older source grants remain compatible until explicitly replaced.

The access catalog discovers live Business Central `Company.Name` identities and their physical table prefixes, Business One `OADM.CompnyName` schemas, and SAP FI `T001` client/company-code identities. Clients/company codes are exact pairs, not independent client/code sets. Company labels do not authorize arbitrary tables. Prefix access checks the most specific live company prefix; schema grants require an unambiguous company schema. Unknown table boundaries fail closed.

`ConnectorRegistry.database_call` applies the same policy to both providers, previews, complete queries, calculation inputs and report breakdowns. Database discovery returns only assigned databases and their company scope. Restricted queries compile permission predicates inside derived base-table references, before model filters, joins, grouping and aggregation; left-join semantics are preserved. These permission predicates are server-owned and cannot be supplied or removed by model query arguments. Views and unbounded registered scripts are unavailable to granular Managers because their cross-database/company dependencies are not verified. Safe SAP shared reference tables and chart metadata use their verified client/chart boundary; tables lacking a provable company boundary require an appropriately separated reporting source.

Each captured query carries a permission receipt. Access is rechecked after reads, calculation execution/export and before publishing reports. Grant changes discard in-flight results and prevent reuse of broader captured calculations. Existing published private reports remain retained as previously authorized snapshots.
