# Chat API

## Send Message

**POST** `/api/chat`

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | yes | The user's message |
| `conversation_id` | string (UUID) | no | Existing conversation ID to continue. Omit to start a new conversation. |
| `database_id` | string (UUID) | no | Database to query against. Falls back to first active database if omitted. |
| `collection_ids` | string[] (UUIDs) | no | Document collections to search. |

### Example Request

```json
{
  "message": "What tables are in the database?",
  "conversation_id": null,
  "database_id": "a1b2c3d4-...",
  "collection_ids": null
}
```

### Response

| Field | Type | Description |
|-------|------|-------------|
| `conversation_id` | string \| null | The conversation ID (new or existing) |
| `content` | string | The assistant's markdown-formatted response |
| `tool_calls` | array | Tools the agent invoked to answer the question |
| `error` | string \| null | Error message if something went wrong |

Each entry in `tool_calls`:

| Field | Type | Description |
|-------|------|-------------|
| `tool` | string | Tool name (e.g. `"execute_sql"`, `"search_documents"`) |
| `args` | object | Arguments passed to the tool |
| `result` | string | Tool output |

### Example Response

```json
{
  "conversation_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "content": "The database has 3 tables: **customers**, **orders**, and **products**.",
  "tool_calls": [
    {
      "tool": "execute_sql",
      "args": { "sql": "SELECT name FROM sqlite_master WHERE type='table'" },
      "result": "customers\norders\nproducts"
    }
  ],
  "error": null
}
```

### Error Example

```json
{
  "conversation_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "content": "",
  "tool_calls": [],
  "error": "Database not found"
}
```
