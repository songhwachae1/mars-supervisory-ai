"""
Numeric thresholds for semantic event detection.

Defines the boundary values at which raw sensor readings
cross into meaningful semantic states.

All monitors and EventDetector import from here — no threshold
values should be hardcoded anywhere else.
"""


# ─────────────────────────────────────────────
# Battery
# ─────────────────────────────────────────────

BATTERY_LOW_PCT      = 20.0   # below this → battery_low event
BATTERY_CRITICAL_PCT = 10.0   # below this → battery_critical event

BATTERY_VOLTAGE_MIN  = 9.0    # voltage at 0% charge (for normalization)
BATTERY_VOLTAGE_MAX  = 12.6   # voltage at 100% charge (for normalization)


# ─────────────────────────────────────────────
# Health Score
# health_score is a float from 0.0 (failed) to 1.0 (perfect)
# ─────────────────────────────────────────────

HEALTH_DEGRADED = 0.6   # below this → health_degraded event
HEALTH_CRITICAL = 0.3   # below this → health_critical event
