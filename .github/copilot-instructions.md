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

```
LLM Client  ──HTTP──▶  server.py (FastAPI + FastMCP)
                            │
                            ▼
                        influx.py (all queries)
                            │
                            ▼
                      InfluxDB (v1 or v2)
                    populated by garmin-grafana
```

- `server.py` — FastAPI app, MCP tool registration, `/health`, startup banner.
- `influx.py` — All InfluxDB connection logic and queries. **Only** file that
  touches the database.
- `utils.py` — Shared helpers: `pick()`, `safe_float()`, `safe_int()`,
  `iso_week_label()`, `week_start_from_label()`.
- `tools/activity.py` — `get_last_activity`, `get_recent_activities`.
- `tools/load.py` — `get_weekly_load_summary`.
- `tools/recovery.py` — `get_daily_recovery`.
- `tools/detail.py` — `get_activity_details`.
- `tools/fitness.py` — `get_fitness_trend`, `get_training_zones`.

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

garmin-grafana uses camelCase field names (e.g. `averageHR`, `sleepScore`,
`bodyBatteryAtWakeTime`). The normalizers in `influx.py` handle multiple
naming variants for robustness.

All field and measurement names are configurable via env vars — see `.env.example`.

## Code conventions

1. **All queries live in `influx.py`** — tools never construct raw InfluxQL/Flux.
2. **Shared helpers live in `utils.py`** — `pick()`, `safe_float()`, `safe_int()`,
   `iso_week_label()`, `week_start_from_label()`.
3. **Normalizers** (`normalise_activity`, `normalise_daily_stats`, etc.) handle
   field-name variations and unit conversions. Missing fields become `None`.
4. **Environmental configuration** — every measurement name, field name, and
   connection parameter is read from environment variables with sensible defaults.
5. **Input clamping** — every tool clamps its parameters to documented ranges.
6. **Error handling** — `ConnectionError` from InfluxDB returns a structured
   `{"error": ..., "hint": ..., "detail": ...}` dict; never raises to the LLM.
7. **No planning logic** — tools return raw data only. The LLM decides what it means.

## Git & Workflow Rules

These rules are mandatory for the agent to follow whenever the user requests a code change, bugfix, or feature addition. They sit alongside the architectural and InfluxDB schema guidance above and are intended to keep the repository consistent and CI/CD-friendly.

1. Branch Management:
    - NEVER write code directly on the `main` branch.
    - Before making edits, the agent MUST check the current git branch. If the working branch is `main`, the agent must either:
       - create and switch to a new descriptive branch using a command such as:
          `git checkout -b feature/add-hr-zones`, or
       - ask the user for the preferred branch name before creating it if the agent cannot run terminal commands itself.
    - Branch names should be hyphen-separated and descriptive: `type/short-description` (examples: `feat/add-training-zones`, `fix/hvr-query`).

2. Changelog Updates:
    - Any time a feature is added, modified, or fixed, the agent MUST update `CHANGELOG.md`.
    - Follow the "Keep a Changelog" format. Place new entries under the `## [Unreleased]` section and include a concise, one-line headline and optionally a short bullet list describing the change.
    - Example entry:
       - `### Added`
          - `- Add HR zone percentages to normalise_activity()` — returns zone_N_pct for zones 1–5.`
    - The agent must include the changelog edit in the same commit as the code change (or in the same branch before creating the PR).

3. Commit & Pull Request Prep:
    - After implementing changes and updating `CHANGELOG.md`, the agent MUST propose a clear, standardized commit message and remind the user to push the branch to trigger CI/CD.
    - Commit message format examples:
       - `feat(<scope>): short description` — for new features
       - `fix(<scope>): short description` — for bug fixes
       - `docs: update copilot-instructions.md (Git & Workflow Rules)` — for documentation-only edits
    - The agent should include the changelog, tests (if applicable), and any relevant notes in the commit.
    - The agent MUST not merge directly into `main`. Instead, push the branch and create a pull request with a descriptive title and body listing:
       - What changed (files and high-level summary)
       - How to test or verify locally
       - Any rollout or CI considerations

Enforcement:
- If the agent cannot run git commands in the environment, it must present the exact commands to the user and clearly explain the required steps to create the branch, commit, push, and open a PR.
- The agent must always include the `CHANGELOG.md` update and the proposed commit message in its response when returning code changes.


## When adding a new tool

1. Add the query function to `influx.py` (with both v1 and v2 variants).
2. Create or extend a file in `tools/` with the business logic.
3. Register the `@mcp.tool()` wrapper in `server.py` with full docstring
   (Parameters + Returns sections — the LLM reads these as tool descriptions).
4. Use shared helpers from `utils.py` for field extraction and type coercion.
5. Always clamp input parameters and handle `ConnectionError`.
6. Add the tool to the docstring at the top of `server.py`.

## Testing locally

```bash
cp .env.example .env   # edit INFLUXDB_HOST to localhost
python server.py        # → http://localhost:8765/mcp
```

For Docker: `docker compose up -d` (requires `garmin-grafana_default` network).
