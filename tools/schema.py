"""
Schema exploration MCP tool.
Allows AI agents to discover InfluxDB measurements, fields, and tags
at runtime instead of guessing field names.
"""

from __future__ import annotations

from typing import Any

import influx


async def explore_schema(measurement_name: str | None = None) -> dict[str, Any]:
    """
    Explore the InfluxDB schema used by garmin-grafana.

    When called with no arguments, returns every measurement (table) in the
    database.  When called with a specific measurement_name, returns the
    full list of fields (with data types) and tags inside that measurement.

    Parameters
    ----------
    measurement_name : str, optional
        The measurement to inspect (e.g. "ActivitySummary").  Omit to list
        all measurements.

    Returns
    -------
    dict
        Either {"measurements": [...]} or
        {"measurement": "<name>", "fields": [...], "tags": [...]}.
    """
    if not measurement_name:
        try:
            measurements = influx.get_measurements()
        except ConnectionError as exc:
            return {
                "error": "InfluxDB connection failed",
                "hint": "Is garmin-grafana running? Check docker ps",
                "detail": str(exc),
            }

        if not measurements:
            return {
                "measurements": [],
                "data_note": "No measurements found — database may be empty or unreachable.",
            }

        return {"measurements": sorted(measurements)}

    # Inspect a specific measurement
    try:
        fields = influx.query_field_keys(measurement_name)
        tags = influx.query_tag_keys(measurement_name)
    except ConnectionError as exc:
        return {
            "error": "InfluxDB connection failed",
            "hint": "Is garmin-grafana running? Check docker ps",
            "detail": str(exc),
        }

    if not fields and not tags:
        return {
            "measurement": measurement_name,
            "fields": [],
            "tags": [],
            "data_note": (
                f"No fields or tags found for '{measurement_name}'. "
                "Check the measurement name — call this tool with no "
                "arguments to list available measurements."
            ),
        }

    return {
        "measurement": measurement_name,
        "fields": fields,
        "tags": tags,
    }
