# Database Agent - Project Specification

## Executive Summary

A conversational database agent that enables natural language interaction with SQLite databases and document collections. Built with FastAPI backend, React frontend, and DSPy-powered agent with vector search capabilities using VectorChord.

---

## 1. Project Overview

### 1.1 Goals
- Connect to SQLite databases with multiple tables
- Upload and search document collections (PDFs, CSVs, etc.)
- Natural language conversations that query both database and documents
- Simple, maintainable architecture following established patterns

### 1.2 Tech Stack

| Component | Technology | Source Pattern |
|-----------|------------|----------------|
| Backend | FastAPI + Python 3.12 | cxs-chatbot |
| Frontend | React + TypeScript + Vite | cxs-chatbot |
| Agent Framework | DSPy ReAct | cxs-chatbot |
| Vector Database | PostgreSQL + VectorChord | sourcing-agent-v2 |
| Document Storage | MinIO (S3-compatible) | sourcing-agent-v2 |
| Primary Database | SQLite (user data) | New |
| Embeddings | OpenAI text-embedding-3-small | sourcing-agent-v2 |
| LLM | Claude Sonnet 4 | Both |
| State Management | Zustand | cxs-chatbot |

### 1.3 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend                           │
│  - Chat Interface (SSE streaming)                            │
│  - Collection Manager                                        │
│  - Database Browser                                          │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP/SSE
┌─────────────────────────▼───────────────────────────────────┐
│                     FastAPI Backend                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Chat Router     │  │ Collections     │  │ Databases    │ │
│  │ /api/chat/*     │  │ /api/collections│  │ /api/db/*    │ │
│  └────────┬────────┘  └────────┬────────┘  └──────┬───────┘ │
│           │                    │                   │         │
│  ┌────────▼────────────────────▼───────────────────▼───────┐│
│  │                    DSPy ReAct Agent                      ││
│  │  Tools: execute_sql_query, search_collections,          ││
│  │         get_database_schema, list_tables,               ││
│  │         get_table_info, list_collections                ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
          │                    │                    │
┌─────────▼──────┐  ┌─────────▼──────┐  ┌─────────▼──────┐
│   PostgreSQL   │  │     MinIO      │  │    SQLite      │
│  + VectorChord │  │  (Documents)   │  │  (User Data)   │
│  (Embeddings)  │  │                │  │                │
└────────────────┘  └────────────────┘  └────────────────┘
```

---

## 2. Database Schema

### 2.1 PostgreSQL (Metadata + Vectors)

```sql
-- Enable VectorChord extension (includes pgvector)
CREATE EXTENSION IF NOT EXISTS vchord CASCADE;

-- Collections table
CREATE TABLE collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    document_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Documents table
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size INTEGER NOT NULL,
    page_count INTEGER,
    minio_object_key VARCHAR(1000) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending', -- pending, processing, completed, failed
    error_message TEXT,
    extracted_text TEXT,
    summary TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Document chunks with embeddings
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    collection_id UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    start_char INTEGER,
    end_char INTEGER,
    embedding VECTOR(1536), -- OpenAI embedding dimension
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for vector similarity search (VectorChord with L2 distance)
CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
ON document_chunks USING vchordrq (embedding vector_l2_ops);

-- Conversations table
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Messages table
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- 'user' or 'assistant'
    content TEXT NOT NULL,
    tool_calls JSONB, -- Store tool execution history
    created_at TIMESTAMP DEFAULT NOW()
);

-- SQLite database connections
CREATE TABLE sqlite_databases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_documents_collection_id ON documents(collection_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_collection_id ON document_chunks(collection_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
```

### 2.2 SQLite Sample Data (Sales Database)

```sql
-- Sample sales database schema
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT,
    city TEXT,
    country TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    price DECIMAL(10, 2) NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customers(id),
    order_date DATE NOT NULL,
    total_amount DECIMAL(10, 2),
    status TEXT DEFAULT 'pending', -- pending, shipped, delivered, cancelled
    shipping_address TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sales_reps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    region TEXT,
    hire_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE customer_sales_rep (
    customer_id INTEGER REFERENCES customers(id),
    sales_rep_id INTEGER REFERENCES sales_reps(id),
    assigned_date DATE,
    PRIMARY KEY (customer_id, sales_rep_id)
);
```

---

## 3. API Endpoints

### 3.1 Chat Endpoints

```
POST /api/chat/stream
    Request:
        {
            "message": string,
            "conversation_id": string | null,
            "collection_ids": string[] | null,
            "database_id": string | null
        }
    Response: SSE stream with content and tool_calls

GET /api/chat/conversations
    Query: skip, limit (pagination)
    Response: List of conversations with metadata

GET /api/chat/conversations/{id}
    Response: Conversation with all messages

DELETE /api/chat/conversations/{id}
    Response: 204 No Content
```

### 3.2 Collection Endpoints

```
POST /api/collections
    Request: { "name": string, "description": string }
    Response: Collection object

GET /api/collections
    Response: List of collections with document counts

GET /api/collections/{id}
    Response: Collection details

DELETE /api/collections/{id}
    Response: 204 No Content

POST /api/collections/{id}/documents
    Request: multipart/form-data with files (max 10, 50MB each)
    Response: List of created document objects

GET /api/collections/{id}/documents
    Response: List of documents with status

GET /api/collections/{id}/status
    Response: { "total": int, "pending": int, "processing": int, "completed": int, "failed": int }

DELETE /api/collections/documents/{id}
    Response: 204 No Content

GET /api/collections/documents/{id}/download
    Response: Presigned MinIO URL for document download

POST /api/collections/search
    Request: { "query": string, "collection_ids": string[], "limit": int }
    Response: List of SearchResult objects with scores
```

### 3.3 Database Endpoints

```
POST /api/databases
    Request: multipart/form-data with SQLite file OR { "name": string, "create_sample": true }
    Response: Database object

GET /api/databases
    Response: List of active databases

GET /api/databases/{id}
    Response: Database info

GET /api/databases/{id}/schema
    Response: Full schema with tables, columns, sample data

POST /api/databases/{id}/query
    Request: { "sql": string }
    Response: Query results (SELECT only, safety-validated)

DELETE /api/databases/{id}
    Response: 204 No Content
```

---

## 4. DSPy Agent Design

### 4.1 Agent Architecture

```python
# Dual-agent pattern for conversation handling
class DatabaseAgent:
    def __init__(self):
        self.lm = dspy.LM("anthropic/claude-sonnet-4-20250514")

        # Initial query agent (no conversation history)
        self.initial_agent = dspy.ReAct(
            InitialQuerySignature,
            tools=[
                execute_sql_query,
                search_collections,
                get_database_schema,
                list_tables,
                get_table_info,
                list_collections,
            ],
            max_iters=10
        )

        # Follow-up agent (has conversation context)
        self.followup_agent = dspy.ReAct(
            FollowUpQuerySignature,
            tools=[...same tools...],
            max_iters=10
        )
```

### 4.2 Agent Tools (6 Total)

#### SQL Tools (4)

**Tool 1: execute_sql_query**
```python
def execute_sql_query(sql: str, database_id: str = None) -> str:
    """
    Execute a SQL query against the SQLite database.

    Args:
        sql: The SQL query to execute (SELECT only)
        database_id: Optional specific database to query

    Returns:
        Query results as formatted text/table

    Security:
        - Only SELECT statements allowed
        - Blocks dangerous keywords (DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE, REPLACE)
        - Row limit (max 1000)
    """
```

**Tool 2: get_database_schema**
```python
def get_database_schema(database_id: str = None) -> str:
    """
    Get the complete schema of the database.

    Returns:
        Formatted schema with:
        - Table names with row/column counts
        - Column names and types
        - Foreign key relationships
        - Sample data (3 rows per table)
    """
```

**Tool 3: list_tables**
```python
def list_tables(database_id: str = None) -> str:
    """
    List all tables in the database with basic info.

    Returns:
        Table names with row counts and column counts
    """
```

**Tool 4: get_table_info**
```python
def get_table_info(table_name: str, database_id: str = None) -> str:
    """
    Get detailed information about a specific table.

    Returns:
        - Column definitions with types
        - Sample data (5 rows)
        - Row count
    """
```

#### Document Search Tools (2)

**Tool 5: search_collections**
```python
def search_collections(query: str, collection_ids: list[str] = None, limit: int = 5) -> str:
    """
    Search document collections using semantic vector search.

    Args:
        query: Natural language search query
        collection_ids: Optional list of collection IDs to search
        limit: Maximum number of results (default 5)

    Returns:
        Relevant document chunks with:
        - Content snippet
        - Document filename
        - Relevance score (L2 distance converted to similarity)
    """
```

**Tool 6: list_collections**
```python
def list_collections() -> str:
    """
    List all available document collections.

    Returns:
        Collection names, descriptions, and document counts
    """
```

### 4.3 Tool Context Management

Tools use thread-local context via `ToolContext` class:
- Passes database session for async operations
- Provides active `database_id` and `collection_ids`
- Handles async event loop detection for sync DSPy tools

### 4.4 Agent Signatures

```python
class InitialQuerySignature(dspy.Signature):
    """You are a database and document assistant. Help users query databases
    and search through document collections. Always verify the schema before
    writing queries. Cite sources when using document content."""

    question: str = dspy.InputField(desc="The user's question")
    answer: str = dspy.OutputField(desc="Your helpful response with data and citations")


class FollowUpQuerySignature(dspy.Signature):
    """You are a database and document assistant with conversation context."""

    conversation_history: str = dspy.InputField(desc="Previous messages")
    question: str = dspy.InputField(desc="The user's current question")
    answer: str = dspy.OutputField(desc="Your helpful response")
```

### 4.5 System Prompt

```python
SYSTEM_PROMPT = """
You are a Database & Document Agent that helps users interact with SQLite databases
and document collections through natural language.

## Your Capabilities

1. **Database Queries**: Execute SQL queries against SQLite databases
   - Always check the schema first using get_database_schema or get_table_info
   - Write efficient, well-formed SQL queries
   - Explain query results in natural language

2. **Document Search**: Search through uploaded document collections
   - Use semantic search to find relevant information
   - Cite sources with document names
   - Combine information from multiple documents

3. **Combined Analysis**: Answer questions using both database and documents

## Guidelines

- Always verify table/column names before writing SQL
- For complex questions, break them into steps
- Cite document sources when using collection data
- If a query returns no results, suggest alternatives
- Format data tables clearly when showing results

## Available Tools

1. `execute_sql_query(sql, database_id)` - Run SQL SELECT queries
2. `get_database_schema(database_id)` - Get full database schema
3. `list_tables(database_id)` - List all tables
4. `get_table_info(table_name, database_id)` - Get table details
5. `search_collections(query, collection_ids, limit)` - Search documents
6. `list_collections()` - List document collections
"""
```

---

## 5. Document Processing Pipeline

### 5.1 Processing Flow (Synchronous)

Document processing runs synchronously on the upload request (no Celery/Redis):

```
Upload Request → API Endpoint
    ↓
Create Document Record (status: pending)
    ↓
Upload to MinIO
    ↓
Process Synchronously:
│
│  1. Update status to 'processing'
│  2. Download from MinIO
│  3. Extract text (by file type)
│  4. Chunk text (semantic splitting)
│  5. Generate embeddings (OpenAI batch)
│  6. Store chunks in PostgreSQL
│  7. Update status to 'completed'
│
└─→ Return response
```

### 5.2 Supported File Types

| Type | MIME Type | Extractor |
|------|-----------|-----------|
| PDF | application/pdf | pdfplumber |
| Word | application/vnd.openxmlformats-officedocument.wordprocessingml.document | python-docx |
| Excel | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | openpyxl |
| CSV | text/csv | pandas |
| Text | text/plain | direct read |
| Markdown | text/markdown | direct read |
| Fallback | application/octet-stream | TextExtractor |

### 5.3 Chunking Configuration

```yaml
chunking:
  strategy: semantic
  chunk_size: 500  # characters
  chunk_overlap: 50  # characters
  separators:
    - "\n\n"  # Paragraphs first
    - "\n"    # Then lines
    - ". "    # Then sentences
    - " "     # Then words
    - ""      # Final fallback
```

### 5.4 Embedding Details

- Model: OpenAI `text-embedding-3-small`
- Dimensions: 1536
- Batch processing: 100 texts per API call
- Retry logic: 3 attempts with exponential backoff

### 5.5 Vector Search

- Database: PostgreSQL with VectorChord extension
- Index: `vchordrq` with `vector_l2_ops` (L2/Euclidean distance)
- Distance operator: `<->` for L2 distance
- Similarity scoring: `1 / (1 + distance)` conversion
- Supports filtering by collection IDs

---

## 6. Frontend Components

### 6.1 Page Structure

```
/                    → Chat page (main interface)
/collections         → Collection management
/databases           → Database browser
```

### 6.2 Tech Stack

- **Framework**: React 18.3 + TypeScript
- **Build Tool**: Vite 5.4
- **Routing**: React Router v6
- **State Management**: Zustand 4.5
- **Styling**: Tailwind CSS 3.4
- **HTTP Client**: Axios 1.7
- **Markdown**: react-markdown 9.0
- **Icons**: lucide-react 0.400

### 6.3 Key Components

```typescript
// Main chat interface
<ChatPage>
  <Sidebar>
    <ConversationList />
    <NewChatButton />
  </Sidebar>
  <MainPanel>
    <ChatHeader>
      <DatabaseSelector />
      <CollectionSelector />
    </ChatHeader>
    <ChatInterface>
      <MessageList />  // With tool call display
      <ChatInput />
    </ChatInterface>
  </MainPanel>
</ChatPage>

// Collection management
<CollectionsPage>
  <CollectionList />
  <CreateCollectionModal />
  <DocumentUploader />  // Drag-drop file upload
  <DocumentList />      // With processing status
</CollectionsPage>

// Database browser
<DatabasesPage>
  <DatabaseList />
  <UploadDatabaseModal />
  <CreateSampleDataButton />
  <SchemaViewer />
  <QueryTester />  // SQL query testing
</DatabasesPage>
```

### 6.4 State Management (Zustand)

```typescript
// Chat store
interface ChatStore {
  conversations: Conversation[]
  currentConversation: Conversation | null
  messages: Message[]
  isStreaming: boolean
  streamingContent: string
  streamingToolCalls: ToolCall[]

  // Actions
  loadConversations(): Promise<void>
  selectConversation(id: string): Promise<void>
  deleteConversation(id: string): Promise<void>
  sendMessage(content: string): Promise<void>
  startNewConversation(): void
}

// Settings store
interface SettingsStore {
  selectedDatabaseId: string | null
  selectedCollectionIds: string[]

  setDatabase(id: string | null): void
  toggleCollection(id: string): void
}

// Collections store
interface CollectionsStore {
  collections: Collection[]
  selectedCollection: Collection | null
  documents: Document[]

  loadCollections(): Promise<void>
  createCollection(name: string, description: string): Promise<void>
  uploadDocuments(collectionId: string, files: File[]): Promise<void>
  deleteCollection(id: string): Promise<void>
  deleteDocument(id: string): Promise<void>
}

// Databases store
interface DatabasesStore {
  databases: Database[]
  selectedDatabase: Database | null
  schema: Schema | null
  queryResult: QueryResult | null

  loadDatabases(): Promise<void>
  createSampleDatabase(): Promise<void>
  uploadDatabase(file: File, name: string): Promise<void>
  selectDatabase(id: string): Promise<void>
  deleteDatabase(id: string): Promise<void>
  executeQuery(sql: string): Promise<void>
}
```

---

## 7. Docker Compose Configuration

```yaml
services:
  # PostgreSQL with VectorChord for embeddings
  postgres:
    image: ghcr.io/tensorchord/vchord-postgres:pg17-v1.0.0
    container_name: db-agent-postgres
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: database_agent
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./migrations/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  # MinIO for document storage
  minio:
    image: minio/minio:latest
    container_name: db-agent-minio
    command: server /data --console-address ":9003"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9002:9000"
      - "9003:9003"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  # FastAPI Backend
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: db-agent-backend
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/database_agent
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=minioadmin
      - MINIO_SECRET_KEY=minioadmin
      - MINIO_BUCKET_NAME=documents
      - MINIO_SECURE=false
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - SQLITE_DATA_PATH=/app/data/sqlite
    ports:
      - "8000:8000"
    volumes:
      - ./backend/src:/app/src
      - sqlite_data:/app/data/sqlite
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy

  # React Frontend
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: db-agent-frontend
    environment:
      - VITE_API_URL=http://localhost:8000
    ports:
      - "3000:3000"
    volumes:
      - ./frontend/src:/app/src
    depends_on:
      - backend

volumes:
  postgres_data:
  minio_data:
  sqlite_data:
```

---

## 8. Project Structure

```
database-agent/
├── docker-compose.yml
├── .env.example
├── Makefile
├── README.md
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   │
│   └── src/
│       ├── main.py                      # FastAPI app entry
│       ├── config.py                    # Settings (Pydantic)
│       │
│       ├── api/
│       │   ├── deps.py                  # Dependencies (DB session)
│       │   └── v1/
│       │       ├── chat.py              # Chat + SSE streaming
│       │       ├── collections.py       # Collection CRUD
│       │       └── databases.py         # SQLite management
│       │
│       ├── models/
│       │   ├── collection.py            # Collection, Document, Chunk
│       │   ├── conversation.py          # Conversation, Message
│       │   └── database.py              # SQLiteDatabase
│       │
│       ├── schemas/
│       │   ├── chat.py                  # Request/Response schemas
│       │   ├── collection.py
│       │   └── database.py
│       │
│       ├── services/
│       │   ├── embedding_service.py     # OpenAI embeddings
│       │   ├── vector_db.py             # VectorChord operations
│       │   ├── search_service.py        # Semantic search
│       │   ├── minio_service.py         # Object storage
│       │   └── sqlite_service.py        # SQLite operations
│       │
│       ├── processing/
│       │   ├── document_processor.py    # Main processing pipeline
│       │   ├── extractors/
│       │   │   ├── base.py
│       │   │   ├── pdf.py
│       │   │   ├── docx.py
│       │   │   ├── excel.py
│       │   │   ├── csv.py
│       │   │   ├── text.py
│       │   │   └── factory.py
│       │   └── chunking/
│       │       └── semantic.py
│       │
│       ├── agent/
│       │   ├── framework.py             # DSPy ReAct setup
│       │   ├── prompts.py               # System prompts
│       │   └── tools/
│       │       ├── sql_tools.py         # 4 SQL tools
│       │       ├── search_tools.py      # 2 search tools
│       │       └── context.py           # Tool context (thread-local)
│       │
│       └── db/
│           └── database.py              # Async SQLAlchemy setup
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   │
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       │
│       ├── components/
│       │   ├── chat/
│       │   │   ├── ChatInterface.tsx
│       │   │   ├── MessageList.tsx
│       │   │   └── ConversationList.tsx
│       │   └── shared/
│       │       └── Layout.tsx
│       │
│       ├── pages/
│       │   ├── ChatPage.tsx
│       │   ├── CollectionsPage.tsx
│       │   └── DatabasesPage.tsx
│       │
│       ├── stores/
│       │   ├── chatStore.ts
│       │   ├── settingsStore.ts
│       │   ├── collectionsStore.ts
│       │   └── databasesStore.ts
│       │
│       ├── services/
│       │   └── api.ts
│       │
│       └── types/
│           └── index.ts
│
├── migrations/
│   └── init.sql                         # PostgreSQL schema
│
└── docs/
    └── DATABASE_AGENT_SPEC.md           # This file
```

---

## 9. Environment Variables

```bash
# .env.example

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/database_agent

# MinIO
MINIO_ENDPOINT=localhost:9002
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=documents
MINIO_SECURE=false

# SQLite storage path
SQLITE_DATA_PATH=./data/sqlite

# LLM APIs
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Embedding model
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536

# Chunking config
CHUNK_SIZE=500
CHUNK_OVERLAP=50

# Backend
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
DEBUG=true

# Frontend
VITE_API_URL=http://localhost:8000
```

---

## 10. Makefile Commands

```makefile
.PHONY: help install dev backend frontend clean

help:
    @echo "Database Agent - Development Commands"
    @echo ""
    @echo "  make install      Install all dependencies"
    @echo "  make dev          Start infrastructure (postgres, minio)"
    @echo "  make backend      Run backend locally"
    @echo "  make frontend     Run frontend locally"
    @echo "  make dev-up       Start all services in Docker"
    @echo "  make down         Stop all services"
    @echo "  make clean        Remove containers and volumes"

install:
    cd backend && uv sync
    cd frontend && bun install

dev:
    docker compose up -d postgres minio

backend:
    cd backend && uv run python -m src.main

frontend:
    cd frontend && bun run dev

dev-up:
    docker compose up -d --build

down:
    docker compose down

clean:
    docker compose down -v
```

---

## 11. Key Implementation Decisions

### 11.1 No Celery/Redis

Document processing runs synchronously on the upload request:
- Simpler architecture with fewer moving parts
- Faster feedback for smaller documents
- Status tracking still works via database state
- Could be async-ified later if needed

### 11.2 VectorChord over pgvector

- Uses `ghcr.io/tensorchord/vchord-postgres:pg17-v1.0.0`
- `vchordrq` index type for better performance
- L2 (Euclidean) distance with `<->` operator
- Similarity score: `1 / (1 + distance)`

### 11.3 Tool Context via Thread-Local Storage

- Elegant solution for passing context to stateless DSPy tools
- Avoids modifying tool signatures
- Supports async event loop detection

### 11.4 SQLite for User Data

- User databases stored in `/data/sqlite` directory
- Supports uploading .db/.sqlite files
- Sample database with realistic sales data
- Query safety: SELECT only, dangerous keywords blocked

### 11.5 Streaming Chat via SSE

- Server-Sent Events for real-time streaming
- Tool calls streamed as they execute
- Conversation auto-saved with title from first message

---

## 12. Security Considerations

1. **SQL Injection Prevention**: Only SELECT allowed, dangerous keywords blocked
2. **Row Limits**: Query results capped to prevent memory issues
3. **File Validation**: MIME type checking, size limits (50MB)
4. **No Credentials in Code**: All secrets via environment variables

---

## 13. Example Conversations

### Example 1: Database Query
```
User: What were the top 5 selling products last month?

Agent: [Thought] I need to check the database schema first.
       [Tool] get_database_schema()
       [Result] Tables: customers, products, orders, order_items...

       [Thought] Now I'll query for top products.
       [Tool] execute_sql_query("""
           SELECT p.name, SUM(oi.quantity) as total_sold
           FROM products p
           JOIN order_items oi ON p.id = oi.product_id
           JOIN orders o ON oi.order_id = o.id
           WHERE o.order_date >= date('now', '-1 month')
           GROUP BY p.id
           ORDER BY total_sold DESC
           LIMIT 5
       """)

Response: Here are the top 5 selling products last month:
| Product | Units Sold |
|---------|------------|
| Widget Pro | 145 |
| ...
```

### Example 2: Document + Database
```
User: Based on the Q3 sales report and our database,
      how did we perform compared to projections?

Agent: [Tool] search_collections("Q3 sales report projections")
       [Result] Found: Q3_Sales_Report.pdf - "Q3 projections: $2.5M..."

       [Tool] execute_sql_query("""
           SELECT SUM(total_amount) as revenue
           FROM orders
           WHERE order_date BETWEEN '2024-07-01' AND '2024-09-30'
       """)
       [Result] Revenue: $2.8M

Response: According to Q3_Sales_Report.pdf, the projected revenue
          was $2.5M. Our database shows actual revenue of $2.8M,
          exceeding projections by 12%.
```

---

## 14. Current Capabilities Summary

| Feature | Status | Details |
|---------|--------|---------|
| Chat Interface | ✅ | Real-time SSE streaming |
| Database Querying | ✅ | SQLite with safety validation |
| Document Upload | ✅ | PDF, DOCX, XLSX, CSV, TXT support |
| Vector Search | ✅ | VectorChord with L2 distance |
| Embeddings | ✅ | OpenAI text-embedding-3-small |
| Agent Tools | ✅ | 6 tools (4 SQL, 2 search) |
| Conversation History | ✅ | Persistent with tool call tracking |
| Docker Deployment | ✅ | Full compose setup |
| Frontend UI | ✅ | React with Tailwind, 3 pages |

---

This specification reflects the actual implementation without Celery/Redis, using VectorChord for vector search, and synchronous document processing.
