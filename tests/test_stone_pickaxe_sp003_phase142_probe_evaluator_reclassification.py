"""Offline checks for the Phase 142 probe-evaluator repair."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    ROOT
    / "scripts/stone_pickaxe_sp003_phase142_probe_evaluator_reclassification.py"
)
SCHEMA_PATH = (
    ROOT
    / "workspace/evals/schemas/"
    "stone_pickaxe_sp003_probe_evaluator_reclassification.schema.json"
)
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"
AUDIT_PATH = (
    ROOT
    / "workspace/evals/"
    "stone_pickaxe_sp003_phase142_probe_evaluator_reclassification.json"
)
AUDIT_SHA256 = "d5f1f7c022ebfc07277c416e09047afc39fd02377039d7faddcb7325493f2d38"


def _module():
    spec = importlib.util.spec_from_file_location(
        "phase142_probe_evaluator_reclassification", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _audit() -> tuple[object, dict]:
    module = _module()
    probe = module.base.repo_path(module.DEFAULT_PROBE)
    source = module.base.repo_path(module.DEFAULT_SOURCE)
    return module, module.build_audit(probe, source)


def test_phase142_binds_immutable_phase141_probe_and_machine_state() -> None:
    module, audit = _audit()

    assert module.PHASE == 142
    assert module.POLICY_ID == (
        "sp003-continuation-probe-runtime-guard-normalization-v1"
    )
    assert audit["source_probe"]["sha256"] == module.SOURCE_PROBE_SHA256
    assert audit["source_probe"]["evidence_commit"] == (
        module.SOURCE_PROBE_EVIDENCE_COMMIT
    )
    assert all(audit["source_probe"]["checks"].values())
    assert audit["source_machine_state"]["sha256"] == (
        module.base.EXPECTED_SOURCE_SHA256
    )
    assert all(audit["source_machine_state"]["checks"].values())


def test_phase142_reclassifies_only_after_exact_production_guard() -> None:
    module, audit = _audit()
    replay = audit["runtime_guard_replay"]

    assert audit["original_result"]["reported_passed"] is False
    assert audit["original_result"]["failed_criteria"] == [
        "exact_expected_action"
    ]
    assert replay["raw_action"] == {
        "type": "dig",
        "parameters": {
            "block": "dark_oak_log",
            "x": 118,
            "y": 141,
            "z": -38,
        },
    }
    assert replay["allowed"] is True
    assert replay["issues"] == []
    assert replay["policy_id"] == "stone-pickaxe-sp003-action-guard-v2"
    assert replay["normalized_action"] == module.base.EXPECTED_ACTION
    assert replay["passed"] is True
    assert audit["corrected_evaluation"]["passed"] is True
    assert all(audit["corrected_evaluation"]["criteria"].values())
    assert audit["evaluator_repair_passed"] is True


def test_phase142_negative_controls_remain_fail_closed() -> None:
    _, audit = _audit()
    controls = audit["negative_controls"]

    assert set(controls) == {
        "unobserved_coordinate",
        "wrong_log_family",
        "non_nearest_same_family",
        "extra_forged_parameter",
    }
    assert all(item["rejected"] for item in controls.values())
    assert all(not item["evaluator_passed"] for item in controls.values())
    assert controls["non_nearest_same_family"]["guard_allowed"] is False
    assert controls["wrong_log_family"]["guard_allowed"] is False
    assert controls["extra_forged_parameter"]["guard_allowed"] is True
    assert controls["extra_forged_parameter"][
        "normalized_action_exact_expected"
    ] is False
    assert audit["all_negative_controls_rejected"] is True


def test_phase142_audit_shape_is_schema_valid_without_live_side_effects() -> None:
    _, audit = _audit()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(audit)
    assert audit["minecraft_process_started"] is False
    assert audit["provider_request_made"] is False
    assert audit["authorization_created"] is False
    assert audit["automatic_retry_attempted"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False


def test_phase142_generator_has_no_provider_or_minecraft_execution_path() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "LLMProvider" not in text
    assert "plan_from_goal" not in text
    assert "Start-Process" not in text
    assert "base.write_evidence(output, audit)" in text


def test_phase142_retained_audit_is_exact_and_schema_valid() -> None:
    module = _module()
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert module.base.file_sha256(AUDIT_PATH) == AUDIT_SHA256
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(audit)
    assert audit["predecessor_commit"] == (
        "ac9454281a25c79c3f794d08eeea014d2bb0720d"
    )
    assert audit["source_probe"]["sha256"] == module.SOURCE_PROBE_SHA256
    assert audit["runtime_guard_replay"]["normalized_action"] == (
        module.base.EXPECTED_ACTION
    )
    assert audit["corrected_evaluation"]["passed"] is True
    assert all(audit["corrected_evaluation"]["criteria"].values())
    assert audit["all_negative_controls_rejected"] is True
    assert audit["evaluator_repair_passed"] is True
    assert audit["separate_authorization_permitted_after_commit_push"] is True
    assert audit["provider_request_made"] is False
    assert audit["minecraft_process_started"] is False
    assert audit["authorization_created"] is False


def test_phase142_evidence_keeps_live_gate_closed_until_push() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    gate = ledger["next_required_gate"]

    assert gate["id"] == (
        "sp003_phase_144_offline_repair_commit_push_then_phase_145_bounded_no_minecraft_step_up_provider_probe"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
