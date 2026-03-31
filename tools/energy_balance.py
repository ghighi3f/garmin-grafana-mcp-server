"""
Daily energy balance and movement patterns MCP tool.
Surfaces time-use breakdown (sedentary/active/sleeping hours), caloric
data (BMR + active), stress attribution, and movement metrics from DailyStats.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from utils import compute_trend


async def get_daily_energy_balance(days: int = 7) -> dict[str, Any]:
    """
    Return daily time-use, energy, movement, and stress attribution data.

    Parameters:
        days – look-back window in days (1–14, default 7)
    """
    days = max(1, min(days, 14))

    try:
        daily_rows = await asyncio.to_thread(influx.query_daily_stats, days)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    if not daily_rows:
        return {
            "data_note": "No daily stats data found for this period",
            "days": [],
            "summary": None,
        }

    result_days = []
    sedentary_vals: list[float] = []
    active_vals: list[float] = []
    highly_active_vals: list[float] = []
    sleeping_vals: list[float] = []
    bmr_vals: list[float] = []
    bb_sleep_vals: list[float] = []
    activity_stress_pct_vals: list[float] = []

    for row in daily_rows:
        entry = {
            "date": row.get("date"),
            "time_use": {
                "sedentary_hours": row.get("sedentary_hours"),
                "active_hours": row.get("active_hours"),
                "highly_active_hours": row.get("highly_active_hours"),
                "sleeping_hours": row.get("sleeping_hours"),
            },
            "energy": {
                "bmr_kcal": row.get("bmr_kcal"),
                "active_kcal": row.get("active_calories"),
            },
            "movement": {
                "total_steps": row.get("total_steps"),
                "total_distance_km": row.get("total_distance_km"),
                "floors_ascended": row.get("floors_ascended"),
                "floors_descended": row.get("floors_descended"),
                "floors_ascended_meters": row.get("floors_ascended_meters"),
                "floors_descended_meters": row.get("floors_descended_meters"),
            },
            "recovery_context": {
                "body_battery_during_sleep": row.get("body_battery_during_sleep"),
                "body_battery_at_wake": row.get("body_battery_at_wake"),
                "resting_hr": row.get("resting_hr"),
            },
            "stress_attribution": {
                "activity_stress_min": row.get("activity_stress_min"),
                "activity_stress_pct": row.get("activity_stress_pct"),
                "total_stress_min": row.get("total_stress_min"),
                "stress_pct": row.get("stress_pct"),
                "uncategorized_stress_min": row.get("uncategorized_stress_min"),
            },
        }
        result_days.append(entry)

        # Accumulate for summary/trends
        if row.get("sedentary_hours") is not None:
            sedentary_vals.append(row["sedentary_hours"])
        if row.get("active_hours") is not None:
            active_vals.append(row["active_hours"])
        if row.get("highly_active_hours") is not None:
            highly_active_vals.append(row["highly_active_hours"])
        if row.get("sleeping_hours") is not None:
            sleeping_vals.append(row["sleeping_hours"])
        if row.get("bmr_kcal") is not None:
            bmr_vals.append(row["bmr_kcal"])
        if row.get("body_battery_during_sleep") is not None:
            bb_sleep_vals.append(row["body_battery_during_sleep"])
        if row.get("activity_stress_pct") is not None:
            activity_stress_pct_vals.append(row["activity_stress_pct"])

    def _avg(vals: list[float], decimals: int = 1):
        return round(sum(vals) / len(vals), decimals) if vals else None

    summary = {
        "days_with_data": len(result_days),
        "avg_sedentary_hours": _avg(sedentary_vals, 1),
        "avg_active_hours": _avg(active_vals, 1),
        "avg_highly_active_hours": _avg(highly_active_vals, 1),
        "avg_sleeping_hours": _avg(sleeping_vals, 1),
        "avg_bmr_kcal": _avg(bmr_vals, 0),
        "avg_body_battery_during_sleep": _avg(bb_sleep_vals, 0),
        "avg_activity_stress_pct": _avg(activity_stress_pct_vals, 1),
        "sedentary_trend": compute_trend(sedentary_vals, higher_is_better=False),
        "bb_during_sleep_trend": compute_trend(bb_sleep_vals, higher_is_better=True),
    }

    return {"days": result_days, "summary": summary}
