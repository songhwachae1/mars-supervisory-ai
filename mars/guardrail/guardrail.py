"""
Policy Guardrail Layer — §6 (light implementation)

Ordered stages:
  1. Schema validation (type in whitelist, required fields, legal ranges)
  2. Referential validation (referenced entities exist)
  3. Impact classification
  4. Feasibility / safety invariants  ← the critical stage
  5. Conflict resolution vs active policies
  6. Bounds & expiry normalization
  7. Rate limiting / hysteresis

Each candidate policy produces: ACCEPT | MODIFY | REJECT | DEFER_HUMAN
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from mars.config import (
    MAX_ACTIVE_AVOID_ZONES,
    POLICY_COOLDOWN_SEC,
    POLICY_MAX_DURATION_SEC,
    POLICY_MIN_DURATION_SEC,
    POLICY_WHITELIST,
)

log = logging.getLogger(__name__)


class GuardrailResult(str, Enum):
    ACCEPT       = "ACCEPT"
    MODIFY       = "MODIFY"
    REJECT       = "REJECT"
    DEFER_HUMAN  = "DEFER_HUMAN"


# Impact tiers per policy type
_IMPACT_TIER: dict[str, str] = {
    "prefer_alternate_route":       "LOW",
    "avoid_zone":                   "MEDIUM",
    "delay_low_priority_missions":  "MEDIUM",
    "reserve_chargers_for_critical": "MEDIUM",
    "lower_target_charge_level":    "MEDIUM",
    "pre_charge_for_demand_spike":  "MEDIUM",
}


def check(
    policy: dict[str, Any],
    active_policies: list[dict[str, Any]],
    world_state: dict[str, Any],
    last_applied: dict[str, float] | None = None,
) -> tuple[GuardrailResult, dict[str, Any], str]:
    """
    Run all guardrail stages.

    Args:
        policy:          candidate policy dict (type, params, duration_sec, ...)
        active_policies: currently active policy dicts
        world_state:     {zones: {zone_id: {charger_zone: bool, mandatory: bool}},
                          charger_zones: [zone_ids], ...}
        last_applied:    {policy_type: last_applied_timestamp}  for cooldown

    Returns:
        (GuardrailResult, possibly_modified_policy, notes_string)
    """
    notes = []
    modified = dict(policy)

    # Stage 1 — Schema validation
    p_type = policy.get("type", "")
    if p_type not in POLICY_WHITELIST:
        return GuardrailResult.REJECT, modified, f"type {p_type!r} not in whitelist"

    if not policy.get("duration_sec"):
        return GuardrailResult.REJECT, modified, "duration_sec is required"

    # Stage 2 — Referential validation
    zone = policy.get("params", {}).get("zone")
    if zone and world_state:
        zones = world_state.get("zones", {})
        if zone not in zones:
            return GuardrailResult.REJECT, modified, f"zone {zone!r} does not exist"

    # Stage 3 — Impact classification
    tier = _IMPACT_TIER.get(p_type, "MEDIUM")
    if tier == "HIGH":
        notes.append(f"HIGH impact policy requires elevated confidence or operator approval")
        return GuardrailResult.DEFER_HUMAN, modified, "; ".join(notes)

    # Stage 4 — Feasibility / safety invariants (per-policy + cumulative)
    result, feas_notes = _feasibility_check(policy, active_policies, world_state)
    if result == GuardrailResult.REJECT:
        return GuardrailResult.REJECT, modified, feas_notes
    if result == GuardrailResult.DEFER_HUMAN:
        return GuardrailResult.DEFER_HUMAN, modified, feas_notes
    notes.extend([feas_notes] if feas_notes else [])

    # Stage 5 — Conflict resolution
    for active in active_policies:
        if active.get("type") == p_type and active.get("params") == policy.get("params"):
            return GuardrailResult.REJECT, modified, f"duplicate of active policy {active.get('policy_id')}"
        # Contradictory: avoid_zone X vs prefer_route_through X (not in current whitelist)

    # Stage 6 — Bounds & expiry normalization
    dur = int(policy.get("duration_sec", POLICY_MIN_DURATION_SEC))
    if dur < POLICY_MIN_DURATION_SEC:
        dur = POLICY_MIN_DURATION_SEC
        notes.append(f"duration clamped to minimum {POLICY_MIN_DURATION_SEC}s")
    if dur > POLICY_MAX_DURATION_SEC:
        dur = POLICY_MAX_DURATION_SEC
        notes.append(f"duration clamped to maximum {POLICY_MAX_DURATION_SEC}s")
    modified["duration_sec"] = dur
    modified["expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=dur)

    # Stage 7 — Rate limiting / hysteresis
    # Cooldown is keyed on (type, zone) so the same zone is rate-limited across
    # bursts while different zones remain independent.
    if last_applied:
        import time
        zone_for_key = policy.get("params", {}).get("zone")
        cooldown_key = (p_type, zone_for_key) if zone_for_key else p_type
        last = last_applied.get(cooldown_key, 0)
        if time.time() - last < POLICY_COOLDOWN_SEC:
            return GuardrailResult.REJECT, modified, (
                f"cooldown: {p_type} zone={zone_for_key!r} applied < {POLICY_COOLDOWN_SEC}s ago"
            )

    final_result = GuardrailResult.MODIFY if notes else GuardrailResult.ACCEPT
    log.info("[guardrail] %s → %s  notes=%s", p_type, final_result, notes)
    return final_result, modified, "; ".join(notes)


def _feasibility_check(
    policy: dict[str, Any],
    active_policies: list[dict[str, Any]],
    world_state: dict[str, Any],
) -> tuple[GuardrailResult, str]:
    """
    Stage 4: ensure the policy doesn't violate global invariants.

    Two layers:
      Per-policy:  avoid_zone must not immediately strand robots from chargers.
      Cumulative:  union of active + proposed avoid_zones must not block charger
                   access or exceed MAX_ACTIVE_AVOID_ZONES.
    """
    if not world_state:
        return GuardrailResult.ACCEPT, ""

    p_type = policy.get("type", "")
    zone   = policy.get("params", {}).get("zone")

    if p_type == "avoid_zone" and zone:
        charger_zones = world_state.get("charger_zones", [])
        zones         = world_state.get("zones", {})

        charger_zone_ids = [
            zid for zid, zdata in zones.items()
            if zdata.get("is_charger_zone") or zid in charger_zones
        ]

        # Per-policy: reject if this single zone is the only charger zone
        if charger_zone_ids and all(czid == zone for czid in charger_zone_ids):
            return (
                GuardrailResult.REJECT,
                f"avoid_zone {zone!r} would strand all robots from chargers",
            )

        # Per-policy: reject mandatory zones
        mandatory_zones = [zid for zid, zd in zones.items() if zd.get("is_mandatory")]
        if zone in mandatory_zones:
            return (
                GuardrailResult.REJECT,
                f"avoid_zone {zone!r} is a mandatory zone — cannot be avoided",
            )

        # Cumulative: collect all currently active avoid_zones + proposed
        active_avoid = {
            p.get("params", {}).get("zone")
            for p in active_policies
            if p.get("type") == "avoid_zone" and p.get("params", {}).get("zone")
        }
        active_avoid.add(zone)

        # MAX_ACTIVE_AVOID_ZONES cap: too many concurrent avoidances signals
        # a fleet-wide problem → escalate rather than stacking another policy
        if len(active_avoid) > MAX_ACTIVE_AVOID_ZONES:
            return (
                GuardrailResult.DEFER_HUMAN,
                f"avoid_zone count {len(active_avoid)} > MAX_ACTIVE_AVOID_ZONES="
                f"{MAX_ACTIVE_AVOID_ZONES}: escalate to fleet-wide handling",
            )

        # Cumulative charger reachability: any charger zone still accessible?
        if charger_zone_ids:
            reachable = [czid for czid in charger_zone_ids if czid not in active_avoid]
            if not reachable:
                return (
                    GuardrailResult.REJECT,
                    f"cumulative avoid_zones {sorted(active_avoid)!r} would block "
                    "all charger access",
                )

    # Charging viability — reserve_chargers_for_critical must leave at least
    # one charger available for normal (non-critical) robots.
    if p_type == "reserve_chargers_for_critical":
        reserve_count  = int(policy.get("params", {}).get("reserve_count", 1))
        total_chargers = world_state.get("total_chargers", 0)
        if total_chargers > 0 and reserve_count >= total_chargers:
            return (
                GuardrailResult.REJECT,
                f"reserve_chargers_for_critical count={reserve_count} ≥ "
                f"total_chargers={total_chargers}: would leave no chargers for normal robots",
            )

    return GuardrailResult.ACCEPT, ""
