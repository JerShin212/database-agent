# Database Agent - API Endpoints & Sequence Diagrams

## Overview

- **Base URL**: `http://localhost:8000`
- **API Prefix**: `/api`
- **Authentication**: None (development mode)
- **CORS Origins**: `http://localhost:3000`, `http://localhost:5173`

---

## Table of Contents

1. [Health & Root](#1-health--root-endpoints)
2. [Chat Endpoints](#2-chat-endpoints)
3. [Collections Endpoints](#3-collections-endpoints)
4. [Databases Endpoints](#4-databases-endpoints)

---

## 1. Health & Root Endpoints

### GET /health
Health check endpoint.

**Response**: `200 OK`
```json
{
  "status": "healthy"
}
```

### GET /
Root endpoint.

**Response**: `200 OK`
```json
{
  "message": "Database Agent API",
  "version": "1.0.0"
}
```

---

## 2. Chat Endpoints

**Router Prefix**: `/api/chat`

### 2.1 POST /api/chat/stream

Stream a chat response using SSE (Server-Sent Events).

**Request Body**:
```json
{
  "message": "string (required)",
  "conversation_id": "UUID (optional)",
  "collection_ids": ["UUID"] (optional),
  "database_id": "UUID (optional)"
}
```

**Response**: `text/event-stream`
```
data: {"type": "content", "content": "Hello..."}
data: {"type": "tool_call", "tool": "get_database_schema", "args": {...}, "result": "..."}
data: {"type": "content", "content": " world!"}
data: {"type": "done", "conversation_id": "uuid"}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │  Agent   │          │  Claude  │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │                     │
     │ POST /chat/stream   │                     │                     │                     │
     │ ─────────────────>  │                     │                     │                     │
     │                     │                     │                     │                     │
     │                     │  Get conversation   │                     │                     │
     │                     │  (if id provided)   │                     │                     │
     │                     │ ──────────────────> │                     │                     │
     │                     │ <────────────────── │                     │                     │
     │                     │                     │                     │                     │
     │                     │  Get messages       │                     │                     │
     │                     │ ──────────────────> │                     │                     │
     │                     │ <────────────────── │                     │                     │
     │                     │                     │                     │                     │
     │                     │  Set ToolContext    │                     │                     │
     │                     │ ─────────────────────────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │                     │                     │  agent.chat()       │
     │                     │                     │                     │ ──────────────────> │
     │                     │                     │                     │                     │
     │                     │                     │                     │  [Tool Calls Loop]  │
     │                     │                     │                     │ <──────────────────>│
     │                     │                     │                     │                     │
     │  SSE: tool_call     │                     │                     │                     │
     │ <───────────────────│<─────────────────────────────────────────│                     │
     │                     │                     │                     │                     │
     │                     │                     │                     │  Final response     │
     │                     │                     │                     │ <────────────────── │
     │                     │                     │                     │                     │
     │  SSE: content       │                     │                     │                     │
     │ <───────────────────│<─────────────────────────────────────────│                     │
     │                     │                     │                     │                     │
     │                     │  Save user message  │                     │                     │
     │                     │ ──────────────────> │                     │                     │
     │                     │                     │                     │                     │
     │                     │  Save assistant msg │                     │                     │
     │                     │ ──────────────────> │                     │                     │
     │                     │                     │                     │                     │
     │  SSE: done          │                     │                     │                     │
     │ <───────────────────│                     │                     │                     │
     │                     │                     │                     │                     │
```

**Components Involved**:
- FastAPI Router
- PostgreSQL (conversations, messages tables)
- DSPy ReAct Agent
- Claude Sonnet 4 (Anthropic API)
- OpenAI Embeddings (if searching collections)
- SQLite Service (if querying database)
- VectorDB Service (if searching documents)

---

### 2.2 GET /api/chat/conversations

List all conversations.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| skip | int | 0 | Offset for pagination |
| limit | int | 50 | Max results to return |

**Response**: `200 OK`
```json
[
  {
    "id": "uuid",
    "title": "string or null",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │
└────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │
     │ GET /conversations  │                     │
     │ ?skip=0&limit=50    │                     │
     │ ──────────────────> │                     │
     │                     │                     │
     │                     │  SELECT * FROM      │
     │                     │  conversations      │
     │                     │  ORDER BY updated   │
     │                     │  DESC LIMIT/OFFSET  │
     │                     │ ──────────────────> │
     │                     │                     │
     │                     │  [Conversation[]]   │
     │                     │ <────────────────── │
     │                     │                     │
     │  200 OK             │                     │
     │  [conversations]    │                     │
     │ <────────────────── │                     │
     │                     │                     │
```

---

### 2.3 GET /api/chat/conversations/{conversation_id}

Get a conversation with all its messages.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| conversation_id | UUID | Conversation ID |

**Response**: `200 OK`
```json
{
  "id": "uuid",
  "title": "string or null",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "Hello",
      "tool_calls": null,
      "created_at": "2024-01-01T00:00:00Z"
    },
    {
      "id": "uuid",
      "role": "assistant",
      "content": "Hi there!",
      "tool_calls": [{"tool": "...", "args": {...}, "result": "..."}],
      "created_at": "2024-01-01T00:00:01Z"
    }
  ]
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │
└────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │
     │ GET /conversations/ │                     │
     │     {id}            │                     │
     │ ──────────────────> │                     │
     │                     │                     │
     │                     │  SELECT FROM        │
     │                     │  conversations      │
     │                     │  WHERE id = ?       │
     │                     │ ──────────────────> │
     │                     │ <────────────────── │
     │                     │                     │
     │                     │  SELECT FROM        │
     │                     │  messages           │
     │                     │  WHERE conv_id = ?  │
     │                     │  ORDER BY created   │
     │                     │ ──────────────────> │
     │                     │ <────────────────── │
     │                     │                     │
     │  200 OK             │                     │
     │  {conversation}     │                     │
     │ <────────────────── │                     │
     │                     │                     │
```

---

### 2.4 DELETE /api/chat/conversations/{conversation_id}

Delete a conversation and all its messages.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| conversation_id | UUID | Conversation ID |

**Response**: `200 OK`
```json
{
  "status": "deleted"
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │
└────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │
     │ DELETE /conversations/{id}                │
     │ ──────────────────> │                     │
     │                     │                     │
     │                     │  SELECT FROM        │
     │                     │  conversations      │
     │                     │  WHERE id = ?       │
     │                     │ ──────────────────> │
     │                     │ <────────────────── │
     │                     │                     │
     │                     │  DELETE FROM        │
     │                     │  conversations      │
     │                     │  WHERE id = ?       │
     │                     │  (CASCADE deletes   │
     │                     │   messages)         │
     │                     │ ──────────────────> │
     │                     │ <────────────────── │
     │                     │                     │
     │  200 OK             │                     │
     │  {"status":"deleted"}                     │
     │ <────────────────── │                     │
     │                     │                     │
```

---

## 3. Collections Endpoints

**Router Prefix**: `/api/collections`

### 3.1 POST /api/collections

Create a new document collection.

**Request Body**:
```json
{
  "name": "string (required)",
  "description": "string (optional)"
}
```

**Response**: `200 OK`
```json
{
  "id": "uuid",
  "name": "My Collection",
  "description": "Description here",
  "document_count": 0,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │
└────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │
     │ POST /collections   │                     │
     │ {name, description} │                     │
     │ ──────────────────> │                     │
     │                     │                     │
     │                     │  INSERT INTO        │
     │                     │  collections        │
     │                     │  (name, desc)       │
     │                     │ ──────────────────> │
     │                     │ <────────────────── │
     │                     │                     │
     │  200 OK             │                     │
     │  {collection}       │                     │
     │ <────────────────── │                     │
     │                     │                     │
```

---

### 3.2 GET /api/collections

List all collections.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| skip | int | 0 | Offset for pagination |
| limit | int | 100 | Max results to return |

**Response**: `200 OK`
```json
[
  {
    "id": "uuid",
    "name": "Collection Name",
    "description": "...",
    "document_count": 5,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │
└────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │
     │ GET /collections    │                     │
     │ ──────────────────> │                     │
     │                     │                     │
     │                     │  SELECT * FROM      │
     │                     │  collections        │
     │                     │  ORDER BY created   │
     │                     │ ──────────────────> │
     │                     │ <────────────────── │
     │                     │                     │
     │  200 OK             │                     │
     │  [collections]      │                     │
     │ <────────────────── │                     │
     │                     │                     │
```

---

### 3.3 GET /api/collections/{collection_id}

Get a collection by ID.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| collection_id | UUID | Collection ID |

**Response**: `200 OK`
```json
{
  "id": "uuid",
  "name": "Collection Name",
  "description": "...",
  "document_count": 5,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

---

### 3.4 DELETE /api/collections/{collection_id}

Delete a collection and all its documents.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| collection_id | UUID | Collection ID |

**Response**: `200 OK`
```json
{
  "status": "deleted"
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │  MinIO   │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ DELETE /collections/{id}                  │                     │
     │ ──────────────────> │                     │                     │
     │                     │                     │                     │
     │                     │  SELECT documents   │                     │
     │                     │  WHERE collection_id│                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │                     │                     │  Delete each file   │
     │                     │                     │  from bucket        │
     │                     │ ────────────────────────────────────────> │
     │                     │ <──────────────────────────────────────── │
     │                     │                     │                     │
     │                     │  DELETE FROM        │                     │
     │                     │  collections        │                     │
     │                     │  (CASCADE deletes   │                     │
     │                     │   documents,chunks) │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │  200 OK             │                     │                     │
     │ <────────────────── │                     │                     │
     │                     │                     │                     │
```

---

### 3.5 GET /api/collections/{collection_id}/status

Get document processing status for a collection.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| collection_id | UUID | Collection ID |

**Response**: `200 OK`
```json
{
  "total": 10,
  "pending": 2,
  "processing": 1,
  "completed": 6,
  "failed": 1
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │
└────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │
     │ GET /collections/   │                     │
     │     {id}/status     │                     │
     │ ──────────────────> │                     │
     │                     │                     │
     │                     │  SELECT status,     │
     │                     │  COUNT(*) FROM      │
     │                     │  documents          │
     │                     │  WHERE collection_id│
     │                     │  GROUP BY status    │
     │                     │ ──────────────────> │
     │                     │ <────────────────── │
     │                     │                     │
     │  200 OK             │                     │
     │  {total, pending,   │                     │
     │   processing, ...}  │                     │
     │ <────────────────── │                     │
     │                     │                     │
```

---

### 3.6 POST /api/collections/{collection_id}/documents

Upload documents to a collection.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| collection_id | UUID | Collection ID |

**Request**: `multipart/form-data`
| Field | Type | Description |
|-------|------|-------------|
| files | File[] | Up to 10 files, max 50MB each |

**Supported File Types**:
- PDF (application/pdf)
- Word (application/vnd.openxmlformats-officedocument.wordprocessingml.document)
- Excel (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet)
- CSV (text/csv)
- Text (text/plain)
- Markdown (text/markdown)

**Response**: `200 OK`
```json
[
  {
    "id": "uuid",
    "collection_id": "uuid",
    "filename": "document.pdf",
    "mime_type": "application/pdf",
    "file_size": 1024000,
    "page_count": 10,
    "status": "completed",
    "error_message": null,
    "summary": "This document contains...",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

**Sequence Diagram**:
```
┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐
│  Client  │      │  FastAPI │      │ Postgres │      │  MinIO   │      │ Processor│      │  OpenAI  │
└────┬─────┘      └────┬─────┘      └────┬─────┘      └────┬─────┘      └────┬─────┘      └────┬─────┘
     │                 │                 │                 │                 │                 │
     │ POST /documents │                 │                 │                 │                 │
     │ [files]         │                 │                 │                 │                 │
     │ ──────────────> │                 │                 │                 │                 │
     │                 │                 │                 │                 │                 │
     │                 │  Verify         │                 │                 │                 │
     │                 │  collection     │                 │                 │                 │
     │                 │ ──────────────> │                 │                 │                 │
     │                 │ <────────────── │                 │                 │                 │
     │                 │                 │                 │                 │                 │
     │                 │  [For each file]│                 │                 │                 │
     │                 │                 │                 │                 │                 │
     │                 │  Upload file    │                 │                 │                 │
     │                 │ ────────────────────────────────> │                 │                 │
     │                 │ <──────────────────────────────── │                 │                 │
     │                 │                 │                 │                 │                 │
     │                 │  INSERT document│                 │                 │                 │
     │                 │  (status:pending)                 │                 │                 │
     │                 │ ──────────────> │                 │                 │                 │
     │                 │ <────────────── │                 │                 │                 │
     │                 │                 │                 │                 │                 │
     │                 │  Process document                 │                 │                 │
     │                 │ ────────────────────────────────────────────────> │                 │
     │                 │                 │                 │                 │                 │
     │                 │                 │                 │  UPDATE status  │                 │
     │                 │                 │                 │  = processing   │                 │
     │                 │                 │ <───────────────────────────────  │                 │
     │                 │                 │                 │                 │                 │
     │                 │                 │                 │  Download file  │                 │
     │                 │                 │                 │ <────────────── │                 │
     │                 │                 │                 │ ──────────────> │                 │
     │                 │                 │                 │                 │                 │
     │                 │                 │                 │  Extract text   │                 │
     │                 │                 │                 │  (PDF/DOCX/etc) │                 │
     │                 │                 │                 │ ─────────────>  │                 │
     │                 │                 │                 │                 │                 │
     │                 │                 │                 │  Chunk text     │                 │
     │                 │                 │                 │ ─────────────>  │                 │
     │                 │                 │                 │                 │                 │
     │                 │                 │                 │  Generate       │                 │
     │                 │                 │                 │  embeddings     │                 │
     │                 │                 │                 │ ───────────────────────────────> │
     │                 │                 │                 │ <─────────────────────────────── │
     │                 │                 │                 │                 │                 │
     │                 │                 │  INSERT chunks  │                 │                 │
     │                 │                 │  with embeddings│                 │                 │
     │                 │                 │ <───────────────────────────────  │                 │
     │                 │                 │                 │                 │                 │
     │                 │                 │  UPDATE document│                 │                 │
     │                 │                 │  status=complete│                 │                 │
     │                 │                 │ <───────────────────────────────  │                 │
     │                 │                 │                 │                 │                 │
     │                 │                 │  UPDATE         │                 │                 │
     │                 │                 │  collection     │                 │                 │
     │                 │                 │  document_count │                 │                 │
     │                 │                 │ <────────────── │                 │                 │
     │                 │                 │                 │                 │                 │
     │  200 OK         │                 │                 │                 │                 │
     │  [documents]    │                 │                 │                 │                 │
     │ <────────────── │                 │                 │                 │                 │
     │                 │                 │                 │                 │                 │
```

---

### 3.7 GET /api/collections/{collection_id}/documents

List documents in a collection.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| collection_id | UUID | Collection ID |

**Response**: `200 OK`
```json
[
  {
    "id": "uuid",
    "collection_id": "uuid",
    "filename": "document.pdf",
    "mime_type": "application/pdf",
    "file_size": 1024000,
    "page_count": 10,
    "status": "completed",
    "error_message": null,
    "summary": "...",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

---

### 3.8 DELETE /api/collections/documents/{document_id}

Delete a document.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| document_id | UUID | Document ID |

**Response**: `200 OK`
```json
{
  "status": "deleted"
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │  MinIO   │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ DELETE /documents/{id}                    │                     │
     │ ──────────────────> │                     │                     │
     │                     │                     │                     │
     │                     │  SELECT document    │                     │
     │                     │  (get minio_key)    │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │                     │                     │  Delete file        │
     │                     │ ────────────────────────────────────────> │
     │                     │ <──────────────────────────────────────── │
     │                     │                     │                     │
     │                     │  DELETE document    │                     │
     │                     │  (CASCADE chunks)   │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │                     │  UPDATE collection  │                     │
     │                     │  document_count - 1 │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │  200 OK             │                     │                     │
     │ <────────────────── │                     │                     │
     │                     │                     │                     │
```

---

### 3.9 GET /api/collections/documents/{document_id}/download

Get a presigned URL to download a document.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| document_id | UUID | Document ID |

**Response**: `200 OK`
```json
{
  "url": "https://minio:9002/documents/...",
  "filename": "document.pdf"
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │  MinIO   │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ GET /documents/     │                     │                     │
     │     {id}/download   │                     │                     │
     │ ──────────────────> │                     │                     │
     │                     │                     │                     │
     │                     │  SELECT document    │                     │
     │                     │  (get minio_key)    │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │                     │                     │  Generate presigned │
     │                     │                     │  URL (1hr expiry)   │
     │                     │ ────────────────────────────────────────> │
     │                     │ <──────────────────────────────────────── │
     │                     │                     │                     │
     │  200 OK             │                     │                     │
     │  {url, filename}    │                     │                     │
     │ <────────────────── │                     │                     │
     │                     │                     │                     │
```

---

### 3.10 POST /api/collections/search

Semantic search across document collections.

**Request Body**:
```json
{
  "query": "string (required)",
  "collection_ids": ["uuid"] (optional),
  "limit": 5 (optional, default: 5)
}
```

**Response**: `200 OK`
```json
[
  {
    "chunk_id": "uuid",
    "document_id": "uuid",
    "collection_id": "uuid",
    "filename": "document.pdf",
    "content": "The relevant text chunk...",
    "score": 0.89
  }
]
```

**Sequence Diagram**:
```
┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐
│  Client  │      │  FastAPI │      │  Search  │      │  OpenAI  │      │ Postgres │
│          │      │          │      │  Service │      │          │      │ +pgvector│
└────┬─────┘      └────┬─────┘      └────┬─────┘      └────┬─────┘      └────┬─────┘
     │                 │                 │                 │                 │
     │ POST /search    │                 │                 │                 │
     │ {query, ...}    │                 │                 │                 │
     │ ──────────────> │                 │                 │                 │
     │                 │                 │                 │                 │
     │                 │  search()       │                 │                 │
     │                 │ ──────────────> │                 │                 │
     │                 │                 │                 │                 │
     │                 │                 │  Get embedding  │                 │
     │                 │                 │  for query      │                 │
     │                 │                 │ ──────────────> │                 │
     │                 │                 │ <────────────── │                 │
     │                 │                 │  [1536 floats]  │                 │
     │                 │                 │                 │                 │
     │                 │                 │  Vector search  │                 │
     │                 │                 │  using L2 dist  │                 │
     │                 │                 │  (<-> operator) │                 │
     │                 │                 │ ────────────────────────────────> │
     │                 │                 │                 │                 │
     │                 │                 │                 │  SELECT chunks  │
     │                 │                 │                 │  JOIN documents │
     │                 │                 │                 │  ORDER BY dist  │
     │                 │                 │                 │  LIMIT ?        │
     │                 │                 │ <──────────────────────────────── │
     │                 │                 │                 │                 │
     │                 │  [SearchResult[]]                 │                 │
     │                 │ <────────────── │                 │                 │
     │                 │                 │                 │                 │
     │  200 OK         │                 │                 │                 │
     │  [results]      │                 │                 │                 │
     │ <────────────── │                 │                 │                 │
     │                 │                 │                 │                 │
```

---

## 4. Databases Endpoints

**Router Prefix**: `/api/databases`

### 4.1 POST /api/databases

Create or upload a SQLite database.

**Request**: `multipart/form-data`

**Option A - Upload existing database**:
| Field | Type | Description |
|-------|------|-------------|
| file | File | SQLite file (.db or .sqlite) |
| data | JSON | `{"name": "string", "description": "string (optional)"}` |

**Option B - Create sample database**:
| Field | Type | Description |
|-------|------|-------------|
| data | JSON | `{"name": "string", "create_sample": true}` |

**Response**: `200 OK`
```json
{
  "id": "uuid",
  "name": "Sales Database",
  "file_path": "/app/data/sqlite/uuid.db",
  "description": "Sample sales data",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Sequence Diagram (Upload)**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │FileSystem│
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ POST /databases     │                     │                     │
     │ {file, data}        │                     │                     │
     │ ──────────────────> │                     │                     │
     │                     │                     │                     │
     │                     │  Validate file ext  │                     │
     │                     │  (.db, .sqlite)     │                     │
     │                     │ ──────────>         │                     │
     │                     │                     │                     │
     │                     │                     │  Save SQLite file   │
     │                     │ ────────────────────────────────────────> │
     │                     │ <──────────────────────────────────────── │
     │                     │                     │                     │
     │                     │  INSERT INTO        │                     │
     │                     │  sqlite_databases   │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │  200 OK             │                     │                     │
     │  {database}         │                     │                     │
     │ <────────────────── │                     │                     │
     │                     │                     │                     │
```

**Sequence Diagram (Create Sample)**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │  SQLite  │
│          │          │          │          │          │          │ Service  │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ POST /databases     │                     │                     │
     │ {create_sample:true}│                     │                     │
     │ ──────────────────> │                     │                     │
     │                     │                     │                     │
     │                     │  create_sample_db() │                     │
     │                     │ ────────────────────────────────────────> │
     │                     │                     │                     │
     │                     │                     │  CREATE tables      │
     │                     │                     │  (customers,        │
     │                     │                     │   products, orders, │
     │                     │                     │   order_items,      │
     │                     │                     │   sales_reps)       │
     │                     │                     │                     │
     │                     │                     │  INSERT sample data │
     │                     │                     │  (100 customers,    │
     │                     │                     │   50 products,      │
     │                     │                     │   500 orders, etc)  │
     │                     │ <──────────────────────────────────────── │
     │                     │                     │                     │
     │                     │  INSERT INTO        │                     │
     │                     │  sqlite_databases   │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │  200 OK             │                     │                     │
     │  {database}         │                     │                     │
     │ <────────────────── │                     │                     │
     │                     │                     │                     │
```

---

### 4.2 GET /api/databases

List all active databases.

**Response**: `200 OK`
```json
[
  {
    "id": "uuid",
    "name": "Sales Database",
    "file_path": "/app/data/sqlite/uuid.db",
    "description": "...",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

---

### 4.3 GET /api/databases/{database_id}

Get a database by ID.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| database_id | UUID | Database ID |

**Response**: `200 OK`
```json
{
  "id": "uuid",
  "name": "Sales Database",
  "file_path": "/app/data/sqlite/uuid.db",
  "description": "...",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

---

### 4.4 GET /api/databases/{database_id}/schema

Get the full schema of a database.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| database_id | UUID | Database ID |

**Response**: `200 OK`
```json
{
  "database_id": "uuid",
  "database_name": "Sales Database",
  "tables": [
    {
      "name": "customers",
      "columns": [
        {
          "name": "id",
          "type": "INTEGER",
          "nullable": false,
          "primary_key": true,
          "foreign_key": null
        },
        {
          "name": "name",
          "type": "TEXT",
          "nullable": false,
          "primary_key": false,
          "foreign_key": null
        }
      ],
      "row_count": 100,
      "sample_data": [
        {"id": 1, "name": "John Doe", ...},
        {"id": 2, "name": "Jane Smith", ...},
        {"id": 3, "name": "Bob Wilson", ...}
      ]
    }
  ]
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │  SQLite  │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ GET /databases/     │                     │                     │
     │     {id}/schema     │                     │                     │
     │ ──────────────────> │                     │                     │
     │                     │                     │                     │
     │                     │  SELECT database    │                     │
     │                     │  (get file_path)    │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │                     │  sqlite_service.    │                     │
     │                     │  get_schema()       │                     │
     │                     │ ────────────────────────────────────────> │
     │                     │                     │                     │
     │                     │                     │  PRAGMA table_list  │
     │                     │                     │ ─────────────────>  │
     │                     │                     │                     │
     │                     │                     │  PRAGMA table_info  │
     │                     │                     │  (for each table)   │
     │                     │                     │ ─────────────────>  │
     │                     │                     │                     │
     │                     │                     │  PRAGMA foreign_keys│
     │                     │                     │ ─────────────────>  │
     │                     │                     │                     │
     │                     │                     │  SELECT COUNT(*)    │
     │                     │                     │  (row counts)       │
     │                     │                     │ ─────────────────>  │
     │                     │                     │                     │
     │                     │                     │  SELECT * LIMIT 3   │
     │                     │                     │  (sample data)      │
     │                     │                     │ ─────────────────>  │
     │                     │                     │                     │
     │                     │ <──────────────────────────────────────── │
     │                     │                     │                     │
     │  200 OK             │                     │                     │
     │  {schema}           │                     │                     │
     │ <────────────────── │                     │                     │
     │                     │                     │                     │
```

---

### 4.5 POST /api/databases/{database_id}/query

Execute a SQL query against a database.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| database_id | UUID | Database ID |

**Request Body**:
```json
{
  "sql": "SELECT * FROM customers LIMIT 10"
}
```

**Response**: `200 OK`
```json
{
  "columns": ["id", "name", "email", "city"],
  "rows": [
    [1, "John Doe", "john@example.com", "New York"],
    [2, "Jane Smith", "jane@example.com", "Los Angeles"]
  ],
  "row_count": 2,
  "error": null
}
```

**Security Restrictions**:
- Only `SELECT` statements allowed
- Blocked keywords: `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `TRUNCATE`, `REPLACE`

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │  SQLite  │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ POST /databases/    │                     │                     │
     │     {id}/query      │                     │                     │
     │ {sql: "SELECT..."}  │                     │                     │
     │ ──────────────────> │                     │                     │
     │                     │                     │                     │
     │                     │  SELECT database    │                     │
     │                     │  (get file_path)    │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │                     │  Validate SQL       │                     │
     │                     │  (SELECT only,      │                     │
     │                     │   no dangerous      │                     │
     │                     │   keywords)         │                     │
     │                     │ ────────────>       │                     │
     │                     │                     │                     │
     │                     │  sqlite_service.    │                     │
     │                     │  execute_query()    │                     │
     │                     │ ────────────────────────────────────────> │
     │                     │                     │                     │
     │                     │                     │  Execute SQL        │
     │                     │                     │ ─────────────────>  │
     │                     │                     │ <─────────────────  │
     │                     │                     │                     │
     │                     │ <──────────────────────────────────────── │
     │                     │                     │                     │
     │  200 OK             │                     │                     │
     │  {columns, rows,    │                     │                     │
     │   row_count}        │                     │                     │
     │ <────────────────── │                     │                     │
     │                     │                     │                     │
```

---

### 4.6 DELETE /api/databases/{database_id}

Delete a database.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| database_id | UUID | Database ID |

**Response**: `200 OK`
```json
{
  "status": "deleted"
}
```

**Sequence Diagram**:
```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  Client  │          │  FastAPI │          │ Postgres │          │FileSystem│
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ DELETE /databases/{id}                    │                     │
     │ ──────────────────> │                     │                     │
     │                     │                     │                     │
     │                     │  SELECT database    │                     │
     │                     │  (get file_path)    │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │                     │                     │  Delete SQLite file │
     │                     │ ────────────────────────────────────────> │
     │                     │ <──────────────────────────────────────── │
     │                     │                     │                     │
     │                     │  DELETE FROM        │                     │
     │                     │  sqlite_databases   │                     │
     │                     │ ──────────────────> │                     │
     │                     │ <────────────────── │                     │
     │                     │                     │                     │
     │  200 OK             │                     │                     │
     │ <────────────────── │                     │                     │
     │                     │                     │                     │
```

---

## Summary

### Endpoint Count by Router

| Router | Count | Description |
|--------|-------|-------------|
| Health | 2 | Health check and root |
| Chat | 4 | Conversations and streaming |
| Collections | 10 | Document management |
| Databases | 6 | SQLite management |
| **Total** | **22** | |

### External Services

| Service | Used By | Purpose |
|---------|---------|---------|
| PostgreSQL | All routers | Metadata storage |
| VectorChord | Collections, Chat | Vector similarity search |
| MinIO | Collections | Document file storage |
| OpenAI | Collections, Chat | Embeddings generation |
| Claude (Anthropic) | Chat | LLM for agent |
| SQLite | Databases, Chat | User data storage |

### Database Tables

| Table | Primary Router | Description |
|-------|---------------|-------------|
| conversations | Chat | Chat sessions |
| messages | Chat | Chat messages |
| collections | Collections | Document collections |
| documents | Collections | Document metadata |
| document_chunks | Collections | Text chunks with embeddings |
| sqlite_databases | Databases | SQLite database metadata |
