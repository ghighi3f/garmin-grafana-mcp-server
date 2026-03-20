"""
Live schema validation tests.

These tests run against the real local InfluxDB instance to detect upstream
schema changes (e.g., garmin-grafana renaming fields or dropping measurements).

They do NOT test our tool logic — only that the database still looks the way
we expect. If no DB connection is available the entire module is skipped.

Run with:  pytest tests/test_live_schema.py -v
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Try to import the influxdb client and connect. Skip everything if we can't.
try:
    from influx import ping, get_measurements, query_field_keys
    _db_reachable = ping()
except Exception:
    _db_reachable = False

pytestmark = pytest.mark.skipif(
    not _db_reachable,
    reason="InfluxDB not reachable — skipping live schema tests",
)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

@pytest.fixture(scope="module")
def measurements() -> list[str]:
    """Cache the measurement list for the module."""
    return get_measurements()


def _field_names(measurement: str) -> set[str]:
    """Return the set of field names present in a measurement."""
    keys = query_field_keys(measurement)
    return {entry["field"] for entry in keys}


# -------------------------------------------------------------------
# Measurement existence
# -------------------------------------------------------------------

class TestMeasurementsExist:
    """Assert that the mandatory measurements still exist in the database."""

    @pytest.mark.parametrize("measurement", [
        "ActivitySummary",
        "DailyStats",
        "HRV_Intraday",
        "SleepSummary",
        "ActivitySession",
        "ActivityLap",
    ])
    def test_core_measurement_exists(self, measurements, measurement):
        assert measurement in measurements, (
            f"Measurement '{measurement}' not found in InfluxDB. "
            f"Available: {measurements}"
        )

    @pytest.mark.parametrize("measurement", [
        "VO2_Max",
        "RacePredictions",
        "BodyComposition",
        "StressIntraday",
        "BodyBatteryIntraday",
    ])
    def test_optional_measurement_exists(self, measurements, measurement):
        """These measurements may not be present for all users but are expected."""
        if measurement not in measurements:
            pytest.skip(f"Optional measurement '{measurement}' not found — skipping")


# -------------------------------------------------------------------
# Critical fields in ActivitySummary
# -------------------------------------------------------------------

class TestActivitySummaryFields:
    """Assert that fields our normalizers rely on still exist."""

    @pytest.fixture(scope="class")
    def fields(self) -> set[str]:
        return _field_names("ActivitySummary")

    @pytest.mark.parametrize("field", [
        "elapsedDuration",
        "distance",
        "averageHR",
        "maxHR",
        "calories",
    ])
    def test_mandatory_field(self, fields, field):
        assert field in fields, (
            f"Field '{field}' missing from ActivitySummary. "
            f"Available fields: {sorted(fields)}"
        )

    @pytest.mark.parametrize("field", [
        "hrTimeInZone_1",
        "hrTimeInZone_2",
        "hrTimeInZone_3",
        "hrTimeInZone_4",
        "hrTimeInZone_5",
    ])
    def test_hr_zone_fields(self, fields, field):
        assert field in fields, (
            f"HR zone field '{field}' missing from ActivitySummary. "
            f"Available fields: {sorted(fields)}"
        )


# -------------------------------------------------------------------
# Critical fields in DailyStats
# -------------------------------------------------------------------

class TestDailyStatsFields:

    @pytest.fixture(scope="class")
    def fields(self) -> set[str]:
        return _field_names("DailyStats")

    @pytest.mark.parametrize("field", [
        "restingHeartRate",
        "bodyBatteryAtWakeTime",
        "totalSteps",
        "highStressDuration",
    ])
    def test_mandatory_field(self, fields, field):
        assert field in fields, (
            f"Field '{field}' missing from DailyStats. "
            f"Available fields: {sorted(fields)}"
        )


# -------------------------------------------------------------------
# Critical fields in SleepSummary
# -------------------------------------------------------------------

class TestSleepSummaryFields:

    @pytest.fixture(scope="class")
    def fields(self) -> set[str]:
        return _field_names("SleepSummary")

    @pytest.mark.parametrize("field", [
        "sleepScore",
        "sleepTimeSeconds",
        "deepSleepSeconds",
        "lightSleepSeconds",
        "remSleepSeconds",
        "avgOvernightHrv",
    ])
    def test_mandatory_field(self, fields, field):
        assert field in fields, (
            f"Field '{field}' missing from SleepSummary. "
            f"Available fields: {sorted(fields)}"
        )


# -------------------------------------------------------------------
# Critical fields in HRV_Intraday
# -------------------------------------------------------------------

class TestHRVFields:

    @pytest.fixture(scope="class")
    def fields(self) -> set[str]:
        return _field_names("HRV_Intraday")

    def test_hrv_value_field(self, fields):
        assert "hrvValue" in fields, (
            f"Field 'hrvValue' missing from HRV_Intraday. "
            f"Available fields: {sorted(fields)}"
        )


# -------------------------------------------------------------------
# Critical fields in StressIntraday
# -------------------------------------------------------------------

class TestStressIntradayFields:

    @pytest.fixture(scope="class")
    def fields(self) -> set[str]:
        return _field_names("StressIntraday")

    def test_stress_level_field(self, fields):
        assert "stressLevel" in fields, (
            f"Field 'stressLevel' missing from StressIntraday. "
            f"Available fields: {sorted(fields)}"
        )


# -------------------------------------------------------------------
# Critical fields in BodyBatteryIntraday
# -------------------------------------------------------------------

class TestBodyBatteryIntradayFields:

    @pytest.fixture(scope="class")
    def fields(self) -> set[str]:
        return _field_names("BodyBatteryIntraday")

    def test_body_battery_level_field(self, fields):
        assert "BodyBatteryLevel" in fields, (
            f"Field 'BodyBatteryLevel' missing from BodyBatteryIntraday. "
            f"Available fields: {sorted(fields)}"
        )
