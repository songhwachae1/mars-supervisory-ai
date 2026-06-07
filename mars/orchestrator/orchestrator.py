"""
Orchestrator — coordinates the slow-path failure analysis workflow.

Responsibilities:
  1. Receive enriched failure events from Aggregator
  2. Call Router to select FAST or SLOW path
  3. On SLOW path: query blackboard, run Retrieval Validator, call agent,
     run Decision Validator, then route to Strategy Trigger Rules
  4. On FAST path: run fast_disposition() immediately

Stateless between events; all durable state is in the blackboard.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from mars.router.router import Path, route
from mars.validators.decision_validator import DVResult, validate_diagnosis

log = logging.getLogger(__name__)


def fast_disposition(failure_event: dict[str, Any]) -> str:
    """
    §3 fast path — deterministic, no LLM.

    Returns one of: 'handoff' | 'retry' | 'escalate'
    """
    fault_flag = failure_event.get("fault_flag")
    failures_for_mission = failure_event.get("failures_for_this_mission", 0)

    if fault_flag:
        # established robot-internal fault — handoff is safe
        return "handoff"

    if failures_for_mission == 0:
        # first failure, no fault — absorb transient glitch
        return "retry"

    # persists with no fault flag → escalate to slow path
    return "escalate"


def slow_disposition(
    failure_event: dict[str, Any],
    diagnosis: dict[str, Any],
    active_policies: list[dict[str, Any]],
) -> str:
    """
    §3 slow path — uses agent diagnosis (post Decision Validator).

    Returns one of: 'reschedule' | 'hold_defer' | 'retry' | 'handoff' | 'abort'
    """
    scope = diagnosis.get("scope", "isolated")
    persistence = diagnosis.get("persistence", "persistent")
    retry_budget = 2   # conservative default — see DECISIONS.md

    if scope in ("zone_wide", "fleet_wide"):
        # handoff propagates the failure → never handoff for env failures
        zone = failure_event.get("zone")
        avoid_active = any(
            p.get("type") == "avoid_zone" and p.get("params", {}).get("zone") == zone
            for p in active_policies
        )
        if avoid_active:
            return "hold_defer"
        return "reschedule"

    if scope in ("isolated", "robot_specific"):
        if persistence == "transient" and failure_event.get("failures_for_this_mission", 0) < retry_budget:
            return "retry"
        return "handoff"

    return "reschedule"


class Orchestrator:
    def __init__(
        self,
        blackboard_queries,
        hot_state,
        failure_analysis_agent,
        retrieval_validator_fn,   # kept for strategy/fleet agents; not used on slow path
        decision_validator_fn,
        strategy_trigger_fn,
        policy_manager,
        embedder,
    ):
        self._bb = blackboard_queries
        self._hot = hot_state
        self._fa_agent = failure_analysis_agent
        self._rv = retrieval_validator_fn
        self._dv = decision_validator_fn
        self._strategy_trigger = strategy_trigger_fn
        self._pm = policy_manager
        self._embedder = embedder

    def handle_failure(
        self, failure_event: dict[str, Any], conn
    ) -> dict[str, Any]:
        """
        Fast-path entry point — called immediately per failure after ingest.

        Failure is already persisted at ingest; failure_id is on the event.
        This method handles FAST disposition only; slow-path analysis is
        coalesced per zone and driven through handle_slow_analysis().
        """
        robot_id   = failure_event.get("robot_id", "?")
        zone       = failure_event.get("zone", "unknown")
        failure_id = failure_event.get("failure_id")  # pre-persisted at ingest

        disposition = failure_event.get("_disposition") or fast_disposition(failure_event)
        log.info("[orchestrator] FAST  robot=%s zone=%s disposition=%s",
                 robot_id, zone, disposition)
        return {"path": "fast", "disposition": disposition, "failure_id": failure_id}

    def handle_slow_analysis(
        self, trigger_event: dict[str, Any], conn
    ) -> dict[str, Any]:
        """
        Coalesced slow-path entry point — called ONCE per zone-burst.

        trigger_event is the latest slow failure in the zone; its failure_id
        is the FK for the diagnosis row.  All failures in the burst are
        already persisted (Change 1) and visible to the investigator's tools.
        """
        robot_id   = trigger_event.get("robot_id", "?")
        zone       = trigger_event.get("zone", "unknown")
        failure_id = trigger_event.get("failure_id")

        log.info("[orchestrator] SLOW (coalesced)  zone=%s trigger_robot=%s", zone, robot_id)

        # Provisional safe action
        log.info("[orchestrator] provisional safe action: HOLD robot=%s", robot_id)

        active_policies = self._pm.get_active()

        # Investigator: evidence assembled via read-only tool calls.
        # INVARIANT: trigger_event.distribution is a routing signal only;
        # the investigator derives scope from raw failures it queries itself.
        agent_output = self._fa_agent.analyze(trigger_event=trigger_event)

        # Decision Validator — grounded against tool transcript
        transcript = agent_output.get("_tool_transcript", {})
        retrieved_precedents = transcript.get("retrieved_precedents", [])
        if retrieved_precedents and isinstance(retrieved_precedents[0], dict):
            scores = [p.get("_trust_score", 0) for p in retrieved_precedents]
            avg    = sum(scores) / len(scores) if scores else 0
            trust_level = "HIGH" if avg >= 0.7 else "MEDIUM" if avg >= 0.4 else "LOW"
        else:
            trust_level = "LOW"
        retrieval_trust = {
            "set_level":     trust_level,
            "support_count": len(retrieved_precedents),
        }
        dv_result, dv_notes = self._dv(agent_output, transcript, retrieval_trust)
        log.info("===========dv result===============\n%s", dv_result)
        log.info("===========dv result===============\n%s", dv_notes)

        # Write diagnosis — attaches to the representative (latest) failure_id
        cause   = agent_output.get("cause", "unknown")
        scope   = agent_output.get("scope", "isolated")
        persist = agent_output.get("persistence", "persistent")
        diagnosis_id = self._bb.write_diagnosis(
            conn,
            {
                "failure_id": failure_id,
                "cause": cause,
                "scope": scope,
                "persistence": persist,
                "affected_zone": agent_output.get("affected_zone"),
                "confidence": agent_output.get("confidence", 0.0),
                "evidence": agent_output.get("evidence", []),
                "relied_on_precedents": agent_output.get("relied_on_precedents", []),
                "decision_validator_result": dv_result.value,
                "decision_validator_notes": dv_notes,
                "retrieval_trust_level": retrieval_trust["set_level"],
            },
        )

        # Embed the diagnosis for future RAG retrieval (PASS/DEGRADE only)
        if dv_result != DVResult.REJECT:
            try:
                from mars.blackboard.queries import write_embedding
                from datetime import datetime, timezone as _tz
                _occurred = trigger_event.get("occurred_at")
                if isinstance(_occurred, (int, float)):
                    _occurred = datetime.fromtimestamp(_occurred, tz=_tz.utc)
                _occurred = _occurred or datetime.now(_tz.utc)
                _summary = (
                    f"zone:{zone} cause:{cause} scope:{scope} persistence:{persist} "
                    f"confidence:{agent_output.get('confidence', 0.0):.2f}"
                )
                _emb = self._embedder.embed(_summary)
                write_embedding(conn, {
                    "source_type": "diagnosis",
                    "source_id":   diagnosis_id,
                    "zone":        zone,
                    "failure_type": cause,
                    "scope":       scope,
                    "summary":     _summary,
                    "embedding":   _emb,
                    "recorded_at": _occurred,
                })
            except Exception:
                log.warning("[orchestrator] embedding failed for diagnosis %s — skipping", diagnosis_id)

        conn.commit()

        if dv_result == DVResult.REJECT:
            log.warning("[orchestrator] REJECT — safe default + operator flag")
            return {
                "path": "slow", "dv_result": "REJECT", "disposition": "hold_defer",
                "failure_id": failure_id, "diagnosis_id": diagnosis_id,
            }

        # Disposition
        effective_diagnosis = agent_output if dv_result == DVResult.PASS else {
            **agent_output,
            "scope": "isolated",       # conservative on DEGRADE
            "persistence": "persistent",
        }
        disposition = slow_disposition(trigger_event, effective_diagnosis, active_policies)

        # Strategy Trigger Rules
        self._strategy_trigger(
            failure_out=effective_diagnosis,
            failure_id=failure_id,
            diagnosis_id=diagnosis_id,
            conn=conn,
        )

        return {
            "path": "slow",
            "dv_result": dv_result.value,
            "disposition": disposition,
            "failure_id": failure_id,
            "diagnosis_id": diagnosis_id,
        }
