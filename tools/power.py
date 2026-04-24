"""
Power meter MCP tools.
Surfaces peak efforts, Coggan power zones, and per-session power history
from ActivityGPS (second-by-second) and ActivityLap (per-lap aggregates).
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from utils import safe_float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Coggan 7-zone definitions: (lower_pct_inclusive, upper_pct_exclusive, label)
# Zone 7 has no upper bound (use float("inf")).
_COGGAN_ZONES: list[tuple[float, float, str, str]] = [
    (0.0,   55.0,  "zone_1", "Active Recovery"),
    (55.0,  75.0,  "zone_2", "Endurance"),
    (75.0,  90.0,  "zone_3", "Tempo"),
    (90.0,  105.0, "zone_4", "Threshold"),
    (105.0, 120.0, "zone_5", "VO2 Max"),
    (120.0, 150.0, "zone_6", "Anaerobic"),
    (150.0, float("inf"), "zone_7", "Neuromuscular"),
]


def _rolling_avg_max(values: list[int], window: int) -> int | None:
    """Return the maximum rolling average over *window* consecutive samples.

    O(n) via sliding-sum. Returns None when fewer samples than the window.
    """
    n = len(values)
    if n < window:
        return None
    win_sum = sum(values[:window])
    best = win_sum
    for i in range(window, n):
        win_sum += values[i] - values[i - window]
        if win_sum > best:
            best = win_sum
    return round(best / window)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def get_peak_power(activity_id: str) -> dict[str, Any]:
    """
    Return peak power efforts and coasting statistics for a single activity.

    Parameters:
        activity_id – the activity ID (from get_recent_activities or
                      get_activity_details)

    Returns:
        activity_id         – echoed back for traceability
        peak_powers         – best average watt over 1s / 5s / 10s / 30s /
                              60s / 5min / 20min rolling windows
        avg_power_total     – mean watts including coasting (0W) samples
        avg_power_pedaling_only – mean watts when Power > 0 only
        coasting_pct        – percentage of samples where Power == 0
        total_work_kj       – total mechanical work (kJ) from Accumulated_Power
        data_points         – number of 1-second samples available
    """
    if not activity_id or not str(activity_id).strip():
        return {"error": "activity_id is required"}

    activity_id = str(activity_id).strip()

    powers, gps_stats = await asyncio.gather(
        asyncio.to_thread(influx.query_activity_gps_power_raw, activity_id),
        asyncio.to_thread(influx.query_activity_gps_stats, activity_id),
    )

    if not powers:
        return {
            "activity_id": activity_id,
            "data_note": "No ActivityGPS power data found for this activity. "
                         "Power meter may not have been active.",
            "peak_powers": None,
        }

    n = len(powers)
    zeros = powers.count(0)
    pedaling = [p for p in powers if p > 0]

    peak_powers: dict[str, Any] = {
        "1s":    max(powers),
        "5s":    _rolling_avg_max(powers, 5),
        "10s":   _rolling_avg_max(powers, 10),
        "30s":   _rolling_avg_max(powers, 30),
        "60s":   _rolling_avg_max(powers, 60),
        "5min":  _rolling_avg_max(powers, 300),
        "20min": _rolling_avg_max(powers, 1200),
    }

    return {
        "activity_id": activity_id,
        "peak_powers": peak_powers,
        "avg_power_total": round(sum(powers) / n, 1),
        "avg_power_pedaling_only": round(sum(pedaling) / len(pedaling), 1) if pedaling else None,
        "coasting_pct": round(zeros / n * 100.0, 1),
        "total_work_kj": gps_stats.get("total_work_kj"),
        "data_points": n,
    }


async def get_power_zones(
    activity_id: str,
    ftp: float = 211.0,
) -> dict[str, Any]:
    """
    Return time-in-zone distribution using Coggan 7-zone model.

    Zone boundaries are computed as percentages of the supplied FTP:
      Zone 1 (Active Recovery): < 55% FTP
      Zone 2 (Endurance):       55–75% FTP
      Zone 3 (Tempo):           75–90% FTP
      Zone 4 (Threshold):       90–105% FTP
      Zone 5 (VO2 Max):         105–120% FTP
      Zone 6 (Anaerobic):       120–150% FTP
      Zone 7 (Neuromuscular):   > 150% FTP

    Coasting (0W) samples are excluded from zone distribution and reported
    separately as coasting_minutes.

    Parameters:
        activity_id – the activity ID
        ftp         – Functional Threshold Power in watts (default 211.0)

    Returns:
        activity_id       – echoed back
        ftp_used          – FTP value applied to compute zone boundaries
        zones             – list of zone dicts (zone_id, label, min_watts,
                            max_watts, minutes, pct_of_power_time)
        coasting_minutes  – time at 0W (excluded from zone percentages)
        total_power_minutes – total pedaling time counted in zones
        data_points       – total 1-second samples
    """
    if not activity_id or not str(activity_id).strip():
        return {"error": "activity_id is required"}
    if ftp <= 0:
        return {"error": "ftp must be a positive number"}

    activity_id = str(activity_id).strip()

    powers = await asyncio.to_thread(influx.query_activity_gps_power_raw, activity_id)

    if not powers:
        return {
            "activity_id": activity_id,
            "data_note": "No ActivityGPS power data found for this activity.",
            "zones": None,
        }

    # Count samples per Coggan zone (exclude 0W coasting)
    zone_counts = [0] * len(_COGGAN_ZONES)
    coasting = 0
    for p in powers:
        if p == 0:
            coasting += 1
            continue
        pct = p / ftp * 100.0
        for i, (lo, hi, _zid, _label) in enumerate(_COGGAN_ZONES):
            if lo <= pct < hi:
                zone_counts[i] += 1
                break
        else:
            # Catch anything above zone 7 lower bound (shouldn't happen with inf)
            zone_counts[-1] += 1

    total_power_seconds = sum(zone_counts)

    zones = []
    for i, (lo, hi, zone_id, label) in enumerate(_COGGAN_ZONES):
        min_w = round(lo / 100.0 * ftp)
        max_w = round(hi / 100.0 * ftp) if hi != float("inf") else None
        secs = zone_counts[i]
        minutes = round(secs / 60.0, 2)
        pct = round(secs / total_power_seconds * 100.0, 1) if total_power_seconds > 0 else 0.0
        zones.append({
            "zone": zone_id,
            "label": label,
            "min_watts": min_w,
            "max_watts": max_w,
            "minutes": minutes,
            "pct_of_power_time": pct,
        })

    return {
        "activity_id": activity_id,
        "ftp_used": ftp,
        "zones": zones,
        "coasting_minutes": round(coasting / 60.0, 2),
        "total_power_minutes": round(total_power_seconds / 60.0, 2),
        "data_points": len(powers),
    }


async def get_power_history(
    days: int = 30,
    sport_type: str = "all",
) -> dict[str, Any]:
    """
    Return per-activity power summary for activities in the last N days.

    Only includes activities that have avg_power data (from ActivityLap).
    Total work (kJ) is sourced from ActivityGPS Accumulated_Power via a
    single bulk GROUP BY query — no per-activity round-trips.

    Parameters:
        days       – look-back window in days (1–90, default 30)
        sport_type – filter by Garmin sport type or "all" (default "all")

    Returns:
        activities  – list (newest first) of: activity_id, timestamp,
                      activity_name, sport_type, distance_km,
                      duration_minutes, avg_power, total_work_kj,
                      training_load, aerobic_te, anaerobic_te
        summary     – avg_power_trend, best_avg_power_session, total_work_kj
    """
    days = max(1, min(days, 90))

    # Run all three bulk queries in parallel — no N+1
    try:
        activities, work_by_id, lap_power = await asyncio.gather(
            asyncio.to_thread(influx.query_activity_load_history, days, sport_type, 100),
            asyncio.to_thread(influx.query_power_history_bulk, days),
            asyncio.to_thread(influx.query_lap_power_bulk, days),
        )
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    # Backfill avg_power from laps for activities missing it in ActivitySummary
    for act in activities:
        if act.get("avg_power") is None:
            aid = str(act.get("activity_id") or "")
            if aid and aid in lap_power:
                act["avg_power"] = lap_power[aid]

    # Filter to activities that have power data
    power_activities = [a for a in activities if a.get("avg_power") is not None]

    if not power_activities:
        return {
            "data_note": "No activities with power data found in this period.",
            "activities": [],
            "summary": None,
        }

    entries = []
    for act in power_activities:
        aid = str(act.get("activity_id") or "")
        entries.append({
            "activity_id": act.get("activity_id"),
            "timestamp": act.get("timestamp"),
            "activity_name": act.get("activity_name"),
            "sport_type": act.get("sport_type"),
            "distance_km": act.get("distance_km"),
            "duration_minutes": act.get("duration_minutes"),
            "avg_power": act.get("avg_power"),
            "total_work_kj": work_by_id.get(aid),
            "training_load": act.get("training_load"),
            "aerobic_training_effect": act.get("aerobic_training_effect"),
            "anaerobic_training_effect": act.get("anaerobic_training_effect"),
        })

    # Summary
    pw_vals = [e["avg_power"] for e in entries if e["avg_power"] is not None]
    total_kj = sum(
        e["total_work_kj"] for e in entries if e["total_work_kj"] is not None
    )

    best_entry = max(entries, key=lambda e: e["avg_power"] or 0)
    best_session = {
        "activity_id": best_entry["activity_id"],
        "activity_name": best_entry["activity_name"],
        "date": str(best_entry["timestamp"] or "")[:10],
        "avg_power": best_entry["avg_power"],
    }

    # Trend: compare first-half vs second-half avg_power (entries are newest-first)
    avg_power_trend: str | None = None
    if len(pw_vals) >= 4:
        mid = len(pw_vals) // 2
        recent_avg = sum(pw_vals[:mid]) / mid
        older_avg = sum(pw_vals[mid:]) / (len(pw_vals) - mid)
        diff = recent_avg - older_avg
        if diff > 5:
            avg_power_trend = "improving"
        elif diff < -5:
            avg_power_trend = "declining"
        else:
            avg_power_trend = "stable"

    summary = {
        "total_activities_with_power": len(entries),
        "avg_power_trend": avg_power_trend,
        "best_avg_power_session": best_session,
        "total_work_kj": round(total_kj, 1) if total_kj else None,
        "period_avg_power": round(sum(pw_vals) / len(pw_vals), 1) if pw_vals else None,
    }

    return {"activities": entries, "summary": summary}
