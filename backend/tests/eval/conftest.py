"""Gating for LLM eval tests.

Evals hit the real Anthropic API (and, for retrieval, the dev Postgres and
Modal endpoints). They are skipped unless explicitly enabled:

    RUN_EVALS=1 .venv/bin/python -m pytest tests/eval -m eval -v

Retrieval evals additionally need:

    RUN_RETRIEVAL_EVALS=1 (plus Postgres on :5433 and ColQwen2 Modal endpoints)
"""

import os
import sys
from pathlib import Path

import pytest

backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))


def _api_key_available() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        from src.config import settings

        return bool(settings.anthropic_api_key)
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    evals_on = os.environ.get("RUN_EVALS") == "1" and _api_key_available()
    retrieval_on = os.environ.get("RUN_RETRIEVAL_EVALS") == "1"

    skip_eval = pytest.mark.skip(
        reason="set RUN_EVALS=1 (with ANTHROPIC_API_KEY configured) to run LLM evals"
    )
    skip_retrieval = pytest.mark.skip(
        reason="set RUN_RETRIEVAL_EVALS=1 (needs Postgres :5433 + Modal) to run retrieval evals"
    )

    for item in items:
        if "eval_retrieval" in item.keywords and not retrieval_on:
            item.add_marker(skip_retrieval)
        elif "eval" in item.keywords and not evals_on:
            item.add_marker(skip_eval)


def get_api_key() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    from src.config import settings

    return settings.anthropic_api_key
