"""
Activity detail MCP tool.
Joins ActivitySummary + ActivitySession + ActivityLap for a single activity.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from influx import normalise_activity, normalise_lap
from utils import pick, safe_float, safe_int


async def get_activity_details(activity_id: str) -> dict[str, Any]:
    """
    Return detailed breakdown of a single activity by ID.

    Parameters:
        activity_id – the activity ID (discoverable from get_recent_activities)

    Returns:
        activity      – core metrics + HR zones + training effect
        laps          – per-lap splits with pace/speed, HR, cadence
        analysis_hints – pre-computed: fastest/slowest lap, HR drift %
    """
    if not activity_id or not str(activity_id).strip():
        return {"error": "activity_id is required"}

    activity_id = str(activity_id).strip()

    # -- 1. ActivitySummary --
    try:
        summary_rows = await asyncio.to_thread(
            influx.query_activity_summary_by_id, activity_id
        )
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    # Filter sentinel rows (activityType='No Activity')
    data_rows = [
        r for r in summary_rows
        if (r.get("activityType") or r.get("activity_type") or "").lower() != "no activity"
    ]

    if not data_rows:
        return {
            "data_note": f"No activity found with ID '{activity_id}'",
            "activity": None,
        }

    raw = data_rows[0]

    # Use the canonical normaliser for base fields (distance, duration,
    # speed, HR, zones, cadence, power, elevation, pace).
    base = normalise_activity(raw)
    sport = base["sport_type"] or "unknown"

    # Detail-only fields not covered by normalise_activity
    moving_raw = safe_float(pick(raw, "movingDuration", "moving_duration"))
    moving_min = round(moving_raw / 60.0, 2) if moving_raw and moving_raw > 300 else (
        round(moving_raw, 2) if moving_raw else None
    )

    max_speed_raw = safe_float(pick(raw, "maxSpeed", "max_speed"))
    max_speed_kmh = round(max_speed_raw * 3.6, 2) if max_speed_raw and max_speed_raw < 100 else (
        round(max_speed_raw, 2) if max_speed_raw else None
    )

    activity_out: dict[str, Any] = {
        "activity_id": activity_id,
        "timestamp": base["timestamp"],
        "activity_name": pick(raw, "activityName", "activity_name", "name"),
        "sport_type": sport,
        "distance_km": base["distance_km"],
        "duration_minutes": base["duration_minutes"],
        "moving_duration_minutes": moving_min,
        "avg_hr": base["avg_hr"],
        "max_hr": base["max_hr"],
        "avg_speed_kmh": base["avg_speed_kmh"],
        "max_speed_kmh": max_speed_kmh,
        "calories": base["calories"],
        "avg_pace_min_per_km": base["avg_pace_min_per_km"],
        "elevation_gain_m": base["elevation_gain_m"],
        "avg_cadence": base["avg_cadence"],
        "avg_power": base["avg_power"],
        "lap_count": safe_int(pick(raw, "lapCount", "lap_count")),
        "location": pick(raw, "locationName", "location_name"),
        "description": pick(raw, "description"),
        "hr_zones": base["hr_zones"],
        "training_effect": None,
    }

    # -- 2. ActivitySession + ActivityLap (independent, run concurrently) --
    session_rows, lap_rows = await asyncio.gather(
        asyncio.to_thread(influx.query_activity_session_by_id, activity_id),
        asyncio.to_thread(influx.query_activity_laps_by_id, activity_id),
    )
    if session_rows:
        sess = session_rows[0]
        aerobic = safe_float(sess.get("Aerobic_Training") or sess.get("aerobic_training"))
        anaerobic = safe_float(sess.get("Anaerobic_Training") or sess.get("anaerobic_training"))
        sub_sport = sess.get("Sub_Sport") or sess.get("sub_sport")
        activity_out["training_effect"] = {
            "aerobic": round(aerobic, 1) if aerobic else None,
            "anaerobic": round(anaerobic, 1) if anaerobic else None,
        }
        if sub_sport:
            activity_out["sub_sport"] = str(sub_sport).lower().strip()

    # -- 3. Lap normalisation --
    laps = [normalise_lap(r, sport) for r in lap_rows]

    # -- 4. Backfill cadence/power from laps (not in ActivitySummary) --
    # Duration-weighted average: a 20-min lap at 90rpm matters more than
    # a 30-second lap at 60rpm.
    if laps and activity_out.get("avg_cadence") is None:
        activity_out["avg_cadence"] = _weighted_avg(laps, "avg_cadence")
    if laps and activity_out.get("avg_power") is None:
        activity_out["avg_power"] = _weighted_avg(laps, "avg_power")

    # -- 5. Analysis hints --
    analysis = _compute_analysis_hints(laps)

    return {
        "activity": activity_out,
        "laps": laps if laps else None,
        "analysis_hints": analysis,
    }


def _weighted_avg(laps: list[dict], field: str) -> float | None:
    """
    Compute a duration-weighted average of *field* across laps.
    Uses elapsed_time_minutes as weight.  Ignores laps where
    the field or duration is missing.
    """
    total_val = 0.0
    total_dur = 0.0
    for lap in laps:
        val = lap.get(field)
        dur = lap.get("elapsed_time_minutes")
        if val is not None and dur is not None and dur > 0:
            total_val += val * dur
            total_dur += dur
    if total_dur <= 0:
        return None
    return round(total_val / total_dur, 1)


def _compute_analysis_hints(laps: list[dict]) -> dict[str, Any] | None:
    """Pre-compute useful analysis metrics from lap data."""
    if not laps or len(laps) < 2:
        return None

    paces: list[tuple[int, float]] = []
    speeds: list[tuple[int, float]] = []
    for lap in laps:
        idx = lap.get("index") or 0
        p = lap.get("avg_pace_min_per_km")
        s = lap.get("avg_speed_kmh")
        if p is not None:
            paces.append((idx, p))
        if s is not None:
            speeds.append((idx, s))

    hints: dict[str, Any] = {"total_laps": len(laps)}

    if paces:
        fastest = min(paces, key=lambda x: x[1])
        slowest = max(paces, key=lambda x: x[1])
        hints["fastest_lap_index"] = fastest[0]
        hints["slowest_lap_index"] = slowest[0]
        hints["pace_range_min_per_km"] = [round(fastest[1], 2), round(slowest[1], 2)]
    elif speeds:
        fastest = max(speeds, key=lambda x: x[1])
        slowest = min(speeds, key=lambda x: x[1])
        hints["fastest_lap_index"] = fastest[0]
        hints["slowest_lap_index"] = slowest[0]
        hints["speed_range_kmh"] = [round(slowest[1], 2), round(fastest[1], 2)]

    # HR drift: compare avg HR of first half vs second half of laps
    hrs = [(i, lap.get("avg_hr")) for i, lap in enumerate(laps) if lap.get("avg_hr")]
    if len(hrs) >= 4:
        mid = len(hrs) // 2
        first_half_avg = sum(h for _, h in hrs[:mid]) / mid
        second_half_avg = sum(h for _, h in hrs[mid:]) / (len(hrs) - mid)
        if first_half_avg > 0:
            drift_pct = round((second_half_avg - first_half_avg) / first_half_avg * 100, 1)
            hints["hr_drift_pct"] = drift_pct

    return hints
