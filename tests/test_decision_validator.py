"""
Unit tests for Decision Validator — §5

Critical tests per coding prompt:
  - ref resolver (grounding check must actually resolve refs)
  - threshold / confidence check
  - consistency check (scope vs evidence)
"""
from __future__ import annotations

import pytest

from mars.validators.decision_validator import (
    DVResult,
    _resolve_ref,
    _ref_grounded,
    _retrieved_precedent_ids,
    validate_diagnosis,
    validate_strategy,
)


# ---------------------------------------------------------------------------
# ref resolver tests
# ---------------------------------------------------------------------------

class TestResolveRef:
    def test_simple_field(self):
        bundle = {"trigger_event": {"robot_id": "R1"}}
        assert _resolve_ref("trigger_event", bundle) is True

    def test_nested_field(self):
        bundle = {"trigger_event": {"robot_id": "R1"}}
        assert _resolve_ref("trigger_event.robot_id", bundle) is True

    def test_list_index(self):
        bundle = {"mission_failures": [{"robot_id": "R1"}, {"robot_id": "R2"}]}
        assert _resolve_ref("mission_failures[0]", bundle) is True
        assert _resolve_ref("mission_failures[1]", bundle) is True

    def test_list_index_subfield(self):
        bundle = {"mission_failures": [{"robot_id": "R1"}]}
        assert _resolve_ref("mission_failures[0].robot_id", bundle) is True

    def test_out_of_bounds_index(self):
        bundle = {"mission_failures": [{"robot_id": "R1"}]}
        assert _resolve_ref("mission_failures[5]", bundle) is False

    def test_missing_field(self):
        bundle = {"trigger_event": {"robot_id": "R1"}}
        assert _resolve_ref("trigger_event.missing_key", bundle) is False

    def test_missing_top_level(self):
        bundle = {}
        assert _resolve_ref("nonexistent", bundle) is False

    def test_null_value_returns_true(self):
        # A null field IS verifiable evidence (e.g. fault_flag=null means no fault).
        # Only a non-existent path is unresolvable.
        bundle = {"trigger_event": {"fault_flag": None}}
        assert _resolve_ref("trigger_event.fault_flag", bundle) is True

    def test_nonexistent_field_returns_false(self):
        bundle = {"trigger_event": {"fault_flag": None}}
        assert _resolve_ref("trigger_event.nonexistent_key", bundle) is False


# ---------------------------------------------------------------------------
# Confidence threshold tests
# ---------------------------------------------------------------------------

class TestConfidenceThreshold:
    def _make_output(self, confidence, scope="isolated"):
        return {
            "cause": "zone_congestion",
            "scope": scope,
            "persistence": "persistent",
            "confidence": confidence,
            "evidence": [
                {"observation": "test", "refs": ["trigger_event.robot_id"]},
            ],
            "relied_on_precedents": [],
        }

    def _make_bundle(self):
        return {
            "trigger_event": {"robot_id": "R1", "fault_flag": None},
            "mission_failures": [{"robot_id": "R1"}],
        }

    def test_pass_above_threshold(self):
        result, _ = validate_diagnosis(self._make_output(0.8), self._make_bundle())
        assert result == DVResult.PASS

    def test_degrade_below_threshold(self):
        result, _ = validate_diagnosis(self._make_output(0.2), self._make_bundle())
        assert result == DVResult.DEGRADE

    def test_exactly_at_threshold_passes(self):
        # DV_TAU_DIAGNOSIS = 0.5 by default
        result, _ = validate_diagnosis(self._make_output(0.5), self._make_bundle())
        assert result == DVResult.PASS


# ---------------------------------------------------------------------------
# Grounding / ref resolution tests
# ---------------------------------------------------------------------------

class TestGrounding:
    def test_unresolvable_ref_causes_reject(self):
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.9,
            "evidence": [
                {"observation": "test", "refs": ["mission_failures[0].robot_id"]},
                {"observation": "hallucinated ref", "refs": ["nonexistent_field.count"]},
            ],
            "relied_on_precedents": [],
        }
        bundle = {
            "trigger_event": {"robot_id": "R1", "fault_flag": None},
            "mission_failures": [{"robot_id": "R1"}],
        }
        result, notes = validate_diagnosis(output, bundle)
        assert result == DVResult.REJECT
        assert "unresolvable ref" in notes

    def test_all_refs_valid_passes_grounding(self):
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.9,
            "evidence": [
                {"observation": "multiple robots", "refs": ["mission_failures[0]", "mission_failures[1]"]},
            ],
            "relied_on_precedents": [],
        }
        bundle = {
            "trigger_event": {"robot_id": "R1", "fault_flag": None},
            "mission_failures": [{"robot_id": "R1"}, {"robot_id": "R2"}],
        }
        result, _ = validate_diagnosis(output, bundle)
        assert result == DVResult.PASS


# ---------------------------------------------------------------------------
# Precedent-ID grounding tests
# ---------------------------------------------------------------------------

class TestPrecedentIdGrounding:
    """
    Agents may cite retrieved precedents by stable ID instead of positional
    refs.  _ref_grounded must accept IDs that were actually retrieved and
    reject IDs that were not.
    """

    _bundle_with_precedents = {
        "trigger_event": {"robot_id": "R1", "fault_flag": None},
        "mission_failures": [{"robot_id": "R1"}, {"robot_id": "R2"}],
        "retrieved_precedents": [
            {"id": "DX157601ead162", "summary": "zone congestion at dock", "trust": 0.85},
            {"id": "INC#42",         "summary": "similar zone block event",  "trust": 0.73},
        ],
    }

    def test_retrieved_precedent_id_is_grounded(self):
        """A ref that is a retrieved precedent's stable ID → grounded (no REJECT)."""
        assert _ref_grounded("DX157601ead162", self._bundle_with_precedents) is True

    def test_fabricated_id_is_unresolvable(self):
        """A DX…-looking ID not in retrieved_precedents → hallucinated → False."""
        assert _ref_grounded("DX999fabricated", self._bundle_with_precedents) is False

    def test_retrieved_precedent_ids_helper(self):
        ids = _retrieved_precedent_ids(self._bundle_with_precedents)
        assert ids == {"DX157601ead162", "INC#42"}

    def test_empty_precedents_returns_empty_set(self):
        assert _retrieved_precedent_ids({}) == set()
        assert _retrieved_precedent_ids({"retrieved_precedents": []}) == set()

    def test_diagnosis_with_id_ref_passes(self):
        """
        The M2 fleet case: evidence citing a retrieved precedent by ID
        must not produce an unresolvable-ref REJECT.
        """
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.82,
            "evidence": [
                {
                    "observation": "similar congestion event resolved with avoid_zone",
                    "refs": ["DX157601ead162"],   # cited by stable ID
                },
                {
                    "observation": "4 distinct robots failed in zone",
                    "refs": ["mission_failures[0]", "mission_failures[1]"],
                },
            ],
            "relied_on_precedents": ["DX157601ead162"],
        }
        result, notes = validate_diagnosis(output, self._bundle_with_precedents)
        assert result != DVResult.REJECT, (
            f"ID ref from retrieved_precedents should be grounded; got {result}, notes={notes}"
        )

    def test_fabricated_id_ref_still_rejects(self):
        """A precedent ID not in retrieved_precedents is unresolvable → REJECT."""
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.82,
            "evidence": [
                {
                    "observation": "hallucinated precedent",
                    "refs": ["DX999fabricated"],  # not in retrieved_precedents
                },
                {
                    "observation": "two robots",
                    "refs": ["mission_failures[0]", "mission_failures[1]"],
                },
            ],
            "relied_on_precedents": [],
        }
        result, notes = validate_diagnosis(output, self._bundle_with_precedents)
        assert result == DVResult.REJECT
        assert "unresolvable ref" in notes

    def test_strategy_with_id_ref_passes(self):
        """validate_strategy uses _ref_grounded too — same fix applies."""
        output = {
            "policy_updates": [
                {"type": "avoid_zone", "params": {"zone": "Receiving Dock"},
                 "duration_sec": 900, "rationale": "zone congestion confirmed"}
            ],
            "no_action_reason": None,
            "confidence": 0.78,
            "evidence": [
                {"observation": "prior avoid_zone effective",
                 "refs": ["INC#42"]},  # valid retrieved-precedent ID
                {"observation": "incident scope",
                 "refs": ["incident_analysis.scope"]},
            ],
            "relied_on_precedents": ["INC#42"],
        }
        bundle_with_ids = {
            "incident_analysis": {"scope": "zone_wide", "affected_zone": "Receiving Dock"},
            "retrieved_precedents": [
                {"id": "INC#42", "summary": "dock congestion", "trust": 0.73},
            ],
        }
        result, notes = validate_strategy(output, bundle_with_ids)
        assert result != DVResult.REJECT, (
            f"INC#42 is retrieved; should be grounded; got {result}, notes={notes}"
        )


# ---------------------------------------------------------------------------
# Consistency tests
# ---------------------------------------------------------------------------

class TestConsistency:
    # Helper bundles
    _four_robot_bundle = {
        "trigger_event": {"robot_id": "R1", "fault_flag": None},
        "mission_failures": [
            {"robot_id": "R1", "zone": "Receiving Dock"},
            {"robot_id": "R2", "zone": "Receiving Dock"},
            {"robot_id": "R3", "zone": "Receiving Dock"},
            {"robot_id": "R4", "zone": "Receiving Dock"},
        ],
    }

    def test_bare_array_ref_counts_all_robots_no_degrade(self):
        """
        The real-world case: refs: ["mission_failures"] (bare array) with four
        robots in the bundle should resolve to 4 distinct robots → no DEGRADE.
        This was spuriously DEGRADE-ing under the old string-count approach.
        """
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.9,
            "evidence": [
                {"observation": "4 distinct robots failed",
                 "refs": ["mission_failures", "zone_state", "retrieved_precedents[4]"]},
            ],
            "relied_on_precedents": [],
        }
        bundle = dict(self._four_robot_bundle)
        bundle["zone_state"] = {"zone": "Receiving Dock"}
        bundle["retrieved_precedents"] = [{}] * 5
        result, notes = validate_diagnosis(output, bundle)
        assert result == DVResult.PASS, (
            f"bare array ref should count 4 robots and pass; got {result}, notes={notes}"
        )

    def test_zone_wide_citing_only_one_robot_degrades(self):
        """zone_wide citing only mission_failures[0] → 1 distinct robot → DEGRADE."""
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.8,
            "evidence": [
                {"observation": "one robot", "refs": ["mission_failures[0]"]},
            ],
            "relied_on_precedents": [],
        }
        bundle = {
            "trigger_event": {"robot_id": "R1", "fault_flag": None},
            "mission_failures": [{"robot_id": "R1"}],
        }
        result, notes = validate_diagnosis(output, bundle)
        assert result == DVResult.DEGRADE
        assert "distinct robots" in notes

    def test_duplicate_index_refs_count_once(self):
        """
        Two refs to mission_failures[0] (same robot) must still count as 1 robot
        → DEGRADE. Old string-count would wrongly pass this.
        """
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.8,
            "evidence": [
                {"observation": "same robot twice",
                 "refs": ["mission_failures[0]", "mission_failures[0].zone"]},
            ],
            "relied_on_precedents": [],
        }
        bundle = {
            "trigger_event": {"robot_id": "R1", "fault_flag": None},
            "mission_failures": [{"robot_id": "R1", "zone": "Dock"}],
        }
        result, notes = validate_diagnosis(output, bundle)
        assert result == DVResult.DEGRADE
        assert "distinct robots" in notes

    def test_robot_specific_scope_unaffected(self):
        """robot_specific diagnosis with a single ref must not trigger the zone check."""
        output = {
            "cause": "robot_internal_fault",
            "scope": "robot_specific",
            "persistence": "persistent",
            "confidence": 0.8,
            "evidence": [
                {"observation": "motor fault", "refs": ["trigger_event.fault_flag"]},
            ],
            "relied_on_precedents": [],
        }
        bundle = {
            "trigger_event": {"robot_id": "R1", "fault_flag": "diagnostics_error"},
            "mission_failures": [],
        }
        result, _ = validate_diagnosis(output, bundle)
        assert result == DVResult.PASS

    def test_zone_wide_two_distinct_robots_passes(self):
        """Two distinct robots cited → ≥2 threshold satisfied → no DEGRADE from this rule."""
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.8,
            "evidence": [
                {"observation": "two robots",
                 "refs": ["mission_failures[0]", "mission_failures[1]"]},
            ],
            "relied_on_precedents": [],
        }
        bundle = {
            "trigger_event": {"robot_id": "R1", "fault_flag": None},
            "mission_failures": [{"robot_id": "R1"}, {"robot_id": "R2"}],
        }
        result, _ = validate_diagnosis(output, bundle)
        assert result == DVResult.PASS


# ---------------------------------------------------------------------------
# Retrieval coherence tests
# ---------------------------------------------------------------------------

class TestRetrievalCoherence:
    def test_high_confidence_low_trust_precedent_degrades(self):
        output = {
            "cause": "zone_congestion",
            "scope": "zone_wide",
            "persistence": "persistent",
            "confidence": 0.9,
            "evidence": [
                {"observation": "ref", "refs": ["mission_failures[0]", "mission_failures[1]"]},
            ],
            "relied_on_precedents": ["STRAT#19"],
        }
        bundle = {
            "trigger_event": {"robot_id": "R1", "fault_flag": None},
            "mission_failures": [{"robot_id": "R1"}, {"robot_id": "R2"}],
        }
        retrieval_trust = {"set_level": "LOW", "support_count": 0}
        result, notes = validate_diagnosis(output, bundle, retrieval_trust)
        assert result == DVResult.DEGRADE
        assert "LOW retrieval_trust" in notes


# ---------------------------------------------------------------------------
# Strategy validation
# ---------------------------------------------------------------------------

class TestStrategyValidation:
    def test_strategy_with_grounded_evidence_passes(self):
        output = {
            "policy_updates": [
                {"type": "avoid_zone", "params": {"zone": "Dock"}, "duration_sec": 900, "rationale": "x"}
            ],
            "no_action_reason": None,
            "confidence": 0.8,
            "evidence": [
                {"observation": "zone congestion", "refs": ["incident_analysis.scope"]},
            ],
            "relied_on_precedents": [],
        }
        bundle = {"incident_analysis": {"scope": "zone_wide", "affected_zone": "Dock"}}
        result, _ = validate_strategy(output, bundle)
        assert result == DVResult.PASS

    def test_empty_policy_updates_with_reason_passes(self):
        output = {
            "policy_updates": [],
            "no_action_reason": "situation is transient",
            "confidence": 0.7,
            "evidence": [],
            "relied_on_precedents": [],
        }
        bundle = {}
        result, _ = validate_strategy(output, bundle)
        # No evidence but no policy_updates either — this is valid restraint
        assert result in (DVResult.PASS, DVResult.DEGRADE)
