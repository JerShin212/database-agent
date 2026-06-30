# Database Agent Backend

FastAPI backend for the Database Agent — a conversational AI that helps users
interact with SQLite databases, external SQL connectors, and document collections.

## Features

- Multi-agent runtime on the **Claude Agent SDK** with in-process MCP tools — an
  orchestrator (Claude Sonnet 4.6) delegates to three Haiku workers (database /
  text-search / visual-search), with NO_RESULTS fallback and Haiku→Sonnet escalation
- SQL querying with layered safety (SELECT/WITH-only validation + row-limit wrapping)
- Document upload, hybrid (BM25 + semantic) search, and ColQwen2 visual page search
- SSE streaming for real-time chat responses (tokens, tool calls, charts, actions)

## Quick Start

```bash
# Requires the `claude` CLI on PATH (the Agent SDK spawns it as a subprocess):
#   npm install -g @anthropic-ai/claude-code

# Install dependencies (uv-managed venv)
uv sync

# Run the server
uv run python -m src.main
```

## Agent layer

The agent code lives in `src/agent/`:

- `framework.py` — `chat()` entrypoint; drives the orchestrator `query()` and
  streams events back as SSE chunks.
- `sdk/` — the Claude Agent SDK integration: `servers.py` (four in-process MCP
  servers + permission lockdown), `worker.py` (`run_worker`), `orchestrator.py`
  (`delegate` + fallback/escalation + event stream), `sql_safety.py`,
  `descriptor.py`.
- `tools/` — the tool implementations (SQL, search, schema catalog, chart, form).
- `prompts.py` — orchestrator and worker system prompts.

## Tests

```bash
.venv/bin/python -m pytest                                   # unit tests
RUN_EVALS=1 .venv/bin/python -m pytest tests/eval -m eval    # LLM evals (need ANTHROPIC_API_KEY)
```

## API Documentation

Run the server and see the interactive OpenAPI docs at `/docs`.
