"""
Activity-level MCP tools.
Pure data retrieval — no planning logic, no goal assumptions.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx


# ---------------------------------------------------------------------------
# Tool: get_last_activity
# ---------------------------------------------------------------------------

async def get_last_activity() -> dict[str, Any]:
    """
    Return the single most recent activity recorded in InfluxDB.

    Fields returned (null when not recorded or unavailable):
        timestamp, sport_type, distance_km, duration_minutes,
        avg_hr, max_hr, calories, avg_pace_min_per_km, avg_speed_kmh,
        elevation_gain_m, avg_cadence, avg_power
    """
    try:
        activity = await asyncio.to_thread(influx.query_last_activity)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    if activity is None:
        return {
            "data_note": "No activities found for this period",
            "activity": None,
        }

    return {"activity": activity}


# ---------------------------------------------------------------------------
# Tool: get_recent_activities
# ---------------------------------------------------------------------------

async def get_recent_activities(
    days: int = 7,
    sport_type: str = "all",
    limit: int = 20,
) -> dict[str, Any]:
    """
    Return a list of activities from the last N days.

    Parameters:
        days       – look-back window in days (1–90, default 7)
        sport_type – filter by Garmin sport type (e.g. "running", "cycling",
                     "swimming", "hiking", "trail_running", "strength_training")
                     or "all" for no filter.  Supports partial/sub-sport matching.
        limit      – max rows returned (1–100, default 20)

    Response includes:
        activities  – list of activity objects, newest first
        summary     – {total_activities, total_distance_km_by_sport,
                       total_duration_minutes, date_range_from, date_range_to}
    """
    # Clamp inputs
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 100))
    if sport_type:
        sport_type = sport_type.strip().lower()
    if not sport_type:
        sport_type = "all"

    try:
        rows = await asyncio.to_thread(
            influx.query_recent_activities,
            days,
            sport_type if sport_type != "all" else None,
            limit,
        )
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    if not rows:
        return {
            "data_note": "No activities found for this period",
            "activities": [],
            "summary": None,
        }

    # Build summary
    dist_by_sport: dict[str, float] = {}
    total_duration = 0.0
    for act in rows:
        sp = act.get("sport_type") or "unknown"
        d = act.get("distance_km") or 0.0
        dist_by_sport[sp] = round(dist_by_sport.get(sp, 0.0) + d, 3)
        total_duration += act.get("duration_minutes") or 0.0

    timestamps = [a["timestamp"] for a in rows if a.get("timestamp")]
    date_from = min(timestamps) if timestamps else None
    date_to = max(timestamps) if timestamps else None

    summary = {
        "total_activities": len(rows),
        "total_distance_km_by_sport": dist_by_sport,
        "total_duration_minutes": round(total_duration, 2),
        "date_range_from": date_from,
        "date_range_to": date_to,
    }

    return {"activities": rows, "summary": summary}
