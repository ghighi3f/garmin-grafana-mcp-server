"""
Fitness trend and training zones MCP tools.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

from typing import Any

import influx
from utils import safe_float, iso_week_label, week_start_from_label


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_race_time(seconds_val) -> str | None:
    """Convert race prediction seconds to human-readable time string."""
    s = safe_float(seconds_val)
    if s is None or s <= 0:
        return None
    total_secs = int(round(s))
    hours, remainder = divmod(total_secs, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _index_by_week(rows: list[dict], value_extractor) -> dict[str, Any]:
    """Build {week_label: value} dict from raw query rows."""
    by_week: dict[str, Any] = {}
    for r in rows:
        ts = r.get("time") or r.get("_time")
        label = iso_week_label(ts)
        if label:
            val = value_extractor(r)
            if val is not None:
                by_week[label] = val
    return by_week


# ---------------------------------------------------------------------------
# Tool: get_fitness_trend
# ---------------------------------------------------------------------------

async def get_fitness_trend(weeks: int = 12) -> dict[str, Any]:
    """
    Return long-term fitness trajectory: VO2max, race predictions,
    weight, resting HR — sampled weekly to minimise tokens.

    Parameters:
        weeks – look-back window in weeks (4–52, default 12)
    """
    weeks = max(4, min(weeks, 52))

    # All non-fatal individually
    vo2_rows = influx.query_vo2max_weekly(weeks)
    race_rows = influx.query_race_predictions_weekly(weeks)
    weight_rows = influx.query_weight_weekly(weeks)
    rhr_rows = influx.query_resting_hr_weekly(weeks)

    # -- Index each by ISO week --
    vo2_by_week = _index_by_week(vo2_rows, lambda r: {
        "running": safe_float(
            r.get("vo2max_running") or r.get("_value") or r.get(influx.FIELD_VO2_MAX_RUNNING)
        ),
        "cycling": safe_float(
            r.get("vo2max_cycling") or r.get(influx.FIELD_VO2_MAX_CYCLING)
        ),
    })

    def _extract_race(r):
        t5k = safe_float(r.get("time_5k") or r.get("_value") or r.get(influx.FIELD_RACE_5K))
        t10k = safe_float(r.get("time_10k") or r.get(influx.FIELD_RACE_10K))
        thalf = safe_float(r.get("time_half") or r.get(influx.FIELD_RACE_HALF))
        tmar = safe_float(r.get("time_marathon") or r.get(influx.FIELD_RACE_MARATHON))
        if t5k is None and t10k is None:
            return None
        return {
            "time_5k": _format_race_time(t5k),
            "time_5k_seconds": t5k,
            "time_10k": _format_race_time(t10k),
            "time_10k_seconds": t10k,
            "time_half_marathon": _format_race_time(thalf),
            "time_marathon": _format_race_time(tmar),
        }

    race_by_week = _index_by_week(race_rows, _extract_race)

    def _extract_weight(r):
        raw = safe_float(r.get("weight") or r.get("_value") or r.get(influx.FIELD_WEIGHT))
        if raw is None:
            return None
        # Stored in grams if > 200 (heuristic: nobody weighs 200+ kg)
        kg = round(raw / 1000.0, 1) if raw > 200 else round(raw, 1)
        return {"weight_kg": kg}

    weight_by_week = _index_by_week(weight_rows, _extract_weight)

    rhr_by_week = _index_by_week(rhr_rows, lambda r: round(
        safe_float(r.get("avg_rhr") or r.get("mean") or r.get("_value")), 1
    ) if safe_float(r.get("avg_rhr") or r.get("mean") or r.get("_value")) else None)

    # -- Build weekly output --
    all_labels = sorted(
        set(vo2_by_week) | set(race_by_week) | set(weight_by_week) | set(rhr_by_week),
        reverse=True,
    )

    if not all_labels:
        return {
            "data_note": "No fitness trend data found for this period",
            "weeks": [],
            "trends": None,
        }

    result_weeks = []
    for label in all_labels:
        vo2 = vo2_by_week.get(label) or {}
        race = race_by_week.get(label)
        wt = weight_by_week.get(label) or {}

        result_weeks.append({
            "week_label": label,
            "week_start_date": week_start_from_label(label),
            "vo2max_running": vo2.get("running") if isinstance(vo2, dict) else None,
            "vo2max_cycling": vo2.get("cycling") if isinstance(vo2, dict) else None,
            "race_predictions": race,
            "weight_kg": wt.get("weight_kg") if isinstance(wt, dict) else None,
            "avg_resting_hr": rhr_by_week.get(label),
        })

    # -- Compute trends --
    trends = _compute_trends(result_weeks)

    return {"weeks": result_weeks, "trends": trends}


def _compute_trends(weeks: list[dict]) -> dict[str, Any]:
    """Compare oldest and newest data points for key metrics."""
    trends: dict[str, Any] = {}

    def _delta(key):
        vals = [(w["week_label"], w.get(key)) for w in weeks if w.get(key) is not None]
        if len(vals) < 2:
            return
        newest_label, newest_val = vals[0]
        oldest_label, oldest_val = vals[-1]
        if newest_val is not None and oldest_val is not None:
            trends[f"{key}_change"] = round(newest_val - oldest_val, 1)
            trends[f"{key}_period"] = f"{oldest_label} -> {newest_label}"

    _delta("vo2max_running")
    _delta("weight_kg")
    _delta("avg_resting_hr")

    # Race 5K trend (seconds)
    race_vals = [
        (w["week_label"], w["race_predictions"].get("time_5k_seconds"))
        for w in weeks
        if w.get("race_predictions") and w["race_predictions"].get("time_5k_seconds")
    ]
    if len(race_vals) >= 2:
        newest_5k = race_vals[0][1]
        oldest_5k = race_vals[-1][1]
        if newest_5k and oldest_5k:
            trends["race_5k_change_seconds"] = round(newest_5k - oldest_5k)

    return trends


# ---------------------------------------------------------------------------
# Tool: get_training_zones
# ---------------------------------------------------------------------------

async def get_training_zones(days: int = 30, sport_type: str = "all") -> dict[str, Any]:
    """
    Aggregate HR zone distribution across activities in the period.

    Parameters:
        days       – look-back window in days (7–180, default 30)
        sport_type – filter: "running", "cycling", "swimming", or "all"

    Returns:
        zone_distribution  – total minutes and % per zone
        polarization       – low/moderate/high intensity breakdown
        by_sport           – per-sport zone distribution (when multiple sports)
    """
    days = max(7, min(days, 180))
    if sport_type not in ("running", "cycling", "swimming", "all", None):
        sport_type = "all"

    try:
        raw_rows = influx.query_activity_hr_zones(days=days, limit=days * 5)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    zone_keys = [
        influx.FIELD_HR_ZONE_1,
        influx.FIELD_HR_ZONE_2,
        influx.FIELD_HR_ZONE_3,
        influx.FIELD_HR_ZONE_4,
        influx.FIELD_HR_ZONE_5,
    ]

    def _get_sport(row):
        for k in ("activityType", "activity_type", "sport_type", "sport"):
            v = row.get(k)
            if v and str(v).lower().strip() != "no activity":
                return str(v).lower().strip()
        return None

    overall = [0.0] * 5
    by_sport: dict[str, dict] = {}
    total_activities = 0

    for row in raw_rows:
        row_sport = _get_sport(row)
        if row_sport is None:
            continue

        if sport_type and sport_type != "all" and row_sport != sport_type:
            continue

        zones = []
        has_zone_data = False
        for zk in zone_keys:
            val = safe_float(row.get(zk))
            zones.append(val or 0.0)
            if val:
                has_zone_data = True

        if not has_zone_data:
            continue

        total_activities += 1
        for i in range(5):
            overall[i] += zones[i]

        if row_sport not in by_sport:
            by_sport[row_sport] = {"zones": [0.0] * 5, "count": 0}
        by_sport[row_sport]["count"] += 1
        for i in range(5):
            by_sport[row_sport]["zones"][i] += zones[i]

    if total_activities == 0:
        return {
            "data_note": "No activities with HR zone data found for this period",
            "period_days": days,
            "sport_type": sport_type,
            "total_activities": 0,
            "zone_distribution": None,
        }

    # Convert seconds → minutes and compute percentages
    overall_min = [round(z / 60.0, 1) for z in overall]
    total_min = sum(overall_min)

    def _pct(val):
        return round(val / total_min * 100, 1) if total_min > 0 else 0.0

    zone_dist = {
        "zone_1_minutes": overall_min[0], "zone_1_pct": _pct(overall_min[0]),
        "zone_2_minutes": overall_min[1], "zone_2_pct": _pct(overall_min[1]),
        "zone_3_minutes": overall_min[2], "zone_3_pct": _pct(overall_min[2]),
        "zone_4_minutes": overall_min[3], "zone_4_pct": _pct(overall_min[3]),
        "zone_5_minutes": overall_min[4], "zone_5_pct": _pct(overall_min[4]),
    }

    polarization = {
        "low_intensity_pct": _pct(overall_min[0] + overall_min[1]),
        "moderate_intensity_pct": _pct(overall_min[2]),
        "high_intensity_pct": _pct(overall_min[3] + overall_min[4]),
    }

    sport_breakdown = None
    if len(by_sport) > 1:
        sport_breakdown = {}
        for sp, data in by_sport.items():
            sp_min = [round(z / 60.0, 1) for z in data["zones"]]
            sp_total = sum(sp_min)

            def _sp_pct(val, total=sp_total):
                return round(val / total * 100, 1) if total > 0 else 0.0

            sport_breakdown[sp] = {
                "activities": data["count"],
                "total_zone_minutes": round(sp_total, 1),
                "zone_1_pct": _sp_pct(sp_min[0]),
                "zone_2_pct": _sp_pct(sp_min[1]),
                "zone_3_pct": _sp_pct(sp_min[2]),
                "zone_4_pct": _sp_pct(sp_min[3]),
                "zone_5_pct": _sp_pct(sp_min[4]),
            }

    return {
        "period_days": days,
        "sport_type": sport_type,
        "total_activities": total_activities,
        "total_hr_zone_minutes": round(total_min, 1),
        "zone_distribution": zone_dist,
        "polarization": polarization,
        "by_sport": sport_breakdown,
    }
