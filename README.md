# garmin-grafana-mcp-server

An optional, self-hosted [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes your Garmin training data to AI assistants. It is designed as a companion add-on to the [arpanghosh8453/garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana) project and reads directly from the InfluxDB instance that garmin-grafana already manages.

**This server is a pure data access layer.** It returns raw numbers from InfluxDB. All interpretation, analysis, and planning is delegated to the AI model consuming the tools — this server makes no assumptions about your fitness goals.

---

## Table of Contents

- [How it fits into the ecosystem](#how-it-fits-into-the-ecosystem)
- [🪄 See it in action: The AI Coach](#-see-it-in-action-the-ai-coach)
- [Prerequisites](#prerequisites)
- [Quick Start (Docker Compose)](#quick-start-docker-compose)
- [Deployment (Docker — recommended)](#deployment-docker--recommended)
- [Local Development](#local-development)
- [Connecting to an MCP Client](#connecting-to-an-mcp-client)
- [MCP Tools](#mcp-tools)
- [Example prompts](#example-prompts)
- [Configuration reference](#configuration-reference)
- [Project structure](#project-structure)
- [Schema compatibility](#schema-compatibility)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## How it fits into the ecosystem

```
Garmin Device
      │
      ▼
garmin-grafana         ← you already have this running
  ├─ Garmin API sync
  ├─ InfluxDB (stores your data)
  └─ Grafana (dashboards)

garmin-grafana-mcp-server   ← this repo adds this
  └─ Reads from the same InfluxDB
  └─ Exposes MCP tools to AI clients (Claude, Copilot, etc.)
```

---

## 🪄 See it in action: The AI Coach

Because this MCP server provides structured, context-aware data to LLMs like Claude, it acts as a world-class personal coach.

Here is an actual, unedited response from Claude (via Copilot) summarizing a ride by cross-referencing **six different MCP tools** simultaneously (Activity Details, Training Status, Sleep/Recovery, Training Zones, and Stress):

> **Prompt:** *"I just came back from my long Z2 ride. Please assess it in detail against our training plan!"*

<details>
<summary><b>View Claude's Analysis (Click to expand)</b></summary>

### 1. SCORECARD vs PLAN
| Metric | Target | Actual | Grade |
|---|---|---|---|
| Duration | 120–150 min | **137.5 min** | ✅ Perfect |
| Time in Z1+Z2 | — | **99.4%** (130.1 min) | ✅ Excellent |
| Max HR | ≤130 (ceiling) | **135 bpm** | ⚠️ Brief breach |
| HR drift | <5% | **-4.5%** | ✅ Excellent |
| Avg cadence | 85–95 rpm | **74 rpm** | ❌ Low |

### 2. LAP-BY-LAP ANALYSIS
- **Laps 3–6 were textbook Z2**: HR locked at 121–122 bpm. This is exactly the metabolic zone we wanted.
- **No cardiac drift**: HR drift = -4.5%. This means your aerobic system handled the load comfortably.
- **Cadence averaged 74 rpm** — below target (85–95). Next time, focus on spinning a lighter gear to reduce muscular fatigue.

### 3. TRAINING STATUS & LOAD
- Status remains **Productive** (code 7).
- ACWR 1.4 is on the higher end of the sweet spot. Be cautious not to spike it further; the next session should be easy.
- Aerobic TE 2.4 with zero anaerobic — exactly the prescribed stimulus.

### 4. POLARIZATION SHIFT — THE BIG WIN
| Metric | Before today | After today |
|---|---|---|
| Low intensity (Z1+Z2) | 49.4% | **56.7%** |

**This single ride shifted your 30-day polarization by +7.3% toward low intensity.** Two more clean Z2 rides like this and you'll cross the 65% threshold.

### 5. RECOMMENDATIONS
**Next session:**
- If HRV/recovery is good: another 90–120 min strict Z2. Same HR targets.
- **Cadence drill**: consciously target 85+ rpm in the main block. Use a lighter gear and focus on pedal circles.
</details>

---

## Prerequisites

| Requirement | Notes |
|---|---|
| [garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana) | Must already be running and populated |
| Docker & Docker Compose | For the recommended deployment path |
| Python 3.11+ | For local development only |

---

## Quick Start (Docker Compose)

If you just want to run the pre-built image alongside your existing garmin-grafana stack, create a `docker-compose.yml` with the snippet below. No need to clone this repository.

```yaml
services:
  garmin-grafana-mcp-server:
    image: ghcr.io/ghighi3f/garmin-grafana-mcp-server:latest
    container_name: garmin-grafana-mcp-server
    restart: unless-stopped
    ports:
      - "8765:8765"
    environment:
      # ── Required ─────────────────────────────────────────────
      # Connection to the InfluxDB instance managed by garmin-grafana.
      INFLUXDB_HOST: influxdb            # container name on the shared Docker network
      INFLUXDB_PORT: 8086
      INFLUXDB_DATABASE: GarminStats     # database name from your garmin-grafana .env
      INFLUXDB_USERNAME: admin           # InfluxDB v1 credentials
      INFLUXDB_PASSWORD: adminpassword   # ← change to your actual password

      # ── InfluxDB v2 only (uncomment if you run v2) ──────────
      # INFLUXDB_VERSION: 2
      # INFLUXDB_TOKEN: "your-influxdb-token"
      # INFLUXDB_ORG: "your-org"

      # ── Optional: override schema names ─────────────────────
      # Only needed if your garmin-grafana uses non-default measurement
      # or field names. The defaults match the standard garmin-grafana schema.
      #
      # Measurement names:
      # MEASUREMENT_ACTIVITIES: ActivitySummary
      # MEASUREMENT_DAILY_STATS: DailyStats
      # MEASUREMENT_SLEEP_SUMMARY: SleepSummary
      # MEASUREMENT_ACTIVITY_SESSION: ActivitySession
      # MEASUREMENT_ACTIVITY_LAP: ActivityLap
      # MEASUREMENT_RESTING_HR: DailyStats
      # MEASUREMENT_HRV: HRV_Intraday
      # MEASUREMENT_VO2_MAX: VO2_Max
      # MEASUREMENT_RACE_PREDICTIONS: RacePredictions
      # MEASUREMENT_BODY_COMPOSITION: BodyComposition
      #
      # Field names:
      # FIELD_RESTING_HR: resting_hr
      # FIELD_HRV: hrv5MinHigh
      # FIELD_VO2_MAX_RUNNING: VO2_max_value
      # FIELD_VO2_MAX_CYCLING: VO2_max_value_cycling
      # FIELD_RACE_5K: time5K
      # FIELD_RACE_10K: time10K
      # FIELD_RACE_HALF: timeHalfMarathon
      # FIELD_RACE_MARATHON: timeMarathon
      # FIELD_WEIGHT: weight
      # FIELD_HR_ZONE_1: hrTimeInZone_1
      # FIELD_HR_ZONE_2: hrTimeInZone_2
      # FIELD_HR_ZONE_3: hrTimeInZone_3
      # FIELD_HR_ZONE_4: hrTimeInZone_4
      # FIELD_HR_ZONE_5: hrTimeInZone_5
      #
      # Training Status & Readiness (garmin-grafana v0.4.0+):
      # MEASUREMENT_TRAINING_STATUS: TrainingStatus
      # MEASUREMENT_TRAINING_READINESS: TrainingReadiness
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

networks:
  default:
    external: true
    name: garmin-grafana_default   # ← must match your garmin-grafana network
```

Then start it:

```bash
docker compose up -d
curl http://localhost:8765/health
```

> **Tip:** The only variables most users need to change are `INFLUXDB_PASSWORD` and possibly `INFLUXDB_DATABASE`. All schema variables have sensible defaults that match the standard garmin-grafana InfluxDB schema out of the box.

---

## Deployment (Docker — recommended)

This is the recommended way to run the server alongside your existing garmin-grafana stack.

### 1. Clone this repository

```bash
git clone https://github.com/ghighi3f/garmin-grafana-mcp-server.git
cd garmin-grafana-mcp-server
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` to match your garmin-grafana setup. The most important values:

| Variable | Default | Description |
|---|---|---|
| `INFLUXDB_HOST` | `influxdb` | Container name of the InfluxDB service inside the garmin-grafana network. Override in `.env` only if your service is named differently. |
| `INFLUXDB_PORT` | `8086` | InfluxDB port (usually unchanged) |
| `INFLUXDB_DATABASE` | `GarminStats` | Database name set in your garmin-grafana config |
| `INFLUXDB_USERNAME` | `admin` | InfluxDB username from your garmin-grafana `.env` |
| `INFLUXDB_PASSWORD` | *(see .env.example)* | InfluxDB password from your garmin-grafana `.env` |
| `INFLUXDB_VERSION` | `1` | `1` for InfluxDB v1; `2` for InfluxDB v2 |
| `MCP_PORT` | `8765` | Port the MCP server listens on |
| `QUERY_TIMEZONE` | `UTC` | IANA timezone — must match `USER_TIMEZONE` in garmin-grafana (see [Timezone](#timezone)) |

> **Note:** `INFLUXDB_HOST` is overridden to `influxdb` directly in `docker-compose.yml` so the container resolves the InfluxDB service by its Docker network name. You do not need to set it in `.env` for the Docker deployment.

### 3. Identify your garmin-grafana Docker network

The `docker-compose.yml` in this repo connects to the same Docker network that garmin-grafana creates. By default that network is named `garmin-grafana_default`.

Verify the network name:

```bash
docker network ls | grep garmin
```

If the name differs from `garmin-grafana_default`, edit the `networks` section at the bottom of `docker-compose.yml`:

```yaml
networks:
  default:
    external: true
    name: your-actual-network-name   # ← change this
```

### 4. Start the server

```bash
docker compose up -d
```

Verify it is running:

```bash
curl http://localhost:8765/health
```

Expected response:

```json
{
  "influxdb": "connected",
  "last_activity_timestamp": "2026-03-17T07:30:00+00:00",
  "measurements_found": ["ActivitySummary", "DailyStats", "SleepSummary", "..."],
  "mcp_endpoint": "http://localhost:8765/mcp",
  "sse_endpoint": "http://localhost:8765/sse"
}
```

---

## Local Development

If you want to run the MCP server directly on your host machine (outside Docker) during development, the server process needs to reach InfluxDB on port `8086`. Since InfluxDB is inside a Docker network, you must expose its port to the host.

**Step 1: Expose InfluxDB port in your garmin-grafana `docker-compose.yml`**

Open the garmin-grafana `docker-compose.yml` and add a `ports` mapping to the `influxdb` service:

```yaml
# In your garmin-grafana docker-compose.yml:
services:
  influxdb:
    image: influxdb:1.8
    ports:
      - "8086:8086"   # ← add this line
    # ... rest of your config
```

Then restart the garmin-grafana stack:

```bash
docker compose down && docker compose up -d
```

**Step 2: Set up the Python environment**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For InfluxDB v2, also install:

```bash
pip install influxdb-client
```

**Step 3: Configure for local access**

```bash
cp .env.example .env
```

Edit `.env` and set:

```env
INFLUXDB_HOST=localhost   # reach InfluxDB via the exposed host port
INFLUXDB_PORT=8086
```

**Step 4: Run the server**

```bash
python server.py
```

You should see:

```
============================================================
  Garmin MCP Server
============================================================
  InfluxDB   : localhost:8086/GarminStats
  Measurements: ['ActivitySummary', 'DailyStats', ...]
  Transports : HTTP + SSE (always active)
  /mcp  (Streamable HTTP) : http://localhost:8765/mcp
  /sse  (SSE, deprecated) : http://localhost:8765/sse
  /health                 : http://localhost:8765/health
============================================================
```

---

## Connecting to an MCP Client

All HTTP transports are always active simultaneously — no `MCP_TRANSPORT` configuration needed for HTTP deployments. Point your client at the right URL and go.

---

### Perplexity Mac / Legacy SSE clients

> **Note:** SSE transport is deprecated in the MCP specification. Kept for backward compatibility — prefer Streamable HTTP for new integrations.

```json
{
  "mcpServers": {
    "garmin": {
      "type": "sse",
      "url": "http://<your-host>:8765/sse"
    }
  }
}
```

---

### ChatGPT / VS Code / Modern clients (Streamable HTTP)

```json
{
  "mcpServers": {
    "garmin": {
      "type": "http",
      "url": "http://<your-host>:8765/mcp"
    }
  }
}
```

Replace `<your-host>` with the IP or hostname of the machine running the server (e.g. `192.168.1.100`, `pi5.local`, or `localhost`).

---

### Claude Desktop / Cursor / Windsurf / Claude Code (Local stdio)

**With Docker** (server reads InfluxDB via the shared garmin-grafana network):

```json
{
  "mcpServers": {
    "garmin": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--network", "garmin-grafana_default",
        "--env-file", "/path/to/.env",
        "ghcr.io/ghighi3f/garmin-grafana-mcp-server:latest",
        "python", "server.py"
      ],
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

**Without Docker** (local Python, `INFLUXDB_HOST=localhost` in `.env`):

```json
{
  "mcpServers": {
    "garmin": {
      "command": "python",
      "args": ["/path/to/garmin-grafana-mcp-server/server.py"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "INFLUXDB_HOST": "localhost",
        "INFLUXDB_PORT": "8086",
        "INFLUXDB_DATABASE": "GarminStats",
        "INFLUXDB_USERNAME": "admin",
        "INFLUXDB_PASSWORD": "your-password"
      }
    }
  }
}
```

Or from the command line:

```bash
MCP_TRANSPORT=stdio python server.py
```

> **Tip:** The startup banner is written to stderr in stdio mode so it never interferes with the MCP protocol on stdout.

---

### No configuration needed

All HTTP transports (SSE + Streamable HTTP) are always active on the same port. `MCP_TRANSPORT` only needs to be set for stdio (subprocess) clients.

---

## MCP Tools

### `get_last_activity`

Returns the single most recent Garmin activity with all available fields. No input parameters.

### `get_recent_activities`

Returns activities from the last N days with a summary.

| Parameter | Type | Default | Range / Values |
|---|---|---|---|
| `days` | int | `7` | 1–90 |
| `sport_type` | str | `"all"` | Any Garmin sport type (e.g. `"running"`, `"cycling"`, `"hiking"`, `"trail_running"`, `"strength_training"`). Supports partial matching — `"cycling"` also matches `"indoor_cycling"`. `"all"` = no filter. |
| `limit` | int | `20` | 1–100 |

### `get_weekly_load_summary`

Groups activities into ISO calendar weeks with resting HR and HRV.

| Parameter | Type | Default | Range |
|---|---|---|---|
| `weeks` | int | `4` | 1–16 |

### `get_daily_recovery`

Merges SleepSummary + DailyStats per date for a holistic recovery view.

| Parameter | Type | Default | Range |
|---|---|---|---|
| `days` | int | `7` | 1–14 |

### `get_activity_details`

Detailed breakdown of a single activity: HR zones, training effect, per-lap splits, and analysis hints (fastest/slowest lap, HR drift).

| Parameter | Type | Description |
|---|---|---|
| `activity_id` | str | Activity ID from `get_recent_activities` |

### `get_fitness_trend`

Long-term fitness trajectory: VO2max, race predictions, weight, resting HR — sampled weekly.

| Parameter | Type | Default | Range |
|---|---|---|---|
| `weeks` | int | `12` | 4–52 |

### `get_training_zones`

HR zone distribution and polarization analysis (low/moderate/high intensity breakdown).

| Parameter | Type | Default | Range / Values |
|---|---|---|---|
| `days` | int | `30` | 7–180 |
| `sport_type` | str | `"all"` | Any Garmin sport type (e.g. `"running"`, `"cycling"`, `"swimming"`, `"hiking"`). Supports partial matching. `"all"` = no filter. |

### `explore_schema`

Discover available InfluxDB measurements, fields, and tags at runtime. Useful for verifying field names before querying or debugging measurement mismatches.

| Parameter | Type | Optional | Description |
|---|---|---|---|
| `measurement_name` | str | Yes | Inspect a specific measurement (e.g. `"ActivitySummary"`). Omit to list all measurements. |

**Returns (no measurement specified):**
```json
{"measurements": ["ActivitySummary", "DailyStats", "SleepSummary", "..."]}
```

**Returns (measurement specified):**
```json
{
  "measurement": "ActivitySummary",
  "fields": [
    {"field": "distance", "type": "float"},
    {"field": "elapsedDuration", "type": "integer"},
    "..."
  ],
  "tags": ["userId", "deviceId", "..."]
}
```

### `get_stress_body_battery`

Daily stress breakdown and body battery trend over 7–30 days. Surfaces systemic fatigue patterns that `get_daily_recovery` buries inside a per-day blob.

| Parameter | Type | Default | Range |
|---|---|---|---|
| `days` | int | `7` | 7–30 |

**Returns:**
- Per-day: stress minutes (high/medium/low/rest) + body battery (at wake, high, low, drained, charged)
- Summary: period averages + trend direction (`"improving"` / `"declining"` / `"stable"` for body battery; `"improving"` / `"worsening"` / `"stable"` for stress)

### `get_personal_records`

All-time personal records grouped by sport type. For each record, returns the value, unit, and the **activity_id, date, and activity_name** of the record-setting activity.

| Parameter | Type | Default | Range / Values |
|---|---|---|---|
| `sport_type` | str | `"all"` | Any Garmin sport type (e.g. `"running"`, `"cycling"`). Supports partial matching. `"all"` returns records for every sport. |

**Records tracked per sport:**

| Record | Unit | Notes |
|---|---|---|
| `longest_distance` | km | |
| `longest_duration` | minutes | Uses moving time (excludes pauses) |
| `top_speed` | km/h | |
| `fastest_avg_pace` | min/km | Pace sports only (running, swimming, walking, hiking) |
| `fastest_avg_speed` | km/h | Speed sports only (cycling, rowing, etc.) |
| `highest_max_hr` | bpm | |
| `highest_avg_hr` | bpm | |
| `most_calories` | kcal | |
| `highest_avg_power` | watts | Duration-weighted average from lap data |
| `highest_max_power` | watts | Peak instantaneous watt from ActivityGPS (server-side MAX aggregate) |

---

### `get_training_status`

Fetches the latest Training Status and Training Readiness entries from InfluxDB. No input parameters required.

**Returns:**

- **`training_status`** — most recent entry from the `TrainingStatus` measurement:

| Field | Type | Description |
|---|---|---|
| `status_code` | int | Garmin training status enum value |
| `status_label` | str | Raw FIT SDK phrase code (e.g. `"PRODUCTIVE_6"`, `"MAINTAINING_1"`) |
| `garmin_coaching_advice` | str\|null | Human-readable coaching text decoded from the FIT SDK `training_status_feedback_phrase` enum (e.g. `"Primarily aerobic training"`) |
| `acute_load` | int | 7-day acute training load |
| `chronic_load` | int | 28-day chronic training load (CTL) |
| `load_balance_ratio` | float | Acute / chronic workload ratio (ACWR) |
| `acwr_percent` | int | ACWR expressed as a percentage |
| `fitness_trend` | int | Garmin fitness trend indicator |
| `max_chronic_load` | float | Upper bound of the optimal chronic load range |
| `min_chronic_load` | float | Lower bound of the optimal chronic load range |
| `timestamp` | str | ISO timestamp of the record |

- **`training_readiness`** — most recent entry from the `TrainingReadiness` measurement (requires garmin-grafana v0.4.0+ and a compatible device). Returns `null` with a `training_readiness_note` if the measurement is not present.

| Field | Type | Description |
|---|---|---|
| `score` | int | Readiness score 0–100 |
| `description` | str | Readiness label (e.g. `"Good"`, `"Fair"`, `"Poor"`) |
| `sleep_score` | int | Sleep component score |
| `hrv_ratio` | float | HRV component ratio |
| `recovery_time_h` | int | Recommended recovery time in hours |
| `stress_history` | float | Stress history component |
| `activity_history` | float | Activity history component |

> **Graceful degradation:** if either measurement is missing (e.g. `TrainingReadiness` is only available with certain garmin-grafana versions and Garmin devices), the corresponding field is `null` and a `data_note` or `training_readiness_note` key explains why. The server never crashes.

### `get_sleep_physiology`

Returns nightly autonomic physiology from SleepIntraday epoch data, merged with enriched SleepSummary.

| Parameter | Type | Default | Range |
|---|---|---|---|
| `days` | int | `7` | 1–14 |

**Returns per night:**
- `intraday` — HR, HRV, respiration, SpO2 (min/max/mean), stress (mean), body battery (first/last/min/max), restlessness (mean), epoch count
- `summary` — sleep score, stage durations, avg overnight HRV, respiration range, SpO2 range

**Summary:** avg minimum HR, avg mean HRV, avg mean respiration, avg min SpO2, avg body battery charged. Trends: `min_hr_trend`, `hrv_trend`, `respiration_trend`.

### `get_activity_load_history`

Returns per-activity training load and training effect scores — shows which sessions drive acute load.

| Parameter | Type | Default | Range / Values |
|---|---|---|---|
| `days` | int | `14` | 1–90 |
| `sport_type` | str | `"all"` | Any Garmin sport type or `"all"` |
| `limit` | int | `30` | 1–100 |

**Returns per activity:** activity ID, sport, distance, duration, `training_load` (Garmin EPOC), `aerobic_training_effect` (0–5), `anaerobic_training_effect` (0–5), avg/max HR.

**Summary:** `total_load`, `avg_load_per_session`, `load_by_sport`, `highest_load_activity`, `avg_aerobic_te`, `avg_anaerobic_te`.

### `get_daily_energy_balance`

Returns daily time-use breakdown, caloric data, movement, and stress attribution — reveals what happens between workouts and sleep.

| Parameter | Type | Default | Range |
|---|---|---|---|
| `days` | int | `7` | 1–14 |

**Returns per day:**
- `time_use` — sedentary, active, highly active, sleeping (hours)
- `energy` — BMR kcal, active kcal
- `movement` — steps, distance, floors ascended/descended + meters
- `recovery_context` — body battery during sleep, body battery at wake, resting HR
- `stress_attribution` — activity stress min/pct, total stress, uncategorized stress

**Summary:** period averages + `sedentary_trend`, `bb_during_sleep_trend`.

### `get_fitness_age`

Returns weekly-sampled fitness age trajectory — a single metric for long-term base-building progress.

| Parameter | Type | Default | Range |
|---|---|---|---|
| `weeks` | int | `12` | 4–52 |

**Returns per week:** `fitness_age`, `chronological_age`, `achievable_fitness_age`, `fitness_age_gap` (fitness – chronological, negative = younger), `improvement_potential` (fitness – achievable).

**Trends:** `fitness_age_change`, `fitness_age_gap_change`, `improvement_potential_change` (delta oldest → newest).

---

## Example prompts

```
"What was my last ride? How did my HR compare to the previous 3?"

"Break down everything I did in the last 2 weeks by sport."

"Given my last 4 weeks of training, suggest a 7-day plan —
 my goal is a sprint triathlon in 6 weeks, I can train Mon/Wed/Thu/Sat/Sun."

"Was my training load balanced across swim/bike/run last month?"

"How has my VO2max trended over the past 3 months?"

"Compare my sleep and recovery over the last 7 days."

"What's my HR zone distribution for the past month?
 Am I spending too much time in zone 3?"

"Show my stress and body battery trend for the last 2 weeks.
 Am I recovering well between hard sessions?"

"What are my all-time personal records for cycling and running?"

"What is my current training status? Am I overloading or undertraining?"
```

---

## Configuration reference

All settings are in `.env`. Copy `.env.example` to get started.

### Measurement names

Override these if your garmin-grafana schema uses different measurement names:

| Variable | Default |
|---|---|
| `MEASUREMENT_ACTIVITIES` | `ActivitySummary` |
| `MEASUREMENT_DAILY_STATS` | `DailyStats` |
| `MEASUREMENT_SLEEP_SUMMARY` | `SleepSummary` |
| `MEASUREMENT_ACTIVITY_SESSION` | `ActivitySession` |
| `MEASUREMENT_ACTIVITY_LAP` | `ActivityLap` |
| `MEASUREMENT_VO2_MAX` | `VO2_Max` |
| `MEASUREMENT_RACE_PREDICTIONS` | `RacePredictions` |
| `MEASUREMENT_BODY_COMPOSITION` | `BodyComposition` |
| `MEASUREMENT_RESTING_HR` | `DailyStats` |
| `MEASUREMENT_HRV` | `HRV_Intraday` |
| `MEASUREMENT_TRAINING_STATUS` | `TrainingStatus` |
| `MEASUREMENT_TRAINING_READINESS` | `TrainingReadiness` |
| `MEASUREMENT_SLEEP_INTRADAY` | `SleepIntraday` |
| `MEASUREMENT_FITNESS_AGE` | `FitnessAge` |

### Field names

| Variable | Default | Used in |
|---|---|---|
| `FIELD_RESTING_HR` | `resting_hr` | Weekly load |
| `FIELD_HRV` | `hrv5MinHigh` | Weekly load |
| `FIELD_VO2_MAX_RUNNING` | `VO2_max_value` | Fitness trend |
| `FIELD_VO2_MAX_CYCLING` | `VO2_max_value_cycling` | Fitness trend |
| `FIELD_RACE_5K` | `time5K` | Fitness trend |
| `FIELD_RACE_10K` | `time10K` | Fitness trend |
| `FIELD_RACE_HALF` | `timeHalfMarathon` | Fitness trend |
| `FIELD_RACE_MARATHON` | `timeMarathon` | Fitness trend |
| `FIELD_WEIGHT` | `weight` | Fitness trend |
| `FIELD_HR_ZONE_1`–`5` | `hrTimeInZone_1`–`5` | Training zones, activity details |
| `FIELD_TRAINING_STATUS_CODE` | `trainingStatus` | Training status (int enum) |
| `FIELD_TRAINING_STATUS_LABEL` | `trainingStatusFeedbackPhrase` | Training status label (string) |
| `FIELD_ACUTE_LOAD` | `dailyTrainingLoadAcute` | 7-day acute training load |
| `FIELD_CHRONIC_LOAD` | `dailyTrainingLoadChronic` | 28-day chronic training load |
| `FIELD_LOAD_BALANCE_RATIO` | `dailyAcuteChronicWorkloadRatio` | Acute/chronic ratio |
| `FIELD_ACWR_PERCENT` | `acwrPercent` | ACWR as percentage |
| `FIELD_FITNESS_TREND` | `fitnessTrend` | Fitness trend indicator |
| `FIELD_READINESS_SCORE` | `trainingReadinessScore` | Readiness score 0–100 |
| `FIELD_READINESS_LABEL` | `trainingReadinessDescription` | Readiness label string |
| `FIELD_SLEEP_HR` | `heartRate` | Sleep HR epochs |
| `FIELD_SLEEP_HRV` | `hrvData` | Sleep HRV epochs |
| `FIELD_SLEEP_RESPIRATION` | `respirationValue` | Sleep respiration epochs |
| `FIELD_SLEEP_SPO2` | `spo2Reading` | Sleep SpO2 epochs |
| `FIELD_SLEEP_STRESS` | `stressValue` | Sleep stress epochs |
| `FIELD_SLEEP_BODY_BATTERY` | `bodyBattery` | Sleep body battery epochs |
| `FIELD_SLEEP_RESTLESS` | `sleepRestlessValue` | Sleep restlessness epochs |
| `FIELD_TRAINING_LOAD` | `activityTrainingLoad` | Per-activity EPOC load |
| `FIELD_AEROBIC_TE` | `aerobicTrainingEffect` | Aerobic training effect (0–5) |
| `FIELD_ANAEROBIC_TE` | `anaerobicTrainingEffect` | Anaerobic training effect (0–5) |
| `FIELD_SEDENTARY_SECONDS` | `sedentarySeconds` | Daily sedentary time |
| `FIELD_ACTIVE_SECONDS` | `activeSeconds` | Daily active time |
| `FIELD_HIGHLY_ACTIVE_SECONDS` | `highlyActiveSeconds` | Daily vigorous movement time |
| `FIELD_SLEEPING_SECONDS` | `sleepingSeconds` | Daily sleeping time |
| `FIELD_BMR_KCAL` | `bmrKilocalories` | Basal metabolic rate calories |
| `FIELD_BB_DURING_SLEEP` | `bodyBatteryDuringSleep` | Body battery charged during sleep |
| `FIELD_ACTIVITY_STRESS_DUR` | `activityStressDuration` | Activity-caused stress seconds |
| `FIELD_ACTIVITY_STRESS_PCT` | `activityStressPercentage` | Activity stress % of total |
| `FIELD_FITNESS_AGE` | `fitnessAge` | Current fitness age |
| `FIELD_CHRONOLOGICAL_AGE` | `chronologicalAge` | Actual age |
| `FIELD_ACHIEVABLE_FITNESS_AGE` | `achievableFitnessAge` | Optimal achievable fitness age |

### Server

| Variable | Default | Description |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `8765` | Bind port |
| `MCP_TRANSPORT` | `http` | Set to `stdio` for subprocess clients (Claude Desktop, Cursor, Windsurf). Leave unset for all HTTP deployments — both SSE and Streamable HTTP are always active. |
| `ALLOWED_HOSTS` | *(empty)* | DNS-rebinding allow-list (e.g. `pi5.local:*,localhost:*`) |

### Timezone

| Variable | Default | Description |
|---|---|---|
| `QUERY_TIMEZONE` | `UTC` | IANA timezone for daily-aggregate queries. Must match `USER_TIMEZONE` in garmin-grafana. |

garmin-grafana stores daily measurements (DailyStats, SleepSummary, etc.) with timestamps anchored to **local midnight**. For a UTC+3 user, local midnight is `21:00:00Z` — without timezone correction the MCP server assigns these records to the previous UTC date, shifting every daily metric one day into the past.

Set `QUERY_TIMEZONE` to the same value as `USER_TIMEZONE` in your garmin-grafana `.env`:

```env
# garmin-grafana .env
USER_TIMEZONE=Europe/Athens

# garmin-grafana-mcp-server .env
QUERY_TIMEZONE=Europe/Athens
```

This injects InfluxQL's `tz()` clause into daily and weekly aggregate queries and converts timestamps to local dates in the normalizer layer. Activity queries (which use actual event timestamps) are not affected.

> **UTC users:** No action needed — the default `UTC` preserves existing behaviour.

---

## Project structure

```
garmin-grafana-mcp-server/
├── server.py              — Starlette app + MCP tool registration + startup banner
├── influx.py              — InfluxDB client, all queries, normalizer functions
├── utils.py               — Shared helpers (pick, safe_float, iso_week_label, etc.)
├── tools/
│   ├── __init__.py
│   ├── activity.py        — get_last_activity, get_recent_activities
│   ├── load.py            — get_weekly_load_summary
│   ├── recovery.py        — get_daily_recovery
│   ├── detail.py          — get_activity_details
│   ├── fitness.py         — get_fitness_trend, get_training_zones
│   ├── records.py         — get_personal_records
│   ├── stress.py          — get_stress_body_battery
│   ├── schema.py          — explore_schema
│   ├── training_status.py — get_training_status
│   ├── sleep_physiology.py — get_sleep_physiology
│   ├── activity_load.py   — get_activity_load_history
│   ├── energy_balance.py  — get_daily_energy_balance
│   └── fitness_age.py     — get_fitness_age
├── Dockerfile
├── docker-compose.yml     — Docker deployment (external garmin-grafana network)
├── .env.example           — Configuration template
├── requirements.txt       — Python dependencies
├── CHANGELOG.md
└── README.md
```

---

## Schema compatibility

This server is designed to be resilient to garmin-grafana schema variations across versions. All measurement names and the key field names used in queries are configurable via environment variables (see the configuration tables above). If a field is missing from a given activity record, it is silently set to `null` — no errors are raised.

If you see empty results after setup, verify your measurement names against InfluxDB:

```bash
# InfluxDB v1 — run from inside the influxdb container or via an exposed port
influx -database GarminStats -execute 'SHOW MEASUREMENTS'
```

Then update the corresponding `MEASUREMENT_*` variables in your `.env`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `"influxdb": "unreachable"` in health check | Network misconfiguration | Verify `docker network ls` and that the `name:` in `docker-compose.yml` matches |
| `"InfluxDB connection failed"` from a tool | garmin-grafana not running | `docker ps`, restart containers |
| Empty `activities` list | Measurement name mismatch | Run `SHOW MEASUREMENTS` and update `MEASUREMENT_ACTIVITIES` in `.env` |
| `AttributeError: streamable_http_app` | `mcp` < 1.6 | `pip install --upgrade mcp` |
| stdio mode not working | Missing `MCP_TRANSPORT=stdio` | Run `MCP_TRANSPORT=stdio python server.py` — uvicorn is not used in stdio mode |
| `/sse` returns 404 | Old deployment cached in container | Rebuild and redeploy: `docker compose up -d --build` |
| Tools not appearing in client | Client connected before server started | Restart the MCP client |

---

## License

MIT
