# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
