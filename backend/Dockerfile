FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Node.js + the Claude Code CLI. The claude-agent-sdk runs the agent loop (query())
# by spawning the `claude` CLI as a subprocess, so the CLI and a Node runtime must
# be present on PATH. Without this, query() fails at runtime with "claude not found".
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && claude --version

# Install uv
RUN pip install uv

# Copy all project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install dependencies (not editable - just install deps from pyproject.toml)
RUN uv pip install --system .

# Create data directory
RUN mkdir -p /app/data/sqlite

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "src.main"]
