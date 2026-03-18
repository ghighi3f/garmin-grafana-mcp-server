"""
Daily recovery / readiness MCP tool.
Merges SleepSummary + DailyStats per day.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

from typing import Any

import influx


async def get_daily_recovery(days: int = 7) -> dict[str, Any]:
    """
    Return daily recovery data combining sleep quality and daily health metrics.

    Parameters:
        days – look-back window in days (1–14, default 7)

    Per-day fields:
        sleep.*  – sleep score, durations (hours), HRV, stress, body battery change
        daily.*  – resting HR, body battery, steps, stress breakdown, SpO2
    Summary:
        Averages across the period for key readiness indicators.
    """
    days = max(1, min(days, 14))

    try:
        daily_rows = influx.query_daily_stats(days)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    try:
        sleep_rows = influx.query_sleep_summary(days)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    # Index by date for merging
    daily_by_date: dict[str, dict] = {}
    for row in daily_rows:
        d = row.get("date")
        if d:
            daily_by_date[d] = row

    sleep_by_date: dict[str, dict] = {}
    for row in sleep_rows:
        d = row.get("date")
        if d:
            sleep_by_date[d] = row

    # Merge by union of dates, newest first
    all_dates = sorted(
        set(daily_by_date.keys()) | set(sleep_by_date.keys()),
        reverse=True,
    )

    if not all_dates:
        return {
            "data_note": "No recovery data found for this period",
            "days": [],
            "summary": None,
        }

    merged_days = []
    sleep_scores: list[float] = []
    sleep_hours_list: list[float] = []
    hrv_values: list[float] = []
    rhr_values: list[float] = []
    bb_wake_values: list[float] = []

    for date in all_dates:
        sleep_data = sleep_by_date.get(date)
        daily_data = daily_by_date.get(date)

        # Strip redundant 'date' key from nested dicts
        sleep_out = {k: v for k, v in sleep_data.items() if k != "date"} if sleep_data else None
        daily_out = {k: v for k, v in daily_data.items() if k != "date"} if daily_data else None

        merged_days.append({
            "date": date,
            "sleep": sleep_out,
            "daily": daily_out,
        })

        # Accumulate for summary
        if sleep_data:
            if sleep_data.get("sleep_score") is not None:
                sleep_scores.append(sleep_data["sleep_score"])
            if sleep_data.get("total_sleep_hours") is not None:
                sleep_hours_list.append(sleep_data["total_sleep_hours"])
            if sleep_data.get("avg_overnight_hrv") is not None:
                hrv_values.append(sleep_data["avg_overnight_hrv"])
        if daily_data:
            if daily_data.get("resting_hr") is not None:
                rhr_values.append(daily_data["resting_hr"])
            if daily_data.get("body_battery_at_wake") is not None:
                bb_wake_values.append(daily_data["body_battery_at_wake"])

    summary = {
        "days_with_data": len(all_dates),
        "avg_sleep_score": round(sum(sleep_scores) / len(sleep_scores), 1) if sleep_scores else None,
        "avg_sleep_hours": round(sum(sleep_hours_list) / len(sleep_hours_list), 2) if sleep_hours_list else None,
        "avg_overnight_hrv": round(sum(hrv_values) / len(hrv_values), 1) if hrv_values else None,
        "avg_resting_hr": round(sum(rhr_values) / len(rhr_values), 1) if rhr_values else None,
        "avg_body_battery_at_wake": round(sum(bb_wake_values) / len(bb_wake_values)) if bb_wake_values else None,
    }

    return {"days": merged_days, "summary": summary}
