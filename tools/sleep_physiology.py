"""
Overnight sleep physiology MCP tool.
Aggregates SleepIntraday epoch data (HR, HRV, respiration, SpO2, stress,
body battery, restlessness) per night, enriched with SleepSummary ranges.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from utils import safe_float, compute_trend


async def get_sleep_physiology(days: int = 7) -> dict[str, Any]:
    """
    Return nightly autonomic physiology from SleepIntraday (min/max/mean
    of HR, HRV, respiration, SpO2) merged with enriched SleepSummary data.

    Parameters:
        days – look-back window in days (1–14, default 7)
    """
    days = max(1, min(days, 14))

    try:
        intraday_rows, sleep_rows = await asyncio.gather(
            asyncio.to_thread(influx.query_sleep_intraday_aggregated, days),
            asyncio.to_thread(influx.query_sleep_summary, days),
        )
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    # Index by date
    intraday_by_date: dict[str, dict] = {}
    for row in intraday_rows:
        d = row.get("date")
        if d:
            intraday_by_date[d] = row

    sleep_by_date: dict[str, dict] = {}
    for row in sleep_rows:
        d = row.get("date")
        if d:
            sleep_by_date[d] = row

    all_dates = sorted(
        set(intraday_by_date.keys()) | set(sleep_by_date.keys()),
        reverse=True,
    )

    if not all_dates:
        return {
            "data_note": "No sleep physiology data found for this period",
            "nights": [],
            "summary": None,
        }

    nights = []
    min_hr_vals: list[float] = []
    mean_hrv_vals: list[float] = []
    mean_resp_vals: list[float] = []
    min_spo2_vals: list[float] = []
    bb_charged_vals: list[float] = []

    for date in all_dates:
        intraday = intraday_by_date.get(date)
        sleep_raw = sleep_by_date.get(date)

        # Build summary from normalised sleep row
        summary_out = None
        if sleep_raw:
            summary_out = {k: v for k, v in sleep_raw.items() if k != "date"}

        # Build intraday block (already in canonical format from influx.py)
        intraday_out = None
        if intraday:
            intraday_out = {k: v for k, v in intraday.items() if k != "date"}

        nights.append({
            "date": date,
            "intraday": intraday_out,
            "summary": summary_out,
        })

        # Accumulate for summary
        if intraday:
            hr = intraday.get("heart_rate")
            if hr and hr.get("min") is not None:
                min_hr_vals.append(hr["min"])
            hrv = intraday.get("hrv")
            if hrv and hrv.get("mean") is not None:
                mean_hrv_vals.append(hrv["mean"])
            resp = intraday.get("respiration")
            if resp and resp.get("mean") is not None:
                mean_resp_vals.append(resp["mean"])
            spo2 = intraday.get("spo2")
            if spo2 and spo2.get("min") is not None:
                min_spo2_vals.append(spo2["min"])
            bb = intraday.get("body_battery")
            if bb and bb.get("first") is not None and bb.get("last") is not None:
                bb_charged_vals.append(bb["last"] - bb["first"])

    summary = {
        "nights_with_data": len(all_dates),
        "avg_min_hr": round(sum(min_hr_vals) / len(min_hr_vals), 1) if min_hr_vals else None,
        "avg_mean_hrv": round(sum(mean_hrv_vals) / len(mean_hrv_vals), 1) if mean_hrv_vals else None,
        "avg_mean_respiration": round(sum(mean_resp_vals) / len(mean_resp_vals), 1) if mean_resp_vals else None,
        "avg_min_spo2": round(sum(min_spo2_vals) / len(min_spo2_vals), 1) if min_spo2_vals else None,
        "avg_body_battery_charged": round(sum(bb_charged_vals) / len(bb_charged_vals)) if bb_charged_vals else None,
        "min_hr_trend": compute_trend(min_hr_vals, higher_is_better=False),
        "hrv_trend": compute_trend(mean_hrv_vals, higher_is_better=True),
        "respiration_trend": compute_trend(mean_resp_vals, higher_is_better=False),
    }

    return {"nights": nights, "summary": summary}
