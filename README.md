# Database Agent

A conversational agent for natural-language interaction with SQLite databases, external SQL connectors, and document collections. Built with FastAPI, React, and the **Claude Agent SDK** (in-process MCP tools).

## Features

- **Natural Language Queries**: Ask questions about your data in plain English
- **Multi-agent orchestration**: A Claude orchestrator routes each question to specialist workers (SQL, document text, visual) and synthesizes their answers
- **SQL databases**: Query local SQLite files or external connectors; read-only (SELECT-only) with layered SQL-injection safety
- **Document collections**: Upload and search PDF, Word, Excel, CSV files
- **Hybrid + visual retrieval**: BM25 keyword + semantic search (RRF fusion), plus ColQwen2 visual page search and image-query search, MaxSim reranked
- **Charts & forms**: The agent can render charts and suggest pre-filled forms as actions
- **Streaming**: Server-Sent Events stream tokens, tool calls, charts, and actions in real time

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                            Database Agent                              │
├──────────────────────────────────────────────────────────────────────┤
│                                                                        │
│   Orchestrator (Claude Sonnet 4.6)  —  tools: delegate / create_chart  │
│                                          / suggest_form                 │
│                       │  delegates to                                   │
│        ┌──────────────┼───────────────────────────┐                    │
│        ▼              ▼                            ▼                    │
│  database_agent   text_search_agent        visual_search_agent         │
│   (Haiku 4.5)        (Haiku 4.5)               (Haiku 4.5)              │
│  database-ops     doc-search MCP            visual-search MCP           │
│   MCP server       server                    server                    │
│        │              │                            │                   │
│        ▼              ▼                            ▼                    │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐      │
│  │   PostgreSQL + VectorChord  │  │   SQLite (User Databases)   │      │
│  │   (Application Database)    │  │                             │      │
│  │ • conversations             │  │ • Uploaded .db/.sqlite      │      │
│  │ • collections / documents   │  │ • Sample sales database     │      │
│  │ • document_chunks (vectors) │  │ • Read-only (SELECT only)   │      │
│  │ • document_pages (visual)   │  │                             │      │
│  │ • schema catalog (vectors)  │  │                             │      │
│  └─────────────────────────────┘  └─────────────────────────────┘      │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐      │
│  │         MinIO               │  │   ColQwen2 (Modal endpoints)│      │
│  │ • Original document files   │  │ • text / pdf / image embeds │      │
│  └─────────────────────────────┘  └─────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────┘
```

Each agent runs as its own `query()` loop from the Claude Agent SDK, and its
tools are exposed as an **in-process MCP server** (`create_sdk_mcp_server`). Tools
are plain Python functions over the DB / retrieval stack — there is no separate
tool server or transport. See [How the agent works](#how-the-agent-works).

**Why two databases?**
- **PostgreSQL + VectorChord**: application data — conversations, document
  embeddings (text chunks + visual pages), the semantic schema catalog, and
  metadata. Uses VectorChord (pgvector) for vector similarity and `pg_search`
  (BM25) for keyword search.
- **SQLite**: user-uploaded databases the agent queries. Each uploaded `.db` file
  is a separate database; the agent runs read-only SQL against it.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI + Python 3.12 |
| Frontend | React + TypeScript + Vite + Zustand |
| Agent | Claude Agent SDK (in-process MCP tools) |
| Orchestrator LLM | Claude Sonnet 4.6 |
| Worker LLMs | Claude Haiku 4.5 (escalates to Sonnet on failure) |
| App Database | PostgreSQL + VectorChord + pg_search (BM25) |
| User Databases | SQLite (uploaded files) / external SQL connectors |
| Document Storage | MinIO |
| Embeddings | ColQwen2 (multi-vector, 128-dim) served on Modal |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- An **Anthropic API key**
- For **local (non-Docker) dev**: the Claude Code CLI on your `PATH` — the Agent
  SDK runs the agent loop by spawning it:
  ```bash
  npm install -g @anthropic-ai/claude-code   # provides the `claude` binary
  ```
  (The Docker image installs this for you — see [Deployment](#deployment-docker).)

### Setup

1. Enter the directory:
```bash
cd database-agent
```

2. Copy the environment file and add your API key:
```bash
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY (and ENCRYPTION_KEY for external connectors)
```

3. Start infrastructure (Postgres, MinIO):
```bash
make dev
```

4. Install dependencies and run locally:
```bash
# Terminal 1 - Backend  (requires the `claude` CLI on PATH, see Prerequisites)
cd backend && uv sync && uv run python -m src.main

# Terminal 2 - Frontend
cd frontend && bun install && bun run dev
```

5. Open the frontend (default Vite dev URL) and start chatting.

### Or use Docker Compose:

```bash
make dev-up
```

## Usage

### 1. Create a Sample Database

1. Go to the **Databases** page
2. Click "Create Sample DB" and name it (e.g., "Sales Database")
3. The sample includes: customers, products, orders

### 2. Upload Documents

1. Go to the **Collections** page → "New Collection"
2. Upload PDF, Word, Excel, or CSV files and wait for processing

### 3. Start Chatting

Ask questions like:

- "What tables are in the database?"
- "Show me the top 10 customers by total orders"
- "Which products are out of stock? Chart it."
- "Search the manuals for the warranty period"
- "Show me the wiring diagram for the outdoor unit" (visual search)
- "Compare our Q3 performance with the projections from the report"

## How the agent works

- **Orchestrator** (Sonnet 4.6) — its only tools are `delegate`, `create_chart`,
  and `suggest_form`. It routes each question to one or more workers and
  synthesizes the result.
- **Workers** (Haiku 4.5), each with a narrow in-process MCP server:
  - `database_agent` → `database-ops`: SQL + schema exploration
  - `text_search_agent` → `doc-search`: hybrid document text search
  - `visual_search_agent` → `visual-search`: ColQwen2 visual / image search
- **Fallback & escalation** (in `delegate`): when a worker returns `NO_RESULTS`,
  the task is retried on the alternate worker (SQL ↔ documents); on a capability
  failure, the worker is retried on a stronger model (Haiku → Sonnet).
- **Safety**: every `query()` is locked down (`permission_mode="dontAsk"`,
  `tools=[]`, `setting_sources=[]`, plus an MCP allowlist) so agents can only call
  their own tools — no shell, file, or web access. `execute_sql_query` is further
  gated by `validate_sql()` (SELECT/WITH-only) + `ensure_limit()`.

### Agent tools (MCP)

| Server | Tools |
|--------|-------|
| `database-ops` | `execute_sql_query`, `get_database_schema`, `list_tables`, `get_table_info`, `search_schema_catalog` |
| `doc-search` | `search_collections`, `read_document`, `list_collections` |
| `visual-search` | `search_visual_documents`, `search_by_image`, `list_collections` |
| `orchestrator-ops` | `delegate`, `create_chart`, `suggest_form` |

## API Endpoints

- `POST /api/chat/` · `POST /api/chat/stream` — chat (stream is SSE)
- `GET|DELETE /api/chat/conversations[/{id}]` — conversation history
- `/api/collections` — document collections (CRUD, upload, search)
- `/api/databases` — SQLite database management (create/upload, schema, query)
- `/api/connectors` — external SQL connector management + semantic catalog indexing
- `/api/schema` — schema catalog indexing
- `/api/forms` — form catalog (suggested-form integration)
- `/api/integrations/*` — module-to-module endpoints (X-API-Key via `INTEGRATION_API_KEY`)

## Deployment (Docker)

The backend `Dockerfile` installs Node + the Claude Code CLI
(`npm install -g @anthropic-ai/claude-code`) so the Agent SDK can spawn the
agent-loop subprocess — the Python SDK is only a client. At runtime the container
needs `ANTHROPIC_API_KEY` in its environment.

> Performance note: each `query()` spawns one `claude` subprocess, so a single
> chat can run up to ~5 concurrent processes (orchestrator + 3 workers +
> escalation). Size container CPU/memory accordingly.

## Development

```bash
make dev        # start infrastructure
make backend    # run backend
make frontend   # run frontend
make logs       # view logs
make clean      # clean up
```

### Tests

```bash
cd backend
.venv/bin/python -m pytest                      # unit tests
RUN_EVALS=1 .venv/bin/python -m pytest tests/eval -m eval   # LLM evals (need ANTHROPIC_API_KEY)
```

## Project Structure

```
database-agent/
├── backend/
│   └── src/
│       ├── api/v1/          # API routes
│       ├── models/          # SQLAlchemy models
│       ├── schemas/         # Pydantic schemas
│       ├── services/        # Business logic (ColQwen2 client, search, connectors)
│       ├── processing/      # Document processing
│       ├── agent/           # Agent runtime
│       │   ├── framework.py #   chat() entrypoint → orchestrator query()
│       │   ├── prompts.py   #   orchestrator + worker system prompts
│       │   ├── sdk/         #   Claude Agent SDK layer
│       │   │   ├── servers.py        # 4 in-process MCP servers + lockdown
│       │   │   ├── worker.py         # run_worker() — worker query() loop
│       │   │   ├── orchestrator.py   # delegate + fallback/escalation + event stream
│       │   │   ├── sql_safety.py     # validate_sql() + ensure_limit()
│       │   │   └── descriptor.py     # per-request descriptor
│       │   └── tools/       #   tool implementations (SQL, search, chart, form)
│       └── scripts/         # Sample data / eval scripts
├── frontend/
│   └── src/                 # components / pages / stores / services
├── migrations/              # SQL migrations
└── docker-compose.yml
```

## License

MIT
