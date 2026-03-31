"""
Per-activity training load history MCP tool.
Surfaces activityTrainingLoad, aerobicTrainingEffect, and
anaerobicTrainingEffect — showing which sessions drive acute load.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from utils import safe_float


async def get_activity_load_history(
    days: int = 14,
    sport_type: str = "all",
    limit: int = 30,
) -> dict[str, Any]:
    """
    Return activities with their training load and training effect scores.

    Parameters:
        days       – look-back window in days (1–90, default 14)
        sport_type – filter by Garmin sport type or "all" (default "all")
        limit      – max activities returned (1–100, default 30)
    """
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 100))

    try:
        activities = await asyncio.to_thread(
            influx.query_activity_load_history, days, sport_type, limit,
        )
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    if not activities:
        return {
            "data_note": "No activities found for this period",
            "activities": [],
            "summary": None,
        }

    # Build load-focused view per activity
    load_entries = []
    total_load = 0.0
    load_by_sport: dict[str, float] = {}
    highest_load_entry: dict[str, Any] | None = None
    highest_load_val = 0.0
    ae_te_vals: list[float] = []
    an_te_vals: list[float] = []

    for act in activities:
        tl = safe_float(act.get("training_load"))
        ae_te = safe_float(act.get("aerobic_training_effect"))
        an_te = safe_float(act.get("anaerobic_training_effect"))
        sport = act.get("sport_type") or "unknown"

        entry = {
            "activity_id": act.get("activity_id"),
            "timestamp": act.get("timestamp"),
            "activity_name": act.get("activity_name"),
            "sport_type": sport,
            "distance_km": act.get("distance_km"),
            "duration_minutes": act.get("duration_minutes"),
            "training_load": tl,
            "aerobic_training_effect": ae_te,
            "anaerobic_training_effect": an_te,
            "avg_hr": act.get("avg_hr"),
            "max_hr": act.get("max_hr"),
            "intensity_minutes": {
                "moderate": act.get("moderate_intensity_min"),
                "vigorous": act.get("vigorous_intensity_min"),
            } if act.get("moderate_intensity_min") or act.get("vigorous_intensity_min") else None,
        }
        load_entries.append(entry)

        if tl is not None:
            total_load += tl
            load_by_sport[sport] = load_by_sport.get(sport, 0.0) + tl
            if tl > highest_load_val:
                highest_load_val = tl
                highest_load_entry = {
                    "activity_id": act.get("activity_id"),
                    "activity_name": act.get("activity_name"),
                    "sport_type": sport,
                    "training_load": tl,
                    "date": str(act.get("timestamp", ""))[:10],
                }

        if ae_te is not None:
            ae_te_vals.append(ae_te)
        if an_te is not None:
            an_te_vals.append(an_te)

    # Round load_by_sport values
    load_by_sport = {k: round(v, 1) for k, v in load_by_sport.items()}

    count_with_load = sum(1 for e in load_entries if e["training_load"] is not None)

    summary = {
        "total_activities": len(load_entries),
        "total_load": round(total_load, 1),
        "avg_load_per_session": round(total_load / count_with_load, 1) if count_with_load else None,
        "load_by_sport": load_by_sport if load_by_sport else None,
        "highest_load_activity": highest_load_entry,
        "avg_aerobic_te": round(sum(ae_te_vals) / len(ae_te_vals), 2) if ae_te_vals else None,
        "avg_anaerobic_te": round(sum(an_te_vals) / len(an_te_vals), 2) if an_te_vals else None,
        "date_range_from": load_entries[-1]["timestamp"] if load_entries else None,
        "date_range_to": load_entries[0]["timestamp"] if load_entries else None,
    }

    return {"activities": load_entries, "summary": summary}
