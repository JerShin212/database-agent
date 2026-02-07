# Database Agent Backend

FastAPI backend for the Database Agent - a conversational AI that helps users interact with SQLite databases and document collections.

## Features

- DSPy ReAct agent with Claude Sonnet 4
- SQLite database querying with safety validation
- Document upload and semantic search via VectorChord
- SSE streaming for real-time chat responses

## Quick Start

```bash
# Install dependencies
uv sync

# Run the server
uv run python -m src.main
```

## API Documentation

See [API_ENDPOINTS.md](../docs/API_ENDPOINTS.md) for full API documentation.
