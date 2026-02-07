.PHONY: help dev dev-up dev-build dev-down dev-logs down logs clean migrate backend frontend test sample-db install

help:
	@echo "Database Agent - Development Commands"
	@echo ""
	@echo "  make install      Install all dependencies"
	@echo "  make dev          Start infrastructure (postgres, minio)"
	@echo "  make dev-up       Start all services in Docker"
	@echo "  make dev-build    Build Docker images without starting"
	@echo "  make dev-down     Stop all Docker services"
	@echo "  make dev-logs     View Docker container logs"
	@echo "  make clean        Remove all containers and volumes"
	@echo ""
	@echo "  make backend      Run backend locally (requires infra)"
	@echo "  make frontend     Run frontend locally"
	@echo ""
	@echo "  make migrate      Run database migrations"
	@echo "  make sample-db    Create sample SQLite database"
	@echo "  make test         Run tests"

# Install dependencies
install:
	cd backend && uv sync
	cd frontend && bun install

# Infrastructure only
dev:
	docker compose up -d postgres minio
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@echo "Infrastructure ready!"
	@echo "PostgreSQL: localhost:5433"
	@echo "MinIO API: localhost:9002 (console: localhost:9003)"

# Full Docker development
dev-up:
	docker compose up -d --build
	@echo "All services started!"
	@echo "Frontend: http://localhost:3020"
	@echo "Backend:  http://localhost:8001"
	@echo "MinIO:    http://localhost:9003"

dev-build:
	docker compose build
	@echo "Docker images built!"

dev-down:
	docker compose down

dev-logs:
	docker compose logs -f

down:
	docker compose down

logs:
	docker compose logs -f

clean:
	docker compose down -v
	rm -rf backend/.venv
	rm -rf frontend/node_modules

# Local development (requires infra running)
backend:
	cd backend && uv run python -m src.main

frontend:
	cd frontend && bun run dev

# Database
migrate:
	@echo "Running migrations..."
	docker compose exec postgres psql -U postgres -d database_agent -f /docker-entrypoint-initdb.d/init.sql

sample-db:
	cd backend && uv run python -m src.scripts.create_sample_db
	@echo "Sample database created!"

# Testing
test:
	cd backend && uv run pytest
	cd frontend && bun run test
