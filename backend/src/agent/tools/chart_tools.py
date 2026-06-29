"""
create_chart tool — validates a constrained chart spec which the framework
forwards to the frontend as a `chart` SSE event (rendered with Chart.js).

The model never emits raw Chart.js config; the constrained spec keeps
rendering safe and predictable:

    {
      "chart_type": "bar" | "line" | "pie" | "scatter",
      "title": "Monthly order totals",
      "labels": ["Jan", "Feb", ...],
      "datasets": [{"label": "Orders", "data": [12, 38, ...]}]
    }

For scatter charts, each dataset's data is a list of {"x": n, "y": n} points
and labels may be empty.
"""

CHART_SUCCESS_PREFIX = "Chart rendered for the user"

_ALLOWED_TYPES = ("bar", "line", "pie", "scatter")
_MAX_DATASETS = 4
_MAX_POINTS = 50


def _validate_scatter_point(point) -> bool:
    return (
        isinstance(point, dict)
        and isinstance(point.get("x"), (int, float))
        and isinstance(point.get("y"), (int, float))
    )


def create_chart(chart_type: str, title: str, labels: list = None, datasets: list = None) -> str:
    """
    Render a chart for the user from structured data.

    Use this after you have the numbers (e.g. from a SQL query) when the user
    asks for a chart/plot/visualization or when comparing numeric series.
    Always accompany the chart with a brief text takeaway.

    Args:
        chart_type: One of "bar", "line", "pie", "scatter"
        title: Short chart title
        labels: X-axis / category labels (one per data point; optional for scatter)
        datasets: 1-4 series: [{"label": str, "data": [numbers]}]; for scatter,
            data is [{"x": number, "y": number}]

    Returns:
        Confirmation that the chart was rendered, or a validation error
    """
    labels = labels or []
    datasets = datasets or []

    if chart_type not in _ALLOWED_TYPES:
        return f"Error: chart_type must be one of {_ALLOWED_TYPES}, got '{chart_type}'."
    if not isinstance(title, str) or not title.strip():
        return "Error: title must be a non-empty string."
    if not isinstance(datasets, list) or not datasets:
        return "Error: datasets must be a non-empty list."
    if len(datasets) > _MAX_DATASETS:
        return f"Error: at most {_MAX_DATASETS} datasets are supported, got {len(datasets)}."
    if chart_type == "pie" and len(datasets) != 1:
        return "Error: pie charts take exactly one dataset."

    if chart_type != "scatter":
        if not isinstance(labels, list) or not labels:
            return "Error: labels must be a non-empty list for bar/line/pie charts."
        if len(labels) > _MAX_POINTS:
            return f"Error: at most {_MAX_POINTS} data points are supported, got {len(labels)}."

    for i, dataset in enumerate(datasets):
        if not isinstance(dataset, dict):
            return f"Error: dataset {i} must be an object with 'label' and 'data'."
        label = dataset.get("label")
        data = dataset.get("data")
        if not isinstance(label, str) or not label.strip():
            return f"Error: dataset {i} needs a non-empty string 'label'."
        if not isinstance(data, list) or not data:
            return f"Error: dataset {i} needs a non-empty 'data' list."
        if len(data) > _MAX_POINTS:
            return f"Error: dataset {i} has {len(data)} points; max is {_MAX_POINTS}."

        if chart_type == "scatter":
            if not all(_validate_scatter_point(p) for p in data):
                return (
                    f"Error: dataset {i} for a scatter chart must contain "
                    '{"x": number, "y": number} points.'
                )
        else:
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in data):
                return f"Error: dataset {i} data must be numbers only."
            if len(data) != len(labels):
                return (
                    f"Error: dataset {i} has {len(data)} values but there are "
                    f"{len(labels)} labels — they must match."
                )

    return f"{CHART_SUCCESS_PREFIX}: '{title}' ({chart_type}). Add a brief text takeaway."
