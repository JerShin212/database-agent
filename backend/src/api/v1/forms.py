"""
Form catalog endpoint — mirrors the contract the form-filling module will
eventually serve (docs/integration-proposal.md). The frontend and teammates
can develop against this mock until the real module is ready.
"""

from fastapi import APIRouter

from src.services.form_catalog import form_catalog

router = APIRouter()


@router.get("/forms")
async def list_forms():
    """List available forms (id, name, description, url, field schema)."""
    return form_catalog.list_forms()


@router.get("/forms/{form_id}")
async def get_form(form_id: str):
    """Get a single form definition."""
    form = form_catalog.get_form(form_id)
    if form is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"No form with id '{form_id}'")
    return form
