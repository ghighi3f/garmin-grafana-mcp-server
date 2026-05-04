"""
Lactate threshold trend MCP tool.
Queries the LactateThreshold measurement written by garmin-grafana.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from utils import iso_week_label, safe_float
from utils import compute_trend


async def get_lactate_threshold_trend(weeks: int = 12) -> dict[str, Any]:
    """
    Return weekly-sampled lactate threshold heart rate and its trend.

    Lactate threshold HR (LTHR) is the highest average HR you can sustain
    for ~60 minutes.  Garmin estimates it automatically and stores it in the
    LactateThreshold measurement.  A rising LTHR (in absolute bpm) indicates
    cardiovascular adaptation — you can sustain higher HR before crossing
    into the anaerobic zone.

    Parameters:
        weeks – look-back window in weeks (4–52, default 12)

    Returns:
        current   – most recent LTHR reading with date
        weeks     – weekly list (newest first): week_label, hr_threshold_running
        trend     – "improving" | "declining" | "stable"
        change_bpm – change over the period (positive = improving)
        data_note  – present when no data is available
    """
    weeks = max(4, min(weeks, 52))

    try:
        rows = await asyncio.to_thread(influx.query_lactate_threshold, weeks)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    if not rows:
        return {
            "data_note": (
                "No LactateThreshold data found. "
                "Garmin estimates LTHR automatically after sufficient running effort — "
                "it may not be available for cycling-only athletes or older device firmware."
            ),
            "current": None,
            "weeks": [],
        }

    # Build weekly list, newest first
    weekly: list[dict[str, Any]] = []
    for r in rows:
        ts = r.get("time") or r.get("_time")
        if ts and hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        label = iso_week_label(str(ts)) if ts else None
        val = safe_float(r.get("hr_threshold") or r.get("last") or r.get("_value"))
        if val is not None:
            weekly.append({
                "week_label": label,
                "hr_threshold_running": round(val, 1),
            })

    if not weekly:
        return {
            "data_note": "LactateThreshold measurement exists but returned no readable values.",
            "current": None,
            "weeks": [],
        }

    weekly.sort(key=lambda x: x["week_label"] or "", reverse=True)

    # Trend: higher LTHR = better cardiovascular adaptation
    values = [w["hr_threshold_running"] for w in weekly if w["hr_threshold_running"] is not None]
    trend = compute_trend(list(reversed(values)), higher_is_better=True) if len(values) >= 2 else "stable"
    change_bpm = round(values[0] - values[-1], 1) if len(values) >= 2 else None

    current_week = weekly[0]
    current = {
        "hr_threshold_running": current_week["hr_threshold_running"],
        "week_label": current_week["week_label"],
    }

    return {
        "current": current,
        "weeks": weekly,
        "trend": trend,
        "change_bpm": change_bpm,
    }
