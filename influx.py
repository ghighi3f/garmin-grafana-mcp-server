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
MEASUREMENT_ACTIVITY_GPS = os.getenv("MEASUREMENT_ACTIVITY_GPS", "ActivityGPS")
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

# Training Status measurement fields (garmin-grafana v0.4.0+)
MEASUREMENT_TRAINING_STATUS    = os.getenv("MEASUREMENT_TRAINING_STATUS",    "TrainingStatus")
MEASUREMENT_TRAINING_READINESS = os.getenv("MEASUREMENT_TRAINING_READINESS", "TrainingReadiness")
FIELD_TRAINING_STATUS_CODE     = os.getenv("FIELD_TRAINING_STATUS_CODE",     "trainingStatus")
FIELD_TRAINING_STATUS_LABEL    = os.getenv("FIELD_TRAINING_STATUS_LABEL",    "trainingStatusFeedbackPhrase")
FIELD_ACUTE_LOAD               = os.getenv("FIELD_ACUTE_LOAD",               "dailyTrainingLoadAcute")
FIELD_CHRONIC_LOAD             = os.getenv("FIELD_CHRONIC_LOAD",             "dailyTrainingLoadChronic")
FIELD_LOAD_BALANCE_RATIO       = os.getenv("FIELD_LOAD_BALANCE_RATIO",       "dailyAcuteChronicWorkloadRatio")
FIELD_ACWR_PERCENT             = os.getenv("FIELD_ACWR_PERCENT",             "acwrPercent")
FIELD_FITNESS_TREND            = os.getenv("FIELD_FITNESS_TREND",            "fitnessTrend")
FIELD_READINESS_SCORE          = os.getenv("FIELD_READINESS_SCORE",          "trainingReadinessScore")
FIELD_READINESS_LABEL          = os.getenv("FIELD_READINESS_LABEL",          "trainingReadinessDescription")

# Sleep physiology (SleepIntraday measurement)
MEASUREMENT_SLEEP_INTRADAY = os.getenv("MEASUREMENT_SLEEP_INTRADAY", "SleepIntraday")
FIELD_SLEEP_HR             = os.getenv("FIELD_SLEEP_HR",             "heartRate")
FIELD_SLEEP_HRV            = os.getenv("FIELD_SLEEP_HRV",           "hrvData")
FIELD_SLEEP_RESPIRATION    = os.getenv("FIELD_SLEEP_RESPIRATION",    "respirationValue")
FIELD_SLEEP_SPO2           = os.getenv("FIELD_SLEEP_SPO2",          "spo2Reading")
FIELD_SLEEP_STRESS         = os.getenv("FIELD_SLEEP_STRESS",        "stressValue")
FIELD_SLEEP_BODY_BATTERY   = os.getenv("FIELD_SLEEP_BODY_BATTERY",  "bodyBattery")
FIELD_SLEEP_RESTLESS       = os.getenv("FIELD_SLEEP_RESTLESS",      "sleepRestlessValue")

# Activity load (fields in ActivitySummary)
FIELD_TRAINING_LOAD  = os.getenv("FIELD_TRAINING_LOAD",  "activityTrainingLoad")
FIELD_AEROBIC_TE     = os.getenv("FIELD_AEROBIC_TE",     "aerobicTrainingEffect")
FIELD_ANAEROBIC_TE   = os.getenv("FIELD_ANAEROBIC_TE",   "anaerobicTrainingEffect")

# Daily energy balance (fields in DailyStats)
FIELD_SEDENTARY_SECONDS      = os.getenv("FIELD_SEDENTARY_SECONDS",      "sedentarySeconds")
FIELD_ACTIVE_SECONDS         = os.getenv("FIELD_ACTIVE_SECONDS",         "activeSeconds")
FIELD_HIGHLY_ACTIVE_SECONDS  = os.getenv("FIELD_HIGHLY_ACTIVE_SECONDS",  "highlyActiveSeconds")
FIELD_SLEEPING_SECONDS       = os.getenv("FIELD_SLEEPING_SECONDS",       "sleepingSeconds")
FIELD_BMR_KCAL               = os.getenv("FIELD_BMR_KCAL",              "bmrKilocalories")
FIELD_BB_DURING_SLEEP        = os.getenv("FIELD_BB_DURING_SLEEP",       "bodyBatteryDuringSleep")
FIELD_ACTIVITY_STRESS_DUR    = os.getenv("FIELD_ACTIVITY_STRESS_DUR",   "activityStressDuration")
FIELD_ACTIVITY_STRESS_PCT    = os.getenv("FIELD_ACTIVITY_STRESS_PCT",   "activityStressPercentage")

# Fitness age (FitnessAge measurement)
MEASUREMENT_FITNESS_AGE       = os.getenv("MEASUREMENT_FITNESS_AGE",       "FitnessAge")
FIELD_FITNESS_AGE             = os.getenv("FIELD_FITNESS_AGE",             "fitnessAge")
FIELD_CHRONOLOGICAL_AGE       = os.getenv("FIELD_CHRONOLOGICAL_AGE",       "chronologicalAge")
FIELD_ACHIEVABLE_FITNESS_AGE  = os.getenv("FIELD_ACHIEVABLE_FITNESS_AGE",  "achievableFitnessAge")

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
    # garmin-grafana always stores distance in metres
    distance_km = round(distance_raw / 1000.0, 3) if distance_raw else None

    duration_raw = safe_float(pick(
        row, "elapsedDuration", "duration", "elapsed_duration",
        "total_elapsed_time", "totalElapsedTime", "moving_duration", "movingDuration"
    ))
    # garmin-grafana always stores duration in seconds
    duration_minutes = round(duration_raw / 60.0, 2) if duration_raw else None

    moving_raw = safe_float(pick(row, "movingDuration", "moving_duration"))
    moving_minutes = round(moving_raw / 60.0, 2) if moving_raw else None

    avg_hr = safe_float(pick(row, "average_hr", "avg_hr", "averageHR", "average_heart_rate"))
    max_hr = safe_float(pick(row, "max_hr", "maxHR", "max_heart_rate"))
    if avg_hr: avg_hr = round(avg_hr, 1)
    if max_hr: max_hr = round(max_hr, 1)

    calories = safe_int(pick(row, "calories", "total_calories", "active_calories"))
    elev = safe_float(pick(row, "totalAscent", "elevation_gain", "total_ascent", "ascent", "elevation_gain_m"))
    if elev: elev = round(elev, 1)

    cadence = safe_float(pick(row, "average_cadence", "avg_cadence", "averageCadence"))
    if cadence: cadence = round(cadence, 1)

    avg_power_val = safe_float(pick(row, "averagePower", "avg_power", "average_power"))
    if avg_power_val: avg_power_val = round(avg_power_val, 1)

    avg_speed_raw = safe_float(pick(
        row, "average_speed", "avg_speed", "averageSpeed", "enhanced_avg_speed"
    ))
    avg_speed_kmh = round(avg_speed_raw * 3.6, 2) if avg_speed_raw and avg_speed_raw < 100 else (
        round(avg_speed_raw, 2) if avg_speed_raw else None
    )

    max_speed_raw = safe_float(pick(row, "maxSpeed", "max_speed", "enhanced_max_speed"))
    max_speed_kmh = round(max_speed_raw * 3.6, 2) if max_speed_raw and max_speed_raw < 100 else (
        round(max_speed_raw, 2) if max_speed_raw else None
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
    activity_name = pick(row, "activityName", "activity_name", "name")

    ts = row.get("time") or row.get("timestamp")
    if ts and hasattr(ts, "isoformat"):
        ts = ts.isoformat()

    return {
        "activity_id": activity_id,
        "timestamp": ts,
        "activity_name": activity_name,
        "sport_type": sport,
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "moving_duration_minutes": moving_minutes,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "calories": calories,
        "avg_pace_min_per_km": avg_pace,
        "avg_speed_kmh": avg_speed_out,
        "max_speed_kmh": max_speed_kmh,
        "elevation_gain_m": elev,
        "avg_cadence": cadence,
        "avg_power": avg_power_val,
        "max_power": None,  # backfilled from ActivityGPS by query_all_activities()
        "training_load": safe_float(pick(row, FIELD_TRAINING_LOAD, "activityTrainingLoad", "training_load")),
        "aerobic_training_effect": safe_float(pick(row, FIELD_AEROBIC_TE, "aerobicTrainingEffect", "aerobic_te")),
        "anaerobic_training_effect": safe_float(pick(row, FIELD_ANAEROBIC_TE, "anaerobicTrainingEffect", "anaerobic_te")),
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

    def _secs_to_hours(val):
        f = safe_float(val)
        return round(f / 3600.0, 2) if f else None

    def _secs_to_mins(val):
        f = safe_float(val)
        return round(f / 60.0, 1) if f else None

    return {
        "date": date_str,
        "resting_hr": safe_float(pick(row, "restingHeartRate", "resting_heart_rate")),
        "body_battery_at_wake": safe_int(pick(row, "bodyBatteryAtWakeTime", "body_battery_at_wake")),
        "body_battery_high": safe_int(pick(row, "bodyBatteryHighestValue", "body_battery_highest")),
        "body_battery_low": safe_int(pick(row, "bodyBatteryLowestValue", "body_battery_lowest")),
        "body_battery_drained": safe_int(pick(row, "bodyBatteryDrainedValue", "body_battery_drained")),
        "body_battery_charged": safe_int(pick(row, "bodyBatteryChargedValue", "body_battery_charged")),
        "body_battery_during_sleep": safe_int(pick(row, FIELD_BB_DURING_SLEEP, "bodyBatteryDuringSleep")),
        "total_steps": safe_int(pick(row, "totalSteps", "total_steps")),
        "total_distance_km": round(dist_raw / 1000.0, 2) if dist_raw else None,
        "active_calories": safe_int(pick(row, "activeKilocalories", "active_kilocalories")),
        "bmr_kcal": safe_int(pick(row, FIELD_BMR_KCAL, "bmrKilocalories")),
        "moderate_intensity_min": safe_float(pick(row, "moderateIntensityMinutes", "moderate_intensity_minutes")),
        "vigorous_intensity_min": safe_float(pick(row, "vigorousIntensityMinutes", "vigorous_intensity_minutes")),
        "stress_high_min": round(high_stress / 60.0, 1) if high_stress else None,
        "stress_medium_min": round(med_stress / 60.0, 1) if med_stress else None,
        "stress_low_min": round(low_stress / 60.0, 1) if low_stress else None,
        "stress_rest_min": round(rest_stress / 60.0, 1) if rest_stress else None,
        "activity_stress_min": _secs_to_mins(pick(row, FIELD_ACTIVITY_STRESS_DUR, "activityStressDuration")),
        "activity_stress_pct": safe_float(pick(row, FIELD_ACTIVITY_STRESS_PCT, "activityStressPercentage")),
        "total_stress_min": _secs_to_mins(pick(row, "stressDuration", "stress_duration")),
        "stress_pct": safe_float(pick(row, "stressPercentage", "stress_percentage")),
        "uncategorized_stress_min": _secs_to_mins(pick(row, "uncategorizedStressDuration", "uncategorized_stress_duration")),
        "sedentary_hours": _secs_to_hours(pick(row, FIELD_SEDENTARY_SECONDS, "sedentarySeconds")),
        "active_hours": _secs_to_hours(pick(row, FIELD_ACTIVE_SECONDS, "activeSeconds")),
        "highly_active_hours": _secs_to_hours(pick(row, FIELD_HIGHLY_ACTIVE_SECONDS, "highlyActiveSeconds")),
        "sleeping_hours": _secs_to_hours(pick(row, FIELD_SLEEPING_SECONDS, "sleepingSeconds")),
        "avg_spo2": safe_float(pick(row, "averageSpo2", "average_spo2")),
        "lowest_spo2": safe_float(pick(row, "lowestSpo2", "lowest_spo2")),
        "max_hr": safe_float(pick(row, "maxHeartRate", "max_heart_rate")),
        "min_hr": safe_float(pick(row, "minHeartRate", "min_heart_rate")),
        "floors_ascended": safe_float(pick(row, "floorsAscended", "floors_ascended")),
        "floors_descended": safe_float(pick(row, "floorsDescended", "floors_descended")),
        "floors_ascended_meters": safe_float(pick(row, "floorsAscendedInMeters", "floors_ascended_in_meters")),
        "floors_descended_meters": safe_float(pick(row, "floorsDescendedInMeters", "floors_descended_in_meters")),
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
        "highest_spo2": safe_float(pick(row, "highestSpO2Value", "highest_spo2_value")),
        "avg_respiration": safe_float(pick(row, "averageRespirationValue", "average_respiration_value")),
        "highest_respiration": safe_float(pick(row, "highestRespirationValue", "highest_respiration_value")),
        "lowest_respiration": safe_float(pick(row, "lowestRespirationValue", "lowest_respiration_value")),
        "restless_count": safe_int(pick(row, "restlessMomentsCount", "restless_moments_count")),
    }


def normalise_lap(row: dict, sport: str = "unknown") -> dict:
    """Map raw ActivityLap fields to canonical schema."""
    index = safe_int(pick(row, "Index", "index", "lap_index"))

    dist_raw = safe_float(pick(row, "Distance", "distance"))
    # garmin-grafana always stores distance in metres
    dist_km = round(dist_raw / 1000.0, 3) if dist_raw else None

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


# Athlete-verified compound status→coaching-advice map.
# Each key is the full trainingStatusFeedbackPhrase string from garmin-grafana
# (e.g. "PRODUCTIVE_1").  Values are human-readable coaching text confirmed
# against the Garmin Connect app.  New statuses are added incrementally as
# the athlete encounters and verifies them.
TRAINING_STATUS_MAP: dict[str, str] = {
    "PRODUCTIVE_1": "Productive (Balanced)",
    "MAINTAINING_2": "Maintaining (High Aerobic Shortage)",
    "MAINTAINING_1": "Maintaining (Balanced)",
    "DETRAINING": "Detraining",
    "RECOVERY_1": "Recovery (Above Targets - Load too high, scale back duration/frequency)",
}


def _decode_feedback_phrase(raw: str | None) -> str | None:
    """Look up compound phrase in TRAINING_STATUS_MAP; flag unmapped ones."""
    if not raw:
        return None
    if raw in TRAINING_STATUS_MAP:
        return TRAINING_STATUS_MAP[raw]
    return f"{raw} (UNMAPPED_STATUS)"


def _normalise_training_status(row: dict) -> dict:
    """Map raw TrainingStatus fields to a canonical dict."""
    ts = row.get("time") or row.get("timestamp")
    raw_phrase = pick(row, FIELD_TRAINING_STATUS_LABEL, "trainingStatusFeedbackPhrase", "status")
    return {
        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        "status_code": safe_int(pick(row, FIELD_TRAINING_STATUS_CODE, "trainingStatus")),
        "status_label": raw_phrase,
        "garmin_coaching_advice": _decode_feedback_phrase(raw_phrase),
        "acute_load": safe_int(pick(row, FIELD_ACUTE_LOAD, "dailyTrainingLoadAcute", "acute_load")),
        "chronic_load": safe_int(pick(row, FIELD_CHRONIC_LOAD, "dailyTrainingLoadChronic", "chronic_load")),
        "load_balance_ratio": safe_float(pick(row, FIELD_LOAD_BALANCE_RATIO, "dailyAcuteChronicWorkloadRatio", "load_balance")),
        "acwr_percent": safe_int(pick(row, FIELD_ACWR_PERCENT, "acwrPercent", "acwr_percent")),
        "fitness_trend": safe_int(pick(row, FIELD_FITNESS_TREND, "fitnessTrend", "fitness_trend")),
        "max_chronic_load": safe_float(pick(row, "maxTrainingLoadChronic", "max_chronic_load")),
        "min_chronic_load": safe_float(pick(row, "minTrainingLoadChronic", "min_chronic_load")),
    }


def _normalise_training_readiness(row: dict) -> dict:
    """Map raw TrainingReadiness fields to a canonical dict."""
    ts = row.get("time") or row.get("timestamp")
    return {
        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        "score": safe_int(pick(row, FIELD_READINESS_SCORE, "trainingReadinessScore", "readinessScore", "score")),
        "description": pick(row, FIELD_READINESS_LABEL, "trainingReadinessDescription", "description"),
        "sleep_score": safe_int(pick(row, "sleepScore", "sleep_score")),
        "hrv_ratio": safe_float(pick(row, "hrvRatio", "hrv_ratio")),
        "recovery_time_h": safe_int(pick(row, "recoveryTimeValue", "recoveryTime", "recovery_time")),
        "stress_history": safe_float(pick(row, "stressHistory", "stress_history")),
        "activity_history": safe_float(pick(row, "activityHistory", "activity_history")),
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


def query_all_activities() -> list[dict]:
    """
    Return ALL activities from ActivitySummary (no time/limit filter),
    deduplicated and normalised.  Used for personal records computation.
    """
    if INFLUXDB_VERSION == 2:
        q = f'''
        from(bucket: "{INFLUXDB_DATABASE}")
          |> range(start: -3650d)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITIES}")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"], desc: true)
        '''
        try:
            raw_rows = _v2_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
    else:
        q = (
            f'SELECT * FROM "{MEASUREMENT_ACTIVITIES}" '
            f'ORDER BY time DESC'
        )
        try:
            raw_rows = _v1_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc

    deduped = _dedup_rows(raw_rows)
    activities = [
        a for a in (normalise_activity(r) for r in deduped)
        if a.get("sport_type") != "no activity"
    ]

    # Backfill power/cadence from ActivityLap for activities that lack them
    missing_ids = [
        a["activity_id"] for a in activities
        if a.get("activity_id") and a.get("avg_power") is None
    ]
    if missing_ids:
        lap_power = _query_all_lap_power()
        for act in activities:
            aid = act.get("activity_id")
            if not aid:
                continue
            entry = lap_power.get(str(aid))
            if entry is None:
                continue
            pw, cad = entry
            if act.get("avg_power") is None and pw is not None:
                act["avg_power"] = pw
            if act.get("avg_cadence") is None and cad is not None:
                act["avg_cadence"] = cad

    # Backfill max_power from ActivityGPS (single server-side MAX aggregate)
    gps_max = _query_all_max_power_from_gps()
    if gps_max:
        for act in activities:
            aid = act.get("activity_id")
            if aid is not None:
                act["max_power"] = gps_max.get(str(aid))

    return activities


def _query_all_lap_power() -> dict[str, tuple[float | None, float | None]]:
    """
    Bulk-fetch Avg_Power and Avg_Cadence from all ActivityLap rows,
    compute duration-weighted averages per ActivityID.

    Returns {activity_id: (weighted_avg_power, weighted_avg_cadence)}.
    """
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -3650d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITY_LAP}")
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
            '''
            raw = _v2_query(q)
        else:
            q = (
                f'SELECT * FROM "{MEASUREMENT_ACTIVITY_LAP}" '
                f'ORDER BY time ASC'
            )
            raw = _v1_query(q)
    except Exception as exc:
        logger.debug("Lap power bulk query failed (non-fatal): %s", exc)
        return {}

    deduped = _dedup_laps(raw)

    # Group laps by ActivityID and compute weighted averages
    from collections import defaultdict
    by_activity: dict[str, list[dict]] = defaultdict(list)
    for lap in deduped:
        aid = lap.get("ActivityID") or lap.get("Activity_ID") or lap.get("activity_id")
        if aid:
            by_activity[str(aid)].append(lap)

    result: dict[str, tuple[float | None, float | None]] = {}
    for aid, laps in by_activity.items():
        total_power_dur = 0.0
        total_power_val = 0.0
        total_cad_dur = 0.0
        total_cad_val = 0.0
        for lap in laps:
            dur = safe_float(lap.get("Elapsed_Time") or lap.get("elapsed_time"))
            if not dur or dur <= 0:
                continue
            pw = safe_float(lap.get("Avg_Power") or lap.get("avg_power"))
            if pw is not None and pw > 0:
                total_power_val += pw * dur
                total_power_dur += dur
            cad = safe_float(lap.get("Avg_Cadence") or lap.get("avg_cadence"))
            if cad is not None and cad > 0:
                total_cad_val += cad * dur
                total_cad_dur += dur

        avg_pw = round(total_power_val / total_power_dur, 1) if total_power_dur > 0 else None
        avg_cad = round(total_cad_val / total_cad_dur, 1) if total_cad_dur > 0 else None
        if avg_pw is not None or avg_cad is not None:
            result[aid] = (avg_pw, avg_cad)

    return result


def _query_all_max_power_from_gps() -> dict[str, float]:
    """
    Return {activity_id: max_power_watts} via a server-side MAX() aggregate on
    ActivityGPS.  Returns one value per activity — no raw samples transferred.
    """
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -3650d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_ACTIVITY_GPS}")
              |> filter(fn: (r) => r["_field"] == "Power")
              |> group(columns: ["ActivityID"])
              |> max()
            '''
            raw = _v2_query(q)
            return {
                str(r["ActivityID"]): float(r["_value"])
                for r in raw
                if r.get("ActivityID") and r.get("_value") is not None
            }
        else:
            q = (
                f'SELECT MAX("Power") FROM "{MEASUREMENT_ACTIVITY_GPS}" '
                f'GROUP BY "ActivityID"'
            )
            result = _v1_client().query(q)
            mapping: dict[str, float] = {}
            for (_meas, tags), points in result.items():
                if not tags or "ActivityID" not in tags:
                    continue
                aid = str(tags["ActivityID"])
                for point in points:
                    val = safe_float(point.get("max"))
                    if val is not None:
                        mapping[aid] = val
            return mapping
    except Exception as exc:
        logger.debug("ActivityGPS max power query failed (non-fatal): %s", exc)
        return {}


def query_latest_training_status() -> dict | None:
    """
    Return the most recent TrainingStatus row, or None if unavailable.
    Non-fatal: missing measurement, empty result, or any DB error all return None.
    """
    q = f'SELECT * FROM "{MEASUREMENT_TRAINING_STATUS}" ORDER BY time DESC LIMIT 1'
    try:
        rows = _v1_query(q)
    except Exception as exc:
        logger.debug("TrainingStatus query failed (non-fatal): %s", exc)
        return None
    if not rows:
        return None
    return _normalise_training_status(rows[0])


def query_latest_training_readiness() -> dict | None:
    """
    Return the most recent TrainingReadiness row, or None if unavailable.
    Non-fatal: missing measurement, empty result, or any DB error all return None.
    """
    q = f'SELECT * FROM "{MEASUREMENT_TRAINING_READINESS}" ORDER BY time DESC LIMIT 1'
    try:
        rows = _v1_query(q)
    except Exception as exc:
        logger.debug("TrainingReadiness query failed (non-fatal): %s", exc)
        return None
    if not rows:
        return None
    return _normalise_training_readiness(rows[0])


# ---------------------------------------------------------------------------
# New query functions for coaching blind-spot tools
# ---------------------------------------------------------------------------

def query_sleep_intraday_aggregated(days: int) -> list[dict]:
    """Return per-day MIN/MAX/MEAN aggregates of SleepIntraday physiology.

    Returns [] silently if measurement doesn't exist.
    """
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -{days}d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_SLEEP_INTRADAY}")
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
              |> window(every: 1d)
            '''
            raw = _v2_query(q)
            # v2 returns raw rows; aggregate in Python for now
            return _aggregate_sleep_intraday_by_day(raw)
        else:
            q = (
                f'SELECT '
                f'MIN("{FIELD_SLEEP_HR}") AS min_hr, MAX("{FIELD_SLEEP_HR}") AS max_hr, MEAN("{FIELD_SLEEP_HR}") AS mean_hr, '
                f'MIN("{FIELD_SLEEP_HRV}") AS min_hrv, MAX("{FIELD_SLEEP_HRV}") AS max_hrv, MEAN("{FIELD_SLEEP_HRV}") AS mean_hrv, '
                f'MIN("{FIELD_SLEEP_RESPIRATION}") AS min_resp, MAX("{FIELD_SLEEP_RESPIRATION}") AS max_resp, MEAN("{FIELD_SLEEP_RESPIRATION}") AS mean_resp, '
                f'MIN("{FIELD_SLEEP_SPO2}") AS min_spo2, MAX("{FIELD_SLEEP_SPO2}") AS max_spo2, MEAN("{FIELD_SLEEP_SPO2}") AS mean_spo2, '
                f'MEAN("{FIELD_SLEEP_STRESS}") AS mean_stress, '
                f'FIRST("{FIELD_SLEEP_BODY_BATTERY}") AS bb_first, LAST("{FIELD_SLEEP_BODY_BATTERY}") AS bb_last, '
                f'MIN("{FIELD_SLEEP_BODY_BATTERY}") AS bb_min, MAX("{FIELD_SLEEP_BODY_BATTERY}") AS bb_max, '
                f'MEAN("{FIELD_SLEEP_RESTLESS}") AS mean_restless, '
                f'COUNT("{FIELD_SLEEP_HR}") AS epoch_count '
                f'FROM "{MEASUREMENT_SLEEP_INTRADAY}" '
                f'WHERE time >= now() - {days}d '
                f'GROUP BY time(1d) fill(none)'
            )
            raw = _v1_query(q)
            return [_normalise_sleep_physiology(r) for r in raw if r.get("epoch_count")]
    except Exception as exc:
        logger.debug("SleepIntraday aggregation failed (non-fatal): %s", exc)
        return []


def _aggregate_sleep_intraday_by_day(raw: list[dict]) -> list[dict]:
    """Aggregate raw SleepIntraday rows by calendar day (v2 fallback)."""
    from collections import defaultdict

    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in raw:
        ts = row.get("_time") or row.get("time")
        if not ts:
            continue
        day_str = str(ts)[:10]
        by_day[day_str].append(row)

    results = []
    for day_str in sorted(by_day.keys(), reverse=True):
        rows = by_day[day_str]
        hrs = [safe_float(r.get(FIELD_SLEEP_HR)) for r in rows]
        hrs = [h for h in hrs if h is not None]
        hrvs = [safe_float(r.get(FIELD_SLEEP_HRV)) for r in rows]
        hrvs = [h for h in hrvs if h is not None]
        resps = [safe_float(r.get(FIELD_SLEEP_RESPIRATION)) for r in rows]
        resps = [r for r in resps if r is not None]
        spo2s = [safe_float(r.get(FIELD_SLEEP_SPO2)) for r in rows]
        spo2s = [s for s in spo2s if s is not None]
        stresses = [safe_float(r.get(FIELD_SLEEP_STRESS)) for r in rows]
        stresses = [s for s in stresses if s is not None]
        bbs = [safe_float(r.get(FIELD_SLEEP_BODY_BATTERY)) for r in rows]
        bbs = [b for b in bbs if b is not None]
        restless = [safe_float(r.get(FIELD_SLEEP_RESTLESS)) for r in rows]
        restless = [r for r in restless if r is not None]

        if not hrs:
            continue

        results.append({
            "date": day_str,
            "heart_rate": {"min": min(hrs), "max": max(hrs), "mean": round(sum(hrs) / len(hrs), 1)},
            "hrv": {"min": min(hrvs), "max": max(hrvs), "mean": round(sum(hrvs) / len(hrvs), 1)} if hrvs else None,
            "respiration": {"min": round(min(resps), 1), "max": round(max(resps), 1), "mean": round(sum(resps) / len(resps), 1)} if resps else None,
            "spo2": {"min": min(spo2s), "max": max(spo2s), "mean": round(sum(spo2s) / len(spo2s), 1)} if spo2s else None,
            "stress": {"mean": round(sum(stresses) / len(stresses), 1)} if stresses else None,
            "body_battery": {"first": bbs[0], "last": bbs[-1], "min": min(bbs), "max": max(bbs)} if bbs else None,
            "restlessness": {"mean": round(sum(restless) / len(restless), 1)} if restless else None,
            "epoch_count": len(hrs),
        })
    return results


def _normalise_sleep_physiology(row: dict) -> dict:
    """Map aggregated SleepIntraday row (from GROUP BY time(1d)) to canonical dict."""
    ts = row.get("time") or row.get("_time")
    date_str = str(ts)[:10] if ts else None

    return {
        "date": date_str,
        "heart_rate": {
            "min": safe_float(row.get("min_hr")),
            "max": safe_float(row.get("max_hr")),
            "mean": round(safe_float(row.get("mean_hr")) or 0, 1) or None,
        },
        "hrv": {
            "min": safe_float(row.get("min_hrv")),
            "max": safe_float(row.get("max_hrv")),
            "mean": round(safe_float(row.get("mean_hrv")) or 0, 1) or None,
        },
        "respiration": {
            "min": round(safe_float(row.get("min_resp")) or 0, 1) or None,
            "max": round(safe_float(row.get("max_resp")) or 0, 1) or None,
            "mean": round(safe_float(row.get("mean_resp")) or 0, 1) or None,
        },
        "spo2": {
            "min": safe_float(row.get("min_spo2")),
            "max": safe_float(row.get("max_spo2")),
            "mean": round(safe_float(row.get("mean_spo2")) or 0, 1) or None,
        },
        "stress": {"mean": round(safe_float(row.get("mean_stress")) or 0, 1) or None},
        "body_battery": {
            "first": safe_int(row.get("bb_first")),
            "last": safe_int(row.get("bb_last")),
            "min": safe_int(row.get("bb_min")),
            "max": safe_int(row.get("bb_max")),
        },
        "restlessness": {"mean": round(safe_float(row.get("mean_restless")) or 0, 1) or None},
        "epoch_count": safe_int(row.get("epoch_count")),
    }


def query_fitness_age_weekly(weeks: int) -> list[dict]:
    """Return weekly-sampled fitness age values."""
    days = weeks * 7
    try:
        if INFLUXDB_VERSION == 2:
            q = f'''
            from(bucket: "{INFLUXDB_DATABASE}")
              |> range(start: -{days}d)
              |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT_FITNESS_AGE}")
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
              |> sort(columns: ["_time"], desc: true)
            '''
            raw = _v2_query(q)
        else:
            q = (
                f'SELECT '
                f'LAST("{FIELD_FITNESS_AGE}") AS fitness_age, '
                f'LAST("{FIELD_CHRONOLOGICAL_AGE}") AS chrono_age, '
                f'LAST("{FIELD_ACHIEVABLE_FITNESS_AGE}") AS achievable_age '
                f'FROM "{MEASUREMENT_FITNESS_AGE}" '
                f'WHERE time >= now() - {days}d '
                f'GROUP BY time(1w) fill(none)'
            )
            raw = _v1_query(q)
        return raw
    except Exception as exc:
        logger.debug("FitnessAge query failed (non-fatal): %s", exc)
        return []


def query_activity_load_history(days: int, sport_type: str | None, limit: int) -> list[dict]:
    """Return activity rows with training-load fields from ActivitySummary.

    Uses the same normalise_activity() as other activity tools so the load
    fields (training_load, aerobic_training_effect, anaerobic_training_effect)
    are included automatically.
    """
    try:
        sport_type = sanitize_sport_type(sport_type)
    except ValueError:
        sport_type = None

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
            sport_clause = (
                f" AND (\"sport_type\" =~ /.*{sport_type}.*/"
                f" OR \"sport\" =~ /.*{sport_type}.*/"
                f" OR \"activityType\" =~ /.*{sport_type}.*/)"
            )
        q = (
            f'SELECT * FROM "{MEASUREMENT_ACTIVITIES}" '
            f'WHERE time >= now() - {days}d{sport_clause} '
            f'ORDER BY time DESC LIMIT {limit}'
        )
        try:
            raw_rows = _v1_query(q)
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc

    deduped = _dedup_rows(raw_rows)
    return [
        a for a in (normalise_activity(r) for r in deduped)
        if a.get("sport_type") != "no activity"
    ]
