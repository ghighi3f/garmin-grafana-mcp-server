# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
