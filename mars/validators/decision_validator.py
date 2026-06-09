"""
Decision Validator — §5

Deterministic gate on agent output.  Applies to Failure Analysis Agent,
Operations Strategy Agent, and Fleet State Analysis Agent.

Four checks:
  1. CONFIDENCE THRESHOLD  — confidence >= tau(action_class)
  2. EVIDENCE GROUNDING    — every evidence.refs resolves against the input bundle
  3. EVIDENCE CONSISTENCY  — evidence supports the stated scope/cause
  4. RETRIEVAL COHERENCE   — HIGH confidence but LOW retrieval_trust + used precedent

Outcomes: PASS | DEGRADE | REJECT
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from mars.config import (
    DV_TAU_DIAGNOSIS,
    DV_TAU_POLICY_HIGH,
    DV_TAU_POLICY_MEDIUM,
)

log = logging.getLogger(__name__)

# Impact tiers for Operations Strategy Agent
_HIGH_IMPACT_POLICIES = {"fleet_wide_throttle"}   # not in current whitelist but future-proof
_MEDIUM_IMPACT_POLICIES = {
    "avoid_zone",
    "delay_low_priority_missions",
    "reserve_chargers_for_critical",
    "lower_target_charge_level",
    "pre_charge_for_demand_spike",
}


class DVResult(str, Enum):
    PASS    = "PASS"
    DEGRADE = "DEGRADE"
    REJECT  = "REJECT"


import re as _re

_MISSING = object()  # sentinel: field does not exist


def _path_exists(ref: str, root: Any) -> bool:
    """Walk a JSON-path ref ('a.b[0].c') from `root`. True if the path exists
    (value may be None — a null field is still verifiable evidence)."""
    current = root
    for segment in ref.split("."):
        if not isinstance(current, dict):
            return False
        if "[" in segment:
            name, rest = segment.split("[", 1)
            try:
                idx = int(rest.rstrip("]"))
            except ValueError:
                return False
            current = current.get(name, _MISSING)
            if current is _MISSING or not isinstance(current, list) or idx >= len(current):
                return False
            current = current[idx]
        else:
            current = current.get(segment, _MISSING)
            if current is _MISSING:
                return False
    return True


def _resolves_nested(ref: str, node: Any, _depth: int = 0) -> bool:
    if _depth > 6 or not isinstance(node, dict):
        return False
    for value in node.values():
        if isinstance(value, dict):
            if _path_exists(ref, value) or _resolves_nested(ref, value, _depth + 1):
                return True
        elif isinstance(value, list):
            for el in value:
                if isinstance(el, dict) and (
                    _path_exists(ref, el) or _resolves_nested(ref, el, _depth + 1)
                ):
                    return True
    return False


def _resolve_ref(ref: str, bundle: dict[str, Any]) -> bool:
    """
    Grounded if the ref resolves as a path from the bundle root
    (e.g. "incident_analysis.scope") OR — because agents often cite a field by
    its section-relative name (e.g. "zone_state" instead of the full path) — if
    it resolves under any nested dict the agent actually received. A field that
    exists nowhere in the bundle still fails, so the hallucination guard holds.
    """
    if _path_exists(ref, bundle):
        return True
    return _resolves_nested(ref, bundle)


def _retrieved_precedent_ids(bundle: dict) -> set[str]:
    """
    Return the set of stable IDs from the bundle's `retrieved_precedents` list.
    Only IDs that were actually retrieved are in this set — fabricated IDs never
    appear here, preserving the hallucination guard.

    Two retrieval paths expose the identifier under different keys:
      - failure investigator (search_incidents): renames it to `id` → DX… string
      - fleet monitor (search_similar / SELECT *): keeps `source_id` → DX… string,
        while `id` is the integer PK of incident_embeddings
    Collecting both as strings ensures the grounding helper matches either path.
    """
    ids: set[str] = set()
    for p in (bundle.get("retrieved_precedents") or []):
        if not isinstance(p, dict):
            continue
        for key in ("id", "source_id"):
            v = p.get(key)
            if v is not None:
                ids.add(str(v))
    return ids


def _ref_grounded(ref: str, bundle: dict) -> bool:
    """
    A ref is grounded if it is either:
      - a JSON-path that resolves against the bundle, OR
      - a retrieved-precedent ID that the agent actually received.

    Citing a precedent by stable ID (e.g. "DX157601ead162") is a *better*
    reference than a positional one (which breaks if the list reorders), and
    is already consistent with how `relied_on_precedents` uses IDs.  Only
    IDs present in `retrieved_precedents` are accepted — unknown IDs still fail.
    """
    if ref in _retrieved_precedent_ids(bundle):
        return True
    return _resolve_ref(ref, bundle)


def _referenced_robot_ids(evidence: list[dict], bundle: dict) -> set[str]:
    """
    For each evidence ref that targets `mission_failures`, resolve it to the
    robot_id(s) it points at and return the set of distinct robot IDs.

    Handles:
      "mission_failures"        → all robots in the array
      "mission_failures[N]"     → robot at index N
      "mission_failures[N].foo" → robot at index N (field suffix ignored)

    Out-of-range indices and missing robot_id fields contribute nothing —
    the grounding check already flags truly unresolvable refs separately.
    """
    mf = bundle.get("mission_failures") or []
    robots: set[str] = set()
    for item in evidence:
        for ref in item.get("refs", []):
            if not ref.startswith("mission_failures"):
                continue
            m = _re.match(r"mission_failures(?:\[(\d+)\])?", ref)
            if m is None:
                continue
            idx = m.group(1)
            if idx is None:                        # bare array ref → all robots
                robots.update(e.get("robot_id") for e in mf if e.get("robot_id"))
            else:                                  # mission_failures[i] (+ optional .field)
                i = int(idx)
                if 0 <= i < len(mf) and mf[i].get("robot_id"):
                    robots.add(mf[i]["robot_id"])
    return robots


def _tau_for_diagnosis() -> float:
    return DV_TAU_DIAGNOSIS


def _tau_for_policy(policy_type: str) -> float:
    if policy_type in _HIGH_IMPACT_POLICIES:
        return DV_TAU_POLICY_HIGH
    return DV_TAU_POLICY_MEDIUM


def validate_diagnosis(
    agent_output: dict[str, Any],
    input_bundle: dict[str, Any],
    retrieval_trust: dict[str, Any] | None = None,
) -> tuple[DVResult, str]:
    """
    Validate Failure Analysis Agent output.

    Returns (DVResult, notes_string).
    """
    notes = []
    result = DVResult.PASS

    confidence = float(agent_output.get("confidence", 0.0))
    tau = _tau_for_diagnosis()

    # 1. Confidence threshold
    if confidence < tau:
        notes.append(f"confidence {confidence:.2f} < tau {tau:.2f}")
        result = DVResult.DEGRADE

    # 2. Evidence grounding — every ref must resolve
    evidence = agent_output.get("evidence", [])
    if not evidence:
        notes.append("evidence is empty")
        result = DVResult.DEGRADE
    else:
        for item in evidence:
            for ref in item.get("refs", []):
                if not _ref_grounded(ref, input_bundle):
                    notes.append(f"unresolvable ref: {ref!r}")
                    result = DVResult.REJECT

    # 3. Consistency: zone_wide/fleet_wide scope must cite ≥2 distinct robots.
    #    We resolve each mission_failures ref to its actual robot_id rather than
    #    counting ref strings — a bare "mission_failures" ref covering four robots
    #    counts correctly, and two refs to [0] (same robot) still counts as one.
    scope = agent_output.get("scope", "")
    if scope in ("zone_wide", "fleet_wide"):
        robots = _referenced_robot_ids(evidence, input_bundle)
        if len(robots) < 2:
            notes.append(
                f"scope={scope} but evidence cites <2 distinct robots in mission_failures"
            )
            if result == DVResult.PASS:
                result = DVResult.DEGRADE

    # 4. Retrieval coherence
    if retrieval_trust:
        relied = agent_output.get("relied_on_precedents", [])
        trust_level = retrieval_trust.get("set_level", "LOW")
        if relied and trust_level == "LOW" and confidence > 0.7:
            notes.append(
                "HIGH confidence despite LOW retrieval_trust and relied_on_precedents non-empty"
            )
            result = DVResult.DEGRADE

    notes_str = "; ".join(notes) if notes else "ok"
    log.info("[decision_validator] diagnosis → %s  notes=%s", result, notes_str)
    return result, notes_str


def validate_strategy(
    agent_output: dict[str, Any],
    input_bundle: dict[str, Any],
    retrieval_trust: dict[str, Any] | None = None,
) -> tuple[DVResult, str]:
    """
    Validate Operations Strategy Agent output.
    """
    notes = []
    result = DVResult.PASS

    confidence = float(agent_output.get("confidence", 0.0))
    policy_updates = agent_output.get("policy_updates", [])

    # Determine highest-impact policy in the output
    max_tau = DV_TAU_POLICY_MEDIUM
    for p in policy_updates:
        max_tau = max(max_tau, _tau_for_policy(p.get("type", "")))

    # 1. Confidence threshold
    if confidence < max_tau:
        notes.append(f"confidence {confidence:.2f} < tau {max_tau:.2f}")
        result = DVResult.DEGRADE

    # 2. Evidence grounding
    evidence = agent_output.get("evidence", [])
    for item in evidence:
        for ref in item.get("refs", []):
            if not _ref_grounded(ref, input_bundle):
                notes.append(f"unresolvable ref: {ref!r}")
                result = DVResult.REJECT

    # 3. Consistency: policy recommendation must tie to evidence
    # (light check — full consistency is subjective, so we only reject if
    #  there is NO evidence at all for a non-empty recommendation)
    if policy_updates and not evidence:
        notes.append("policy_updates non-empty but evidence is empty")
        result = DVResult.DEGRADE

    # 4. Retrieval coherence
    if retrieval_trust:
        relied = agent_output.get("relied_on_precedents", [])
        trust_level = retrieval_trust.get("set_level", "LOW")
        if relied and trust_level == "LOW" and confidence > 0.7:
            notes.append("HIGH confidence despite LOW retrieval_trust")
            result = DVResult.DEGRADE

    notes_str = "; ".join(notes) if notes else "ok"
    log.info("==============================================\n\n")
    log.info("[decision_validator] strategy → %s  notes=%s", result, notes_str)
    log.info("==============================================\n\n")
    return result, notes_str


def validate_fleet_state(
    agent_output: dict[str, Any],
    input_bundle: dict[str, Any],
    retrieval_trust: dict[str, Any] | None = None,
) -> tuple[DVResult, str]:
    """
    Validate Fleet State Analysis Agent output (same checks, diagnosis tau).
    """
    # Reuse diagnosis validation logic (same threshold)
    return validate_diagnosis(agent_output, input_bundle, retrieval_trust)
