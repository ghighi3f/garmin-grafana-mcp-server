"""
Unit tests for influx.py normalizer functions and utils.py helpers.

These tests are fully offline — they use static dicts mimicking raw InfluxDB
rows and never create a database connection.
"""

import datetime
import pytest

from influx import (
    normalise_activity,
    normalise_daily_stats,
    normalise_sleep,
    normalise_lap,
    PACE_SPORTS,
    sanitize_sport_type,
)
from utils import pick, safe_float, safe_int, iso_week_label, week_start_from_label
from tools.stress import (
    _aggregate_stress_intraday,
    _aggregate_body_battery_intraday,
    _synthesize_today_row,
)


# ===================================================================
# utils.py helpers
# ===================================================================

class TestPick:
    def test_returns_first_present_key(self):
        row = {"a": 1, "b": 2, "c": 3}
        assert pick(row, "x", "b", "c") == 2

    def test_returns_none_when_no_match(self):
        assert pick({"a": 1}, "x", "y") is None

    def test_skips_none_values(self):
        row = {"a": None, "b": 42}
        assert pick(row, "a", "b") == 42

    def test_returns_zero(self):
        """0 is a valid value, not None — pick() should return it."""
        row = {"a": 0, "b": 99}
        assert pick(row, "a", "b") == 0

    def test_empty_row(self):
        assert pick({}, "a") is None


class TestSafeFloat:
    def test_normal(self):
        assert safe_float("3.14") == 3.14

    def test_int_input(self):
        assert safe_float(42) == 42.0

    def test_none(self):
        assert safe_float(None) is None

    def test_garbage_string(self):
        assert safe_float("not-a-number") is None

    def test_default(self):
        assert safe_float(None, default=-1) == -1


class TestSafeInt:
    def test_normal(self):
        assert safe_int("42") == 42

    def test_float_input(self):
        assert safe_int(3.9) == 3

    def test_none(self):
        assert safe_int(None) is None

    def test_garbage(self):
        assert safe_int("abc") is None


class TestIsoWeekLabel:
    def test_string_timestamp(self):
        label = iso_week_label("2024-01-15T12:00:00Z")
        assert label == "2024-W03"

    def test_datetime_object(self):
        dt = datetime.datetime(2024, 1, 1, 0, 0, 0)
        label = iso_week_label(dt)
        assert label == "2024-W01"

    def test_none(self):
        assert iso_week_label(None) is None


class TestWeekStartFromLabel:
    def test_normal(self):
        assert week_start_from_label("2024-W03") == "2024-01-15"

    def test_garbage(self):
        # Should return the input string unchanged on parse failure
        assert week_start_from_label("not-a-week") == "not-a-week"


# ===================================================================
# normalise_activity
# ===================================================================

class TestNormaliseActivity:
    """Tests for normalise_activity() — the core activity row mapper."""

    # -- A realistic garmin-grafana row (camelCase, metres, seconds) --------
    FULL_ROW = {
        "time": "2024-06-15T08:30:00Z",
        "Activity_ID": "abc123",
        "activityType": "Running",
        "distance": 10500.0,            # metres
        "elapsedDuration": 3120.0,       # seconds (52 min)
        "averageHR": 155.0,
        "maxHR": 178.0,
        "calories": 620,
        "totalAscent": 85.3,
        "averageCadence": 88.5,
        "averageSpeed": 3.37,            # m/s  → ~12.1 km/h
        "hrTimeInZone_1": 600.0,         # 10 min
        "hrTimeInZone_2": 720.0,         # 12 min
        "hrTimeInZone_3": 900.0,         # 15 min
        "hrTimeInZone_4": 480.0,         # 8 min
        "hrTimeInZone_5": 300.0,         # 5 min (total 50 min)
    }

    def test_full_row_basic_fields(self):
        result = normalise_activity(self.FULL_ROW)
        assert result["activity_id"] == "abc123"
        assert result["sport_type"] == "running"
        assert result["timestamp"] == "2024-06-15T08:30:00Z"

    def test_distance_converted_from_metres(self):
        result = normalise_activity(self.FULL_ROW)
        assert result["distance_km"] == 10.5

    def test_duration_converted_from_seconds(self):
        result = normalise_activity(self.FULL_ROW)
        assert result["duration_minutes"] == 52.0

    def test_heart_rate(self):
        result = normalise_activity(self.FULL_ROW)
        assert result["avg_hr"] == 155.0
        assert result["max_hr"] == 178.0

    def test_elevation(self):
        result = normalise_activity(self.FULL_ROW)
        assert result["elevation_gain_m"] == 85.3

    def test_cadence(self):
        result = normalise_activity(self.FULL_ROW)
        assert result["avg_cadence"] == 88.5

    def test_calories(self):
        result = normalise_activity(self.FULL_ROW)
        assert result["calories"] == 620

    def test_pace_for_running(self):
        """Running activities should have pace, not speed."""
        result = normalise_activity(self.FULL_ROW)
        assert result["avg_pace_min_per_km"] is not None
        assert result["avg_speed_kmh"] is None

    def test_speed_for_cycling(self):
        """Cycling activities should have speed, not pace."""
        row = {**self.FULL_ROW, "activityType": "Cycling", "averageSpeed": 8.33}  # ~30 km/h
        result = normalise_activity(row)
        assert result["avg_speed_kmh"] is not None
        assert result["avg_pace_min_per_km"] is None

    def test_hr_zones_present(self):
        result = normalise_activity(self.FULL_ROW)
        zones = result["hr_zones"]
        assert zones is not None
        assert zones["zone_1_minutes"] == 10.0
        assert zones["zone_3_minutes"] == 15.0

    def test_hr_zone_percentages_sum_to_100(self):
        result = normalise_activity(self.FULL_ROW)
        zones = result["hr_zones"]
        total_pct = sum(
            zones[f"zone_{i}_pct"]
            for i in range(1, 6)
            if zones.get(f"zone_{i}_pct") is not None
        )
        assert abs(total_pct - 100.0) < 0.5

    # -- Edge cases ---------------------------------------------------------

    def test_empty_row(self):
        """An empty dict should return a valid structure with all-None values."""
        result = normalise_activity({})
        assert result["sport_type"] == "unknown"
        assert result["distance_km"] is None
        assert result["duration_minutes"] is None
        assert result["hr_zones"] is None

    def test_sentinel_row_produces_no_activity(self):
        """Sentinel rows written by garmin-grafana have activityType='No Activity'."""
        row = {"activityType": "No Activity", "time": "2024-01-01T00:00:00Z"}
        result = normalise_activity(row)
        assert result["sport_type"] == "no activity"

    def test_missing_hr_zones_yields_none(self):
        """If no zone data exists, hr_zones should be None, not empty."""
        row = {"activityType": "Running", "distance": 5000}
        result = normalise_activity(row)
        assert result["hr_zones"] is None

    def test_zero_zone_times(self):
        """All zone seconds = 0.0 → total is 0 → hr_zones should be None."""
        row = {
            "activityType": "Running",
            "hrTimeInZone_1": 0.0,
            "hrTimeInZone_2": 0.0,
            "hrTimeInZone_3": 0.0,
            "hrTimeInZone_4": 0.0,
            "hrTimeInZone_5": 0.0,
        }
        result = normalise_activity(row)
        assert result["hr_zones"] is None

    def test_small_distance_treated_as_km(self):
        """Distance < 500 is assumed already in km (no conversion)."""
        row = {"distance": 5.2, "activityType": "Running"}
        result = normalise_activity(row)
        assert result["distance_km"] == 5.2

    def test_short_duration_treated_as_minutes(self):
        """Duration <= 300 is assumed already in minutes (no conversion)."""
        row = {"elapsedDuration": 45.0, "activityType": "Running"}
        result = normalise_activity(row)
        assert result["duration_minutes"] == 45.0

    def test_snake_case_field_variants(self):
        """normalise_activity handles snake_case alternatives too."""
        row = {
            "activity_type": "Running",
            "total_distance": 8000.0,
            "elapsed_duration": 2400.0,
            "average_heart_rate": 150.0,
        }
        result = normalise_activity(row)
        assert result["sport_type"] == "running"
        assert result["distance_km"] == 8.0
        assert result["avg_hr"] == 150.0

    def test_datetime_timestamp(self):
        """datetime objects should be serialised via .isoformat()."""
        row = {"time": datetime.datetime(2024, 3, 1, 10, 0, 0), "activityType": "Run"}
        result = normalise_activity(row)
        assert result["timestamp"] == "2024-03-01T10:00:00"

    def test_activity_id_variants(self):
        """Should pick activity ID from multiple possible field names."""
        for key in ("Activity_ID", "ActivityID", "activity_id", "activityId"):
            row = {key: "id-999"}
            result = normalise_activity(row)
            assert result["activity_id"] == "id-999", f"Failed for key: {key}"


# ===================================================================
# normalise_daily_stats
# ===================================================================

class TestNormaliseDailyStats:
    FULL_ROW = {
        "time": "2024-06-15T00:00:00Z",
        "restingHeartRate": 52.0,
        "bodyBatteryAtWakeTime": 78,
        "bodyBatteryHighestValue": 95,
        "bodyBatteryLowestValue": 12,
        "bodyBatteryDrainedValue": 83,
        "bodyBatteryChargedValue": 66,
        "totalSteps": 9845,
        "totalDistanceMeters": 7500.0,
        "activeKilocalories": 450,
        "moderateIntensityMinutes": 30.0,
        "vigorousIntensityMinutes": 15.0,
        "highStressDuration": 3600.0,       # 1 hour
        "mediumStressDuration": 7200.0,     # 2 hours
        "lowStressDuration": 10800.0,       # 3 hours
        "restStressDuration": 14400.0,      # 4 hours
        "averageSpo2": 97.0,
        "lowestSpo2": 92.0,
        "maxHeartRate": 120.0,
        "minHeartRate": 48.0,
        "floorsAscended": 8.0,
    }

    def test_basic_fields(self):
        result = normalise_daily_stats(self.FULL_ROW)
        assert result["date"] == "2024-06-15"
        assert result["resting_hr"] == 52.0
        assert result["total_steps"] == 9845
        assert result["active_calories"] == 450

    def test_distance_converted(self):
        result = normalise_daily_stats(self.FULL_ROW)
        assert result["total_distance_km"] == 7.5

    def test_stress_converted_to_minutes(self):
        result = normalise_daily_stats(self.FULL_ROW)
        assert result["stress_high_min"] == 60.0
        assert result["stress_medium_min"] == 120.0

    def test_body_battery(self):
        result = normalise_daily_stats(self.FULL_ROW)
        assert result["body_battery_at_wake"] == 78
        assert result["body_battery_high"] == 95
        assert result["body_battery_low"] == 12

    def test_empty_row(self):
        result = normalise_daily_stats({})
        assert result["date"] is None
        assert result["resting_hr"] is None
        assert result["total_steps"] is None

    def test_snake_case_variants(self):
        row = {
            "time": "2024-01-01T00:00:00Z",
            "resting_heart_rate": 55.0,
            "total_steps": 5000,
        }
        result = normalise_daily_stats(row)
        assert result["resting_hr"] == 55.0
        assert result["total_steps"] == 5000


# ===================================================================
# normalise_sleep
# ===================================================================

class TestNormaliseSleep:
    FULL_ROW = {
        "time": "2024-06-15T07:00:00Z",
        "sleepScore": 82,
        "sleepTimeSeconds": 27000.0,        # 7.5 hours
        "deepSleepSeconds": 5400.0,         # 1.5 hours
        "lightSleepSeconds": 14400.0,       # 4.0 hours
        "remSleepSeconds": 5400.0,          # 1.5 hours
        "awakeSleepSeconds": 1800.0,        # 0.5 hours
        "awakeCount": 3,
        "avgOvernightHrv": 45.0,
        "avgSleepStress": 18.0,
        "bodyBatteryChange": 55,
        "restingHeartRate": 50.0,
        "averageSpO2Value": 96.5,
        "lowestSpO2Value": 91.0,
        "averageRespirationValue": 15.0,
        "restlessMomentsCount": 7,
    }

    def test_basic_fields(self):
        result = normalise_sleep(self.FULL_ROW)
        assert result["date"] == "2024-06-15"
        assert result["sleep_score"] == 82
        assert result["awake_count"] == 3

    def test_seconds_to_hours_conversion(self):
        result = normalise_sleep(self.FULL_ROW)
        assert result["total_sleep_hours"] == 7.5
        assert result["deep_sleep_hours"] == 1.5
        assert result["rem_sleep_hours"] == 1.5
        assert result["awake_hours"] == 0.5

    def test_hrv_and_stress(self):
        result = normalise_sleep(self.FULL_ROW)
        assert result["avg_overnight_hrv"] == 45.0
        assert result["avg_sleep_stress"] == 18.0

    def test_empty_row(self):
        result = normalise_sleep({})
        assert result["date"] is None
        assert result["sleep_score"] is None
        assert result["total_sleep_hours"] is None


# ===================================================================
# normalise_lap
# ===================================================================

class TestNormaliseLap:
    RUNNING_LAP = {
        "Index": 1,
        "Distance": 1000.0,        # metres
        "Elapsed_Time": 300.0,      # seconds (5 min)
        "Avg_HR": 160.0,
        "Max_HR": 175.0,
        "Avg_Speed": 3.33,          # m/s  → ~12 km/h
        "Max_Speed": 4.17,          # m/s  → ~15 km/h
        "Calories": 95,
        "Avg_Cadence": 90.0,
        "Avg_Power": None,
        "Avg_Temperature": 22.0,
    }

    def test_running_lap_basic(self):
        result = normalise_lap(self.RUNNING_LAP, sport="running")
        assert result["index"] == 1
        assert result["distance_km"] == 1.0
        assert result["elapsed_time_minutes"] == 5.0

    def test_running_lap_has_pace_not_speed(self):
        result = normalise_lap(self.RUNNING_LAP, sport="running")
        assert result["avg_pace_min_per_km"] is not None
        assert result["avg_speed_kmh"] is None
        assert result["max_speed_kmh"] is None

    def test_cycling_lap_has_speed_not_pace(self):
        result = normalise_lap(self.RUNNING_LAP, sport="cycling")
        assert result["avg_speed_kmh"] is not None
        assert result["avg_pace_min_per_km"] is None

    def test_empty_lap(self):
        result = normalise_lap({})
        assert result["index"] is None
        assert result["distance_km"] is None

    def test_snake_case_fields(self):
        row = {"index": 2, "distance": 2000.0, "avg_hr": 145.0}
        result = normalise_lap(row)
        assert result["index"] == 2
        assert result["avg_hr"] == 145.0


# ===================================================================
# Stress intraday aggregation helpers
# ===================================================================

class TestAggregateStressIntraday:
    """Tests for _aggregate_stress_intraday from tools/stress.py."""

    def test_all_buckets(self):
        rows = [
            {"stressLevel": 10},   # rest
            {"stressLevel": 40},   # low
            {"stressLevel": 60},   # medium
            {"stressLevel": 85},   # high
        ]
        result = _aggregate_stress_intraday(rows)
        assert result is not None
        assert result["rest_min"] == 3.0
        assert result["low_min"] == 3.0
        assert result["medium_min"] == 3.0
        assert result["high_min"] == 3.0

    def test_boundary_values(self):
        """Test exact boundary values between buckets."""
        rows = [
            {"stressLevel": 25},   # rest (upper bound)
            {"stressLevel": 26},   # low (lower bound)
            {"stressLevel": 50},   # low (upper bound)
            {"stressLevel": 51},   # medium (lower bound)
            {"stressLevel": 75},   # medium (upper bound)
            {"stressLevel": 76},   # high (lower bound)
            {"stressLevel": 100},  # high (upper bound)
        ]
        result = _aggregate_stress_intraday(rows)
        assert result["rest_min"] == 3.0      # 1 reading
        assert result["low_min"] == 6.0       # 2 readings
        assert result["medium_min"] == 6.0    # 2 readings
        assert result["high_min"] == 6.0      # 2 readings

    def test_skips_negative_and_zero(self):
        rows = [
            {"stressLevel": -1},
            {"stressLevel": 0},
            {"stressLevel": -2},
            {"stressLevel": 50},   # low
        ]
        result = _aggregate_stress_intraday(rows)
        assert result is not None
        assert result["low_min"] == 3.0
        assert result["rest_min"] == 0.0
        assert result["high_min"] == 0.0

    def test_empty_rows(self):
        assert _aggregate_stress_intraday([]) is None

    def test_all_unmeasured(self):
        rows = [{"stressLevel": -1}, {"stressLevel": 0}]
        assert _aggregate_stress_intraday(rows) is None

    def test_missing_field(self):
        rows = [{"other_field": 42}]
        assert _aggregate_stress_intraday(rows) is None


class TestAggregateBodyBatteryIntraday:
    """Tests for _aggregate_body_battery_intraday from tools/stress.py."""

    def test_high_low(self):
        rows = [
            {"BodyBatteryLevel": 80},
            {"BodyBatteryLevel": 65},
            {"BodyBatteryLevel": 50},
            {"BodyBatteryLevel": 55},
        ]
        result = _aggregate_body_battery_intraday(rows)
        assert result is not None
        assert result["high"] == 80
        assert result["low"] == 50
        assert result["at_wake"] is None

    def test_charged_drained(self):
        rows = [
            {"BodyBatteryLevel": 80},   # start
            {"BodyBatteryLevel": 65},   # -15 drained
            {"BodyBatteryLevel": 70},   # +5  charged
            {"BodyBatteryLevel": 50},   # -20 drained
        ]
        result = _aggregate_body_battery_intraday(rows)
        assert result["drained"] == 35   # 15 + 20
        assert result["charged"] == 5

    def test_only_draining(self):
        rows = [
            {"BodyBatteryLevel": 90},
            {"BodyBatteryLevel": 80},
            {"BodyBatteryLevel": 70},
        ]
        result = _aggregate_body_battery_intraday(rows)
        assert result["drained"] == 20
        assert result["charged"] is None

    def test_only_charging(self):
        rows = [
            {"BodyBatteryLevel": 50},
            {"BodyBatteryLevel": 60},
            {"BodyBatteryLevel": 70},
        ]
        result = _aggregate_body_battery_intraday(rows)
        assert result["charged"] == 20
        assert result["drained"] is None

    def test_empty_rows(self):
        assert _aggregate_body_battery_intraday([]) is None

    def test_zero_values_skipped(self):
        rows = [{"BodyBatteryLevel": 0}]
        assert _aggregate_body_battery_intraday(rows) is None

    def test_single_reading(self):
        rows = [{"BodyBatteryLevel": 75}]
        result = _aggregate_body_battery_intraday(rows)
        assert result["high"] == 75
        assert result["low"] == 75
        assert result["charged"] is None
        assert result["drained"] is None


class TestSynthesizeTodayRow:
    """Tests for _synthesize_today_row from tools/stress.py."""

    def test_no_data_returns_none(self):
        assert _synthesize_today_row("2026-03-20", [], []) is None

    def test_stress_only(self):
        stress = [{"stressLevel": 80}]
        result = _synthesize_today_row("2026-03-20", stress, [])
        assert result is not None
        assert result["date"] == "2026-03-20"
        assert result["stress_high_min"] == 3.0
        assert result["body_battery_high"] is None

    def test_body_battery_only(self):
        bb = [{"BodyBatteryLevel": 75}, {"BodyBatteryLevel": 60}]
        result = _synthesize_today_row("2026-03-20", [], bb)
        assert result is not None
        assert result["date"] == "2026-03-20"
        assert result["stress_high_min"] is None
        assert result["body_battery_high"] == 75
        assert result["body_battery_low"] == 60

    def test_both_sources(self):
        stress = [{"stressLevel": 30}, {"stressLevel": 80}]
        bb = [{"BodyBatteryLevel": 90}, {"BodyBatteryLevel": 70}]
        result = _synthesize_today_row("2026-03-20", stress, bb)
        assert result is not None
        assert result["stress_low_min"] == 3.0
        assert result["stress_high_min"] == 3.0
        assert result["body_battery_high"] == 90
        assert result["body_battery_at_wake"] is None


# ===================================================================
# PACE_SPORTS constant
# ===================================================================

class TestPaceSports:
    """Tests for the PACE_SPORTS constant and its integration."""

    def test_known_pace_sports(self):
        for sport in ("running", "run", "swimming", "swim", "walk",
                      "hiking", "trail_running", "trail running"):
            assert sport in PACE_SPORTS, f"{sport} should be in PACE_SPORTS"

    def test_known_speed_sports(self):
        for sport in ("cycling", "rowing", "kayaking"):
            assert sport not in PACE_SPORTS, f"{sport} should NOT be in PACE_SPORTS"

    def test_walk_gets_pace_not_speed(self):
        """Regression: walk previously got both pace AND speed."""
        row = {"activityType": "Walk", "averageSpeed": 1.39}  # ~5 km/h
        result = normalise_activity(row)
        assert result["avg_pace_min_per_km"] is not None
        assert result["avg_speed_kmh"] is None

    def test_hiking_gets_pace_not_speed(self):
        """Regression: hiking previously got both pace AND speed."""
        row = {"activityType": "Hiking", "averageSpeed": 1.11}  # ~4 km/h
        result = normalise_activity(row)
        assert result["avg_pace_min_per_km"] is not None
        assert result["avg_speed_kmh"] is None

    def test_trail_running_gets_pace(self):
        row = {"activityType": "Trail_Running", "averageSpeed": 2.78}  # ~10 km/h
        result = normalise_activity(row)
        assert result["avg_pace_min_per_km"] is not None
        assert result["avg_speed_kmh"] is None

    def test_cycling_gets_speed_not_pace(self):
        row = {"activityType": "Cycling", "averageSpeed": 8.33}  # ~30 km/h
        result = normalise_activity(row)
        assert result["avg_speed_kmh"] is not None
        assert result["avg_pace_min_per_km"] is None

    def test_lap_walk_gets_pace_not_speed(self):
        row = {"Index": 1, "Avg_Speed": 1.39, "Distance": 1000.0, "Elapsed_Time": 720.0}
        result = normalise_lap(row, sport="walk")
        assert result["avg_pace_min_per_km"] is not None
        assert result["avg_speed_kmh"] is None

    def test_lap_cycling_gets_speed_not_pace(self):
        row = {"Index": 1, "Avg_Speed": 8.33, "Distance": 5000.0, "Elapsed_Time": 600.0}
        result = normalise_lap(row, sport="cycling")
        assert result["avg_speed_kmh"] is not None
        assert result["avg_pace_min_per_km"] is None


# ===================================================================
# sanitize_sport_type
# ===================================================================

class TestSanitizeSportType:
    """Tests for the sanitize_sport_type() query safety function."""

    def test_none_returns_none(self):
        assert sanitize_sport_type(None) is None

    def test_empty_returns_none(self):
        assert sanitize_sport_type("") is None
        assert sanitize_sport_type("   ") is None

    def test_all_returns_none(self):
        assert sanitize_sport_type("all") is None
        assert sanitize_sport_type("ALL") is None
        assert sanitize_sport_type("  All  ") is None

    def test_valid_sport_passes_through(self):
        assert sanitize_sport_type("running") == "running"
        assert sanitize_sport_type("Trail_Running") == "trail_running"
        assert sanitize_sport_type("  Cycling  ") == "cycling"

    def test_sport_with_space(self):
        assert sanitize_sport_type("trail running") == "trail running"

    def test_sport_with_hyphen(self):
        assert sanitize_sport_type("e-bike") == "e-bike"

    def test_injection_attempt_raises(self):
        with pytest.raises(ValueError):
            sanitize_sport_type("running'; DROP MEASUREMENT --")

    def test_quotes_rejected(self):
        with pytest.raises(ValueError):
            sanitize_sport_type('running"')

    def test_special_chars_rejected(self):
        with pytest.raises(ValueError):
            sanitize_sport_type("running|cycling")
