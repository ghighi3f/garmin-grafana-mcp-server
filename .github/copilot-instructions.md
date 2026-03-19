# Copilot Instructions — garmin-grafana-mcp-server

## What this project is

This is a **Model Context Protocol (MCP) server** built with **FastMCP** in Python.
It reads Garmin health and training data from a local **InfluxDB** instance
(populated by [garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana))
and exposes it as MCP tools for LLM clients (Claude, Copilot, etc.) to consume.

The server is a **pure data access layer** — it never interprets data, never
generates coaching advice, and never computes derived fitness metrics like
ATL/CTL/TSB. The LLM is responsible for analysis.

## Architecture

```text
LLM Client  ──HTTP/SSE──▶  server.py (FastAPI + FastMCP)
                               │
                               ▼
                           influx.py (all queries)
                               │
                               ▼
                         InfluxDB (v1 or v2)
                       populated by garmin-grafana
```

- `server.py` — FastAPI app, MCP tool registration, `/health`, startup banner.
- `influx.py` — All InfluxDB connection logic and queries. **Only** file that touches the database.
- `utils.py` — Shared helpers: `pick()`, `safe_float()`, `safe_int()`, `iso_week_label()`, `week_start_from_label()`.
- `tools/` — Directory containing categorized tools (`activity.py`, `load.py`, `recovery.py`, `detail.py`, `fitness.py`, `schema.py`).

## InfluxDB schema (garmin-grafana)

### Measurements

| Variable                      | Default value      | Contains                                  |
|-------------------------------|--------------------|-------------------------------------------|
| `MEASUREMENT_ACTIVITIES`      | `ActivitySummary`  | Per-activity: distance, duration, HR, etc.|
| `MEASUREMENT_ACTIVITY_SESSION`| `ActivitySession`  | Training effect, sub-sport                |
| `MEASUREMENT_ACTIVITY_LAP`    | `ActivityLap`      | Per-lap splits: pace, HR, cadence, power  |
| `MEASUREMENT_DAILY_STATS`     | `DailyStats`       | Body battery, stress, steps, resting HR   |
| `MEASUREMENT_SLEEP_SUMMARY`   | `SleepSummary`     | Sleep score, stages, HRV, SpO2            |
| `MEASUREMENT_RESTING_HR`      | `DailyStats`       | Resting heart rate field                  |
| `MEASUREMENT_HRV`             | `HRV_Intraday`     | HRV values (hrv5MinHigh)                  |
| `MEASUREMENT_VO2_MAX`         | `VO2_Max`          | VO2max running and cycling                |
| `MEASUREMENT_RACE_PREDICTIONS`| `RacePredictions`  | 5K, 10K, half, marathon times             |
| `MEASUREMENT_BODY_COMPOSITION`| `BodyComposition`  | Weight                                    |

### Key field-name conventions

garmin-grafana uses camelCase field names (e.g. `averageHR`, `sleepScore`, `bodyBatteryAtWakeTime`). The normalizers in `influx.py` handle multiple naming variants for robustness. All field and measurement names are configurable via env vars — see `.env.example`.

## Code conventions

1. **All queries live in `influx.py`** — tools never construct raw InfluxQL/Flux.
2. **Shared helpers live in `utils.py`**.
3. **Normalizers** handle field-name variations and unit conversions. Missing fields become `None`.
4. **Environmental configuration** — read from environment variables with sensible defaults.
5. **Input clamping** — every tool clamps its parameters to documented ranges.
6. **Error handling** — `ConnectionError` from InfluxDB returns a structured dict; never raises to the LLM.
7. **No planning logic** — tools return raw data only.

## Git & Workflow Rules

These rules are mandatory for the agent to follow to keep the repository consistent and CI/CD-friendly.

1. **Branch Management:**
    - NEVER write code directly on `main` or `development`.
    - The **base branch** for all new work is `development` (NOT `main`).
    - Create and switch to a descriptive branch from `development` (e.g., `git checkout -b feature/add-hr-zones development`).
    - Pull Requests should target `development`.

2. **Changelog Updates:**
    - Any time a feature is added, modified, or fixed, the agent MUST update `CHANGELOG.md` under the `## [Unreleased]` section.
    - Example: `- Add HR zone percentages to normalise_activity()`

3. **Commit & Pull Request Prep:**
    - Propose a standardized commit message: `feat(<scope>): short description` or `fix(<scope>): short description`.
    - Do not merge directly into `main`. Push the branch and create a PR.

## ⚠️ When adding a new tool (The Definition of Done)

When tasked with creating a new MCP tool, the agent MUST complete all of the following steps:

1. **Backend:** Add the query function to `influx.py` (with both v1 and v2 variants).
2. **Business Logic:** Create or extend a file in `tools/`. Use helpers from `utils.py`.
3. **MCP Registration:** Register the `@mcp.tool()` wrapper in `server.py`.
   - **Crucial:** Write a full docstring (Parameters + Returns). The LLM reads this to know how to use the tool.
   - **Crucial:** Use broad default arguments (e.g., `days=14`, `sport_type="all"`) to prevent LLM clients from accidentally querying too narrow a window and missing data.
4. **Testing:** Add or update tests in `tests/test_normalizers.py`. Run `pytest -v` inside the local Docker container to ensure no regressions.
5. **Documentation:** Update `README.md` to add the new tool to the "Available Tools" section. Add the tool to the docstring at the top of `server.py`.

## Testing Requirements

This project uses **pytest** for automated testing. All tests must pass before opening a Pull Request against the `development` branch.

### Test structure

```text
tests/
├── conftest.py              # sys.path setup so imports work
├── test_normalizers.py      # Offline unit tests for normalizer functions + utils
└── test_live_schema.py      # Live InfluxDB schema validation (skipped if no DB)
```

### Running tests

Run tests **inside the local Docker container**, not on the host machine. This project already has a Docker-based local workflow, and using the container keeps the Python environment and dependencies consistent with the app runtime.

```bash
# Start the local dev container if needed
docker compose up -d

# Unit tests only (offline, no DB needed)
docker compose exec garmin-grafana-mcp-server pytest tests/test_normalizers.py -v

# Live schema validation (requires InfluxDB + .env)
docker compose exec garmin-grafana-mcp-server pytest tests/test_live_schema.py -v

# Full suite
docker compose exec garmin-grafana-mcp-server pytest -v
```

### Rules for the agent

1. **Before creating a PR** against `development`, run `pytest -v` **inside the local container**, not on the host. Unit tests must pass with zero failures. Live schema tests may be skipped if no DB is available.
2. **When modifying normalizers** (`normalise_activity`, `normalise_daily_stats`, `normalise_sleep`, `normalise_lap` in `influx.py`), add or update the corresponding tests in `tests/test_normalizers.py`.
3. **When adding a new measurement or field dependency**, add a schema assertion to `tests/test_live_schema.py` so upstream renames are caught early.
4. Tests should be run from the app container because it is the preferred local development environment for this repo. Do not default to host-side `pytest` unless the user explicitly asks for that.
5. The agent must report the exact container test command it used when returning code changes.

## Testing locally

```bash
cp .env.example .env
docker compose up -d
docker compose exec garmin-grafana-mcp-server pytest -v
```

For containerized development, prefer running commands inside `garmin-grafana-mcp-server` rather than on the host.

## Release Management Workflow

1. Ensure all feature PRs are merged into `development`.
2. Move entries from `## [Unreleased]` in `CHANGELOG.md` into a new `## [X.Y.Z] - YYYY-MM-DD` section.
3. Push a PR from `development` → `main` named `release/vX.Y.Z`.
4. Merging the `release/v*` branch automatically tags the release and triggers the Docker build to `ghcr.io` via GitHub Actions.
