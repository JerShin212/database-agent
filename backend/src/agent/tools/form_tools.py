"""
suggest_form tool — the orchestrator suggests a relevant form as the user's
next action. Validated suggestions are forwarded to the frontend as an
`action` SSE event (rendered as a clickable card that opens the form with
prefilled fields).
"""

from src.services.form_catalog import form_catalog

FORM_SUGGESTION_PREFIX = "Form suggestion sent to the user"


def build_suggest_form_description() -> str:
    """Tool description listing the currently available forms."""
    forms = form_catalog.list_forms()
    if forms:
        lines = "\n".join(f"- {f['id']}: {f['description']}" for f in forms)
    else:
        lines = "(no forms available)"
    return (
        "Suggest a form for the user to fill as their next action — a clickable "
        "card is shown alongside your answer. Use when the user's intent matches "
        "a form (filing, requesting, complaining, inquiring). Prefill any field "
        "values you already know from the conversation or worker results.\n\n"
        f"Available forms:\n{lines}"
    )


def suggest_form(form_id: str, prefill: dict = None) -> str:
    """Validate a form suggestion against the catalog."""
    prefill = prefill or {}

    form = form_catalog.get_form(form_id)
    if form is None:
        available = ", ".join(f["id"] for f in form_catalog.list_forms()) or "(none)"
        return f"Error: No form with id '{form_id}'. Available forms: {available}"

    if not isinstance(prefill, dict):
        return "Error: prefill must be an object mapping field names to values."

    field_names = {f["name"] for f in form.get("fields", [])}
    unknown = set(prefill) - field_names
    if unknown:
        return (
            f"Error: Unknown prefill field(s) {sorted(unknown)} for form '{form_id}'. "
            f"Valid fields: {sorted(field_names)}"
        )

    return (
        f"{FORM_SUGGESTION_PREFIX}: '{form['name']}' ({form_id}) with "
        f"{len(prefill)} prefilled field(s). Mention the suggestion briefly in your answer."
    )
