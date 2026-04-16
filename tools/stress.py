"""
Stress and Body Battery trend MCP tool.
Uses DailyStats for historical days and synthesises today's partial data
from StressIntraday + BodyBatteryIntraday when DailyStats lacks it.
Pure data retrieval — no planning logic.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import influx
from utils import compute_trend, pick, safe_int

# Garmin stress-level buckets
# <= 0: unmeasured / activity marker (skip)
# 1-25: rest, 26-50: low, 51-75: medium, 76-100: high
_STRESS_INTERVAL_MIN = 3.0  # Garmin writes stress readings every ~3 minutes


def _aggregate_stress_intraday(rows: list[dict]) -> dict | None:
    """Categorise raw StressIntraday readings into Garmin's standard buckets.

    Returns minutes per bucket, or None if no valid readings exist.
    """
    rest = low = medium = high = 0

    for row in rows:
        level = safe_int(pick(row, influx.FIELD_STRESS_LEVEL, "stressLevel"))
        if level is None or level <= 0:
            continue
        if level <= 25:
            rest += 1
        elif level <= 50:
            low += 1
        elif level <= 75:
            medium += 1
        else:
            high += 1

    total = rest + low + medium + high
    if total == 0:
        return None

    return {
        "rest_min": round(rest * _STRESS_INTERVAL_MIN, 1),
        "low_min": round(low * _STRESS_INTERVAL_MIN, 1),
        "medium_min": round(medium * _STRESS_INTERVAL_MIN, 1),
        "high_min": round(high * _STRESS_INTERVAL_MIN, 1),
    }


def _aggregate_body_battery_intraday(rows: list[dict]) -> dict | None:
    """Compute body battery summary from intraday readings.

    ``at_wake`` is None because we cannot determine wake time from
    intraday data alone — DailyStats derives this from sleep tracking.
    """
    values: list[int] = []
    for row in rows:
        val = safe_int(pick(row, influx.FIELD_BODY_BATTERY_LEVEL, "BodyBatteryLevel"))
        if val is not None and val > 0:
            values.append(val)

    if not values:
        return None

    charged = 0
    drained = 0
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        if diff > 0:
            charged += diff
        elif diff < 0:
            drained += abs(diff)

    return {
        "at_wake": None,
        "high": max(values),
        "low": min(values),
        "charged": charged if charged > 0 else None,
        "drained": drained if drained > 0 else None,
    }


def _synthesize_today_row(
    today_date: str,
    stress_rows: list[dict],
    bb_rows: list[dict],
) -> dict | None:
    """Build a synthetic DailyStats-shaped dict for today from intraday data.

    Returns None if neither measurement has data.
    """
    stress = _aggregate_stress_intraday(stress_rows)
    bb = _aggregate_body_battery_intraday(bb_rows)

    if stress is None and bb is None:
        return None

    return {
        "date": today_date,
        "stress_high_min": stress["high_min"] if stress else None,
        "stress_medium_min": stress["medium_min"] if stress else None,
        "stress_low_min": stress["low_min"] if stress else None,
        "stress_rest_min": stress["rest_min"] if stress else None,
        "body_battery_at_wake": bb["at_wake"] if bb else None,
        "body_battery_high": bb["high"] if bb else None,
        "body_battery_low": bb["low"] if bb else None,
        "body_battery_drained": bb["drained"] if bb else None,
        "body_battery_charged": bb["charged"] if bb else None,
    }


async def get_stress_body_battery(days: int = 7) -> dict[str, Any]:
    """
    Return daily stress breakdown and body battery trend.

    Parameters:
        days – look-back window in days (7–30, default 7)

    Per-day fields:
        stress.*        – high_min, medium_min, low_min, rest_min, total_stress_min
        body_battery.*  – at_wake, high, low, drained, charged
    Summary:
        Period averages, plus trend direction for body battery and stress.
    """
    days = max(7, min(days, 30))

    try:
        daily_rows = await asyncio.to_thread(influx.query_daily_stats, days)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    # Synthesise today from intraday if DailyStats lacks it
    today_local = datetime.now(influx.QUERY_TZ).date().isoformat()
    has_today = any(row.get("date") == today_local for row in daily_rows)

    if not has_today:
        try:
            stress_intraday, bb_intraday = await asyncio.gather(
                asyncio.to_thread(influx.query_stress_intraday_today),
                asyncio.to_thread(influx.query_body_battery_intraday_today),
            )
        except Exception:
            stress_intraday, bb_intraday = [], []

        today_row = _synthesize_today_row(today_local, stress_intraday, bb_intraday)
        if today_row:
            daily_rows.insert(0, today_row)  # prepend (newest-first)

    if not daily_rows:
        return {
            "data_note": "No stress/body battery data found for this period",
            "days": [],
            "summary": None,
        }

    result_days = []
    stress_high_vals: list[float] = []
    stress_rest_vals: list[float] = []
    bb_wake_vals: list[float] = []

    for row in daily_rows:
        date = row.get("date")
        if not date:
            continue

        high = row.get("stress_high_min")
        med = row.get("stress_medium_min")
        low = row.get("stress_low_min")
        rest = row.get("stress_rest_min")

        non_none = [v for v in (high, med, low, rest) if v is not None]
        total_stress = round(sum(non_none), 1) if non_none else None

        bb_wake = row.get("body_battery_at_wake")
        bb_high = row.get("body_battery_high")
        bb_low = row.get("body_battery_low")
        bb_drained = row.get("body_battery_drained")
        bb_charged = row.get("body_battery_charged")

        result_days.append({
            "date": date,
            "source": "intraday" if date == today_local and not has_today else "daily_stats",
            "stress": {
                "high_min": high,
                "medium_min": med,
                "low_min": low,
                "rest_min": rest,
                "total_stress_min": total_stress,
            },
            "body_battery": {
                "at_wake": bb_wake,
                "high": bb_high,
                "low": bb_low,
                "drained": bb_drained,
                "charged": bb_charged,
            },
        })

        if high is not None:
            stress_high_vals.append(high)
        if rest is not None:
            stress_rest_vals.append(rest)
        if bb_wake is not None:
            bb_wake_vals.append(bb_wake)

    summary = {
        "days_with_data": len(result_days),
        "avg_stress_high_min": (
            round(sum(stress_high_vals) / len(stress_high_vals), 1)
            if stress_high_vals else None
        ),
        "avg_stress_rest_min": (
            round(sum(stress_rest_vals) / len(stress_rest_vals), 1)
            if stress_rest_vals else None
        ),
        "avg_body_battery_at_wake": (
            round(sum(bb_wake_vals) / len(bb_wake_vals))
            if bb_wake_vals else None
        ),
        "body_battery_trend": compute_trend(bb_wake_vals, higher_is_better=True),
        "stress_trend": compute_trend(stress_high_vals, higher_is_better=False),
    }

    return {"days": result_days, "summary": summary}


