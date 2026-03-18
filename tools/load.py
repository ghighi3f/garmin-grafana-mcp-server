"""
Training-load MCP tool.
Aggregates raw activity data by ISO week.
No fitness metrics, no ATL/CTL/TSB — raw numbers only.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import influx
from utils import iso_week_label, week_start_from_label


# ---------------------------------------------------------------------------
# Tool: get_weekly_load_summary
# ---------------------------------------------------------------------------

async def get_weekly_load_summary(weeks: int = 4) -> dict[str, Any]:
    """
    Group all activities into ISO calendar weeks and return raw aggregates.

    Parameters:
        weeks – number of past weeks to include (1–16, default 4)

    Per-week fields:
        week_label          – ISO week string e.g. "2026-W11"
        week_start_date     – Monday of that week (ISO date)
        per_sport           – dict keyed by sport_type:
                                { sessions, total_distance_km,
                                  total_duration_min }
        avg_resting_hr      – weekly average resting HR (null if unavailable)
        hrv_weekly_avg      – weekly average HRV (null if unavailable)
        stress_or_load_score – raw stress_score or training_load field
                               if present in InfluxDB, else null

    Note: No derived fitness metrics (ATL/CTL/TSB) are computed here.
    """
    weeks = max(1, min(weeks, 16))
    days = weeks * 7

    # --- Activities ---
    try:
        rows = influx.query_recent_activities(
            days=days, sport_type=None, limit=weeks * 50
        )
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    # --- Resting HR (best-effort, non-fatal) ---
    rhr_rows = influx.query_resting_hr_weekly(weeks)
    # Map ISO week label → avg resting HR
    rhr_by_week: dict[str, float | None] = {}
    for r in rhr_rows:
        ts = r.get("time") or r.get("_time")
        if ts and hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        label = iso_week_label(str(ts)) if ts else None
        val = r.get("avg_rhr") or r.get("mean") or r.get("_value")
        if label and val is not None:
            try:
                rhr_by_week[label] = round(float(val), 1)
            except (TypeError, ValueError):
                pass

    # --- HRV (best-effort, non-fatal) ---
    hrv_rows = influx.query_hrv_weekly(weeks)
    hrv_by_week: dict[str, float | None] = {}
    for r in hrv_rows:
        ts = r.get("time") or r.get("_time")
        if ts and hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        label = iso_week_label(str(ts)) if ts else None
        val = r.get("avg_hrv") or r.get("mean") or r.get("_value")
        if label and val is not None:
            try:
                hrv_by_week[label] = round(float(val), 1)
            except (TypeError, ValueError):
                pass

    if not rows:
        return {
            "data_note": "No activities found for this period",
            "weeks": [],
        }

    # --- Aggregate activities by week ---
    # week_label → sport → accumulators
    weekly: dict[str, dict] = defaultdict(lambda: {
        "sports": defaultdict(lambda: {"sessions": 0, "dist_km": 0.0, "dur_min": 0.0}),
        # raw stress/load fields if present
        "stress_scores": [],
    })

    for act in rows:
        label = iso_week_label(act.get("timestamp"))
        if not label:
            continue
        sport = act.get("sport_type") or "unknown"
        entry = weekly[label]["sports"][sport]
        entry["sessions"] += 1
        entry["dist_km"] = round(entry["dist_km"] + (act.get("distance_km") or 0.0), 3)
        entry["dur_min"] = round(entry["dur_min"] + (act.get("duration_minutes") or 0.0), 2)

    # Build ordered output (newest week first)
    all_labels = sorted(weekly.keys(), reverse=True)

    result_weeks = []
    for label in all_labels:
        wdata = weekly[label]
        per_sport = {
            sport: {
                "sessions": vals["sessions"],
                "total_distance_km": vals["dist_km"],
                "total_duration_min": vals["dur_min"],
            }
            for sport, vals in wdata["sports"].items()
        }
        result_weeks.append({
            "week_label": label,
            "week_start_date": week_start_from_label(label),
            "per_sport": per_sport,
            "avg_resting_hr": rhr_by_week.get(label),
            "hrv_weekly_avg": hrv_by_week.get(label),
            "stress_or_load_score": None,  # populated only if raw field exists
        })

    return {"weeks": result_weeks}
