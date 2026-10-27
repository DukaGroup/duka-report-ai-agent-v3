# Security and public web access review — 26 October 2026

Scope: the current v3 checkout, the shared “Reuse report scripts” conversation, local Docker configuration, authentication/recovery, source secrets, database/company authorization, generated scripts, uploads, previews, export safety and dependency advisories. Existing uncommitted product changes were retained. Tests use synthetic accounts and data; production database privileges and remote infrastructure were not modified.

## Corrected findings

| Finding | Result |
| --- | --- |
| Sign-in limits were process-local and keyed only by source IP | SQLite-backed, atomic budgets now apply to both normalized account and client IP. They survive application restarts and multiple workers. Login, setup, recovery and password-change budgets use separate namespaces. |
| More than 10,000 IP buckets cleared every existing counter | Expired budgets are pruned; capacity exhaustion rejects new budgets without clearing existing protection. |
| Repeated password checks blocked the async request loop | Expensive password verification/hashing runs in a thread with at most two operations in flight per worker. A canceled request retains its capacity slot until its actual computation finishes. |
| Session issuance could race password replacement/deactivation | Session creation checks active state and the exact verified password hash under a write transaction. Password changes recheck after asynchronous worker cleanup. Member creation rechecks administrative authority after hashing. |
| Disabled accounts retained unused recovery codes | Deactivation now deletes recovery codes together with sessions; reactivation cannot revive an old code. |
| Non-ASCII bootstrap tokens raised a server error | Constant-time comparison now operates on encoded bytes and rejects invalid tokens normally. Invalid Unicode credential fields produce validation errors without reflecting secrets. |
| Authentication bodies could be oversized before field validation | Authentication POST bodies are bounded to 16 KiB before JSON parsing, including streamed bodies. |
| Unbounded/misconfigured session lifetime | Startup accepts `SESSION_HOURS` from 1 through 168; the default remains 24 hours. |
| Vulnerable PDF parser and file-lock dependency pins | `pypdf` updated from 6.21.1 to 6.21.2; `filelock` from 4.1.1 to 4.2.1. The patched pinned Python dependency audit and frontend npm audit report no known vulnerabilities. |
| Pinned, unreachable office DNS prevented provider routing | Default Docker deployment inherits host DNS. Explicit private/VPN resolvers require the optional `deploy/compose-dns.yaml` override. The old environment settings are preserved but unused by default. |

Each sign-in/recovery budget permits ten attempts in a five-minute window, including successful attempts. Blocked retries do not extend the window. Responses include `Retry-After`. Account and IP identifiers are hashed before persistence. The app uses the ASGI client address, not an arbitrary application-parsed `X-Forwarded-For`; preserve the deployment's trusted-proxy configuration.

Password storage uses independent random salts and scrypt (`N=16384, r=8, p=5`), one of [OWASP's documented configurations](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Legacy password verifiers upgrade after successful authentication. Password checks preserve complete Unicode input and do not truncate passwords. [OWASP authentication guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) supports account-based throttling alongside other abuse controls.

## Public internet access

Both integrations previously prevented public web research. ChatGPT now sets `web_search="live"` in its native configuration and in new/resumed thread configuration. Local command networking remains disabled, shell/edit/multi-agent tools remain disabled, and each process retains its own read-only workspace profile. See [OpenAI's configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Claude explicitly exposes only `WebSearch` and `WebFetch` as built-in tools, plus the existing authorized reporting MCP tools. A `PreToolUse` check rejects non-HTTP(S) schemes, embedded credentials, nonstandard ports, local/private/link-local/metadata addresses, IPv6 translation routes and mixed public/private DNS answers before `WebFetch`. Failed DNS checks deny access. The native provider tool owns the actual request and redirects; this application hook is an additional check rather than an independent network firewall. Empty setting sources and strict MCP configuration prevent user/project tool configuration from being imported. See [Claude's Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python).

Shared instructions require live lookup for current facts such as Tirana weather, distinguish observations from forecasts, and request readable source links. Webpages are untrusted evidence. Private report contents, uploads, credentials and database rows must not be placed into web queries or URLs. Report figures continue to come from supplied data and permission-checked reporting tools. Prompt instructions reduce exfiltration risk but do not constitute a technical guarantee against every model error; internet-enabled models that also process business data require ongoing monitoring and a suitable data-sharing policy.

Public search/page reading does not provide every ChatGPT product feature. Image generation, arbitrary browser actions, external account integrations and other tools require their own implementations and authorization. Provider/model/subscription availability still applies.

## Encryption and deployment boundaries

- Login passwords are hashed; session and recovery bearer tokens are stored as SHA-256 hashes. Session cookies use HttpOnly and SameSite=Strict; public configurations require Secure cookies and HTTPS.
- Public configuration rejects HTTP origins, wildcard origins, unexpected hosts and insecure cookie settings. Production database connectors refuse weakened transport; native SQL Server deployment validates its FreeTDS certificate policy, and HANA requires certificate validation.
- Recovery archives use authenticated AES-256-GCM encryption. Existing tests cover wrong keys, tampering, symlinks, unsafe restoration and preservation of accounts/grants.
- **Live `.env`/`runtime.env`, SQLite business snapshots, reports, uploads and native provider history are not application-encrypted at rest.** Managed database credentials intentionally live in private environment profiles under the existing product design. Filesystem permissions and Docker isolation restrict access; they are not encryption. Use encrypted disks/volumes and separately protected encrypted backups where protection against offline disk/backup theft is required. A server administrator or compromised service account can access live plaintext data.
- The local app is bound to `127.0.0.1:8080`, with development HTTP settings and non-Secure cookies. This is suitable only for the intended local connection. Remote publication requires the documented production HTTPS configuration. No remote firewall, certificate, database privilege or disk encryption state was verified.
- The local `.env` ACL grants the host owner and container UID 10001 access, with no ordinary group/other access. Its apparent mode 660 reflects the ACL mask; do not blindly chmod it and remove container access.

## Remaining operator work

The earlier [security maintenance record](security-maintenance.md) documents credentials formerly tracked in Git. Untracking and a sanitized local history copy do not revoke exposed credentials. Confirm rotation with the DBA and coordinate any remote history cleanup. No password or remote repository history was changed in this review.

MFA is not implemented. Dedicated SELECT-only database logins, the actual server's effective privileges, TLS certificate chains, disk encryption, backup key separation, operating-system patching and upstream account security remain deployment responsibilities. A dependency audit describes known advisories at its check time; it does not prove that no vulnerabilities exist.

## Verification results

- Final security/deployment/public-web checks: **85 passed**. These include concurrent login counters, expiry/capacity/restart behavior, password changes during concurrent revocation, session hashing/expiry/logout, Unicode/oversized requests, recovery invalidation, blocked private destinations and native integration configuration.
- Broader backend suite: **616 passed, two optional native checks skipped, one outdated deletion expectation failed** in the first full run. The stale test expected immediate permanent deletion despite the established recoverable trash behavior. It now verifies both trash and explicit permanent purge; its complete three-test module passed. Three additional IPv4/IPv6 special-address cases subsequently passed in the final security run. All 622 collected backend cases have passing evidence across these runs, including the two native cases below.
- Actual native Codex CLI permission checks: **2 passed**, including per-process filesystem policy with a shared login and live-search configuration.
- Frontend: **78 tests passed** and production build succeeded.
- Pinned Python packages, packages installed in the rebuilt Docker image, frontend npm dependencies and the bundled Codex npm dependency tree: **no known vulnerabilities reported** by their audits at check time. OS packages and vulnerabilities inside vendor binaries were not independently scanned.
- Live ChatGPT check: the exact prompt **“si eshte moti ne tirane sot”** completed with a `WebSearch` tool event and an Albanian answer for 26 October containing a clickable weather-source URL. Claude's account is currently disconnected, so its live lookup could not be verified; its configured SDK tools and public-address guard passed automated checks.
- Local Docker app rebuilt/recreated and health check passed. Before/after fingerprints match for users, saved credentials, source/database/company/dataset grants, reports and conversations. No account/grant/business-record replacement or credential rotation was performed.

Verification evidence is retained under `work/security-review-20261026/` (ignored local artifacts). The app remains bound to loopback; this review does not certify a remote production deployment or every possible attack case.
