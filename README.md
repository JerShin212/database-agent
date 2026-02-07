# Database Agent

A conversational database agent that enables natural language interaction with SQLite databases and document collections. Built with FastAPI, React, and DSPy.

## Features

- **Natural Language Queries**: Ask questions about your data in plain English
- **SQLite Database Support**: Connect to SQLite databases and query them conversationally
- **Document Collections**: Upload and search through PDF, Word, Excel, CSV files
- **Vector Search**: Semantic search using OpenAI embeddings and VectorChord
- **DSPy Agent**: Intelligent agent that decides when to query databases vs search documents

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         Database Agent                              │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐  │
│  │   PostgreSQL + VectorChord  │  │   SQLite (User Databases)   │  │
│  │   (Application Database)    │  │                             │  │
│  ├─────────────────────────────┤  ├─────────────────────────────┤  │
│  │ • conversations             │  │ • Uploaded .db/.sqlite      │  │
│  │ • collections               │  │ • Sample sales database     │  │
│  │ • documents                 │  │ • Agent queries these       │  │
│  │ • document_chunks (vectors) │  │ • Read-only (SELECT only)   │  │
│  │ • sqlite_databases (meta)   │  │                             │  │
│  └─────────────────────────────┘  └─────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐  │
│  │         MinIO               │  │      DSPy ReAct Agent       │  │
│  ├─────────────────────────────┤  ├─────────────────────────────┤  │
│  │ • Original document files   │  │ • Claude Sonnet 4           │  │
│  │ • PDF, Word, Excel, CSV     │  │ • 6 tools (SQL + Search)    │  │
│  └─────────────────────────────┘  └─────────────────────────────┘  │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

**Why two databases?**
- **PostgreSQL**: Stores application data (conversations, document embeddings, metadata). Uses VectorChord extension for vector similarity search.
- **SQLite**: Stores user-uploaded databases that the agent can query. Each uploaded `.db` file is a separate SQLite database. The agent executes read-only SQL queries against these files.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI + Python 3.12 |
| Frontend | React + TypeScript + Vite |
| Agent | DSPy ReAct |
| App Database | PostgreSQL + VectorChord |
| User Databases | SQLite (uploaded files) |
| Document Storage | MinIO |
| Embeddings | OpenAI text-embedding-3-small |
| LLM | Claude Sonnet 4 |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- OpenAI API key
- Anthropic API key

### Setup

1. Clone and enter the directory:
```bash
cd database-agent
```

2. Copy environment file and add your API keys:
```bash
cp .env.example .env
# Edit .env with your OPENAI_API_KEY and ANTHROPIC_API_KEY
```

3. Start infrastructure:
```bash
make dev
```

4. Install dependencies and run locally:
```bash
# Terminal 1 - Backend
cd backend && uv sync && uv run python -m src.main

# Terminal 2 - Frontend
cd frontend && bun install && bun run dev
```

5. Open http://localhost:3000

### Or use Docker Compose:

```bash
make dev-up
```

## Usage

### 1. Create a Sample Database

1. Go to **Databases** page
2. Click "Create Sample DB"
3. Enter a name (e.g., "Sales Database")
4. The sample database includes: customers, products, orders, sales_reps

### 2. Upload Documents

1. Go to **Collections** page
2. Click "New Collection"
3. Upload PDF, Word, Excel, or CSV files
4. Wait for processing to complete

### 3. Start Chatting

Go to the **Chat** page and ask questions like:

- "What tables are in the database?"
- "Show me the top 10 customers by total orders"
- "What products have low stock?"
- "Search for documents about quarterly sales"
- "Compare our Q3 performance with projections from the report"

## API Endpoints

### Chat
- `POST /api/chat/stream` - Stream chat responses (SSE)
- `GET /api/chat/conversations` - List conversations
- `GET /api/chat/conversations/{id}` - Get conversation with messages
- `DELETE /api/chat/conversations/{id}` - Delete conversation

### Collections
- `POST /api/collections` - Create collection
- `GET /api/collections` - List collections
- `POST /api/collections/{id}/documents` - Upload documents
- `POST /api/collections/search` - Semantic search

### Databases
- `POST /api/databases` - Create/upload database
- `GET /api/databases` - List databases
- `GET /api/databases/{id}/schema` - Get schema
- `POST /api/databases/{id}/query` - Execute SQL query

## Agent Tools

The DSPy agent has access to:

1. **execute_sql_query** - Run SELECT queries
2. **get_database_schema** - Get full database schema
3. **list_tables** - List all tables
4. **get_table_info** - Get table details
5. **search_collections** - Semantic document search
6. **list_collections** - List document collections

## Development

```bash
# Start infrastructure
make dev

# Run backend
make backend

# Run frontend
make frontend

# View logs
make logs

# Clean up
make clean
```

## Project Structure

```
database-agent/
├── backend/
│   └── src/
│       ├── api/v1/          # API routes
│       ├── models/          # SQLAlchemy models
│       ├── schemas/         # Pydantic schemas
│       ├── services/        # Business logic
│       ├── processing/      # Document processing
│       ├── agent/           # DSPy agent & tools
│       └── scripts/         # Sample data
├── frontend/
│   └── src/
│       ├── components/      # React components
│       ├── pages/           # Page components
│       ├── stores/          # Zustand stores
│       └── services/        # API client
├── migrations/              # SQL migrations
└── docker-compose.yml
```

## License

MIT
