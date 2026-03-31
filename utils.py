"""Shared helpers used across influx.py and tools."""

from __future__ import annotations

import datetime


def pick(row: dict, *keys):
    """Return the first non-None value from *keys* in *row*."""
    for k in keys:
        v = row.get(k)
        if v is not None:
            return v
    return None


def safe_float(val, default=None):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def safe_int(val, default=None):
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def iso_week_label(ts) -> str | None:
    """Convert a timestamp (string or datetime) to 'YYYY-Www' label."""
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        ts = ts.isoformat()
    s = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    except (ValueError, AttributeError):
        return None


def week_start_from_label(label: str) -> str:
    """Return the Monday date string for a given 'YYYY-Www' label."""
    try:
        year, week_part = label.split("-W")
        monday = datetime.datetime.fromisocalendar(int(year), int(week_part), 1)
        return monday.date().isoformat()
    except Exception:
        return label


def compute_trend(
    values: list[float],
    higher_is_better: bool,
    threshold_pct: float = 5.0,
) -> str | None:
    """Compare average of newer half vs older half of values.

    Values are ordered newest-first (from query_daily_stats).
    Requires >= 4 data points, else returns None.
    """
    if len(values) < 4:
        return None
    mid = len(values) // 2
    newer_avg = sum(values[:mid]) / mid
    older_avg = sum(values[mid:]) / (len(values) - mid)
    if older_avg == 0:
        return "stable"
    diff_pct = (newer_avg - older_avg) / older_avg * 100
    if higher_is_better:
        if diff_pct > threshold_pct:
            return "improving"
        elif diff_pct < -threshold_pct:
            return "declining"
    else:
        if diff_pct < -threshold_pct:
            return "improving"
        elif diff_pct > threshold_pct:
            return "worsening"
    return "stable"
