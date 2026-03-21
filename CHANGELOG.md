# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`get_training_status_tool`** — new MCP tool (11th) exposing Garmin Training
  Status and Training Readiness data from InfluxDB.
  - Queries two measurements in parallel via `asyncio.gather()`:
    - `TrainingStatus` — acute load, chronic load, ACWR, fitness trend, and
      training status label (e.g. `"PRODUCTIVE_6"`).
    - `TrainingReadiness` — readiness score (0–100), description, sleep score,
      HRV ratio, recovery time, stress history, and activity history.
  - **Fully graceful fallback:** both query functions are Tier-2 (non-fatal). If
    either measurement is absent (e.g. `TrainingReadiness` requires
    garmin-grafana v0.4.0+), the field returns `null` plus a human-readable
    `data_note` or `training_readiness_note`. The server never crashes.
  - Confirmed `TrainingStatus` schema against live InfluxDB: fields verified as
    `trainingStatus` (int enum), `trainingStatusFeedbackPhrase` (string),
    `dailyTrainingLoadAcute`, `dailyTrainingLoadChronic`,
    `dailyAcuteChronicWorkloadRatio`, `acwrPercent`, `fitnessTrend`,
    `maxTrainingLoadChronic`, `minTrainingLoadChronic`.
  - New normaliser functions in `influx.py`: `_normalise_training_status()` and
    `_normalise_training_readiness()`, both using `pick()` with camelCase-first
    field candidates and env-var-overridable defaults.
  - New query functions in `influx.py`: `query_latest_training_status()` and
    `query_latest_training_readiness()` (both non-fatal: catch all exceptions,
    return `None` on empty result or DB error).
  - New tool module: `tools/training_status.py`.
  - Registered in `server.py` as the 11th MCP tool.
  - Added to `test_tools.py` integration test (test 10/10).

- **New environment variables** for Training Status schema overrides (all
  commented out in `.env.example` — defaults match the standard garmin-grafana
  schema and require no changes for most users):
  - `MEASUREMENT_TRAINING_STATUS` (default: `TrainingStatus`)
  - `MEASUREMENT_TRAINING_READINESS` (default: `TrainingReadiness`)
  - `FIELD_TRAINING_STATUS_CODE` (default: `trainingStatus`)
  - `FIELD_TRAINING_STATUS_LABEL` (default: `trainingStatusFeedbackPhrase`)
  - `FIELD_ACUTE_LOAD` (default: `dailyTrainingLoadAcute`)
  - `FIELD_CHRONIC_LOAD` (default: `dailyTrainingLoadChronic`)
  - `FIELD_LOAD_BALANCE_RATIO` (default: `dailyAcuteChronicWorkloadRatio`)
  - `FIELD_ACWR_PERCENT` (default: `acwrPercent`)
  - `FIELD_FITNESS_TREND` (default: `fitnessTrend`)
  - `FIELD_READINESS_SCORE` (default: `trainingReadinessScore`)
  - `FIELD_READINESS_LABEL` (default: `trainingReadinessDescription`)

## [1.1.0] - 2026-03-20

### Highlights

- **FIX:** Removed dangerous distance/duration heuristics, replacing them with strict SI unit divisions to resolve the phantom PR bug.
- **FEAT:** Added `highest_max_power` personal record via memory-safe, server-side `MAX()` aggregate.
- **DOCS:** Added explicit tool documentation instructing LLMs that Normalized Power (NP) cannot be calculated, preventing OOM hallucinations.

### Changed

- **Expanded sport type support** — `get_recent_activities` and
  `get_training_zones` now accept any Garmin sport type string (e.g.
  "hiking", "trail_running", "strength_training"), not just the
  previously hardcoded set of "running", "cycling", and "swimming".
  The special value "all" still means "no filter".
  - Removed hardcoded validation gates in `tools/activity.py` and
    `tools/fitness.py`.
  - Centralised pace-vs-speed sport set as `PACE_SPORTS` constant in
    `influx.py`, used by both `normalise_activity()` and `normalise_lap()`.
  - Added `trail_running` and `trail running` to the pace sports set.
  - Updated MCP tool docstrings in `server.py` to document arbitrary
    sport type support.

- **Regex-based sport filtering** — InfluxQL and Flux queries now use
  regex matching (`=~ /.*{sport_type}.*/`) instead of strict equality
  for sport_type filtering. This catches sub-sports automatically (e.g.
  filtering by "cycling" also matches "indoor_cycling", "road_biking").
  Post-fetch filtering in `tools/fitness.py` uses substring matching
  for consistency.

### Fixed

- **Unit conversion heuristics removed** — `normalise_activity()` and
  `normalise_lap()` had heuristics that treated small raw values as "already
  converted" (distance < 500 → assumed km, duration < 300 → assumed minutes).
  Since garmin-grafana always stores distance in metres and duration in seconds,
  short activities (e.g. a 230-metre ride) were reported with wildly inflated
  values (230 km). Conversions are now unconditional: always divide by 1000 for
  distance, always divide by 60 for duration.

- **`longest_duration` personal record used elapsed time instead of moving time**
  — paused activities (e.g. a ride with a 12-hour cafe stop) inflated the record.
  Now uses `moving_duration_minutes` (from `movingDuration`) which excludes pauses.

- **Walk and hiking activities now correctly suppress speed** —
  `normalise_activity()` had an inconsistency where walk/hiking got
  pace (min/km) but also kept speed (km/h). Now uses the unified
  `PACE_SPORTS` constant, matching the existing `normalise_lap()` behavior.

- **`_get_sport()` field priority mismatch** — `tools/fitness.py` used
  a different field lookup order (`activityType` first) than
  `normalise_activity()` (`sport_type` first), which could produce
  different sport type strings for the same row. Now uses `pick()` with
  the same priority order.

- **Sport type query injection prevention** — added `sanitize_sport_type()`
  in `influx.py` that validates user-provided sport strings before
  interpolation into InfluxQL/Flux queries. Only alphanumeric characters,
  spaces, underscores, and hyphens are allowed.

- **CI:** Fixed version extraction in `.github/workflows/auto-tag-on-merge.yml`
  — the workflow used `${{ }}` expression syntax for bash parameter
  expansion (`#prefix`), which is not valid in GitHub Actions expressions.
  Now correctly assigns to a bash variable first and uses `${BRANCH#release/v}`.

### Added

- **`get_personal_records_tool`** — new MCP tool for all-time personal records
  per sport type. Uses a full scan of ActivitySummary with Python-side
  aggregation to find the best value for each metric (longest distance, longest
  duration, fastest pace/speed, top speed, highest HR, most calories, highest
  avg power) along with the **activity_id, date, and activity_name** of the
  record-setting activity. Pace/speed convention follows `PACE_SPORTS` (pace
  for running/swimming/walking/hiking, speed for cycling and other sports).
  - New query function in `influx.py`: `query_all_activities()`.
  - New tool module: `tools/records.py`.
  - Registered in `server.py` as the 10th MCP tool.
  - Added to `test_tools.py` integration test and `tests/test_normalizers.py`
    unit tests.

- **`moving_duration_minutes` field** added to `normalise_activity()` output —
  extracted from `movingDuration` / `moving_duration` in ActivitySummary.
  Represents actual moving time excluding pauses. All activity-level tool
  responses now include moving duration alongside elapsed duration.

- **Power/cadence backfill in `get_personal_records`** — `query_all_activities()`
  now bulk-fetches `Avg_Power` and `Avg_Cadence` from ActivityLap and computes
  duration-weighted averages per activity. Activities with power meter data (e.g.
  indoor trainer) now have `avg_power` and `avg_cadence` populated even
  though ActivitySummary lacks these fields. Adds `highest_avg_power` (watts)
  as a personal record metric.

- **`highest_max_power` personal record** — peak instantaneous power (watts) tracked
  across all activities via a server-side `MAX("Power")` aggregate on `ActivityGPS`.
  Lightweight: returns one row per activity, no raw samples transferred to Python.

- **`max_speed_kmh` field** added to `normalise_activity()` output — extracted
  from `maxSpeed` / `max_speed` / `enhanced_max_speed` in ActivitySummary.
  All activity-level tool responses now include top speed.

- **`activity_name` field** added to `normalise_activity()` output — extracted
  from `activityName` / `activity_name` / `name` in ActivitySummary.

- **`get_stress_body_battery_tool`** — new MCP tool for daily stress breakdown
  and body battery trend over 7–30 days. Returns per-day stress minutes
  (high/medium/low/rest) and body battery levels (at wake/high/low/drained/charged),
  plus summary averages and trend direction ("improving"/"declining"/"stable").
  - New tool module: `tools/stress.py`.
  - Registered in `server.py` as the 9th MCP tool.
  - Added to `test_tools.py` integration test.

- **Duration-weighted cadence/power backfill** in `get_activity_details` —
  `avg_cadence` and `avg_power` are now computed from ActivityLap data
  (weighted by lap duration) when ActivitySummary lacks these fields.

### Changed

- **Connection pooling** — `influx.py` now uses lazy thread-safe singletons
  (double-checked locking) instead of creating a new InfluxDB client on every
  query. Graceful cleanup via `atexit`. Removes all per-call `client.close()`
  patterns from `_v1_query`, `_v2_query`, `ping`, `query_field_keys`,
  `query_tag_keys`, and measurement-list helpers.

- **Async I/O** — all tool functions now wrap synchronous InfluxDB calls in
  `asyncio.to_thread()` to avoid blocking uvicorn's event loop. Independent
  queries parallelized with `asyncio.gather()` (fitness trend: 4 queries,
  activity detail: session+laps, schema: fields+tags, load: resting HR+HRV).

- **DRY refactor of `tools/detail.py`** — replaced ~65 lines of duplicated
  normalisation logic with a call to `influx.normalise_activity()` for base
  fields, overlaying detail-only extras (activity name, moving duration, max
  speed, lap count, location, description). Eliminates field-name candidate
  drift between the two code paths.

### Fixed

- **Multi-device row deduplication** — garmin-grafana writes one row per paired
  Garmin device (e.g. Edge 540 + Forerunner 165), causing doubled data. Added
  `_dedup_rows()` and `_dedup_laps()` helpers in `influx.py` that group rows by
  timestamp (and lap index for laps), keeping the row with the most populated
  fields. Applied to `query_activity_summary_by_id`,
  `query_activity_session_by_id`, `query_activity_laps_by_id`, and
  `query_daily_stats`.

- **`get_stress_body_battery` now includes today's partial data** — when DailyStats
  lacks today's row (common before end-of-day sync), the tool synthesises today's
  entry from `StressIntraday` and `BodyBatteryIntraday` measurements. Stress readings
  are categorised into Garmin's standard rest/low/medium/high buckets; body battery
  reports today's high, low, charged, and drained values. Each day now includes a
  `"source"` field (`"daily_stats"` or `"intraday"`) to distinguish complete vs
  partial data. `body_battery_at_wake` is `null` for intraday days (requires
  sleep-tracking context). New env vars: `MEASUREMENT_STRESS_INTRADAY`,
  `MEASUREMENT_BODY_BATTERY_INTRADAY`, `FIELD_STRESS_LEVEL`,
  `FIELD_BODY_BATTERY_LEVEL`.

## [1.0.0] - 2026-03-19

### Fixed

- **CI:** Prevent double Docker build on release — `.github/workflows/docker-publish.yml`
  now triggers only on pushed tags `v*.*.*` (and `workflow_dispatch`), and
  `docker/metadata-action` now applies both the semantic version tag and
  the `latest` tag when a `v*.*.*` tag is pushed. Updated
  `copilot-instructions.md` Release Management Workflow to clarify the change.


### Added

- **Automated GitHub Releases** — `docker-publish.yml` now triggers on `v*.*.*`
  tag pushes in addition to `main` branch pushes. Tag pushes build versioned
  Docker images (e.g. `:1.2.0`, `:1.2`) and create a GitHub Release with
  auto-generated release notes via `softprops/action-gh-release@v2`.
  Added "Release Management Workflow" section to `copilot-instructions.md`.

- **`pytest` test suite** — regression protection and upstream schema validation.
  - `tests/test_normalizers.py` — offline unit tests for `normalise_activity`,
    `normalise_daily_stats`, `normalise_sleep`, `normalise_lap`, and `utils.py`
    helpers (`pick`, `safe_float`, `safe_int`, `iso_week_label`,
    `week_start_from_label`). Covers edge cases: empty rows, zero-value zones,
    sentinel rows, camelCase/snake_case field variants, unit conversions.
  - `tests/test_live_schema.py` — live InfluxDB schema assertions. Verifies
    mandatory measurements exist and critical fields haven't been renamed.
    Auto-skipped when no DB connection is available.
  - `tests/conftest.py` — shared fixtures and `sys.path` setup.
  - Added `pytest>=8.0.0` and `pytest-asyncio>=0.23.0` to `requirements.txt`.
  - Added "Testing Requirements" section to `copilot-instructions.md`.
  - **CI:** GitHub Actions workflow (`.github/workflows/python-tests.yml`) runs
    offline unit tests on every PR targeting `development`.

- **`explore_schema_tool`** — new MCP tool for runtime InfluxDB schema
  introspection. Call with no arguments to list all measurements; call with a
  measurement name to get exact field names, types, and tag keys.  AI agents
  should use this tool to verify field names before building queries.
  - New query functions in `influx.py`: `query_field_keys()`, `query_tag_keys()`
    (InfluxQL v1 and Flux v2 support).
  - New tool module: `tools/schema.py`.

### Changed

- **Branch model now uses `development` as the base branch** — feature branches
  are checked out from `development` and PRs target `development`.  Merges into
  `main` only happen for batch releases (triggering the Docker image build).
  Updated `copilot-instructions.md` accordingly.

### Fixed

- **Sentinel "No Activity" rows no longer leak into tool responses** — `query_last_activity()`
  now fetches up to 5 rows and skips rows where `sport_type` normalises to `"no activity"`,
  returning the first real activity. `query_recent_activities()` filters sentinel rows from
  the returned list before it reaches any tool. Both `get_last_activity` and
  `get_recent_activities` / `get_weekly_load_summary` subsequently receive clean data.

- **`duration_minutes` now populated for all activities** — `normalise_activity()` was
  missing the camelCase field variants used by garmin-grafana (`elapsedDuration`,
  `movingDuration`, `totalElapsedTime`). The `pick()` call now tries these names first,
  so elapsed duration converts correctly from seconds to minutes.

- **`avg_resting_hr` and `hrv_weekly_avg` now populated in weekly tools** — the default
  field names `FIELD_RESTING_HR` and `FIELD_HRV` were `resting_hr` and `hrv5MinHigh`
  respectively, but the actual garmin-grafana field names are `restingHeartRate` and
  `hrvValue`. Defaults corrected in `influx.py`; `.env.example` updated to match.
  Existing deployments must update `FIELD_RESTING_HR=restingHeartRate` and
  `FIELD_HRV=hrvValue` in their `.env` and redeploy.

- **`zone_N_pct` is now `null` when `zone_N_minutes` is `null`** — previously, minutes
  for a zero-time zone were `null` (via `0.0 or None`) but the percentage was `0.0`,
  an inconsistent pair. The `_zone_pct()` helper in both `normalise_activity()` and
  `tools/detail.py` now returns `null` when the per-zone value is zero or absent.

- **`elevation_gain_m` now picks up `totalAscent`** — garmin-grafana stores this field
  as `totalAscent` (camelCase); added as first candidate in the `pick()` call inside
  `normalise_activity()`.

### Added

- **`test_tools.py`** — standalone validation script that calls all seven MCP tool
  functions directly (no HTTP layer) and prints the full JSON response or any traceback
  to stdout. Useful for verifying InfluxDB schema field names against live data.

### Changed

- **Sensible defaults for zero-config Docker deployment** — fix
  `MEASUREMENT_ACTIVITIES` default from `Activities` → `ActivitySummary`,
  `MEASUREMENT_RESTING_HR` default from `RestingHeartRate` → `DailyStats`, and
  `MEASUREMENT_HRV` default from `HRV` → `HRV_Intraday` in `influx.py` to
  match the standard garmin-grafana schema. Users pulling the pre-built GHCR
  image no longer need to provide any schema environment variables.

### Added

- **Quick Start (Docker Compose) section** in `README.md` — copy-pasteable
  `docker-compose.yml` snippet using the public GHCR image with an inline
  `environment:` block. Lists required variables (URL, credentials, database)
  and optional schema overrides (measurement and field names, commented out).

- **HR zone percentages** across all tools that return zone data:
  - `get_recent_activities` / `get_last_activity` — `normalise_activity()` now
    returns an `hr_zones` object with `zone_N_minutes` **and** `zone_N_pct`
    (percentage of total zone time) for zones 1–5. `hr_zones` is `null` when
    no zone data is present for that activity.
  - `get_activity_details` — `hr_zones` now includes `zone_N_pct` alongside
    the existing `zone_N_minutes` fields, with a stable shape (null values)
    even when no zone data was recorded.

- **CI:** Add GitHub Actions workflow to build and push the Docker image
  to GitHub Container Registry (`.github/workflows/docker-image.yml`).
  This introduced the first automated image build and push.

- **CI:** Remove duplicate `docker-image.yml` workflow in favor of a
  single consolidated `docker-publish.yml` workflow (multi-arch build,
  metadata tags, manual dispatch). The repository now builds and pushes
  images using `.github/workflows/docker-publish.yml`.

## [0.1.0] - 2025-03-18

### Added

- **MCP server** with streamable-HTTP transport (SSE fallback for older `mcp` versions).
- **7 MCP tools** exposing Garmin training data from InfluxDB:
  - `get_last_activity` — most recent activity with full metrics.
  - `get_recent_activities` — activities over N days with summary aggregates.
  - `get_weekly_load_summary` — ISO-week training volume, resting HR, and HRV.
  - `get_daily_recovery` — sleep quality + daily health merged by date.
  - `get_activity_details` — HR zones, training effect, and per-lap splits.
  - `get_fitness_trend` — VO2max, race predictions, weight, resting HR over weeks.
  - `get_training_zones` — HR zone distribution and polarization analysis.
- **`/health` endpoint** returning InfluxDB status, last activity timestamp, and available measurements.
- **InfluxDB v1 and v2 support** — query layer auto-selects InfluxQL or Flux.
- **Fully configurable schema** — all measurement and field names overridable via environment variables.
- **Normalizer functions** handling garmin-grafana field-name variations across versions.
- **Docker deployment** with `docker-compose.yml` joining the existing `garmin-grafana_default` network.
- **DNS-rebinding protection** configurable via `ALLOWED_HOSTS`.
- **Startup banner** with InfluxDB connection status and endpoint URLs.
