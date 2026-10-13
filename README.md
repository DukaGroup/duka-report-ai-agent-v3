# Duka Report Agent

A custom conversation/reporting workspace with a **Python backend**, **React frontend**, **admin panel**, and one Docker application container.

Conversations use the official **Codex CLI signed in with a ChatGPT subscription**, following the subscription-backed harness approach described by [T3 Code](https://t3.codes/). Python talks to `codex app-server` over local stdio. There is no OpenAI SDK, API-key configuration, or API billing fallback. Codex manages authentication and credential renewal. Your subscription's **Codex allowance** applies; this does not import your existing ChatGPT chats or memories.

## Start

Create `.env` from `.env.example` if it does not exist. Keep your existing `.env` and credentials.

```bash
docker compose up --build -d
```

Open **http://localhost:8080**.

1. Create the first workspace administrator with your own password.
2. Choose **Lidh llogarinë** or open **Lidhja me ChatGPT**.
3. Open the OpenAI sign-in link and enter the one-time device code.
4. Complete ChatGPT sign-in. The app detects completion automatically.
5. Select an available model and send a message.

An eligible subscription with Codex access is required. Enable **device code login** in ChatGPT security settings if necessary; workspace admins may need to permit it. Enter your ChatGPT password only on OpenAI's sign-in page. Workspace login and ChatGPT connection are separate: admins create app members, and each member connects their own subscription. Each user has an isolated Codex credential/history directory and process.

## Voice

- Click the microphone, speak, and click again to send the recording.
- **Fillo bisedën me zë** detects pauses, transcribes, sends, reads the reply, and listens again after playback.
- **Ndalo zërin** stops recording/playback; **Ndalo përgjigjen** interrupts generation.
- Select **Shqip** under **Gjuha e të folurit**, allow microphone access, and speak naturally. **Anglisht** and automatic detection are also available. Transcription uses local CPU Whisper; playback uses browser/device speech voices. No paid audio API is used.
- First transcription downloads the speech model into the persistent volume. `WHISPER_MODEL=tiny` is lighter; `base`/`small` generally provide better multilingual transcription with more resources.
- Microphone access requires **localhost or HTTPS**. OS/browser voice availability varies. This is turn-based voice with transcription/generation latency, not native ChatGPT realtime voice.

## Reports

Use **Reports → Create report**, select a template, and supply manual JSON rows:

```json
[
  {"month": "September", "revenue": 12500, "orders": 84},
  {"month": "October", "revenue": 14900, "orders": 102}
]
```

The backend saves the exact data snapshot/provenance, computes basic decimal totals, generates a report through your subscription, validates structured output, and automatically creates a formatted **Excel (.xlsx)** workbook, with Markdown, JSON, and source CSV available as additional downloads. Review AI-generated interpretations against the underlying data.

Reports without data or with an unconfigured source are saved as **blocked**, with an explanation; no report inference is sent. No figures or sample rows are inserted automatically.

Admin controls include member creation/disable, service/runtime status, and audit events. **Data sources** defines source metadata, registered-query datasets, and per-member access grants. SQL Server connects through private per-source settings entered in the admin form (or legacy backend environment variables) and approved query scripts. The admin panel tests connections, displays sanitized errors, and enables datasets. The assistant can discover authorized database tables, inspect columns/relationships, filter/join/aggregate real data, and save reports directly from chat, without manual dataset definitions. The frontend is Albanian. Chat replies, spoken replies, and report narratives default to English unless another language is explicitly requested.

See [architecture](docs/architecture.md), [schema](docs/schema.md), and [SQL Server setup and query scripts](docs/database-connectors.md).

## SQL Server setup

1. Run `docker compose up --build -d` and sign in as administrator.
2. Put the five SQL Server values in the project-root `.env`, then add/configure a source of type **SQL Server**. The backend reads the file privately and gives it priority over old form settings. The five connection fields are: `SQLSERVER_HOST`, `SQLSERVER_PORT` (default 1433), `SQLSERVER_USER`, `SQLSERVER_PASSWORD`, and `SQLSERVER_DATABASE`. Use a dedicated database login with SELECT permissions only.
3. Save, then click **Test connection**. Existing sources have **Configure connection** so you can save settings without recreating the source or datasets. The form shows configuration presence and `.env` mode rather than exposing credential values. Blank form fields never delete stored settings. When `.env` has SQL settings, it is authoritative for SQL sources; form-saved per-source credentials are used when no SQL connection is configured in the environment. Administration shows connection status and sanitized errors.
4. Administrators automatically have analysis access to connected SQL Server sources. Grant members database-wide access using **Qasja te burimi**; access is constrained to tables/views available to the source's SELECT-only login. No datasets or query files must be defined for automatic analysis.
5. In chat, ask **“Zbulo tabelat e databazës dhe më trego çfarë të dhënash kemi.”** Then ask, for example, **“Analizo shitjet e muajit të kaluar dhe krijo një raport në shqip.”** The assistant discovers your actual schema and uses backend scripts for reads, joins, filters and aggregates.
6. An Excel report card appears directly in the chat, with progress and **Shkarko Excel** when ready. The same workbook is available in **Raportet**. A request for a report automatically creates Excel; users do not need to specify a file format. The original data and query scope are captured by the backend.

The assistant can submit one primary query plus up to eight named analyses for period trends, comparable periods, breakdowns and supporting detail. Each query retains the 500-row/100 KB guard; aggregate queries can cover all matching database transactions without downloading every raw record. Workbooks include an overview, filtered Excel tables, source scope, calculated growth/three-period averages or category shares, and line/bar charts when a dimension and multiple rows are available. Matching revenue/cost columns enable profit and weighted margin formulas; unsupported or missing metrics are identified rather than invented.

Result column aliases may be readable labels such as `Sales incl VAT` or `Posting Month`; the backend bracket-quotes them and rejects duplicates. Table aliases remain simple identifiers. Validation failures return field paths without private input values. A failed optional supplementary query (for example a view with SQL error 208) is recorded in the workbook's limitations while successful complete analyses are retained. Set `required: true` on a supplementary analysis when its failure should block the report. Connection/access failures and truncated results still block generation. Reporting failure audit entries identify the stage and exception class without credentials or raw exception payloads.

Chat text and microphone controls remain locked while any of the user's reports are queued or running, including after the chat response ends and after reload. **Ndërprit raportin** explicitly cancels generation and unlocks input. The backend independently rejects chat messages during report generation. Excel files are written before a report becomes completed, retained privately under `/data/reports`, and downloaded only by their owner. Existing completed reports acquire an Excel export on first download without another model request. All dropdowns use accessible custom controls with keyboard navigation.

`list_sources`, `list_tables`, `describe_table`, `query_database`, and `create_database_report` are built-in Python tools; they never give the model credential files, SQL connection strings or shell access. Query plans are structured objects, not arbitrary SQL. They support up to four joined tables, scalar filters, date buckets (day/month/year), grouping, sorting and SUM/AVG/MIN/MAX/COUNT metrics. Reads return at most 500 rows and 100 KB and clearly mark previews; reports reject truncated previews, so large datasets should use aggregate queries. Manual datasets/query files remain optional for curated or more specialized reports.

**Bisedat** opens a searchable conversation library with cards, message previews, counts and last activity. Clicking a card opens that conversation; **Bisedë e re** saves and opens a fresh empty conversation immediately. Unassigned reports never appear in a fresh chat. **Raportet** provides cards with open, Excel download and delete actions. Reports open in a closeable preview with Excel, Markdown, JSON and CSV exports. Deleting a report moves it to **Të fshira**, where **Rikthe raportin** restores its data and downloads. Active reports must be interrupted before deletion. All report operations check ownership; deleted reports and downloads return 404 until restored.

User messages appear on the right and assistant messages on the left. Delete conversations using the sidebar trash icon or **Historiku i bisedave** in the top bar (also available on mobile). Deletion removes local messages and retains saved reports; Codex's internal rollout files and data snapshots are independent server records.

## Settings and persistence

Copy `.env.example` to `.env` only when overriding defaults. The project-root `.env` is mounted read-only at `/run/duka.env`. SQL Server settings from this file take precedence over container environment variables and old form-saved credentials. Password characters such as `$` are preserved literally. Outside Docker, `Settings` reads the project-root file (or the path configured by `ENV_FILE`). Backend connection resolution refreshes changed settings; after editing `.env`, run `docker compose up -d --force-recreate` so editor file replacement and other container variables are refreshed. There is no API-key setting.

| Setting | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8080` | Host port; also update `ALLOWED_ORIGINS` if changed |
| `ALLOWED_ORIGINS` | localhost/127.0.0.1 on 8080 | Exact allowed browser origins |
| `SECURE_COOKIES` | `false` | Use `true` behind HTTPS |
| `SESSION_HOURS` | `24` | App session lifetime |
| `VOICE_ENABLED` | `true` | Enable local transcription |
| `WHISPER_MODEL` | `base` | Local speech model |
| `WHISPER_LANGUAGE` | empty | Auto-detect, or ISO code such as `en`/`sq` |
| `MAX_CODEX_RUNTIMES` | `8` | Maximum live per-user runtimes |
| `TURN_TIMEOUT_SECONDS` | `300` | Response timeout |
| `SQLSERVER_HOST` | empty | SQL Server hostname; backend only |
| `SQLSERVER_PORT` | `1433` | SQL Server TCP port |
| `SQLSERVER_USER` | empty | Dedicated SELECT-only login |
| `SQLSERVER_PASSWORD` | empty | Database password; backend only |
| `SQLSERVER_DATABASE` | empty | Business database name |
| `SQLSERVER_ENCRYPTION` | `require` | Require encrypted database transport |
| `SQLSERVER_TIMEOUT_SECONDS` | `15` | Login and query timeout |

Application SQLite, the source credential encryption key, per-user credentials/history, and speech models live in the sensitive `workspace-data` volume. Back up the volume as a unit; the database credential key is required to decrypt saved source settings. `docker compose down` preserves it; `down -v` deletes it permanently.

The container runs non-root with a read-only filesystem, dropped capabilities, and a writable data volume. The host port binds to loopback. Keep the prototype local; remote access needs an authenticated HTTPS deployment, secure cookies, exact origins, and appropriate subscription eligibility/deployment review.

## Development and tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
# Optional outside Docker:
.venv/bin/pip install -r backend/requirements-voice.txt
cd frontend
npm ci
npm run build
cd ..
npm install --prefix work/codex --save-exact @openai/codex@0.162.1
CODEX_BINARY="$PWD/work/codex/node_modules/.bin/codex" \
  .venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8080
```

For frontend hot reload, run `npm run dev` inside `frontend/` and start Python with `ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`. Vite proxies `/api` to Python on port 8080.

```bash
.venv/bin/pytest -q
.venv/bin/ruff check backend tests
cd frontend && npm test && npm run build
```

Automated integration tests use an explicitly named **local protocol fixture**, not live credentials/inference. A real completed response after your sign-in is the final subscription check.

For native Codex protocol regression checks, set `NATIVE_CODEX_BINARY` to the installed CLI when running pytest. These checks use an isolated credential-free home and verify named permission profiles, turn validation, resume, and recovery after a rejected first turn; they do not use your subscription credentials.

## Troubleshooting

- **Device sign-in fails:** Enable device code login in ChatGPT security/workspace settings, check outbound OpenAI access, and start a fresh code.
- **Usage limit reached:** Wait for the reset or manage your plan in ChatGPT. No API billing fallback is provided.
- **Model unavailable:** Reload the account/model picker and choose a permitted model. A catalog alone is not an entitlement guarantee.
- **Runtime capacity:** Administration → People & access → Restart an idle runtime, or increase `MAX_CODEX_RUNTIMES`. Saved credentials remain.
- **Microphone over a LAN IP:** Use HTTPS.
- **Voice fails:** Check model download access to Hugging Face and RAM/disk, or choose a smaller model.
- **Startup errors:** `docker compose logs --tail=100 app`. Access logs and Codex stderr are suppressed to avoid credential/auth-URL exposure.

## References

- [T3 Code](https://t3.codes/)
- [Official Codex app-server protocol](https://learn.chatgpt.com/docs/app-server)
- [Official authentication and headless login](https://learn.chatgpt.com/docs/auth)

Codex is pinned at **0.162.1**. Re-test protocol compatibility/login when upgrading it.

SQL Server error **208** means a selected table/view or one of its dependencies is unavailable. Login and schema discovery can still succeed. This appears as a query error with a connected source; check the view definition/permissions in SQL Server or ask the assistant to use physical tables (`list_tables` supports `kind=table` and `name_contains`). The backend never changes business database schema to repair broken views automatically.
