"""
Personal records MCP tool.
Returns all-time best metrics per sport, with full activity context
(date, ActivityID, activity name) for each record.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from influx import PACE_SPORTS
from utils import safe_float, safe_int


# Max-based record metrics (higher = better)
_MAX_METRICS: dict[str, str] = {
    "longest_distance":  "distance_km",
    "longest_duration":  "moving_duration_minutes",
    "top_speed":         "max_speed_kmh",
    "highest_max_hr":    "max_hr",
    "highest_avg_hr":    "avg_hr",
    "most_calories":     "calories",
    "highest_avg_power": "avg_power",
    "highest_max_power": "max_power",
}

# Units for each record key
_UNITS: dict[str, str] = {
    "longest_distance":   "km",
    "longest_duration":   "minutes",
    "fastest_avg_speed":  "km/h",
    "fastest_avg_pace":   "min/km",
    "top_speed":          "km/h",
    "highest_max_hr":     "bpm",
    "highest_avg_hr":     "bpm",
    "most_calories":      "kcal",
    "highest_avg_power":  "watts",
    "highest_max_power":  "watts",
}


def _activity_context(act: dict) -> dict:
    """Extract date, activity_id, and name from a normalised activity dict."""
    ts = act.get("timestamp") or ""
    return {
        "activity_id": act.get("activity_id"),
        "date": ts[:10] if ts else None,
        "activity_name": act.get("activity_name"),
    }


def _compute_records(activities: list[dict], sport: str) -> dict:
    """
    Single pass through activities to find the record holder for each metric.

    Returns a dict with one entry per record key, each containing
    value, unit, activity_id, date, and activity_name.
    """
    best: dict[str, tuple[float, dict]] = {}  # metric -> (best_value, activity)

    for act in activities:
        # Max-based metrics: higher is better
        for rec_key, field in _MAX_METRICS.items():
            val = safe_float(act.get(field))
            if val is None:
                continue
            current = best.get(rec_key)
            if current is None or val > current[0]:
                best[rec_key] = (val, act)

        # Speed/pace metric: depends on sport type
        if sport in PACE_SPORTS:
            pace = safe_float(act.get("avg_pace_min_per_km"))
            if pace is not None and pace > 0:
                current = best.get("fastest_avg_pace")
                if current is None or pace < current[0]:  # lower pace = faster
                    best["fastest_avg_pace"] = (pace, act)
        else:
            speed = safe_float(act.get("avg_speed_kmh"))
            if speed is not None:
                current = best.get("fastest_avg_speed")
                if current is None or speed > current[0]:
                    best["fastest_avg_speed"] = (speed, act)

    # Build output
    records: dict[str, Any] = {}
    all_keys = list(_MAX_METRICS.keys())
    if sport in PACE_SPORTS:
        all_keys.append("fastest_avg_pace")
    else:
        all_keys.append("fastest_avg_speed")

    for key in all_keys:
        entry = best.get(key)
        if entry is None:
            records[key] = None
        else:
            val, act = entry
            # Round value appropriately
            if key == "most_calories":
                display_val = safe_int(val)
            elif key in ("highest_max_hr", "highest_avg_hr", "highest_avg_power", "highest_max_power"):
                display_val = round(val, 1)
            else:
                display_val = round(val, 2)
            records[key] = {
                "value": display_val,
                "unit": _UNITS.get(key, ""),
                **_activity_context(act),
            }

    records["total_activities"] = len(activities)
    return records


# ---------------------------------------------------------------------------
# Tool: get_personal_records
# ---------------------------------------------------------------------------

async def get_personal_records(sport_type: str = "all") -> dict[str, Any]:
    """
    Return all-time personal records (best metrics) grouped by sport type.

    Each record includes the value, unit, activity_id, date, and activity
    name of the record-setting activity.

    Parameters:
        sport_type – filter by Garmin sport type (e.g. "running", "cycling")
                     or "all" for records across every sport.
                     Supports partial/sub-sport matching.
    """
    if sport_type:
        sport_type = sport_type.strip().lower()
    if not sport_type:
        sport_type = "all"

    try:
        all_activities = await asyncio.to_thread(influx.query_all_activities)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    if not all_activities:
        return {
            "data_note": "No activities found",
            "records_by_sport": {},
            "summary": None,
        }

    # Group by sport
    by_sport: dict[str, list[dict]] = {}
    for act in all_activities:
        sp = act.get("sport_type") or "unknown"
        by_sport.setdefault(sp, []).append(act)

    # Filter if a specific sport was requested (substring match)
    if sport_type != "all":
        by_sport = {
            sp: acts for sp, acts in by_sport.items()
            if sport_type in sp
        }

    if not by_sport:
        return {
            "data_note": f"No activities found matching sport_type='{sport_type}'",
            "records_by_sport": {},
            "summary": None,
        }

    # Compute records per sport
    records_by_sport: dict[str, dict] = {}
    for sp in sorted(by_sport.keys()):
        records_by_sport[sp] = _compute_records(by_sport[sp], sp)

    total_activities = sum(
        r.get("total_activities", 0) for r in records_by_sport.values()
    )

    summary = {
        "total_sports": len(records_by_sport),
        "total_activities": total_activities,
        "sport_list": sorted(records_by_sport.keys()),
    }

    return {"records_by_sport": records_by_sport, "summary": summary}
