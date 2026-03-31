"""
Fitness age trend MCP tool.
Tracks fitness age vs chronological age and achievable fitness age over time.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from utils import safe_float, iso_week_label, week_start_from_label


async def get_fitness_age(weeks: int = 12) -> dict[str, Any]:
    """
    Return weekly-sampled fitness age trajectory.

    Parameters:
        weeks – look-back window in weeks (4–52, default 12)
    """
    weeks = max(4, min(weeks, 52))

    try:
        raw_rows = await asyncio.to_thread(influx.query_fitness_age_weekly, weeks)
    except Exception as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    if not raw_rows:
        return {
            "data_note": "No fitness age data found for this period",
            "weeks": [],
            "trends": None,
        }

    # Index by ISO week
    by_week: dict[str, dict] = {}
    for r in raw_rows:
        ts = r.get("time") or r.get("_time")
        label = iso_week_label(ts)
        if not label:
            continue

        fa = safe_float(r.get("fitness_age") or r.get(influx.FIELD_FITNESS_AGE))
        ca = safe_float(r.get("chrono_age") or r.get(influx.FIELD_CHRONOLOGICAL_AGE) or r.get("chronologicalAge"))
        aa = safe_float(r.get("achievable_age") or r.get(influx.FIELD_ACHIEVABLE_FITNESS_AGE) or r.get("achievableFitnessAge"))

        if fa is None:
            continue

        by_week[label] = {
            "fitness_age": round(fa, 1),
            "chronological_age": round(ca, 1) if ca else None,
            "achievable_fitness_age": round(aa, 1) if aa else None,
        }

    if not by_week:
        return {
            "data_note": "No fitness age data found for this period",
            "weeks": [],
            "trends": None,
        }

    all_labels = sorted(by_week.keys(), reverse=True)

    result_weeks = []
    for label in all_labels:
        data = by_week[label]
        fa = data["fitness_age"]
        ca = data["chronological_age"]
        aa = data["achievable_fitness_age"]

        result_weeks.append({
            "week_label": label,
            "week_start_date": week_start_from_label(label),
            "fitness_age": fa,
            "chronological_age": ca,
            "achievable_fitness_age": aa,
            "fitness_age_gap": round(fa - ca, 1) if fa is not None and ca is not None else None,
            "improvement_potential": round(fa - aa, 1) if fa is not None and aa is not None else None,
        })

    # Compute trends
    trends: dict[str, Any] = {}
    if len(result_weeks) >= 2:
        newest = result_weeks[0]
        oldest = result_weeks[-1]

        if newest["fitness_age"] is not None and oldest["fitness_age"] is not None:
            trends["fitness_age_change"] = round(newest["fitness_age"] - oldest["fitness_age"], 1)
        if newest.get("fitness_age_gap") is not None and oldest.get("fitness_age_gap") is not None:
            trends["fitness_age_gap_change"] = round(newest["fitness_age_gap"] - oldest["fitness_age_gap"], 1)
        if newest.get("improvement_potential") is not None and oldest.get("improvement_potential") is not None:
            trends["improvement_potential_change"] = round(
                newest["improvement_potential"] - oldest["improvement_potential"], 1,
            )
        trends["period"] = f"{oldest['week_label']} -> {newest['week_label']}"

    return {"weeks": result_weeks, "trends": trends if trends else None}
