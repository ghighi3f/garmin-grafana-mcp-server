"""
InfluxDB connection factory and all query functions.
All InfluxQL / Flux queries live here — never inline in tools.
"""

import os
import re
import logging
import threading
import atexit
from datetime import datetime, timezone
from typing import Any

from utils import pick, safe_float, safe_int

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection singletons (lazy, thread-safe)
# ---------------------------------------------------------------------------
_client_lock = threading.Lock()
_v1_singleton: Any = None
_v2_singleton: Any = None

# ---------------------------------------------------------------------------
# Config (read once from environment)
# ---------------------------------------------------------------------------
INFLUXDB_HOST = os.getenv("INFLUXDB_HOST", "localhost")
INFLUXDB_PORT = int(os.getenv("INFLUXDB_PORT", 8086))
INFLUXDB_DATABASE = os.getenv("INFLUXDB_DATABASE", "GarminStats")
INFLUXDB_USERNAME = os.getenv("INFLUXDB_USERNAME", "admin")
INFLUXDB_PASSWORD = os.getenv("INFLUXDB_PASSWORD", "adminpassword")
INFLUXDB_VERSION = int(os.getenv("INFLUXDB_VERSION", 1))
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "")           # v2 only
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")       # v2 only

# Measurement names — override if your garmin-grafana schema differs
MEASUREMENT_ACTIVITIES = os.getenv("MEASUREMENT_ACTIVITIES", "ActivitySummary")
MEASUREMENT_RESTING_HR = os.getenv("MEASUREMENT_RESTING_HR", "DailyStats")
MEASUREMENT_HRV = os.getenv("MEASUREMENT_HRV", "HRV_Intraday")

# Measurement names for recovery, detail, fitness, and zone tools
MEASUREMENT_DAILY_STATS = os.getenv("MEASUREMENT_DAILY_STATS", "DailyStats")
MEASUREMENT_SLEEP_SUMMARY = os.getenv("MEASUREMENT_SLEEP_SUMMARY", "SleepSummary")
MEASUREMENT_ACTIVITY_SESSION = os.getenv("MEASUREMENT_ACTIVITY_SESSION", "ActivitySession")
MEASUREMENT_ACTIVITY_LAP = os.getenv("MEASUREMENT_ACTIVITY_LAP", "ActivityLap")
MEASUREMENT_VO2_MAX = os.getenv("MEASUREMENT_VO2_MAX", "VO2_Max")
MEASUREMENT_RACE_PREDICTIONS = os.getenv("MEASUREMENT_RACE_PREDICTIONS", "RacePredictions")
MEASUREMENT_BODY_COMPOSITION = os.getenv("MEASUREMENT_BODY_COMPOSITION", "BodyComposition")

# Intraday measurements for live "today" data
MEASUREMENT_STRESS_INTRADAY = os.getenv("MEASUREMENT_STRESS_INTRADAY", "StressIntraday")
MEASUREMENT_BODY_BATTERY_INTRADAY = os.getenv("MEASUREMENT_BODY_BATTERY_INTRADAY", "BodyBatteryIntraday")
FIELD_STRESS_LEVEL = os.getenv("FIELD_STRESS_LEVEL", "stressLevel")
FIELD_BODY_BATTERY_LEVEL = os.getenv("FIELD_BODY_BATTERY_LEVEL", "BodyBatteryLevel")

# Field names within measurements — override if your schema uses different names
FIELD_RESTING_HR = os.getenv("FIELD_RESTING_HR", "restingHeartRate")
FIELD_HRV = os.getenv("FIELD_HRV", "hrvValue")
FIELD_VO2_MAX_RUNNING = os.getenv("FIELD_VO2_MAX_RUNNING", "VO2_max_value")
FIELD_VO2_MAX_CYCLING = os.getenv("FIELD_VO2_MAX_CYCLING", "VO2_max_value_cycling")
FIELD_RACE_5K = os.getenv("FIELD_RACE_5K", "time5K")
FIELD_RACE_10K = os.getenv("FIELD_RACE_10K", "time10K")
FIELD_RACE_HALF = os.getenv("FIELD_RACE_HALF", "timeHalfMarathon")
FIELD_RACE_MARATHON = os.getenv("FIELD_RACE_MARATHON", "timeMarathon")
FIELD_WEIGHT = os.getenv("FIELD_WEIGHT", "weight")
FIELD_HR_ZONE_1 = os.getenv("FIELD_HR_ZONE_1", "hrTimeInZone_1")
FIELD_HR_ZONE_2 = os.getenv("FIELD_HR_ZONE_2", "hrTimeInZone_2")
FIELD_HR_ZONE_3 = os.getenv("FIELD_HR_ZONE_3", "hrTimeInZone_3")
FIELD_HR_ZONE_4 = os.getenv("FIELD_HR_ZONE_4", "hrTimeInZone_4")
FIELD_HR_ZONE_5 = os.getenv("FIELD_HR_ZONE_5", "hrTimeInZone_5")

# Sports that use pace (min/km) instead of speed (km/h)
PACE_SPORTS: frozenset[str] = frozenset({
    "running", "run",
    "swimming", "swim",
    "walk", "hiking",
    "trail_running", "trail running",
})

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _v1_client():
    """Return the v1 client singleton (lazy, thread-safe)."""
    global _v1_singleton
    if _v1_singleton is None:
        with _client_lock:
            if _v1_singleton is None:
                from influxdb import InfluxDBClient  # type: ignore
                _v1_singleton = InfluxDBClient(
                    host=INFLUXDB_HOST,
                    port=INFLUXDB_PORT,
                    username=INFLUXDB_USERNAME,
                    password=INFLUXDB_PASSWORD,
                    database=INFLUXDB_DATABASE,
                )
    return _v1_singleton


def _v2_client():
    """Return the v2 client singleton (lazy, thread-safe)."""
    global _v2_singleton
    if _v2_singleton is None:
        with _client_lock:
            if _v2_singleton is None:
                from influxdb_client import InfluxDBClient  # type: ignore
                url = f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}"
                _v2_singleton = InfluxDBClient(url=url, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    return _v2_singleton


def _close_clients():
    """Close singleton clients on interpreter shutdown."""
    global _v1_singleton, _v2_singleton
    for client in (_v1_singleton, _v2_singleton):
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    _v1_singleton = None
    _v2_singleton = None


atexit.register(_close_clients)


def get_client():
    """Return the shared client singleton based on INFLUXDB_VERSION."""
    if INFLUXDB_VERSION == 2:
        return _v2_client()
    return _v1_client()


def sanitize_sport_type(sport_type: str | None) -> str | None:
    """
    Sanitize a user-provided sport_type for safe interpolation into
    InfluxQL / Flux queries.

    Returns None if the value is None, empty, or "all".
    Raises ValueError for characters that could enable query injection.
    """
    if sport_type is None or sport_type.strip() == "" or sport_type.strip().lower() == "all":
        return None
    cleaned = sport_type.strip().lower()
    if not re.match(r'^[a-z0-9 _-]+$', cleaned):
        raise ValueError(f"Invalid sport_type: {sport_type!r}")
    return cleaned


def normalise_activity(row: dict) -> dict:
    """
    Map raw InfluxDB field names (which vary across garmin-grafana versions)
    to the canonical schema expected by the MCP tools.
    Missing fields are silently set to None — never raised as errors.
    """
    sport = pick(row, "sport_type", "sport", "activityType", "activity_type") or "unknown"
    sport = sport.lower().strip()

    distance_raw = safe_float(pick(row, "distance", "total_distance"))
    # garmin-grafana stores distance in metres; convert to km
    distance_km = round(distance_raw / 1000.0, 3) if distance_raw and distance_raw > 500 else (
        round(distance_raw, 3) if distance_raw else None
    )

    duration_raw = safe_float(pick(
        row, "elapsedDuration", "duration", "elapsed_duration",
        "total_elapsed_time", "totalElapsedTime", "moving_duration", "movingDuration"
    ))
    # duration in seconds → minutes
    duration_minutes = round(duration_raw / 60.0, 2) if duration_raw and duration_raw > 300 else (
        round(duration_raw, 2) if duration_raw else None
    )

    avg_hr = safe_float(pick(row, "average_hr", "avg_hr", "averageHR", "average_heart_rate"))
    max_hr = safe_float(pick(row, "max_hr", "maxHR", "max_heart_rate"))
    if avg_hr: avg_hr = round(avg_hr, 1)
    if max_hr: max_hr = round(max_hr, 1)

    calories = safe_int(pick(row, "calories", "total_calories", "active_calories"))
    elev = safe_float(pick(row, "totalAscent", "elevation_gain", "total_ascent", "ascent", "elevation_gain_m"))
    if elev: elev = round(elev, 1)

    cadence = safe_float(pick(row, "average_cadence", "avg_cadence", "averageCadence"))
    if cadence: cadence = round(cadence, 1)

    np_val = safe_float(pick(row, "normalized_power", "normalisedPower", "np"))
    if np_val: np_val = round(np_val, 1)

    avg_speed_raw = safe_float(pick(
        row, "average_speed", "avg_speed", "averageSpeed", "enhanced_avg_speed"
    ))
    avg_speed_kmh = round(avg_speed_raw * 3.6, 2) if avg_speed_raw and avg_speed_raw < 100 else (
        round(avg_speed_raw, 2) if avg_speed_raw else None
    )

    # Pace (min/km) for run/swim/walk/hike; speed (km/h) for cycling/row/etc.
    if avg_speed_kmh and avg_speed_kmh > 0:
        avg_pace = round(60.0 / avg_speed_kmh, 2) if sport in PACE_SPORTS else None
        avg_speed_out = avg_speed_kmh if sport not in PACE_SPORTS else None
    else:
        avg_pace = None
        avg_speed_out = None

    # HR zones: seconds → minutes + percentage of total zone time
    _zone_fields = [FIELD_HR_ZONE_1, FIELD_HR_ZONE_2, FIELD_HR_ZONE_3, FIELD_HR_ZONE_4, FIELD_HR_ZONE_5]
    _zone_secs = [safe_float(pick(row, f)) or 0.0 for f in _zone_fields]
    _zone_mins = [round(s / 60.0, 1) for s in _zone_secs]
    _total_zone_min = sum(_zone_mins)

    def _zone_pct(val):
        if not val or _total_zone_min <= 0:
            return None
        return round(val / _total_zone_min * 100.0, 1)

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
    } if _total_zone_min > 0 else None

    activity_id = pick(row, "Activity_ID", "ActivityID", "activity_id", "activityId")

    ts = row.get("time") or row.get("timestamp")
    if ts and hasattr(ts, "isoformat"):
        ts = ts.isoformat()

    return {
        "activity_id": activity_id,
        "timestamp": ts,
        "sport_type": sport,
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "calories": calories,
        "avg_pace_min_per_km": avg_pace,
        "avg_speed_kmh": avg_speed_out,
        "elevation_gain_m": elev,
        "avg_cadence": cadence,
        "normalized_power": np_val,
        "hr_zones": hr_zones,
    }


def normalise_daily_stats(row: dict) -> dict:
    """Map raw DailyStats fields to canonical schema with friendly units."""
    ts = row.get("time") or row.get("_time")
    if ts and hasattr(ts, "isoformat"):
        ts = ts.isoformat()
    date_str = str(ts)[:10] if ts else None

    high_stress = safe_float(pick(row, "highStressDuration", "high_stress_duration"))
    med_stress = safe_float(pick(row, "mediumStressDuration", "medium_stress_duration"))
    low_stress = safe_float(pick(row, "lowStressDuration", "low_stress_duration"))
    rest_stress = safe_float(pick(row, "restStressDuration", "rest_stress_duration"))
    dist_raw = safe_float(pick(row, "totalDistanceMeters", "total_distance_meters"))

    return {
        "date": date_str,
        "resting_hr": safe_float(pick(row, "restingHeartRate", "resting_heart_rate")),
        "body_battery_at_wake": safe_int(pick(row, "bodyBatteryAtWakeTime", "body_battery_at_wake")),
        "body_battery_high": safe_int(pick(row, "bodyBatteryHighestValue", "body_battery_highest")),
        "body_battery_low": safe_int(pick(row, "bodyBatteryLowestValue", "body_battery_lowest")),
        "body_battery_drained": safe_int(pick(row, "bodyBatteryDrainedValue", "body_battery_drained")),
        "body_battery_charged": safe_int(pick(row, "bodyBatteryChargedValue", "body_battery_charged")),
        "total_steps": safe_int(pick(row, "totalSteps", "total_steps")),
        "total_distance_km": round(dist_raw / 1000.0, 2) if dist_raw else None,
        "active_calories": safe_int(pick(row, "activeKilocalories", "active_kilocalories")),
        "moderate_intensity_min": safe_float(pick(row, "moderateIntensityMinutes", "moderate_intensity_minutes")),
        "vigorous_intensity_min": safe_float(pick(row, "vigorousIntensityMinutes", "vigorous_intensity_minutes")),
        "stress_high_min": round(high_stress / 60.0, 1) if high_stress else None,
        "stress_medium_min": round(med_stress / 60.0, 1) if med_stress else None,
        "stress_low_min": round(low_stress / 60.0, 1) if low_stress else None,
        "stress_rest_min": round(rest_stress / 60.0, 1) if rest_stress else None,
        "avg_spo2": safe_float(pick(row, "averageSpo2", "average_spo2")),
        "lowest_spo2": safe_float(pick(row, "lowestSpo2", "lowest_spo2")),
        "max_hr": safe_float(pick(row, "maxHeartRate", "max_heart_rate")),
        "min_hr": safe_float(pick(row, "minHeartRate", "min_heart_rate")),
        "floors_ascended": safe_float(pick(row, "floorsAscended", "floors_ascended")),
    }


def normalise_sleep(row: dict) -> dict:
    """Map raw SleepSummary fields to canonical schema. Seconds -> hours."""
    ts = row.get("time") or row.get("_time")
    if ts and hasattr(ts, "isoformat"):
        ts = ts.isoformat()
    date_str = str(ts)[:10] if ts else None

    def _secs_to_hours(val):
        f = safe_float(val)
        return round(f / 3600.0, 2) if f else None

    return {
        "date": date_str,
        "sleep_score": safe_int(pick(row, "sleepScore", "sleep_score")),
        "total_sleep_hours": _secs_to_hours(pick(row, "sleepTimeSeconds", "sleep_time_seconds")),
        "deep_sleep_hours": _secs_to_hours(pick(row, "deepSleepSeconds", "deep_sleep_seconds")),
        "light_sleep_hours": _secs_to_hours(pick(row, "lightSleepSeconds", "light_sleep_seconds")),
        "rem_sleep_hours": _secs_to_hours(pick(row, "remSleepSeconds", "rem_sleep_seconds")),
        "awake_hours": _secs_to_hours(pick(row, "awakeSleepSeconds", "awake_sleep_seconds")),
        "awake_count": safe_int(pick(row, "awakeCount", "awake_count")),
        "avg_overnight_hrv": safe_float(pick(row, "avgOvernightHrv", "avg_overnight_hrv")),
        "avg_sleep_stress": safe_float(pick(row, "avgSleepStress", "avg_sleep_stress")),
        "body_battery_change": safe_int(pick(row, "bodyBatteryChange", "body_battery_change")),
        "resting_hr": safe_float(pick(row, "restingHeartRate", "resting_heart_rate")),
        "avg_spo2": safe_float(pick(row, "averageSpO2Value", "average_spo2_value")),
        "lowest_spo2": safe_float(pick(row, "lowestSpO2Value", "lowest_spo2_value")),
        "avg_respiration": safe_float(pick(row, "averageRespirationValue", "average_respiration_value")),
        "restless_count": safe_int(pick(row, "restlessMomentsCount", "restless_moments_count")),
    }


def normalise_lap(row: dict, sport: str = "unknown") -> dict:
    """Map raw ActivityLap fields to canonical schema."""
    index = safe_int(pick(row, "Index", "index", "lap_index"))

    dist_raw = safe_float(pick(row, "Distance", "distance"))
    dist_km = round(dist_raw / 1000.0, 3) if dist_raw and dist_raw > 500 else (
        round(dist_raw, 3) if dist_raw else None
    )

    elapsed_raw = safe_float(pick(row, "Elapsed_Time", "elapsed_time", "total_elapsed_time"))
    # Lap durations are typically < 300s, so use seconds-to-minutes without heuristic
    elapsed_min = round(elapsed_raw / 60.0, 2) if elapsed_raw else None

    avg_speed_raw = safe_float(pick(row, "Avg_Speed", "avg_speed"))
    avg_speed_kmh = round(avg_speed_raw * 3.6, 2) if avg_speed_raw and avg_speed_raw < 100 else (
        round(avg_speed_raw, 2) if avg_speed_raw else None
    )
    max_speed_raw = safe_float(pick(row, "Max_Speed", "max_speed"))
    max_speed_kmh = round(max_speed_raw * 3.6, 2) if max_speed_raw and max_speed_raw < 100 else (
        round(max_speed_raw, 2) if max_speed_raw else None
    )

    avg_pace = round(60.0 / avg_speed_kmh, 2) if avg_speed_kmh and avg_speed_kmh > 0 and sport in PACE_SPORTS else None

    return {
        "index": index,
        "distance_km": dist_km,
        "elapsed_time_minutes": elapsed_min,
        "avg_hr": safe_float(pick(row, "Avg_HR", "avg_hr")),
        "max_hr": safe_float(pick(row, "Max_HR", "max_hr")),
        "avg_speed_kmh": avg_speed_kmh if sport not in PACE_SPORTS else None,
        "max_speed_kmh": max_speed_kmh if sport not in PACE_SPORTS else None,
        "avg_pace_min_per_km": avg_pace,
        "calories": safe_int(pick(row, "Calories", "calories")),
        "avg_cadence": safe_float(pick(row, "Avg_Cadence", "avg_cadence")),
        "avg_power": safe_float(pick(row, "Avg_Power", "avg_power")),
        "avg_temperature_c": safe_float(pick(row, "Avg_Temperature", "avg_temperature")),
    }


# ---------------------------------------------------------------------------
# InfluxQL queries (v1)
# ---------------------------------------------------------------------------

def _v1_query(q: str) -> list[dict]:
    client = _v1_client()
    result = client.query(q)
    return list(result.get_points())


def _v1_show_measurements() -> list[str]:
    client = _v1_client()
    result = client.query("SHOW MEASUREMENTS")
    return [p["name"] for p in result.get_points()]


# ---------------------------------------------------------------------------
# Flux queries (v2)
# ---------------------------------------------------------------------------

def _v2_query(q: str) -> list[dict]:
    client = _v2_client()
    qapi = client.query_api()
    tables = qapi.query(q)
    rows = []
    for table in tables:
        for record in table.records:
            rows.append(record.values)
    return rows


def _v2_show_measurements() -> list[str]:
    q = f'''
    import "influxdata/influxdb/schema"
    schema.measurements(bucket: "{INFLUXDB_DATABASE}")
    '''
    client = _v2_client()
    qapi = client.query_api()
    tables = qapi.query(q)
    names = []
    for table in tables:
        for record in table.records:
            names.append(record.get_value())
    return names


# ---------------------------------------------------------------------------
# Public API used by tools
# ---------------------------------------------------------------------------

def get_measurements() -> list[str]:
    """Return all measurement names in the database."""
    try:
        if INFLUXDB_VERSION == 2:
            return _v2_show_measurements()
        return _v1_show_measurements()
    except Exception as exc:
        logger.warning("Could not list measurements: %s", exc)
        return []


def ping() -> bool:
    """Return True if InfluxDB responds."""
    try:
        if INFLUXDB_VERSION == 2:
            _v2_client().health()
        else:
            _v1_client().ping()
        return True
    except Exception:
        return False


def query_last_activity() -> dict | None:
    """
    Return the single most-recent activity row, normalised.
    Returns None if the measurement is empty or unreachable.
    """
    raw_rows: list[dict] = []

    if INFLUXDB_VERSION == 2:
        q = f'''
        from(bucket: "{INFLUXDB_DATABASE}")
          |> range(start: -365d)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITIES}")
          |> last()
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        try:
            raw_rows = _v2_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    else:
        # Fetch a small window so we can skip "No Activity" sentinel rows
        q = (
            f'SELECT * FROM "{MEASUREMENT_ACTIVITIES}" '
            f'ORDER BY time DESC LIMIT 5'
        )
        try:
            raw_rows = _v1_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc

    if not raw_rows:
        return None
    for row in raw_rows:
        normalised = normalise_activity(row)
        if normalised.get("sport_type") != "no activity":
            return normalised
    return None


def query_recent_activities(days: int, sport_type: str | None, limit: int) -> list[dict]:
    """
    Return activity rows for the last `days` days, optionally filtered
    by sport_type, newest-first, capped at `limit`.
    """
    try:
        sport_type = sanitize_sport_type(sport_type)
    except ValueError:
        sport_type = None  # invalid input → no filter

    raw_rows: list[dict] = []

    if INFLUXDB_VERSION == 2:
        sport_filter = ""
        if sport_type:
            sport_filter = (
                f'|> filter(fn: (r) => r["sport_type"] =~ /.*{sport_type}.*/i'
                f' or r["sport"] =~ /.*{sport_type}.*/i'
                f' or r["activityType"] =~ /.*{sport_type}.*/i)'
            )
        q = f'''
        from(bucket: "{INFLUXDB_DATABASE}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITIES}")
          {sport_filter}
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: {limit})
        '''
        try:
            raw_rows = _v2_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    else:
        sport_clause = ""
        if sport_type:
            # Regex match: catches sub-sports (e.g. "cycling" matches
            # "road_biking" won't, but "cycling" matches "indoor_cycling").
            sport_clause = (
                f" AND (\"sport_type\" =~ /.*{sport_type}.*/"
                f" OR \"sport\" =~ /.*{sport_type}.*/"
                f" OR \"activityType\" =~ /.*{sport_type}.*/)"
            )
        q = (
            f'SELECT * FROM "{MEASUREMENT_ACTIVITIES}" '
            f"WHERE time >= now() - {days}d"
            f"{sport_clause} "
            f"ORDER BY time DESC LIMIT {limit}"
        )
        try:
            raw_rows = _v1_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc

    return [
        a for a in (normalise_activity(r) for r in raw_rows)
        if a.get("sport_type") != "no activity"
    ]


def query_resting_hr_weekly(weeks: int) -> list[dict]:
    """
    Return weekly-average resting HR rows for the last `weeks` weeks.
    Returns [] silently if the measurement doesn't exist.
    """
    days = weeks * 7

    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -{days}d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_RESTING_HR}")
              |> aggregateWindow(every: 1w, fn: mean, createEmpty: false)
              |> yield(name: "mean")
            '''
            return _v2_query(q)
        else:
            q = (
                f'SELECT MEAN("{FIELD_RESTING_HR}") AS avg_rhr '
                f'FROM "{MEASUREMENT_RESTING_HR}" '
                f'WHERE time >= now() - {days}d '
                f'GROUP BY time(1w) fill(none)'
            )
            return _v1_query(q)
    except Exception as exc:
        logger.debug("Resting HR query failed (non-fatal): %s", exc)
        return []


def query_hrv_weekly(weeks: int) -> list[dict]:
    """
    Return weekly-average HRV rows.
    Returns [] silently if the measurement doesn't exist.
    """
    days = weeks * 7

    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -{days}d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_HRV}")
              |> aggregateWindow(every: 1w, fn: mean, createEmpty: false)
              |> yield(name: "mean")
            '''
            return _v2_query(q)
        else:
            q = (
                f'SELECT MEAN("{FIELD_HRV}") AS avg_hrv '
                f'FROM "{MEASUREMENT_HRV}" '
                f'WHERE time >= now() - {days}d '
                f'GROUP BY time(1w) fill(none)'
            )
            return _v1_query(q)
    except Exception as exc:
        logger.debug("HRV query failed (non-fatal): %s", exc)
        return []


# ---------------------------------------------------------------------------
# New query functions for recovery, detail, fitness, and zone tools
# ---------------------------------------------------------------------------

def query_daily_stats(days: int) -> list[dict]:
    """Return normalised DailyStats rows for the last `days` days."""
    if INFLUXDB_VERSION == 2:
        q = f'''
        from(bucket: "{INFLUXDB_DATABASE}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_DAILY_STATS}")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"], desc: true)
        '''
        try:
            raw = _v2_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    else:
        q = (
            f'SELECT * FROM "{MEASUREMENT_DAILY_STATS}" '
            f'WHERE time >= now() - {days}d '
            f'ORDER BY time DESC'
        )
        try:
            raw = _v1_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    return [normalise_daily_stats(r) for r in _dedup_rows(raw)]


def query_stress_intraday_today() -> list[dict]:
    """Return raw StressIntraday readings from UTC midnight today to now.

    Returns [] silently if the measurement doesn't exist or has no data.
    """
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: {today_start})
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_STRESS_INTRADAY}")
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
              |> sort(columns: ["_time"], desc: false)
            '''
            return _dedup_rows(_v2_query(q))
        else:
            q = (
                f'SELECT * FROM "{MEASUREMENT_STRESS_INTRADAY}" '
                f"WHERE time >= '{today_start}' "
                f"ORDER BY time ASC"
            )
            return _dedup_rows(_v1_query(q))
    except Exception as exc:
        logger.debug("StressIntraday query failed (non-fatal): %s", exc)
        return []


def query_body_battery_intraday_today() -> list[dict]:
    """Return raw BodyBatteryIntraday readings from UTC midnight today to now.

    Returns [] silently if the measurement doesn't exist or has no data.
    """
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: {today_start})
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_BODY_BATTERY_INTRADAY}")
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
              |> sort(columns: ["_time"], desc: false)
            '''
            return _dedup_rows(_v2_query(q))
        else:
            q = (
                f'SELECT * FROM "{MEASUREMENT_BODY_BATTERY_INTRADAY}" '
                f"WHERE time >= '{today_start}' "
                f"ORDER BY time ASC"
            )
            return _dedup_rows(_v1_query(q))
    except Exception as exc:
        logger.debug("BodyBatteryIntraday query failed (non-fatal): %s", exc)
        return []


def query_sleep_summary(days: int) -> list[dict]:
    """Return normalised SleepSummary rows for the last `days` days."""
    if INFLUXDB_VERSION == 2:
        q = f'''
        from(bucket: "{INFLUXDB_DATABASE}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_SLEEP_SUMMARY}")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"], desc: true)
        '''
        try:
            raw = _v2_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    else:
        q = (
            f'SELECT * FROM "{MEASUREMENT_SLEEP_SUMMARY}" '
            f'WHERE time >= now() - {days}d '
            f'ORDER BY time DESC'
        )
        try:
            raw = _v1_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    return [normalise_sleep(r) for r in raw]


def _non_null_count(row: dict) -> int:
    """Count non-None, non-empty values (ignoring tag/meta keys)."""
    _SKIP = {"time", "_time", "Device", "Database_Name", "ActivitySelector", "ActivityID"}
    return sum(1 for k, v in row.items() if k not in _SKIP and v is not None and v != "")


def _dedup_rows(rows: list[dict], key: str = "time") -> list[dict]:
    """
    Remove duplicate rows caused by garmin-grafana writing one row per
    device (e.g. Edge 540 + Forerunner 165).  When duplicates exist,
    keeps the row with the most populated fields.
    """
    groups: dict[Any, list[dict]] = {}
    for r in rows:
        k = r.get(key)
        groups.setdefault(k, []).append(r)
    out: list[dict] = []
    for group in groups.values():
        best = max(group, key=_non_null_count) if len(group) > 1 else group[0]
        out.append(best)
    return out


def _dedup_laps(rows: list[dict]) -> list[dict]:
    """
    Remove duplicate lap rows using (time, Index) as composite key.
    Keeps the row with the most populated fields.
    """
    groups: dict[Any, list[dict]] = {}
    for r in rows:
        k = (r.get("time") or r.get("_time"), r.get("Index"))
        groups.setdefault(k, []).append(r)
    out: list[dict] = []
    for group in groups.values():
        best = max(group, key=_non_null_count) if len(group) > 1 else group[0]
        out.append(best)
    return out


def query_activity_summary_by_id(activity_id: str) -> list[dict]:
    """
    Return raw ActivitySummary rows for a specific activity ID.
    May include sentinel rows — caller should filter activityType='No Activity'.
    """
    if INFLUXDB_VERSION == 2:
        q = f'''
        from(bucket: "{INFLUXDB_DATABASE}")
          |> range(start: -365d)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITIES}")
          |> filter(fn: (r) => r["ActivityID"] == "{activity_id}")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        try:
            return _dedup_rows(_v2_query(q))
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    else:
        q = (
            f'SELECT * FROM "{MEASUREMENT_ACTIVITIES}" '
            f"WHERE \"ActivityID\" = '{activity_id}'"
        )
        try:
            return _dedup_rows(_v1_query(q))
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc


def query_activity_session_by_id(activity_id: str) -> list[dict]:
    """
    Return raw ActivitySession rows for a specific activity ID.
    Returns [] silently if measurement doesn't exist.
    """
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -365d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITY_SESSION}")
              |> filter(fn: (r) => r["ActivityID"] == "{activity_id}")
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
            '''
            return _dedup_rows(_v2_query(q))
        else:
            q = (
                f'SELECT * FROM "{MEASUREMENT_ACTIVITY_SESSION}" '
                f"WHERE \"ActivityID\" = '{activity_id}'"
            )
            return _dedup_rows(_v1_query(q))
    except Exception as exc:
        logger.debug("ActivitySession query failed (non-fatal): %s", exc)
        return []


def query_activity_laps_by_id(activity_id: str) -> list[dict]:
    """
    Return raw ActivityLap rows for a specific activity ID, ordered by time ASC.
    Returns [] silently if measurement doesn't exist.
    """
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -365d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITY_LAP}")
              |> filter(fn: (r) => r["ActivityID"] == "{activity_id}")
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
              |> sort(columns: ["_time"], desc: false)
            '''
            return _dedup_laps(_v2_query(q))
        else:
            q = (
                f'SELECT * FROM "{MEASUREMENT_ACTIVITY_LAP}" '
                f"WHERE \"ActivityID\" = '{activity_id}' "
                f"ORDER BY time ASC"
            )
            return _dedup_laps(_v1_query(q))
    except Exception as exc:
        logger.debug("ActivityLap query failed (non-fatal): %s", exc)
        return []


def query_vo2max_weekly(weeks: int) -> list[dict]:
    """Return weekly-sampled VO2max values. Returns [] silently on failure."""
    days = weeks * 7
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -{days}d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_VO2_MAX}")
              |> aggregateWindow(every: 1w, fn: last, createEmpty: false)
              |> yield(name: "last")
            '''
            return _v2_query(q)
        else:
            q = (
                f'SELECT LAST("{FIELD_VO2_MAX_RUNNING}") AS vo2max_running, '
                f'LAST("{FIELD_VO2_MAX_CYCLING}") AS vo2max_cycling '
                f'FROM "{MEASUREMENT_VO2_MAX}" '
                f'WHERE time >= now() - {days}d '
                f'GROUP BY time(1w) fill(none)'
            )
            return _v1_query(q)
    except Exception as exc:
        logger.debug("VO2max query failed (non-fatal): %s", exc)
        return []


def query_race_predictions_weekly(weeks: int) -> list[dict]:
    """Return weekly-sampled race prediction times. Returns [] silently on failure."""
    days = weeks * 7
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -{days}d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_RACE_PREDICTIONS}")
              |> aggregateWindow(every: 1w, fn: last, createEmpty: false)
              |> yield(name: "last")
            '''
            return _v2_query(q)
        else:
            q = (
                f'SELECT LAST("{FIELD_RACE_5K}") AS time_5k, '
                f'LAST("{FIELD_RACE_10K}") AS time_10k, '
                f'LAST("{FIELD_RACE_HALF}") AS time_half, '
                f'LAST("{FIELD_RACE_MARATHON}") AS time_marathon '
                f'FROM "{MEASUREMENT_RACE_PREDICTIONS}" '
                f'WHERE time >= now() - {days}d '
                f'GROUP BY time(1w) fill(none)'
            )
            return _v1_query(q)
    except Exception as exc:
        logger.debug("Race predictions query failed (non-fatal): %s", exc)
        return []


def query_weight_weekly(weeks: int) -> list[dict]:
    """Return weekly-sampled weight values. Returns [] silently on failure."""
    days = weeks * 7
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -{days}d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_BODY_COMPOSITION}")
              |> aggregateWindow(every: 1w, fn: last, createEmpty: false)
              |> yield(name: "last")
            '''
            return _v2_query(q)
        else:
            q = (
                f'SELECT LAST("{FIELD_WEIGHT}") AS weight '
                f'FROM "{MEASUREMENT_BODY_COMPOSITION}" '
                f'WHERE time >= now() - {days}d '
                f'GROUP BY time(1w) fill(none)'
            )
            return _v1_query(q)
    except Exception as exc:
        logger.debug("Weight query failed (non-fatal): %s", exc)
        return []


def query_field_keys(measurement: str) -> list[dict[str, str]]:
    """
    Return field keys and their types for a given measurement.
    Each entry: {"field": "<name>", "type": "<type>"}.
    Returns [] on failure.
    """
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            import "influxdata/influxdb/schema"
            schema.measurementFieldKeys(
                bucket: "{INFLUXDB_DATABASE}",
                measurement: "{measurement}",
            )
            '''
            tables = _v2_client().query_api().query(q)
            fields = []
            for table in tables:
                for record in table.records:
                    fields.append({
                        "field": record.get_value(),
                        "type": record.values.get("type", "unknown"),
                    })
            return fields
        else:
            result = _v1_client().query(
                f'SHOW FIELD KEYS FROM "{measurement}"'
            )
            return [
                {"field": p["fieldKey"], "type": p.get("fieldType", "unknown")}
                for p in result.get_points()
            ]
    except Exception as exc:
        logger.warning("Could not get field keys for %s: %s", measurement, exc)
        return []


def query_tag_keys(measurement: str) -> list[str]:
    """
    Return tag key names for a given measurement.
    Returns [] on failure.
    """
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            import "influxdata/influxdb/schema"
            schema.measurementTagKeys(
                bucket: "{INFLUXDB_DATABASE}",
                measurement: "{measurement}",
            )
            '''
            tables = _v2_client().query_api().query(q)
            tags = []
            for table in tables:
                for record in table.records:
                    val = record.get_value()
                    if not val.startswith("_"):
                        tags.append(val)
            return tags
        else:
            result = _v1_client().query(
                f'SHOW TAG KEYS FROM "{measurement}"'
            )
            return [p["tagKey"] for p in result.get_points()]
    except Exception as exc:
        logger.warning("Could not get tag keys for %s: %s", measurement, exc)
        return []


def query_activity_hr_zones(days: int, limit: int) -> list[dict]:
    """
    Return raw activity rows with HR zone fields for aggregation.
    Sport filtering is done in Python for consistency with field-name flexibility.
    """
    if INFLUXDB_VERSION == 2:
        q = f'''
        from(bucket: "{INFLUXDB_DATABASE}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITIES}")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: {limit})
        '''
        try:
            return _v2_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    else:
        q = (
            f'SELECT * FROM "{MEASUREMENT_ACTIVITIES}" '
            f'WHERE time >= now() - {days}d '
            f'ORDER BY time DESC LIMIT {limit}'
        )
        try:
            return _v1_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
