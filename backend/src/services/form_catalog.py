"""
Form catalog abstraction for the intelligent form-filling module integration.

Until the form-filling module (teammate's) exposes its API, the catalog is
served from a local JSON file (backend/data/forms.json). Swapping to their
REST API later is one class: set FORM_CATALOG_URL and RestFormCatalog takes
over — the contract is GET {base_url}/forms returning the same shape (see
docs/integration-proposal.md).

Form shape:
    {
      "id": "warranty-claim",
      "name": "Warranty Claim Form",
      "description": "...",
      "url": "/forms/warranty-claim",
      "fields": [{"name": "...", "label": "...", "type": "...", "required": bool}]
    }
"""

import json
import logging
import time
from pathlib import Path
from typing import Protocol

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class FormCatalog(Protocol):
    def list_forms(self) -> list[dict]: ...

    def get_form(self, form_id: str) -> dict | None: ...


class JsonFormCatalog:
    """Mock catalog backed by a local JSON file (re-read when it changes)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._forms: list[dict] = []
        self._mtime: float | None = None

    def list_forms(self) -> list[dict]:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            logger.warning("Form catalog file not found: %s", self.path)
            return []
        if mtime != self._mtime:
            self._forms = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = mtime
        return self._forms

    def get_form(self, form_id: str) -> dict | None:
        return next((f for f in self.list_forms() if f.get("id") == form_id), None)


class RestFormCatalog:
    """Catalog backed by the form-filling module's REST API (cached briefly)."""

    _CACHE_TTL = 60.0

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._forms: list[dict] = []
        self._fetched_at: float = 0.0

    def list_forms(self) -> list[dict]:
        now = time.monotonic()
        if now - self._fetched_at > self._CACHE_TTL:
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(f"{self.base_url}/forms")
                    response.raise_for_status()
                    self._forms = response.json()
                    self._fetched_at = now
            except Exception:
                logger.exception("Failed to fetch form catalog from %s", self.base_url)
        return self._forms

    def get_form(self, form_id: str) -> dict | None:
        return next((f for f in self.list_forms() if f.get("id") == form_id), None)


def _build_catalog() -> FormCatalog:
    if settings.form_catalog_url:
        return RestFormCatalog(settings.form_catalog_url)
    return JsonFormCatalog(settings.form_catalog_path)


# Singleton — swap implementation via FORM_CATALOG_URL
form_catalog: FormCatalog = _build_catalog()
