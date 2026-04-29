"""
Cycling dynamics MCP tool.

Surfaces advanced pedaling metrics from the CyclingDynamics measurement
written by the garmin-grafana CyclingDynamics patch.  Requires a compatible
Garmin power meter (Rally, Vector, or similar).

Provides per-activity:
  - Normalized Power, TSS, Intensity Factor
  - Left/right power balance
  - Torque effectiveness (left + right)
  - Pedal smoothness (left + right)
  - Power phase angles (start/end, left + right)
  - Peak power phase angles (start/end, left + right)
  - Platform Center Offset (left + right)
"""

from __future__ import annotations

import asyncio
from typing import Any

import influx
from utils import safe_float


async def get_cycling_dynamics(activity_id: str) -> dict[str, Any]:
    """
    Return cycling dynamics for a single activity.

    Data comes from the CyclingDynamics measurement added by the
    garmin-grafana CyclingDynamics patch.  If the measurement does not exist
    or the activity has no dynamics data, a descriptive data_note is returned
    instead of an error so callers can handle missing hardware gracefully.

    Parameters:
        activity_id – the activity ID (from get_recent_activities or
                      get_activity_details)

    Returns:
        activity_id     – echoed back for traceability
        power           – normalized_power (W), training_stress_score,
                          intensity_factor, left_right_balance
                          ({left_pct, right_pct})
        left_pedal      – torque_effectiveness (%), pedal_smoothness (%),
                          platform_center_offset_mm,
                          power_phase {start_deg, end_deg},
                          power_phase_peak {start_deg, end_deg}
        right_pedal     – same structure as left_pedal
        data_note       – present (instead of the above) when no data found
    """
    if not activity_id or not str(activity_id).strip():
        return {"error": "activity_id is required"}

    activity_id = str(activity_id).strip()

    row = await asyncio.to_thread(influx.query_cycling_dynamics, activity_id)

    if not row:
        return {
            "activity_id": activity_id,
            "data_note": (
                "No CyclingDynamics data found for this activity. "
                "This requires the garmin-grafana CyclingDynamics patch and "
                "a compatible Garmin power meter (Rally, Vector, or similar)."
            ),
            "cycling_dynamics": None,
        }

    lr = safe_float(row.get("left_right_balance"))

    return {
        "activity_id": activity_id,
        "power": {
            "normalized_power":      safe_float(row.get("normalized_power")),
            "training_stress_score": safe_float(row.get("training_stress_score")),
            "intensity_factor":      safe_float(row.get("intensity_factor")),
            "left_right_balance": {
                "left_pct":  lr,
                "right_pct": round(100.0 - lr, 1) if lr is not None else None,
            } if lr is not None else None,
        },
        "left_pedal": {
            "torque_effectiveness":      safe_float(row.get("avg_left_torque_effectiveness")),
            "pedal_smoothness":          safe_float(row.get("avg_left_pedal_smoothness")),
            "platform_center_offset_mm": safe_float(row.get("avg_left_pco")),
            "power_phase": {
                "start_deg": safe_float(row.get("avg_left_power_phase_start")),
                "end_deg":   safe_float(row.get("avg_left_power_phase_end")),
            },
            "power_phase_peak": {
                "start_deg": safe_float(row.get("avg_left_power_phase_peak_start")),
                "end_deg":   safe_float(row.get("avg_left_power_phase_peak_end")),
            },
        },
        "right_pedal": {
            "torque_effectiveness":      safe_float(row.get("avg_right_torque_effectiveness")),
            "pedal_smoothness":          safe_float(row.get("avg_right_pedal_smoothness")),
            "platform_center_offset_mm": safe_float(row.get("avg_right_pco")),
            "power_phase": {
                "start_deg": safe_float(row.get("avg_right_power_phase_start")),
                "end_deg":   safe_float(row.get("avg_right_power_phase_end")),
            },
            "power_phase_peak": {
                "start_deg": safe_float(row.get("avg_right_power_phase_peak_start")),
                "end_deg":   safe_float(row.get("avg_right_power_phase_peak_end")),
            },
        },
    }
