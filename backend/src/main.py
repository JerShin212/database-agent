import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.config import settings
from src.db.database import init_db
from src.services.mlflow_tracing import flush_traces, init_mlflow, stop_health_probe
from src.api.v1 import chat, collections, connectors, databases, forms, integrations, schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # The Claude Agent SDK's CLI subprocess authenticates from the process
    # environment — set it once here, not per request.
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    init_mlflow()  # non-fatal — the app runs fine without the MLflow server
    await init_db()
    print("Database initialized")
    yield
    # Shutdown
    stop_health_probe()
    flush_traces()  # async trace export is batched — drain before exit
    print("Shutting down...")


app = FastAPI(
    title="Database Agent API",
    description="A conversational agent for databases and document collections",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(collections.router, prefix="/api/collections", tags=["collections"])
app.include_router(connectors.router, prefix="/api", tags=["connectors"])
app.include_router(databases.router, prefix="/api/databases", tags=["databases"])
app.include_router(schema.router, prefix="/api", tags=["schema"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["integrations"])
app.include_router(forms.router, prefix="/api", tags=["forms"])


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/")
async def root():
    return {
        "name": "Database Agent API",
        "version": "0.1.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.debug,
    )
