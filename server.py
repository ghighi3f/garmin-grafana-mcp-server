"""
Garmin MCP Server — data access layer for garmin-grafana InfluxDB.

All HTTP transports are always active simultaneously:
  • POST /mcp        — Streamable HTTP  (ChatGPT, VS Code, modern clients)
  • GET  /sse        — SSE stream       (Perplexity, legacy — deprecated in MCP spec)
  • POST /messages/  — SSE message endpoint
  • GET  /health     — health / readiness probe

For local subprocess clients (Claude Desktop, Cursor, Windsurf, Claude Code):
  set MCP_TRANSPORT=stdio and run with `python server.py` (no HTTP server).

All fifteen MCP tools work identically across every transport.

Tools:
  • get_last_activity
  • get_recent_activities
  • get_weekly_load_summary
  • get_daily_recovery
  • get_activity_details
  • get_fitness_trend
  • get_training_zones
  • explore_schema
  • get_stress_body_battery
  • get_personal_records
  • get_training_status
  • get_sleep_physiology       (NEW — overnight autonomic deep-dive)
  • get_activity_load_history  (NEW — per-session load attribution)
  • get_daily_energy_balance   (NEW — non-training recovery context)
  • get_fitness_age            (NEW — long-term base-building compass)

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
# MCP_TRANSPORT is only consulted to detect stdio mode (MCP_TRANSPORT=stdio).
# All HTTP transports (Streamable HTTP + SSE) are always mounted simultaneously.
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "http").lower().strip()

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
from tools.training_status import get_training_status  # noqa: E402
from tools.sleep_physiology import get_sleep_physiology  # noqa: E402
from tools.activity_load import get_activity_load_history  # noqa: E402
from tools.energy_balance import get_daily_energy_balance  # noqa: E402
from tools.fitness_age import get_fitness_age  # noqa: E402

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
    avg_power, training_load (Garmin EPOC load), aerobic_training_effect
    (0–5), anaerobic_training_effect (0–5).  Fields not recorded by
    Garmin show as null.

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
                             body_battery_change, resting_hr, SpO2,
                             highest/lowest_respiration, highest_spo2
        - daily            : resting_hr, body_battery_at_wake/high/low,
                             body_battery_during_sleep, total_steps,
                             stress breakdown (minutes), activity_stress_min/pct,
                             active_calories, bmr_kcal, intensity minutes,
                             sedentary/active/highly_active/sleeping hours,
                             SpO2, floors_ascended/descended + meters
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


@mcp.tool()
async def get_training_status_tool() -> dict:
    """
    Fetch the latest Training Status and Training Readiness from InfluxDB.

    No input parameters required.

    Returns
    -------
    training_status
        Most recent entry from the TrainingStatus measurement, containing:
        - status_code         : Garmin training status enum (integer)
        - status_label        : Raw FIT SDK phrase code (e.g. "PRODUCTIVE_6")
        - garmin_coaching_advice : Human-readable coaching text decoded from the
                               FIT SDK training_status_feedback_phrase enum
                               (e.g. "Primarily aerobic training"); null if unknown
        - acute_load          : 7-day acute training load
        - chronic_load        : 28-day chronic training load (CTL)
        - load_balance_ratio  : Acute / chronic workload ratio (ACWR)
        - acwr_percent        : ACWR expressed as a percentage
        - fitness_trend       : Fitness trend indicator (integer)
        - max_chronic_load    : Upper bound of optimal chronic load range
        - min_chronic_load    : Lower bound of optimal chronic load range
        - timestamp           : Time of the record
    training_readiness
        Most recent entry from the TrainingReadiness measurement (requires
        garmin-grafana v0.4.0+), or null if unavailable, containing:
        - score               : Readiness score 0–100
        - description         : Readiness label (e.g. "Good", "Fair")
        - sleep_score, hrv_ratio, recovery_time_h, stress_history,
          activity_history
    data_note / training_readiness_note
        Present only when a measurement is unavailable; explains why.
    """
    return await get_training_status()


@mcp.tool()
async def get_sleep_physiology_tool(days: int = 7) -> dict:
    """
    Return nightly autonomic physiology from SleepIntraday epoch data,
    merged with enriched SleepSummary (respiration + SpO2 ranges).

    Parameters
    ----------
    days : int
        Look-back window in days.  Range: 1–14.  Default: 7.

    Returns
    -------
    nights : list
        One entry per date (newest first), each containing:
        - intraday  : heart_rate/hrv/respiration/spo2 (min/max/mean),
                      stress (mean), body_battery (first/last/min/max),
                      restlessness (mean), epoch_count
        - summary   : sleep_score, total_sleep_hours, stage durations,
                      avg_overnight_hrv, avg_sleep_stress,
                      body_battery_change, resting_hr,
                      highest/lowest_respiration, highest/lowest_spo2
    summary
        Period averages: avg_min_hr, avg_mean_hrv, avg_mean_respiration,
        avg_min_spo2, avg_body_battery_charged.
        Trends: min_hr_trend, hrv_trend, respiration_trend.
    """
    return await get_sleep_physiology(days=days)


@mcp.tool()
async def get_activity_load_history_tool(
    days: int = 14,
    sport_type: str = "all",
    limit: int = 30,
) -> dict:
    """
    Return per-activity training load and training effect scores.

    Shows which sessions are driving your acute load — complements
    get_training_status (which gives aggregate ACWR only).

    Parameters
    ----------
    days : int
        Look-back window in days.  Range: 1–90.  Default: 14.
    sport_type : str
        Filter by sport (e.g. "running", "cycling").  Default: "all".
    limit : int
        Maximum activities returned.  Range: 1–100.  Default: 30.

    Returns
    -------
    activities
        List (newest first), each with: activity_id, sport_type,
        distance_km, duration_minutes, training_load (Garmin EPOC),
        aerobic_training_effect (0–5), anaerobic_training_effect (0–5),
        avg_hr, max_hr, intensity_minutes.
    summary
        total_load, avg_load_per_session, load_by_sport,
        highest_load_activity, avg_aerobic_te, avg_anaerobic_te.
    """
    return await get_activity_load_history(
        days=days, sport_type=sport_type, limit=limit,
    )


@mcp.tool()
async def get_daily_energy_balance_tool(days: int = 7) -> dict:
    """
    Return daily time-use breakdown, caloric data, movement patterns,
    and stress attribution from DailyStats.

    Reveals what happens in the 14–16 waking hours between workouts and
    sleep — sedentary time, NEAT movement, and training-vs-life stress.

    Parameters
    ----------
    days : int
        Look-back window in days.  Range: 1–14.  Default: 7.

    Returns
    -------
    days : list
        One entry per date (newest first), each containing:
        - time_use            : sedentary/active/highly_active/sleeping hours
        - energy              : bmr_kcal, active_kcal
        - movement            : total_steps, distance_km, floors up/down + meters
        - recovery_context    : body_battery_during_sleep, body_battery_at_wake,
                                resting_hr
        - stress_attribution  : activity_stress_min/pct, total_stress_min,
                                stress_pct, uncategorized_stress_min
    summary
        Period averages for time-use, BMR, body battery during sleep.
        Trends: sedentary_trend, bb_during_sleep_trend.
    """
    return await get_daily_energy_balance(days=days)


@mcp.tool()
async def get_fitness_age_tool(weeks: int = 12) -> dict:
    """
    Return weekly-sampled fitness age trajectory.

    Tracks fitness age vs chronological age and the achievable fitness age
    target — a single metric for long-term base-building progress.

    Parameters
    ----------
    weeks : int
        Look-back window in weeks.  Range: 4–52.  Default: 12.

    Returns
    -------
    weeks : list
        One entry per ISO week (newest first), each containing:
        - fitness_age, chronological_age, achievable_fitness_age
        - fitness_age_gap     : fitness_age - chronological_age (negative = younger)
        - improvement_potential : fitness_age - achievable_fitness_age
    trends
        Delta between oldest and newest data points: fitness_age_change,
        fitness_age_gap_change, improvement_potential_change.
    """
    return await get_fitness_age(weeks=weeks)


# ---------------------------------------------------------------------------
# FastAPI app — all HTTP transports active simultaneously
# ---------------------------------------------------------------------------
from contextlib import asynccontextmanager  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from mcp.server.sse import SseServerTransport  # noqa: E402


async def _health_response() -> dict:
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
        "sse_endpoint": f"http://{host_display}:{MCP_PORT}/sse",
    }


# ── Streamable HTTP (/mcp) ────────────────────────────────────────────────
mcp_asgi = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[misc]
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Garmin MCP Server", version="1.1.0", redirect_slashes=False, lifespan=lifespan)


@app.get("/health", response_class=JSONResponse)
async def health_check() -> dict:
    return await _health_response()


# ── SSE transport (/sse + /messages/) ────────────────────────────────────
# Mounted as pure ASGI apps so the SSE transport owns the ASGI response
# lifecycle entirely — no "response already completed" RuntimeErrors.
_sse = SseServerTransport("/messages/")


async def _sse_asgi(scope, receive, send):
    async with _sse.connect_sse(scope, receive, send) as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream,
            write_stream,
            mcp._mcp_server.create_initialization_options(),
        )


async def _messages_asgi(scope, receive, send):
    await _sse.handle_post_message(scope, receive, send)


app.mount("/messages/", _messages_asgi)
app.mount("/sse", _sse_asgi)

# Streamable-HTTP catch-all must come after the more-specific /sse and
# /messages/ mounts so those paths are not swallowed by the root mount.
app.mount("/", mcp_asgi)


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------
def _print_banner() -> None:
    # In stdio mode stdout IS the MCP protocol channel — write only to stderr.
    out = sys.stderr if MCP_TRANSPORT == "stdio" else sys.stdout
    host_display = "localhost" if MCP_HOST in ("0.0.0.0", "") else MCP_HOST

    try:
        measurements = influx.get_measurements() if influx.ping() else ["<InfluxDB unreachable>"]
    except Exception:
        measurements = ["<error>"]

    def _p(line: str = "") -> None:
        print(line, file=out)

    _p()
    _p("=" * 60)
    _p("  Garmin MCP Server")
    _p("=" * 60)
    _p(f"  InfluxDB   : {influx.INFLUXDB_HOST}:{influx.INFLUXDB_PORT}/{influx.INFLUXDB_DATABASE}")
    _p(f"  Measurements: {measurements}")
    if MCP_TRANSPORT == "stdio":
        _p("  Transport  : stdio")
        _p("  Listening on stdin / stdout (no HTTP server)")
    else:
        _p("  Transports : HTTP + SSE (always active)")
        _p(f"  /mcp  (Streamable HTTP) : http://{host_display}:{MCP_PORT}/mcp")
        _p(f"  /sse  (SSE, deprecated) : http://{host_display}:{MCP_PORT}/sse")
        _p(f"  /health                 : http://{host_display}:{MCP_PORT}/health")
    _p("=" * 60)
    _p()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if MCP_TRANSPORT == "stdio":
        from mcp.server.stdio import stdio_server  # noqa: E402

        _print_banner()

        async def _run_stdio() -> None:
            async with stdio_server() as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )

        asyncio.run(_run_stdio())
    else:
        import uvicorn  # noqa: E402

        _print_banner()

        uvicorn.run(
            "server:app",
            host=MCP_HOST,
            port=MCP_PORT,
            reload=False,
            log_level="info",
        )
