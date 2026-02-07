FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

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
