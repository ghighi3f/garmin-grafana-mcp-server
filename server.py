"""
Garmin MCP Server — data access layer for garmin-grafana InfluxDB.

Exposes nine MCP tools over HTTP (streamable-HTTP transport):
  • get_last_activity
  • get_recent_activities
  • get_weekly_load_summary
  • get_daily_recovery
  • get_activity_details
  • get_fitness_trend
  • get_training_zones
  • explore_schema
  • get_stress_body_battery

Also provides a /health REST endpoint and a startup banner.
"""

from __future__ import annotations

import os
import sys
import logging
import asyncio

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", 8765))

# Import after env vars are loaded so influx.py picks them up
import influx  # noqa: E402
from tools.activity import get_last_activity, get_recent_activities  # noqa: E402
from tools.load import get_weekly_load_summary  # noqa: E402
from tools.recovery import get_daily_recovery  # noqa: E402
from tools.detail import get_activity_details  # noqa: E402
from tools.fitness import get_fitness_trend, get_training_zones  # noqa: E402
from tools.schema import explore_schema  # noqa: E402
from tools.stress import get_stress_body_battery  # noqa: E402
from tools.records import get_personal_records  # noqa: E402

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "garmin-local",
    instructions=(
        "Provides raw Garmin training data from a local InfluxDB instance "
        "populated by garmin-grafana. Covers activity summaries, lap splits, "
        "HR zones, training effect, daily recovery (sleep + body battery + "
        "stress), fitness trends (VO2max, race predictions, weight), and "
        "training intensity distribution. All data is uninterpreted — the "
        "model is responsible for analysis and recommendations."
    ),
)

# Configure DNS-rebinding protection.
# ALLOWED_HOSTS accepts comma-separated "hostname:*" patterns.
# When unset, protection is disabled so any hostname (e.g. pi5.pi-home) works.
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

_allowed_hosts_raw = os.getenv("ALLOWED_HOSTS", "").strip()
if _allowed_hosts_raw:
    _allowed_hosts = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
    )
else:
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )


@mcp.tool()
async def get_last_activity_tool() -> dict:
    """
    Return the single most recent Garmin activity from InfluxDB.

    No input parameters required.

    Returns fields: timestamp, sport_type, distance_km, duration_minutes,
    avg_hr, max_hr, calories, avg_pace_min_per_km (runs/swims),
    avg_speed_kmh (cycling/other), elevation_gain_m, avg_cadence,
    avg_power.  Fields not recorded by Garmin show as null.

    Power note: only avg_power (duration-weighted average from lap data) is
    available.  Normalized Power (NP) cannot be queried or calculated — the
    upstream database does not store the required second-by-second data in a
    form that can be aggregated without crashing the server.  Do not attempt
    to compute or estimate NP.
    """
    return await get_last_activity()


@mcp.tool()
async def get_recent_activities_tool(
    days: int = 7,
    sport_type: str = "all",
    limit: int = 20,
) -> dict:
    """
    Return Garmin activities from the last N days.

    Parameters
    ----------
    days : int
        Look-back window in days.  Range: 1–90.  Default: 7.
    sport_type : str
        Filter by sport.  Any valid Garmin sport type string
        (e.g. "running", "cycling", "swimming", "hiking",
        "trail_running", "strength_training").  Supports partial
        matching for sub-sports (e.g. "cycling" matches
        "indoor_cycling").  Use "all" for no filter.  Default: "all".
    limit : int
        Maximum number of records returned.  Range: 1–100.  Default: 20.

    Returns
    -------
    activities
        List of activity objects (newest first), each with the same
        fields as get_last_activity.
    summary
        Aggregate block: total_activities, total_distance_km_by_sport,
        total_duration_minutes, date_range_from, date_range_to.
    """
    return await get_recent_activities(days=days, sport_type=sport_type, limit=limit)


@mcp.tool()
async def get_weekly_load_summary_tool(weeks: int = 4) -> dict:
    """
    Group Garmin activities into ISO calendar weeks and return raw aggregates.

    Parameters
    ----------
    weeks : int
        Number of past weeks to include.  Range: 1–16.  Default: 4.

    Returns
    -------
    weeks : list
        One entry per ISO week (newest first), each containing:
        - week_label           : "YYYY-Www"
        - week_start_date      : ISO date of the Monday
        - per_sport            : { sport: { sessions, total_distance_km,
                                            total_duration_min } }
        - avg_resting_hr       : weekly average resting HR, or null
        - hrv_weekly_avg       : weekly average HRV, or null
        - stress_or_load_score : raw field from InfluxDB, or null

    No derived fitness metrics (ATL/CTL/TSB) are computed.
    """
    return await get_weekly_load_summary(weeks=weeks)


@mcp.tool()
async def get_daily_recovery_tool(days: int = 7) -> dict:
    """
    Return daily recovery and readiness data combining sleep quality
    with daily health metrics.

    Parameters
    ----------
    days : int
        Look-back window in days.  Range: 1–14.  Default: 7.

    Returns
    -------
    days : list
        One entry per date (newest first), each containing:
        - date             : ISO date string
        - sleep            : sleep_score, total_sleep_hours, deep/light/rem/awake
                             hours, avg_overnight_hrv, avg_sleep_stress,
                             body_battery_change, resting_hr, SpO2
        - daily            : resting_hr, body_battery_at_wake/high/low,
                             total_steps, stress breakdown (minutes),
                             active_calories, intensity minutes, SpO2
    summary
        Period averages: avg_sleep_score, avg_sleep_hours, avg_overnight_hrv,
        avg_resting_hr, avg_body_battery_at_wake.
    """
    return await get_daily_recovery(days=days)


@mcp.tool()
async def get_activity_details_tool(activity_id: str) -> dict:
    """
    Return detailed breakdown of a single activity including HR zones,
    training effect, and per-lap splits.

    Parameters
    ----------
    activity_id : str
        The activity ID.  Discoverable from get_recent_activities_tool
        (each activity includes an activity_id field).

    Returns
    -------
    activity
        Core metrics (distance, duration, HR, speed) plus:
        - hr_zones        : minutes in each zone (1–5)
        - training_effect : aerobic and anaerobic (0–5 scale)
    laps
        Per-lap splits: distance_km, elapsed_time_minutes, avg_hr,
        max_hr, pace or speed, cadence, power.
    analysis_hints
        Pre-computed: fastest/slowest lap index, pace range,
        HR drift percentage (cardiac drift detection).
    """
    return await get_activity_details(activity_id=activity_id)


@mcp.tool()
async def get_fitness_trend_tool(weeks: int = 12) -> dict:
    """
    Return long-term fitness trajectory sampled weekly.

    Parameters
    ----------
    weeks : int
        Look-back window in weeks.  Range: 4–52.  Default: 12.

    Returns
    -------
    weeks : list
        One entry per ISO week (newest first), each containing:
        - vo2max_running / vo2max_cycling
        - race_predictions : 5K/10K/half/marathon times (formatted + seconds)
        - weight_kg
        - avg_resting_hr
    trends
        Delta between oldest and newest data points for key metrics
        (vo2max, weight, resting HR, 5K time).
    """
    return await get_fitness_trend(weeks=weeks)


@mcp.tool()
async def get_training_zones_tool(days: int = 30, sport_type: str = "all") -> dict:
    """
    Aggregate HR zone distribution across activities in the period.

    Parameters
    ----------
    days : int
        Look-back window in days.  Range: 7–180.  Default: 30.
    sport_type : str
        Filter by sport.  Any valid Garmin sport type string
        (e.g. "running", "cycling", "swimming", "hiking",
        "trail_running").  Supports partial matching for sub-sports.
        Use "all" for no filter.  Default: "all".

    Returns
    -------
    zone_distribution
        Total minutes and percentage per zone (1–5).
    polarization
        Three-band breakdown: low_intensity_pct (zone 1+2),
        moderate_intensity_pct (zone 3), high_intensity_pct (zone 4+5).
        Useful for detecting the "moderate intensity trap" in training.
    by_sport
        Per-sport zone percentages (only when multiple sports present).
    """
    return await get_training_zones(days=days, sport_type=sport_type)


@mcp.tool()
async def explore_schema_tool(measurement_name: str | None = None) -> dict:
    """
    Explore the InfluxDB schema to discover available measurements, fields,
    and tags.  AI agents should call this tool BEFORE attempting to build
    queries or reference field names (e.g. to verify whether the elevation
    field is called "totalAscent", "elevationGain", or something else).

    Usage
    -----
    1. Call with no arguments to list every measurement (table) in the
       database (e.g. ActivitySummary, DailyStats, SleepSummary, ...).
    2. Call with a measurement_name (e.g. "ActivitySummary") to get the
       exact field names and their data types, plus any tag keys.

    Parameters
    ----------
    measurement_name : str, optional
        The measurement to inspect.  Omit to list all measurements.

    Returns
    -------
    measurements : list[str]
        (when measurement_name is omitted) All measurement names in the DB.
    fields : list[dict]
        (when measurement_name is given) Each entry has "field" (name) and
        "type" (e.g. "float", "integer", "string").
    tags : list[str]
        (when measurement_name is given) Tag key names.
    """
    return await explore_schema(measurement_name=measurement_name)


@mcp.tool()
async def get_stress_body_battery_tool(days: int = 7) -> dict:
    """
    Return daily stress breakdown and body battery trend.

    Parameters
    ----------
    days : int
        Look-back window in days.  Range: 7–30.  Default: 7.

    Returns
    -------
    days : list
        One entry per date (newest first), each containing:
        - stress       : high_min, medium_min, low_min, rest_min,
                         total_stress_min
        - body_battery : at_wake, high, low, drained, charged
    summary
        Period averages and trend direction for body battery
        ("improving" / "declining" / "stable") and stress
        ("improving" / "worsening" / "stable").
    """
    return await get_stress_body_battery(days=days)


@mcp.tool()
async def get_personal_records_tool(sport_type: str = "all") -> dict:
    """
    Return all-time personal records (best metrics) grouped by sport type.

    Uses a full scan of ActivitySummary to find the best value for each
    metric, along with the activity_id, date, and activity_name of the
    record-setting activity.

    Parameters
    ----------
    sport_type : str
        Filter by sport.  Any valid Garmin sport type string
        (e.g. "running", "cycling", "swimming", "hiking",
        "trail_running").  Supports partial matching for sub-sports.
        Use "all" to get records for every sport.  Default: "all".

    Returns
    -------
    records_by_sport
        Dict keyed by sport type, each containing records with:
        - longest_distance, longest_duration, top_speed,
          highest_max_hr, highest_avg_hr, most_calories,
          highest_avg_power, highest_max_power
        - fastest_avg_pace (pace sports) or fastest_avg_speed (speed sports)
        Each record has: value, unit, activity_id, date, activity_name.
    summary
        total_sports, total_activities, sport_list.

    Power limitation: only avg_power (duration-weighted lap average) and
    max_power (peak watt from ActivityGPS) are available.  Normalized Power
    (NP) is impossible to calculate — do not attempt to query, compute, or
    estimate it.  The database does not expose the necessary data without
    transferring millions of raw samples, which will crash the server.
    """
    return await get_personal_records(sport_type=sport_type)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
from contextlib import asynccontextmanager  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

# Build the MCP ASGI app first — this initialises mcp.session_manager which
# the lifespan below must start.  FastAPI does not propagate lifespan events
# to mounted sub-apps, so we drive the session-manager lifecycle ourselves.
try:
    mcp_asgi = mcp.streamable_http_app()
    _transport_label = "streamable-HTTP"
except AttributeError:
    # Older mcp versions fall back to SSE
    mcp_asgi = mcp.sse_app()
    _transport_label = "SSE"


@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Garmin MCP Server", version="1.1.0", redirect_slashes=False, lifespan=lifespan)


@app.get("/health", response_class=JSONResponse)
async def health_check():
    """
    Liveness / readiness probe.

    Returns InfluxDB connectivity status, last recorded activity timestamp,
    available measurements, and the MCP endpoint URL.
    """
    connected = await asyncio.to_thread(influx.ping)
    influx_status = "connected" if connected else "unreachable"

    last_ts = None
    measurements: list[str] = []

    if connected:
        measurements = await asyncio.to_thread(influx.get_measurements)
        try:
            last = await asyncio.to_thread(influx.query_last_activity)
            if last:
                last_ts = last.get("timestamp")
        except Exception:
            pass

    host_display = "localhost" if MCP_HOST in ("0.0.0.0", "") else MCP_HOST
    return {
        "influxdb": influx_status,
        "last_activity_timestamp": last_ts,
        "measurements_found": measurements,
        "mcp_endpoint": f"http://{host_display}:{MCP_PORT}/mcp",
    }


app.mount("/", mcp_asgi)


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------
def _print_banner():
    host_display = "localhost" if MCP_HOST in ("0.0.0.0", "") else MCP_HOST
    measurements = influx.get_measurements() if influx.ping() else ["<InfluxDB unreachable>"]
    print()
    print("=" * 60)
    print("  Garmin MCP Server")
    print("=" * 60)
    print(f"  InfluxDB   : {influx.INFLUXDB_HOST}:{influx.INFLUXDB_PORT}/{influx.INFLUXDB_DATABASE}")
    print(f"  Measurements found: {measurements}")
    print(f"  Transport  : {_transport_label}")
    print(f"  MCP endpoint ready: http://{host_display}:{MCP_PORT}/mcp")
    print(f"  /health check:      http://{host_display}:{MCP_PORT}/health")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn  # noqa: E402

    _print_banner()

    uvicorn.run(
        "server:app",
        host=MCP_HOST,
        port=MCP_PORT,
        reload=False,
        log_level="info",
    )
