"""
Activity detail MCP tool.
Joins ActivitySummary + ActivitySession + ActivityLap for a single activity.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

from typing import Any

import influx
from utils import pick, safe_float, safe_int
from influx import normalise_lap


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
        summary_rows = influx.query_activity_summary_by_id(activity_id)
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

    sport = (pick(raw, "activityType", "activity_type", "sport_type", "sport") or "unknown").lower().strip()

    # Distance and duration — same heuristics as normalise_activity
    dist_raw = safe_float(pick(raw, "distance", "total_distance"))
    dist_km = round(dist_raw / 1000.0, 3) if dist_raw and dist_raw > 500 else (
        round(dist_raw, 3) if dist_raw else None
    )

    dur_raw = safe_float(pick(raw, "elapsedDuration", "elapsed_duration", "duration"))
    dur_min = round(dur_raw / 60.0, 2) if dur_raw and dur_raw > 300 else (
        round(dur_raw, 2) if dur_raw else None
    )
    moving_raw = safe_float(pick(raw, "movingDuration", "moving_duration"))
    moving_min = round(moving_raw / 60.0, 2) if moving_raw and moving_raw > 300 else (
        round(moving_raw, 2) if moving_raw else None
    )

    avg_speed_raw = safe_float(pick(raw, "averageSpeed", "average_speed", "avg_speed"))
    avg_speed_kmh = round(avg_speed_raw * 3.6, 2) if avg_speed_raw and avg_speed_raw < 100 else (
        round(avg_speed_raw, 2) if avg_speed_raw else None
    )
    max_speed_raw = safe_float(pick(raw, "maxSpeed", "max_speed"))
    max_speed_kmh = round(max_speed_raw * 3.6, 2) if max_speed_raw and max_speed_raw < 100 else (
        round(max_speed_raw, 2) if max_speed_raw else None
    )

    ts = raw.get("time") or raw.get("_time")
    if ts and hasattr(ts, "isoformat"):
        ts = ts.isoformat()

    # HR zones: seconds → minutes + percentage of total zone time
    _zone_secs = [
        safe_float(raw.get(influx.FIELD_HR_ZONE_1)) or 0.0,
        safe_float(raw.get(influx.FIELD_HR_ZONE_2)) or 0.0,
        safe_float(raw.get(influx.FIELD_HR_ZONE_3)) or 0.0,
        safe_float(raw.get(influx.FIELD_HR_ZONE_4)) or 0.0,
        safe_float(raw.get(influx.FIELD_HR_ZONE_5)) or 0.0,
    ]
    _zone_mins = [round(s / 60.0, 1) for s in _zone_secs]
    _total_zone_min = sum(_zone_mins)

    def _zone_pct(val):
        return round(val / _total_zone_min * 100.0, 1) if _total_zone_min > 0 else None

    hr_zones = {
        "zone_1_minutes": _zone_mins[0] or None,
        "zone_1_pct": _zone_pct(_zone_mins[0]),
        "zone_2_minutes": _zone_mins[1] or None,
        "zone_2_pct": _zone_pct(_zone_mins[1]),
        "zone_3_minutes": _zone_mins[2] or None,
        "zone_3_pct": _zone_pct(_zone_mins[2]),
        "zone_4_minutes": _zone_mins[3] or None,
        "zone_4_pct": _zone_pct(_zone_mins[3]),
        "zone_5_minutes": _zone_mins[4] or None,
        "zone_5_pct": _zone_pct(_zone_mins[4]),
    } if _total_zone_min > 0 else {
        "zone_1_minutes": None, "zone_1_pct": None,
        "zone_2_minutes": None, "zone_2_pct": None,
        "zone_3_minutes": None, "zone_3_pct": None,
        "zone_4_minutes": None, "zone_4_pct": None,
        "zone_5_minutes": None, "zone_5_pct": None,
    }

    activity_out: dict[str, Any] = {
        "activity_id": activity_id,
        "timestamp": str(ts) if ts else None,
        "activity_name": pick(raw, "activityName", "activity_name", "name"),
        "sport_type": sport,
        "distance_km": dist_km,
        "duration_minutes": dur_min,
        "moving_duration_minutes": moving_min,
        "avg_hr": safe_float(pick(raw, "averageHR", "average_hr", "avg_hr")),
        "max_hr": safe_float(pick(raw, "maxHR", "max_hr")),
        "avg_speed_kmh": avg_speed_kmh,
        "max_speed_kmh": max_speed_kmh,
        "calories": safe_int(pick(raw, "calories", "total_calories")),
        "lap_count": safe_int(pick(raw, "lapCount", "lap_count")),
        "location": pick(raw, "locationName", "location_name"),
        "description": pick(raw, "description"),
        "hr_zones": hr_zones,
        "training_effect": None,
    }

    # -- 2. ActivitySession (training effect) --
    session_rows = influx.query_activity_session_by_id(activity_id)
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

    # -- 3. ActivityLap (splits) --
    lap_rows = influx.query_activity_laps_by_id(activity_id)
    laps = [normalise_lap(r, sport) for r in lap_rows]

    # -- 4. Analysis hints --
    analysis = _compute_analysis_hints(laps)

    return {
        "activity": activity_out,
        "laps": laps if laps else None,
        "analysis_hints": analysis,
    }


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
