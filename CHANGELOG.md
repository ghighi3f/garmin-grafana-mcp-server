# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
