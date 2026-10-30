# The AI Harness: what it is and how to make Hana faster and cheaper without losing accuracy

## 1. What a "harness" is

An AI agent has two parts:

| Part | What it is | In this project |
|---|---|---|
| **Model** | The LLM that reads text and decides what to do next | Claude (Agent SDK) or ChatGPT (Codex app-server) |
| **Harness** | Everything *around* the model: the loop that calls it, the instructions, the tools, the context you send, the limits, the checks on its output | `provider.py`, `claude_provider.py`, `chat_jobs.py`, `database_tools.py`, `calculation_*`, `workbook_*`, `investigation.py`, etc. |

If the model is the engine, the harness is the rest of the car. Two teams can use the same model and get very different speed, cost and accuracy, and the difference is almost always in the harness. The **harness method** means you improve results by engineering the harness (context, tools, loop, verification) instead of only switching models or rewriting prompts.

A harness does five jobs:

1. **Instructions**: the system prompt (`BASE_INSTRUCTIONS`, `INVESTIGATION_INSTRUCTIONS`).
2. **Tools**: what the model can do (`REPORT_TOOLS`: 23 tools such as `query_database` and `calculate_data`).
3. **Context**: what the model sees on each call (history, tool results, attachments, handoff context).
4. **The loop**: model → tool call → result → model → … until a final answer (`ClaudeRuntime._stream`, `CodexRuntime.stream`).
5. **Guardrails and verification**: access checks, sandboxing, `require()` checks, workbook validation, and the JSON-schema output for reports.

## 2. How the loop costs you tokens

The most important fact: **a model has no memory between calls. Each step in the loop sends the full context again.**

One user question that needs 6 tool calls actually means about 7 model calls, and each one sends:

```
[ system prompt ] + [ all tool definitions ] + [ chat history ] + [ every tool result so far ] + [ new step ]
```

### Measured in this repo (2026-10-30)

| Fixed part sent on every model call | Size | ≈ Tokens |
|---|---|---|
| `BASE_INSTRUCTIONS` (system prompt) | 30,442 chars | ~7,500 |
| `REPORT_TOOLS` (23 tool schemas) | 58,021 chars | ~14,500 |
| **Total fixed overhead** | **~88 KB** | **~22,000** |

The three largest tool schemas take about two thirds of the tool budget:

| Tool | Schema size |
|---|---|
| `create_database_report` | 13,439 chars |
| `calculate_data` | 13,184 chars |
| `create_attachment_report` | 12,615 chars |

So a "hi, how are you?" message starts at ~22k input tokens. A report that takes 10 loop steps resends that overhead 10 times (≈220k tokens), plus a history that keeps growing, before counting any actual data.

**Prompt caching** reduces this. When the start of the request (system prompt + tools) is byte-for-byte identical to a recent call, the provider reads it from cache, which is much cheaper and faster. It only works if that prefix **stays stable**. Anything that changes near the top (a timestamp, the user's name, a tool list that differs from turn to turn) breaks the cache from that point onward.

Because you use **subscriptions** (not API keys), "credits" here means **subscription usage limits**. The same rules apply: fewer and smaller uncached tokens, and fewer loop steps, mean more work before you hit the limit.

## 3. Rule zero: measure before you optimize

Right now the harness **does not record token usage**. `claude_provider.py` handles `RateLimitEvent` but ignores the `ResultMessage` usage data. Without numbers you cannot prove that a change saved tokens without hurting accuracy.

The Claude SDK's final `ResultMessage` includes `usage` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`), `num_turns`, `duration_ms` and `total_cost_usd`, where cost is a notional API-equivalent figure. Record these for every chat or report turn, for example through the existing `traffic` / system-logs path:

```python
# claude_provider.py, inside the receive_response() loop
if isinstance(message, ResultMessage):
    usage = message.usage or {}
    self.traffic.record("model-backend", "turn/usage", "ok", user_id=self.user_id, details={
        "thread": thread_id,
        "turns": message.num_turns,
        "duration_ms": message.duration_ms,
        "input": usage.get("input_tokens"),
        "output": usage.get("output_tokens"),
        "cache_read": usage.get("cache_read_input_tokens"),
        "cache_write": usage.get("cache_creation_input_tokens"),
        "cost_equiv_usd": message.total_cost_usd,
    })
```

Adjust the call to match the real `traffic.record` signature. For Codex, read the token-usage notifications from app-server in the same way.

Track these KPIs per request type (chat, calculation, report):

- **Loop steps per answer** (`num_turns`)
- **Uncached input tokens** (the expensive part)
- **Cache hit ratio** = `cache_read / (input + cache_read + cache_write)`, aiming for 80%+
- **Wall-clock time**
- **Accuracy** (see §5)

## 4. The levers, ranked by impact

### Lever 1: Keep the fixed prefix small and stable *(large saving, low risk)*

**a. Remove legacy content from the always-on prompt.** `BASE_INSTRUCTIONS` contains long compatibility sections: the `CALCULATE_DATA` / `EXPORT_CALCULATION` envelopes for old catalogs, `calculate_balances` / `create_balance_report` retirement notes, and the full list of calculation builtins. Every new chat pays for these on every step, although only old chats need them. Options:

- Inject the compatibility block only when the chat's saved capability revision is old. The harness already tracks a capability revision per native session.
- Move the script-helper documentation into the `calculate_data` tool description only, and keep it in one place instead of two.

**b. De-duplicate rules between the system prompt and tool descriptions.** Rules such as scope preservation, exact decimals and confidentiality appear in both. State a rule once, in the place where the model needs it: global rules in the system prompt, tool-specific rules in the tool.

**c. Shorten the three ~13 KB tool schemas.** Long schemas usually contain explanatory prose that belongs in a short description plus one example. Target 3–5 KB each. A good pattern is a small `read_tool_guide(topic)` tool that returns the detailed guide **only when the model needs it**. The guide then costs tokens once, when used, instead of on every call.

**d. Keep the prefix byte-stable.** Never put dates, user names, grants or other per-request data at the top of the system prompt. Put dynamic facts in the user message or in a tool result. Keep the tool list order deterministic.

> Expected effect: cutting the ~22k fixed overhead to ~10–12k roughly halves the cost of *every* loop step, and it makes caching more effective. Accuracy risk is low if you only remove duplicates and legacy content, and §5 lets you verify that.

### Lever 2: Fewer loop steps *(saves tokens and time)*

Each step resends everything and adds latency. Ways to reduce steps:

- **Composite tools.** `discover_sales` already shows this pattern: one call replaces several. Do the same for other frequent sequences, for example `list_tables` → `describe_table` × N → `query_database`. A `describe_tables([...])` batch, or a `find_relevant_tables(question)` that returns tables *with* their columns, removes several steps.
- **Cache schema metadata on the server.** Table and column catalogs rarely change. Cache them per source for a set period (TTL) so discovery calls are instant and the model does not need to re-explore in every new chat.
- **Push script reuse.** `find_calculation_scripts` / `read_calculation_script` plus hash-checked edits (`script_reuse.py`) already exist. Tell the model to check for a reusable script *before* writing a new calculation. A reused, validated script is faster, cheaper and more accurate.
- **Parallel tool calls.** Instruct the model to issue independent calls (for example several `describe_table` calls) in the **same** step. Both providers support this.
- **Set a step budget.** Give the loop a sensible maximum (for example via `max_turns` in `ClaudeAgentOptions`) so a confused run stops and reports instead of burning usage.

### Lever 3: Smaller tool results *(the hidden cost)*

Tool results stay in the context for the rest of the turn and are resent on every following step.

- **Compact JSON.** `json.dumps(result)` in `provider.py` uses default separators. `json.dumps(result, separators=(",", ":"), ensure_ascii=False)` is free and saves a few percent. `ensure_ascii=False` also stops Albanian letters (ë, ç) from being expanded into `ë` escapes.
- **Columnar rows.** Return `{"columns": [...], "rows": [[...], ...]}` instead of a list of dicts that repeats every key on every row. For 100 rows × 10 columns this often cuts the result by 40–60%.
- **Lower default preview limits.** `query_database` defaults to 100 rows (max 500). The model rarely needs 100 rows to *understand* data. It needs a sample plus aggregates, so default to around 20 and let it ask for more. Complete datasets for reports already go through snapshots and calculations, not the model's context, so accuracy is unaffected.
- **Aggregate on the server.** Let SQL or `calculate_data` compute totals, and give the model only the result. The model should read numbers, not add them up itself, which is also more accurate.
- **Drop noise.** Leave out null columns, internal IDs the model does not need, and repeated metadata.

### Lever 4: Right-size model and effort per task *(large saving on simple traffic)*

You already have per-conversation reasoning effort (`reasoning.py`, **Arsyetimi**). Use it automatically:

| Request type | Model | Effort |
|---|---|---|
| Greetings, short questions, explanations of an existing answer | Smaller or faster model (e.g. Sonnet/Haiku class) | low |
| Data look-ups, single queries | Mid-tier model | medium |
| Calculations, reconciliations, Excel reports, investigations | Top model (Opus class) | high |

A simple router can be a few rules on the backend: whether attachments are present, whether the message contains a report or calculation keyword, and whether the previous turn used tools. Use **escalation, not demotion**: if the cheap path fails validation or the model signals uncertainty, retry on the strong model. Accuracy stays at its maximum because hard work always ends up on the strongest model.

> Note: switching model *inside* one native session can invalidate its cache and session. Route at the start of each new chat or report job, not between steps.

### Lever 5: Manage long-conversation context *(important for heavy users)*

Native sessions are resumed with their full history, including old, bulky tool results. In a long chat, every new question pays for every old query result.

- After a turn ends, old tool results are rarely needed. Prefer starting report jobs in a **fresh session** with a short, explicit handoff (the `read_handoff_context` tool already exists) instead of the full chat history.
- Add **summarize-and-restart**: once a session passes a threshold (for example 100k tokens), summarize the conversation (decisions, scope, filters, and IDs of saved calculations) and continue in a new native session seeded with that summary. Saved calculations and scripts stay reachable by ID, so no facts are lost.

### Lever 6: Speed specifically

- Streaming is already in place, so users see progress.
- Speed comes mostly from Levers 2 and 3: fewer steps and smaller payloads.
- Keep database connections pooled and warm, and keep the metadata cache.
- Use lower effort for simple turns (Lever 4). Thinking tokens are output tokens, which are the slowest part.

## 5. Keeping accuracy at its maximum: let the harness check the work

Accuracy should be **guaranteed by the harness, not hoped for from the model**. This project already does many things right:

- Calculations run as deterministic, sandboxed scripts (`calculate_data`, `require()`, exact decimals) instead of the model doing arithmetic.
- Reports use JSON-schema outputs and workbook validation, and incomplete translations block generation.
- Access checks run before any data is read.

The one missing piece is an **evaluation set**. You need it before cutting tokens, because it is the only way to prove that accuracy did not drop.

1. Collect **30–50 real questions** with known correct answers: sales for a period, a balance, an investigation, a report. Use a test or reporting database with stable data.
2. For each question, record: the expected figures (exact), the expected scope (company, period, currency), and whether a report should have been created.
3. Add a script (for example `dev/eval.py`) that runs every question through the real harness and scores:
   - **Correctness**: figures match exactly
   - **Scope**: no extra periods or companies
   - **Confidentiality**: no table, column or SQL names in the answer (easy to check with a regex)
   - **Cost**: tokens, loop steps, time (from §3)
4. Run it **before and after every harness change**. Keep a change only if accuracy stays the same and cost goes down.

`tests/fake_claude.py` and `fake_codex.py` cover the plumbing. The eval set covers model behavior, so you need both.

## 6. Suggested rollout

| Phase | Work | Risk | Expected gain |
|---|---|---|---|
| 1 | Record token usage, steps and time (§3) and build the eval set (§5) | None | You can see where the cost goes |
| 2 | Compact JSON, columnar rows, smaller preview limits (Lever 3) | Very low | 10–30% fewer tokens in tool-heavy turns |
| 3 | Remove legacy content and duplicates from the prompt and tools, shorten the 3 big schemas (Lever 1) | Low, verified by evals | ~40–50% less fixed overhead per step |
| 4 | Metadata cache, batch/composite discovery tools, script-reuse-first, parallel calls (Lever 2) | Medium | Fewer steps, faster answers |
| 5 | Model and effort routing with escalation (Lever 4) | Medium, verified by evals | Large savings on simple chats |
| 6 | Summarize-and-restart for long chats, fresh sessions for reports (Lever 5) | Medium | Stable cost in long conversations |

The percentages are estimates based on the sizes measured above. Phase 1 gives you the real numbers.

## 7. Quick checklist for every future change

- [ ] Does this add text to the system prompt or tools? Could it go into a tool result or an on-demand guide instead?
- [ ] Is the prompt and tool prefix still byte-identical across requests (caching)?
- [ ] Does any tool return more data than the model needs to *decide*?
- [ ] Could two or more frequent tool calls be one call?
- [ ] Is the arithmetic done by code (SQL or `calculate_data`), not by the model?
- [ ] Did the eval set pass, with the same accuracy and the same or lower tokens, steps and time?
