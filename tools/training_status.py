"""
Training Status and Readiness tool.

Fetches the latest TrainingStatus and TrainingReadiness entries from InfluxDB.
TrainingStatus is available in garmin-grafana (confirmed present).
TrainingReadiness requires garmin-grafana v0.4.0+ and a compatible device.

Both queries are non-fatal — missing measurements return None gracefully.
Pure data retrieval; no planning logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx


async def get_training_status() -> dict[str, Any]:
    """
    Return the latest Training Status and Training Readiness data.

    Runs both queries in parallel. If a measurement is absent (e.g.
    TrainingReadiness not yet in the DB), that field is null and a
    note explains why — the server never crashes.
    """
    status, readiness = await asyncio.gather(
        asyncio.to_thread(influx.query_latest_training_status),
        asyncio.to_thread(influx.query_latest_training_readiness),
    )

    result: dict[str, Any] = {
        "training_status": status,
        "training_readiness": readiness,
    }

    if status is None and readiness is None:
        result["data_note"] = (
            "No TrainingStatus or TrainingReadiness data found. "
            "TrainingStatus requires a compatible Garmin device. "
            "TrainingReadiness may require garmin-grafana v0.4.0 or later."
        )
    elif status is None:
        result["training_status_note"] = "TrainingStatus data unavailable"
    elif readiness is None:
        result["training_readiness_note"] = (
            "TrainingReadiness data unavailable — "
            "may require garmin-grafana v0.4.0+ or a compatible device"
        )

    return result
