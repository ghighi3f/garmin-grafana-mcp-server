"""
Standalone test script for all MCP tools.

Calls each tool function directly (bypassing the HTTP/MCP layer) and prints
the raw JSON-serialisable output or any exception to stdout.

Usage:
    python test_tools.py

Requires a valid .env (or environment variables) pointing at a live InfluxDB.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from datetime import datetime

# Load env vars BEFORE importing influx or any tool module
from dotenv import load_dotenv
load_dotenv()

from tools.activity import get_last_activity, get_recent_activities  # noqa: E402
from tools.load import get_weekly_load_summary  # noqa: E402
from tools.recovery import get_daily_recovery  # noqa: E402
from tools.detail import get_activity_details  # noqa: E402
from tools.fitness import get_fitness_trend, get_training_zones  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dump(obj) -> str:
    """Best-effort JSON serialisation — converts un-serialisable types to str."""
    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, indent=2, default=_default)


def _header(title: str) -> None:
    width = 60
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


async def _call(label: str, coro) -> dict:
    """Run a coroutine, print the result, and return it (or an error dict)."""
    _header(label)
    try:
        result = await coro
        print(_dump(result))
        return result
    except Exception:
        print("[EXCEPTION]")
        traceback.print_exc()
        return {}


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

async def main() -> None:
    print()
    print("Garmin MCP — tool validation script")
    print(f"Python {sys.version}")
    print()

    # ------------------------------------------------------------------ #
    # 1. get_last_activity                                                 #
    # ------------------------------------------------------------------ #
    await _call(
        "1 / 7  get_last_activity()",
        get_last_activity(),
    )

    # ------------------------------------------------------------------ #
    # 2. get_recent_activities  (3 days, all sports, up to 5 rows)        #
    #    We also fish out the first activity_id for test 5 below.         #
    # ------------------------------------------------------------------ #
    recent_result = await _call(
        "2 / 7  get_recent_activities(days=7, sport_type='all', limit=5)",
        get_recent_activities(days=7, sport_type="all", limit=5),
    )

    # Try to find a usable activity_id for the detail test
    activity_id: str | None = None
    activities = recent_result.get("activities") or []
    for act in activities:
        candidate = act.get("activity_id")
        if candidate:
            activity_id = str(candidate)
            break

    if activity_id:
        print(f"\n[info] Will use activity_id '{activity_id}' for detail test.")
    else:
        activity_id = "DUMMY_ID_REPLACE_ME"
        print(f"\n[warn] No activity_id found in recent activities. "
              f"Using dummy '{activity_id}' — detail test will return 'not found'.")

    # ------------------------------------------------------------------ #
    # 3. get_weekly_load_summary  (last 4 weeks)                          #
    # ------------------------------------------------------------------ #
    await _call(
        "3 / 7  get_weekly_load_summary(weeks=4)",
        get_weekly_load_summary(weeks=4),
    )

    # ------------------------------------------------------------------ #
    # 4. get_daily_recovery  (last 7 days)                                #
    # ------------------------------------------------------------------ #
    await _call(
        "4 / 7  get_daily_recovery(days=7)",
        get_daily_recovery(days=7),
    )

    # ------------------------------------------------------------------ #
    # 5. get_activity_details  (real ID from step 2, or dummy)            #
    # ------------------------------------------------------------------ #
    await _call(
        f"5 / 7  get_activity_details(activity_id='{activity_id}')",
        get_activity_details(activity_id=activity_id),
    )

    # ------------------------------------------------------------------ #
    # 6. get_fitness_trend  (last 12 weeks)                               #
    # ------------------------------------------------------------------ #
    await _call(
        "6 / 7  get_fitness_trend(weeks=12)",
        get_fitness_trend(weeks=12),
    )

    # ------------------------------------------------------------------ #
    # 7. get_training_zones  (last 30 days, all sports)                   #
    # ------------------------------------------------------------------ #
    await _call(
        "7 / 7  get_training_zones(days=30, sport_type='all')",
        get_training_zones(days=30, sport_type="all"),
    )

    # ------------------------------------------------------------------ #
    # Bonus: edge-case — empty params / boundary clamp                    #
    # ------------------------------------------------------------------ #
    _header("BONUS  get_recent_activities(days=1, sport_type='running', limit=3)")
    print("[info] Narrow window — valid but may return empty list.")
    await _call(
        "BONUS  get_recent_activities(days=1, sport_type='running', limit=3)",
        get_recent_activities(days=1, sport_type="running", limit=3),
    )

    print()
    print("=" * 60)
    print("  All tool calls completed. Paste output above to Claude.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    asyncio.run(main())
