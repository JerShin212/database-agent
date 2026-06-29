---
name: scaffold-agent-mcp
description: Scaffold an in-process MCP (Model Context Protocol) tool server that gives a Claude Agent SDK agent safe, schema-validated tools over your own database, retrieval stack, or internal services. Use this skill whenever you are setting up the Claude Agent SDK with custom tools, building an agent or chatbot that needs to query a database or call internal APIs, adding NL2SQL or retrieval tools to an LLM, or porting an in-process MCP pattern to a new codebase — e.g. "add an AI agent that can query our DB", "build an MCP server for the chatbot", "let Claude call our retrieval pipeline as a tool", "set up create_sdk_mcp_server", "give my agent custom tools safely". Covers the per-request server factory, the @tool definition pattern, the tool registry, the allowed_tools allowlist as a REAL gate under dontAsk permission mode, built-in tool lockdown, SQL/input safety, the system prompt, and the query() agent loop with streaming and sessions. Defaults to Python (Claude Agent SDK); TypeScript differences noted inline.
---

# Scaffold an Agent MCP Server (Claude Agent SDK, in-process)

This skill scaffolds an **in-process MCP server**: tools exposed to a Claude agent
as safe, schema-validated functions, driven by the Claude Agent SDK.

"In-process" means there is **no separate server binary and no transport** — tools
are plain functions registered via `create_sdk_mcp_server()` (Python) /
`createSdkMcpServer()` (TypeScript) and handed to `query()` in the same process.
This is the right pattern when the agent runs inside YOUR backend and the tools
just need your DB client / retrieval pipeline / service layer. (If instead you
need a standalone server that *external* clients connect to over stdio/HTTP, that
is a different shape — build a normal MCP server and connect to it via the SDK's
`mcp_servers` HTTP/stdio config rather than this in-process pattern.)

> Language: examples are **Python** (the Claude Agent SDK Python package). The
> architecture is identical in TypeScript; key differences are flagged as **[TS]**.

## The mental model — six layers

```
query(prompt, options)                ← (6) Loop: runs the agent, streams output
  └─ options.mcp_servers["my-ops"]    ← (5) Server factory: create_sdk_mcp_server(name, version, tools)
       └─ tools=[ ... ]               ← (2) Registry: assemble_tools(deps) -> list
            └─ @tool("Name", desc,    ← (1) Tool definition: @tool + schema + handler
                     schema)
  └─ options.allowed_tools=[...]      ← (3) Allowlist: "mcp__my-ops__Name" (hand-kept)
  └─ options.permission_mode="dontAsk"← (3) makes the allowlist a REAL gate (see below)
  └─ options.system_prompt="..."      ← (4) System prompt: tells the model each tool exists
```

Two cross-cutting facts that make or break it:

- **Tool names must line up exactly.** `mcp_servers` key == server `name` == the
  `mcp__<name>__<Tool>` allowlist prefix. All three must be the same string.
- **Every tool the model should use must be described in the (4) system prompt.**
  A registered-but-undocumented tool is rarely invoked.

## Dependencies

```bash
pip install claude-agent-sdk           # plus your data client, e.g. asyncpg / psycopg
# [TS]: bun add @anthropic-ai/claude-agent-sdk zod
```

The SDK authenticates with `ANTHROPIC_API_KEY` from the process environment. There
is no per-tool key. **A 401 is permanent — fast-fail it, don't retry.**

## Layer 1 — a tool

Use a **factory** that takes its dependencies (DB client, retrieval handle,
context) as arguments and returns the tool. Never close over a global client —
the factory is what lets you bind a per-request instance later. In Python, define
the handler inside the factory and apply `@tool` there.

```python
# tools/query_database.py
from claude_agent_sdk import tool

def create_query_database_tool(read_db, descriptor):
    @tool(
        "query_database",                                  # ToolName, no prefix here
        build_query_description(descriptor),               # describe WHAT + WHEN
        {"sql": str},                                      # schema: see note below
    )
    async def query_database(args):
        sql = args["sql"]
        ok, reason = validate_sql(sql, descriptor)         # SELECT-only validator
        if not ok:
            return {"content": [{"type": "text", "text": f"Rejected: {reason}"}],
                    "is_error": True}
        try:
            rows = await read_db.fetch(ensure_limit(sql, args.get("limit", 100)))
            return {"content": [{"type": "text",
                                 "text": json.dumps([dict(r) for r in rows])}]}
        except Exception as e:                             # in-band, not raised
            return {"content": [{"type": "text", "text": f"Failed: {e}"}],
                    "is_error": True}
    return query_database
```

Rules baked into that template:

- **Schema shape.** In Python the schema is a **dict** mapping field names to
  types: `{"sql": str}`. The SDK converts it to JSON Schema. Every key is
  **required** — for an optional param, leave it out of the schema, mention it in
  the description, and read it with `args.get("limit", default)`. For an enum
  (e.g. constraining a category so the model can't pass an arbitrary value), pass
  a **full JSON Schema dict** instead:
  ```python
  {"type": "object",
   "properties": {"kind": {"type": "string", "enum": ["a", "b"]}},
   "required": ["kind"]}
  ```
  **[TS]:** the schema is a bare **ZodRawShape** — `{ sql: z.string() }`, NOT
  `z.object({...})`. Wrapping it in `z.object()` breaks input-schema generation.
  This is the #1 TypeScript mistake.
- **Return contract:** `{"content": [{"type": "text", "text": str}], "is_error": bool}`.
  Stringify structured data into `text`. **[TS]** uses `isError` (camelCase);
  **Python** uses `is_error` (snake_case).
- **Errors: prefer `is_error: True` over raising.** Not because a raise stops the
  loop — it doesn't; the SDK catches an uncaught exception and surfaces the
  stringified message to the model as a tool error, and the loop continues.
  Returning `is_error` is better because it lets *you* control the message the
  model sees (and decide what to leak).
- **Parameterize all queries.** Never string-interpolate model-supplied values.
  Use your client's parameter binding for filter values; only the NL2SQL tool
  takes raw SQL, and that goes through the validator below.
- **Mark read-only tools** with `readOnlyHint` so the orchestrator can run them in
  parallel. **[TS]:** 5th arg to `tool()`. **Python:** `annotations=ToolAnnotations(readOnlyHint=True)`.

### Tool flavours

- **Data / retrieval tool (read):** binds a read client or retrieval handle, runs a
  query/search, returns rows or hits. Most tools. Mark `readOnlyHint`.
- **Action tool (write / side-effecting):** two sub-patterns —
  - *direct* — write through the client.
  - *HTTP proxy* — `httpx`-fetch an internal route in your main app with an auth
    header. Use when the real logic and its credentials live in the app, not the
    worker (e.g. a GPU reranker service). The tool stays a thin proxy.

## Layer 2 — the registry

One module assembles every tool into the list the server consumes. This is also
where **conditional gating** lives — only include a tool when the deployment /
user is entitled to it.

```python
# tools/__init__.py
from .query_database import create_query_database_tool
from .hybrid_search import create_hybrid_search_tool

def assemble_tools(read_db, retriever, descriptor):
    tools = [create_query_database_tool(read_db, descriptor)]
    if descriptor.has_vector_index:                 # gate by capability
        tools.append(create_hybrid_search_tool(retriever))
    return tools

# The allowlist (Layer 3) — hand-maintained, must mirror what you may register.
TOOL_NAMES = [
    "mcp__my-ops__query_database",
    "mcp__my-ops__hybrid_search",
]
```

## Layer 3 — the allowlist (a REAL gate, under dontAsk)

`allowed_tools` is a hand-kept list of `mcp__<name>__<Tool>` strings. **There is no
automatic derivation.** Its behaviour depends entirely on the permission mode:

| Mode | Tool NOT in `allowed_tools` |
| --- | --- |
| `dontAsk` *(use this)* | **Denied outright** — the allowlist is a real gate. |
| `default` | Falls through to your `can_use_tool` callback; with no callback it stalls. |
| `bypassPermissions` *(avoid)* | **Approved anyway** — the allowlist does NOT restrict anything. |

So pair `allowed_tools` with `permission_mode="dontAsk"`. Then:

- Registered but missing from `allowed_tools` → **denied at call time** (now a true
  safety gate, not a silent footgun).
- In `allowed_tools` but never registered → harmless (the SDK won't invoke a tool
  that isn't on the server). This lets you list a conditionally-registered tool
  unconditionally.

**Do not use `bypassPermissions` for this.** It disables the allowlist as a gate,
approves *every* built-in (Bash, Write, Edit) without prompting, and — critically —
**is inherited by every subagent and cannot be overridden**, granting subagents
full autonomous system access. For a hierarchical multi-agent design this is a
serious hole.

## Lock down the built-in tools

Custom tools sit alongside SDK built-ins (Read, Write, Bash, WebFetch, the subagent
tool…). Under `dontAsk`, anything not in `allowed_tools` is already denied — so a
tight allowlist of only your `mcp__` tools means Bash/Write/etc. cannot run. Add
two defense-in-depth measures:

```python
options = ClaudeAgentOptions(
    ...,
    allowed_tools=TOOL_NAMES,                 # ONLY your tools are approved
    permission_mode="dontAsk",                # everything else is denied
    disallowed_tools=["Bash", "Write", "Edit"],  # deny rules hold even if mode changes
    # tools=[]  # optional: remove built-ins from context entirely to save tokens.
                # Confirm the exact option name against your installed SDK version.
)
```

`disallowed_tools` deny rules are evaluated first and hold in **every** mode,
including `bypassPermissions` — so they are your hard floor regardless of mode.

## Layer 4 — the system prompt

A function that builds the prompt and describes each tool: what it returns, its
params, and when to call it. **Gate prompt sections on the same flags you gate the
tools on** — don't describe a tool the deployment didn't register, or the model
will try to call something it can't reach. Registration and prompt drift
independently; a missing description means the tool goes unused.

```python
def get_system_prompt(descriptor) -> str:
    parts = ["You are a search assistant with these tools:",
             "\n### query_database\nRuns a read-only SQL SELECT over the factory DB. "
             "Call it for precise/aggregated questions. Param: sql (SELECT only)."]
    if descriptor.has_vector_index:
        parts.append("\n### hybrid_search\nSearches manuals/SOPs by natural language "
                     "(BM25 + visual retrieval fused with RRF). Call it for "
                     "how-to / document questions. Param: query_text, top_k (opt).")
    return "\n".join(parts)
```

## Layer 5 — the server factory

Thin. Binds dependencies into tools and wraps them in a named server. **Build it
per request**, not once at boot — that is the isolation boundary (below).

```python
from claude_agent_sdk import create_sdk_mcp_server

def create_ops_server(read_db, retriever, descriptor):
    return create_sdk_mcp_server(
        name="my-ops",                          # the <name> in mcp__my-ops__*
        version="1.0.0",                        # include it
        tools=assemble_tools(read_db, retriever, descriptor),
    )
```

## Layer 6 — the agent loop

Resolve per-request deps, build the server, call `query()`, consume the stream.

```python
from claude_agent_sdk import (query, ClaudeAgentOptions,
                              ResultMessage, AssistantMessage, ToolUseBlock)

async def run_agent_turn(user_message, *, read_db, retriever, descriptor,
                         session_id=None):
    server = create_ops_server(read_db, retriever, descriptor)
    options = ClaudeAgentOptions(
        model="claude-opus-4-8",                # orchestrator; subagents can be cheaper
        system_prompt=get_system_prompt(descriptor),
        mcp_servers={"my-ops": server},         # key MUST equal server name
        allowed_tools=TOOL_NAMES,
        permission_mode="dontAsk",              # allowlist is the gate
        disallowed_tools=["Bash", "Write", "Edit"],
        max_turns=12,
        resume=session_id,                      # multi-turn: SDK manages history
    )
    consecutive_errors = 0
    async for message in query(prompt=user_message, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    pass                        # surface tool call to UI if wanted
        elif isinstance(message, ResultMessage) and message.subtype == "success":
            return message.result
```

Operational notes:

- **Token-level streaming:** set `include_partial_messages=True`
  (**[TS]** `includePartialMessages`) and forward the partial `text`/`thinking`
  deltas to your UI.
- **Non-convergence guard:** count **consecutive** errored tool results (reset on
  any success) and break past a threshold (~8). Raising `max_turns` does NOT fix a
  loop stuck on a failing tool — it just burns more turns. Common when a freshly
  set-up data source is empty.
- **Multi-turn:** persist the SDK session id and pass `resume=session_id` next turn.
  If the tool set or system prompt changes mid-conversation, also set
  `fork_session=True` (**[TS]** `forkSession`) so the new config takes effect — a
  plain resume reuses the baked-in options.

## Input safety (the most important part for NL2SQL)

If any tool accepts free-form SQL, it is your highest-risk surface. Layer the
defenses; never rely on one:

1. **`validate_sql()`** — must start with `SELECT`/`WITH`; CTEs must resolve to a
   SELECT; block keywords (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE,
   plus DO/PERFORM/COPY), patterns (`--`, `;`, `/*`), dangerous functions
   (`pg_read_file`, `pg_write_file`, `pg_terminate_backend`, …), and sensitive /
   auth / control-plane tables. Cap SELECT count to limit subquery complexity.
2. **Optional per-role table allowlist** — only let this user touch these tables.
3. **`ensure_limit()`** — wrap as `SELECT * FROM (<query>) AS _limited LIMIT n`,
   immune to `LIMIT ALL` / `LIMIT $var` bypasses.
4. **Only then** run it, against a **read replica / read-only role**.
5. **Everything that isn't free-form SQL uses parameterized queries** — model
   values can never reach the query string directly.

Write unit tests that throw injection attempts at `validate_sql()` and assert they
are all rejected — cheap, and a strong thing to show in an evaluation.

## Per-request binding & gating (why the factory pattern)

The factory is not ceremony — it is the isolation boundary:

- **Bind the data clients per request** in the loop, so a tool can only touch the
  data for the current user/role. The model never passes identity; you inject it.
- **A "descriptor"** (a small resolved object describing what this deployment has:
  which sources exist, which features are on, the user's role) drives *both* which
  tools you register *and* which prompt sections you include — one source of truth.
  Single-tenant projects still benefit: it gates capabilities and feeds the schema
  documentation the NL2SQL tool advertises.

## Narrow per-run servers

You don't need one giant server. For a focused job (or a scoped subagent), build a
server exposing exactly the tools that job needs, with run context baked into the
factory closure so the model cannot forge it. Fewer tools = lower cost, smaller
hallucination surface, tighter safety. A retrieval-only subagent that physically
cannot reach the SQL tool is a cleaner, more defensible design than one big server.

## From-scratch checklist

1. `pip install claude-agent-sdk` (+ data client). Set `ANTHROPIC_API_KEY`.
2. Pick a server name (kebab, e.g. `my-ops`) — it fixes the `mcp__my-ops__*` prefix.
3. One tool factory per capability (Layer 1): factory + `@tool` + dict/JSON schema
   + try/except returning `is_error`.
4. Aggregate in `assemble_tools(deps)` with conditional gating (Layer 2).
5. Maintain the `TOOL_NAMES` allowlist beside it (Layer 3).
6. `get_system_prompt(descriptor)` describing each tool + when to call it (Layer 4);
   gate sections like you gate tools.
7. `create_sdk_mcp_server(name, version, tools)` (Layer 5).
8. `query()` with `permission_mode="dontAsk"`, `allowed_tools`, `disallowed_tools`,
   `mcp_servers`, `system_prompt`, `max_turns`; consume the stream (Layer 6).
9. Add the SQL/input safety layers if you expose raw queries.

## Gotchas

- **Permission model.** Use `permission_mode="dontAsk"` + a tight `allowed_tools`
  so the allowlist is a real gate. Do NOT use `bypassPermissions` — it nullifies
  the allowlist, auto-approves Bash/Write, and is inherited (un-overridably) by
  subagents.
- **Allowlist drift.** Under `dontAsk`, a tool registered but missing from
  `allowed_tools` is denied at call time. In the list but not registered is
  harmless.
- **Prompt drift.** A tool absent from the system prompt is essentially never used.
- **Name alignment.** `mcp_servers` key == server `name` == allowlist prefix.
- **Schema shape.** Python: a dict (`{"sql": str}`), full JSON Schema for enums.
  **[TS]:** a bare ZodRawShape, never `z.object(...)`.
- **Return, don't (just) raise.** A raise is caught and surfaced as a tool error
  and the loop continues, but return `is_error: True` to control the message.
- **Parameterize queries; constrain enum inputs** in the schema.
- **`version`** belongs in `create_sdk_mcp_server`.
- **401 is permanent** — uses the process `ANTHROPIC_API_KEY`; don't retry it.
- **The SDK moves fast.** Re-verify option names (especially the built-in
  availability option) against your installed version, and watch for the
  TypeScript V2 preview if you build in TS.
