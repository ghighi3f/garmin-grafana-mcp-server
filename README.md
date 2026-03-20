# garmin-grafana-mcp-server

An optional, self-hosted [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes your Garmin training data to AI assistants. It is designed as a companion add-on to the [arpanghosh8453/garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana) project and reads directly from the InfluxDB instance that garmin-grafana already manages.

**This server is a pure data access layer.** It returns raw numbers from InfluxDB. All interpretation, analysis, and planning is delegated to the AI model consuming the tools — this server makes no assumptions about your fitness goals.

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
  "mcp_endpoint": "http://localhost:8765/mcp"
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
  Measurements found: ['ActivitySummary', 'DailyStats', ...]
  Transport  : streamable-HTTP
  MCP endpoint ready: http://localhost:8765/mcp
  /health check:      http://localhost:8765/health
============================================================
```

---

## Registering with an MCP-compatible AI client

Add this to your AI client's MCP configuration (e.g. Claude Desktop `claude_desktop_config.json`, VS Code settings):

```json
{
  "mcpServers": {
    "garmin-local": {
      "type": "http",
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

> If the MCP server and AI client run on different machines, replace `localhost` with the server's IP or hostname.

---

## MCP Tools

### `get_last_activity`

Returns the single most recent Garmin activity with all available fields. No input parameters.

### `get_recent_activities`

Returns activities from the last N days with a summary.

| Parameter | Type | Default | Range / Values |
|---|---|---|---|
| `days` | int | `7` | 1–90 |
| `sport_type` | str | `"all"` | `"running"`, `"cycling"`, `"swimming"`, `"all"` |
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
| `sport_type` | str | `"all"` | `"running"`, `"cycling"`, `"swimming"`, `"all"` |

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

### Server

| Variable | Default | Description |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `8765` | Bind port |
| `ALLOWED_HOSTS` | *(empty)* | DNS-rebinding allow-list (e.g. `pi5.local:*,localhost:*`) |

---

## Project structure

```
garmin-grafana-mcp-server/
├── server.py              — FastAPI app + MCP tool registration + startup banner
├── influx.py              — InfluxDB client, all queries, normalizer functions
├── utils.py               — Shared helpers (pick, safe_float, iso_week_label, etc.)
├── tools/
│   ├── __init__.py
│   ├── activity.py        — get_last_activity, get_recent_activities
│   ├── load.py            — get_weekly_load_summary
│   ├── recovery.py        — get_daily_recovery
│   ├── detail.py          — get_activity_details
│   ├── fitness.py         — get_fitness_trend, get_training_zones
│   ├── stress.py          — get_stress_body_battery
│   └── schema.py          — explore_schema
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
| `AttributeError: streamable_http_app` | `mcp` < 1.2 | `pip install --upgrade mcp` |
| Tools not appearing in client | Client connected before server started | Restart the MCP client |

---

## License

MIT
