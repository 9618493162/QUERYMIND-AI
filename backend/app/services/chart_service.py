"""Chart recommendation based on actual result column shapes."""

from __future__ import annotations

from typing import Any

CHART_TYPES = ("bar", "line", "pie", "area", "table")


def recommend_chart(columns: list[dict[str, str]], rows: list[list[Any]]) -> dict[str, Any]:
    """Return {type, x, y, available, reason} describing the best visualization."""
    if not columns or not rows:
        return {
            "type": "table",
            "available": False,
            "reason": "No rows to visualize.",
        }

    numeric_idx = [i for i, c in enumerate(columns) if c.get("type") == "number"]
    datetime_idx = [i for i, c in enumerate(columns) if c.get("type") == "datetime"]
    other_idx = [i for i, c in enumerate(columns) if i not in numeric_idx and i not in datetime_idx]

    if not numeric_idx:
        return {
            "type": "table",
            "available": False,
            "reason": "The result has no numeric column to plot.",
        }

    y = columns[numeric_idx[0]]["name"]

    if datetime_idx:
        x = columns[datetime_idx[0]]["name"]
        if other_idx:
            x = columns[datetime_idx[0]]["name"]
        return {"type": "line", "x": x, "y": y, "available": True,
                "reason": "A time column paired with a numeric measure suits a line chart."}

    if other_idx:
        x = columns[other_idx[0]]["name"]
        distinct = {r[other_idx[0]] for r in rows if r[other_idx[0]] is not None}
        if len(rows) <= 8 and len(numeric_idx) == 1 and len(distinct) == len(rows):
            return {"type": "pie", "x": x, "y": y, "available": True,
                    "reason": "Few categories with a single measure suit a pie chart."}
        return {"type": "bar", "x": x, "y": y, "available": True,
                "reason": "Categories paired with a numeric measure suit a bar chart."}

    return {"type": "bar", "x": columns[0]["name"], "y": y, "available": True,
            "reason": "Single numeric column; plotted against its row index."}
