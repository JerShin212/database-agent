"""
In-process MCP tool servers (one per agent role) for the Claude Agent SDK.

Each server is built per request via a factory that closes over the request
`descriptor` (the old ToolContext — db ids, paths, collection ids, image bytes).
Binding the descriptor into the closure is the isolation boundary: the model can
never forge identity, and there is no process-global state shared across the
concurrent requests that run on the one event loop.

Tool name alignment (must match exactly):
    mcp_servers key  ==  create_sdk_mcp_server(name=...)  ==  mcp__<name>__<Tool>
The hand-kept TOOL_NAMES lists below are the allowlists handed to query().

Lockdown (verified against the installed CLI, SDK 0.2.110): a narrow
`allowed_tools` under `dontAsk` does NOT by itself remove the built-in/harness
tools — `tools=[]` does, and `setting_sources=[]` stops the SDK loading the user's
local Claude settings. LOCKDOWN bundles those; pair it with the role's allowlist.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from src.agent.tools import (
    execute_sql_query,
    get_database_schema,
    list_tables,
    get_table_info,
    search_schema_catalog,
    search_collections,
    read_document,
    list_collections,
    search_visual_documents,
    search_by_image,
    create_chart,
    CHART_SUCCESS_PREFIX,
)
from src.agent.tools.form_tools import (
    FORM_SUGGESTION_PREFIX,
    suggest_form,
)
from src.agent.sdk.sql_safety import validate_sql, ensure_limit
from src.services.mlflow_tracing import SpanType, span as tspan

# ---------------------------------------------------------------------------
# Permission lockdown — applied to EVERY query() (orchestrator + workers).
# tools=[]          -> removes all built-in / harness tools from the model.
# setting_sources=[]-> do not load user/project/local Claude settings.
# permission_mode   -> no interactive prompts.
# Pair with allowed_tools=<role's mcp__ names>.
# ---------------------------------------------------------------------------
LOCKDOWN: dict[str, Any] = {
    "permission_mode": "dontAsk",
    "setting_sources": [],
    "tools": [],
}

_READONLY = ToolAnnotations(readOnlyHint=True)

# Row cap enforced on every model-written SQL query, independent of any LIMIT
# the model did or didn't write. Kept close to what the tool actually renders
# back to the model (50 rows) so we don't fetch hundreds of rows it never sees.
_SQL_ROW_CAP = 100


def _query_schema(query_desc: str) -> dict[str, Any]:
    """JSON Schema for the common (query, limit?) search-tool signature."""
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": query_desc},
            "limit": {"type": "integer", "description": "Max results to return.",
                      "default": 5, "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
    }


def _result(text: str | None, is_error: bool | None = None) -> dict[str, Any]:
    """Build the MCP tool return contract from a plain string result.

    Existing tools return strings whose prefixes are load-bearing (NO_RESULTS
    drives the orchestrator's cross-agent fallback). Preserve them verbatim in
    `text`. NO_RESULTS is a *successful* "nothing found" result (is_error=False)
    so it does not trip the SDK's consecutive-error guard.
    """
    text = text if text is not None else ""
    if is_error is None:
        stripped = text.lstrip()
        is_error = stripped.startswith(("Error", "[Tool error]", "[Unknown", "[Invalid"))
        if stripped.startswith("NO_RESULTS"):
            is_error = False
    return {"content": [{"type": "text", "text": text}], "is_error": bool(is_error)}


async def _run(fn: Callable[..., str], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run a blocking (DB / Modal HTTP) tool function off the event loop and wrap
    its string result. Keeps concurrent requests from blocking on one tool.

    Also opens the tool's MLflow span here — the async layer — because trace
    context does not propagate into the to_thread worker thread. Scalar args
    only in span inputs (skips descriptor objects / image bytes)."""
    with tspan(f"tool:{fn.__name__}", span_type=SpanType.TOOL) as s:
        if s:
            s.set_inputs({"args": [a for a in args if isinstance(a, (str, int, float))]})
        try:
            text = await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as exc:  # backstop — tools already catch their own errors
            if s:
                s.set_outputs({"result": f"[Tool error] {exc}", "is_error": True})
            return _result(f"[Tool error] {exc}", is_error=True)
        wrapped = _result(text)
        if s:
            s.set_outputs({"result": (text or "")[:2000],
                           "is_error": wrapped["is_error"]})
        return wrapped


# ===========================================================================
# database-ops  (worker: database_agent)
# ===========================================================================

DATABASE_TOOL_NAMES = [
    "mcp__database-ops__execute_sql_query",
    "mcp__database-ops__get_database_schema",
    "mcp__database-ops__list_tables",
    "mcp__database-ops__get_table_info",
    "mcp__database-ops__search_schema_catalog",
]


def build_database_server(descriptor):
    @tool("execute_sql_query",
          "Execute a read-only SQL SELECT query against the connected database "
          "(local SQLite or external connector). Only SELECT / WITH is allowed. "
          "Param: sql (string).",
          {"sql": str}, annotations=_READONLY)
    async def _execute_sql_query(args):
        sql = args["sql"]
        ok, reason = validate_sql(sql)
        if not ok:
            return _result(f"Error: query rejected — {reason}. Only read-only "
                           "SELECT / WITH queries are permitted.", is_error=True)
        return await _run(execute_sql_query, ensure_limit(sql, _SQL_ROW_CAP), descriptor)

    @tool("get_database_schema",
          "Return the full database schema (tables, columns, types, relationships). "
          "No params.", {}, annotations=_READONLY)
    async def _get_database_schema(args):
        return await _run(get_database_schema, descriptor)

    @tool("list_tables", "List all tables in the database with row/column counts. "
          "No params.", {}, annotations=_READONLY)
    async def _list_tables(args):
        return await _run(list_tables, descriptor)

    @tool("get_table_info",
          "Get columns, types, keys and sample rows for one table. Param: table_name.",
          {"table_name": str}, annotations=_READONLY)
    async def _get_table_info(args):
        return await _run(get_table_info, args["table_name"], descriptor)

    @tool("search_schema_catalog",
          "Semantic search over the schema catalog (keyword + embedding + value "
          "match, RRF + MaxSim). Returns matched tables/columns with JOIN hints.",
          _query_schema("Natural-language phrase describing the data you need; "
                        "include literal values from the question (names, emails, "
                        "statuses) so value-matching can find their columns."),
          annotations=_READONLY)
    async def _search_schema_catalog(args):
        limit = int(args.get("limit", 5) or 5)
        return await _run(search_schema_catalog, args["query"], descriptor, None, limit)

    server = create_sdk_mcp_server(
        name="database-ops", version="1.0.0",
        tools=[_execute_sql_query, _get_database_schema, _list_tables,
               _get_table_info, _search_schema_catalog],
    )
    return server, DATABASE_TOOL_NAMES


# ===========================================================================
# doc-search  (worker: text_search_agent)
# ===========================================================================

DOC_TOOL_NAMES = [
    "mcp__doc-search__search_collections",
    "mcp__doc-search__read_document",
    "mcp__doc-search__list_collections",
]


def build_doc_server(descriptor):
    @tool("search_collections",
          "Hybrid search (BM25 + semantic, RRF) over document collections.",
          _query_schema("Descriptive natural-language search query — focus on "
                        "the concept, not just keywords."),
          annotations=_READONLY)
    async def _search_collections(args):
        limit = int(args.get("limit", 5) or 5)
        return await _run(search_collections, args["query"], descriptor, None, limit)

    @tool("read_document",
          "Read a document's extracted text (paginated). The response header "
          "tells you the start_char for the next page.",
          {
              "type": "object",
              "properties": {
                  "filename": {"type": "string",
                               "description": "Document filename (partial match ok)."},
                  "start_char": {"type": "integer", "default": 0, "minimum": 0,
                                 "description": "Character offset to start reading from."},
                  "length": {"type": "integer", "default": 15000,
                             "minimum": 1, "maximum": 20000,
                             "description": "Number of characters to return."},
              },
              "required": ["filename"],
          }, annotations=_READONLY)
    async def _read_document(args):
        start_char = int(args.get("start_char", 0) or 0)
        length = int(args.get("length", 15000) or 15000)
        return await _run(read_document, args["filename"], descriptor, start_char, length)

    @tool("list_collections", "List all document collections. No params.",
          {}, annotations=_READONLY)
    async def _list_collections(args):
        return await _run(list_collections)

    server = create_sdk_mcp_server(
        name="doc-search", version="1.0.0",
        tools=[_search_collections, _read_document, _list_collections],
    )
    return server, DOC_TOOL_NAMES


# ===========================================================================
# visual-search  (worker: visual_search_agent)
# ===========================================================================

VISUAL_TOOL_NAMES = [
    "mcp__visual-search__search_visual_documents",
    "mcp__visual-search__search_by_image",
    "mcp__visual-search__list_collections",
]


def build_visual_server(descriptor):
    @tool("search_visual_documents",
          "Visual page search via ColQwen2 (diagrams, figures, schematics, "
          "complex tables).",
          _query_schema("Phrase describing what the visual content looks like, "
                        "e.g. 'wiring diagram for unit A'."),
          annotations=_READONLY)
    async def _search_visual_documents(args):
        limit = int(args.get("limit", 5) or 5)
        return await _run(search_visual_documents, args["query"], descriptor, None, limit)

    @tool("search_by_image",
          "Search document pages using the image the user attached to their "
          "message.",
          {
              "type": "object",
              "properties": {
                  "text_query": {"type": "string",
                                 "description": "Short description of the image; "
                                 "fuses a text search with the image search for "
                                 "better results."},
                  "limit": {"type": "integer", "default": 5,
                            "minimum": 1, "maximum": 20,
                            "description": "Max results to return."},
              },
          }, annotations=_READONLY)
    async def _search_by_image(args):
        text_query = args.get("text_query")
        limit = int(args.get("limit", 5) or 5)
        return await _run(search_by_image, descriptor, text_query, limit)

    @tool("list_collections", "List all document collections. No params.",
          {}, annotations=_READONLY)
    async def _list_collections(args):
        return await _run(list_collections)

    server = create_sdk_mcp_server(
        name="visual-search", version="1.0.0",
        tools=[_search_visual_documents, _search_by_image, _list_collections],
    )
    return server, VISUAL_TOOL_NAMES


# ===========================================================================
# orchestrator-ops  (orchestrator)
# ===========================================================================

ORCHESTRATOR_TOOL_NAMES = [
    "mcp__orchestrator-ops__delegate",
    "mcp__orchestrator-ops__create_chart",
    "mcp__orchestrator-ops__suggest_form",
]

_DELEGATE_SCHEMA = {
    "type": "object",
    "properties": {
        "agent": {
            "type": "string",
            "enum": ["database_agent", "text_search_agent", "visual_search_agent"],
            "description": "Which specialist worker to run the task.",
        },
        "task": {"type": "string", "description": "The full task description for the worker."},
    },
    "required": ["agent", "task"],
}

_CHART_SCHEMA = {
    "type": "object",
    "properties": {
        "chart_type": {"type": "string", "enum": ["bar", "line", "pie", "scatter"],
                       "description": "Chart type."},
        "title": {"type": "string", "description": "Short chart title."},
        "labels": {"type": "array", "items": {"type": "string"},
                   "description": "Category/x-axis labels, one per point (omit for scatter)."},
        "datasets": {"type": "array", "items": {"type": "object"},
                     "description": '1-4 series: [{"label": str, "data": [numbers]}]; '
                                    'for scatter, data is [{"x": number, "y": number}].'},
    },
    "required": ["chart_type", "title", "datasets"],
}


def build_orchestrator_server(
    descriptor,
    emit: Callable[[dict], None],
    delegate_fn: Callable[[str, str], Awaitable[str]],
):
    """Orchestrator tools. `emit` pushes chart/action/tool_call events to the
    output stream; `delegate_fn` runs a worker (with fallback/escalation)."""

    @tool("delegate", "Send a task to a specialist worker and get its response. "
          "agents: database_agent (SQL/structured data), text_search_agent "
          "(document text), visual_search_agent (diagrams/figures/images).",
          _DELEGATE_SCHEMA)
    async def _delegate(args):
        agent, task = args["agent"], args["task"]
        # Emit before running so the UI shows the delegation ahead of the
        # worker tool calls it produces; the completion event carries the result.
        emit({"type": "tool_call", "agent": "orchestrator", "tool": "delegate",
              "args": {"agent": agent, "task": task},
              "result": f"(running {agent}…)", "is_error": False})
        # Worker (and fallback/escalation) spans opened inside delegate_fn
        # auto-nest under this span.
        with tspan("tool:delegate", span_type=SpanType.TOOL) as s:
            if s:
                s.set_inputs({"agent": agent, "task": task[:2000]})
            result = await delegate_fn(agent, task)
            if s:
                s.set_outputs({"result": (result or "")[:2000]})
        emit({"type": "tool_call", "agent": "orchestrator", "tool": "delegate",
              "args": {"agent": agent, "task": task}, "result": (result or "")[:500],
              "is_error": False})
        return _result(result)

    @tool("create_chart",
          "Render a chart for the user from structured data (after you have the "
          "numbers, e.g. from database_agent). chart_type: bar|line|pie|scatter.",
          _CHART_SCHEMA)
    async def _create_chart(args):
        with tspan("tool:create_chart", span_type=SpanType.TOOL) as s:
            if s:
                s.set_inputs(args)
            text = create_chart(
                args.get("chart_type"), args.get("title"),
                args.get("labels"), args.get("datasets"),
            )
            ok = text.startswith(CHART_SUCCESS_PREFIX)
            if s:
                s.set_outputs({"result": text[:2000], "is_error": not ok})
        emit({"type": "tool_call", "agent": "orchestrator", "tool": "create_chart",
              "args": args, "result": text[:500], "is_error": not ok})
        if ok:
            emit({"type": "chart", "spec": args})
        return _result(text, is_error=not ok)

    @tool("suggest_form",
          "Suggest a relevant form for the user to fill as their next action.",
          {
              "type": "object",
              "properties": {
                  "form_id": {"type": "string",
                              "description": "Id of the form from the catalog."},
                  "prefill": {"type": "object", "additionalProperties": True,
                              "description": "Field values you already know from "
                              "the conversation or worker results, keyed by field "
                              "name."},
              },
              "required": ["form_id"],
          })
    async def _suggest_form(args):
        form_id = args.get("form_id", "")
        prefill = args.get("prefill") or {}
        with tspan("tool:suggest_form", span_type=SpanType.TOOL) as s:
            if s:
                s.set_inputs({"form_id": form_id, "prefill": prefill})
            text = suggest_form(form_id, prefill)
            ok = text.startswith(FORM_SUGGESTION_PREFIX)
            if s:
                s.set_outputs({"result": text[:2000], "is_error": not ok})
        emit({"type": "tool_call", "agent": "orchestrator", "tool": "suggest_form",
              "args": args, "result": text[:500], "is_error": not ok})
        if ok:
            from src.services.form_catalog import form_catalog
            form = form_catalog.get_form(form_id)
            if form is not None:
                emit({"type": "action", "action": "form_suggestion",
                      "form_id": form["id"], "form_name": form["name"],
                      "redirect_url": form["url"], "prefill": prefill})
        return _result(text, is_error=not ok)

    server = create_sdk_mcp_server(
        name="orchestrator-ops", version="1.0.0",
        tools=[_delegate, _create_chart, _suggest_form],
    )
    return server, ORCHESTRATOR_TOOL_NAMES


def make_options(*, server, tool_names, system_prompt, model, max_turns,
                 include_partial_messages=False, resume=None) -> ClaudeAgentOptions:
    """Build a locked-down ClaudeAgentOptions for one agent's query().

    `resume` continues a prior CLI session (multi-turn conversations) — the
    session transcript lives on the container's disk, so callers must handle a
    failed resume (see framework.chat's retry-without-resume)."""
    server_name = tool_names[0].split("__")[1]  # mcp__<name>__<tool>
    return ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        mcp_servers={server_name: server},
        allowed_tools=tool_names,
        max_turns=max_turns,
        include_partial_messages=include_partial_messages,
        resume=resume,
        **LOCKDOWN,
    )
