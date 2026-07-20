"""Reclassify the Phase 141 probe through the exact production SP-003 guard."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import stone_pickaxe_sp003_phase140_continuation_provider_probe as base


PHASE = 142
POLICY_ID = "sp003-continuation-probe-runtime-guard-normalization-v1"
SOURCE_PROBE_SHA256 = (
    "2c67ac6a3706871a10c42c35d617fad6c0e63879884babf3f2308c5b7a6dbb40"
)
SOURCE_PROBE_EVIDENCE_COMMIT = "00e08cd828d6b6e2d6f4059c247d4c3e2bff59bf"
DEFAULT_PROBE = Path(
    "workspace/evals/"
    "stone_pickaxe_sp003_phase141_continuation_provider_recovery_probe.json"
)
DEFAULT_SOURCE = base.DEFAULT_SOURCE
DEFAULT_OUTPUT = Path(
    "workspace/evals/"
    "stone_pickaxe_sp003_phase142_probe_evaluator_reclassification.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reclassify Phase 141 with the production SP-003 action guard"
    )
    parser.add_argument("--probe", default=DEFAULT_PROBE.as_posix())
    parser.add_argument("--source", default=DEFAULT_SOURCE.as_posix())
    parser.add_argument("--output", default=DEFAULT_OUTPUT.as_posix())
    return parser.parse_args()


def exact_source_probe(path: Path) -> tuple[dict, dict]:
    probe = json.loads(path.read_text(encoding="utf-8"))
    failed_criteria = sorted(
        name for name, passed in probe.get("criteria", {}).items() if not passed
    )
    checks = {
        "artifact_sha256": base.file_sha256(path) == SOURCE_PROBE_SHA256,
        "phase": probe.get("phase") == 141,
        "tooling_commit": probe.get("predecessor_commit")
        == "009a3cfe56e40fb03e08e8d1eba6d4630cce0c85",
        "reported_false": probe.get("passed") is False,
        "only_raw_action_criterion_failed": failed_criteria
        == ["exact_expected_action"],
        "single_request": probe.get("request_count") == 1,
        "zero_retries": probe.get("retry_count") == 0,
        "real_llm_call": probe.get("real_llm_call") is True,
        "schema_valid": probe.get("schema_valid") is True,
        "response_sha256": probe.get("response_sha256")
        == "ca946548743600b286599ba1f554fc6388cea927f426292d49de84a1fb84613e",
        "no_minecraft_or_authorization": (
            probe.get("minecraft_process_started") is False
            and probe.get("authorization_created") is False
        ),
        "no_retry_or_credit": (
            probe.get("automatic_retry_attempted") is False
            and probe.get("counts_toward_baseline_success") is False
            and probe.get("counts_toward_capability") is False
            and probe.get("counts_toward_m4") is False
        ),
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError("Phase 141 probe mismatch: " + ",".join(failed))
    return probe, checks


def exact_source_state(path: Path) -> tuple[dict, dict]:
    observation, call = base.retained_observation_before_call(
        path, base.SOURCE_CALL_ID
    )
    world_state = observation["event"]["data"]
    checks = {
        "session_sha256": base.file_sha256(path) == base.EXPECTED_SOURCE_SHA256,
        "observation_line": observation["line_number"]
        == base.EXPECTED_OBSERVATION_LINE_NUMBER,
        "observation_sha256": base.canonical_sha256(observation["event"])
        == base.EXPECTED_OBSERVATION_CANONICAL_SHA256,
        "failed_call_index": call["data"].get("call_index") == 3,
        "failed_call_kind": call["data"].get("plan_kind") == "continuation",
        "failed_call_id": call["data"].get("call_id") == base.SOURCE_CALL_ID,
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError("Phase 139 state mismatch: " + ",".join(failed))
    return world_state, {
        "path": base.repo_relative(path),
        "sha256": base.file_sha256(path),
        "observation_line_number": observation["line_number"],
        "observation_canonical_sha256": base.canonical_sha256(
            observation["event"]
        ),
        "checks": checks,
    }


def evaluator_result(action: dict, world_state: dict) -> dict:
    guarded = base.runtime_guard_action_evidence(action, world_state)
    passed = (
        guarded["allowed"]
        and not guarded["issues"]
        and guarded["normalized_action_exact_expected"]
    )
    return {**guarded, "passed": passed}


def negative_controls(world_state: dict) -> dict:
    controls = {
        "unobserved_coordinate": {
            "type": "dig",
            "parameters": {
                "block": "dark_oak_log",
                "x": 117,
                "y": 141,
                "z": -38,
            },
        },
        "wrong_log_family": {
            "type": "dig",
            "parameters": {
                "block": "oak_log",
                "x": 119,
                "y": 141,
                "z": -33,
            },
        },
        "non_nearest_same_family": {
            "type": "dig",
            "parameters": {
                "block": "dark_oak_log",
                "x": 118,
                "y": 142,
                "z": -38,
            },
        },
        "extra_forged_parameter": {
            "type": "dig",
            "parameters": {
                "block": "dark_oak_log",
                "x": 118,
                "y": 141,
                "z": -38,
                "forged": "value",
            },
        },
    }
    results = {}
    for name, action in controls.items():
        result = evaluator_result(action, world_state)
        results[name] = {
            "action": action,
            "guard_allowed": result["allowed"],
            "guard_issues": result["issues"],
            "normalized_action": result["normalized_action"],
            "normalized_action_exact_expected": result[
                "normalized_action_exact_expected"
            ],
            "evaluator_passed": result["passed"],
            "rejected": not result["passed"],
        }
    return results


def build_audit(probe_path: Path, source_path: Path) -> dict:
    probe, probe_checks = exact_source_probe(probe_path)
    world_state, source = exact_source_state(source_path)
    actions = probe["returned_plan"]["actions"]
    raw_action = actions[0] if len(actions) == 1 else {}
    guarded = evaluator_result(raw_action, world_state)
    controls = negative_controls(world_state)

    corrected_criteria = copy.deepcopy(probe["criteria"])
    original_exact = corrected_criteria.pop("exact_expected_action")
    corrected_criteria["single_provider_action"] = len(actions) == 1
    corrected_criteria["runtime_guard_normalized_expected_action"] = guarded[
        "passed"
    ]
    corrected_passed = all(corrected_criteria.values())
    controls_rejected = all(item["rejected"] for item in controls.values())

    return {
        "type": "stone_pickaxe_sp003_probe_evaluator_reclassification",
        "schema_version": 1,
        "phase": PHASE,
        "policy_id": POLICY_ID,
        "task_id": "SP-003",
        "generated_at_utc": base.utc_now(),
        "predecessor_commit": base.current_head(),
        "source_probe": {
            "path": base.repo_relative(probe_path),
            "sha256": base.file_sha256(probe_path),
            "evidence_commit": SOURCE_PROBE_EVIDENCE_COMMIT,
            "immutable": True,
            "rewritten": False,
            "checks": probe_checks,
        },
        "source_machine_state": source,
        "original_result": {
            "reported_passed": probe["passed"],
            "failed_criteria": ["exact_expected_action"],
            "exact_expected_action_value": original_exact,
            "raw_action": raw_action,
            "response_sha256": probe["response_sha256"],
            "request_count": probe["request_count"],
            "retry_count": probe["retry_count"],
            "real_llm_call": probe["real_llm_call"],
            "schema_valid": probe["schema_valid"],
        },
        "runtime_guard_replay": guarded,
        "corrected_evaluation": {
            "criteria": corrected_criteria,
            "passed": corrected_passed,
            "decision": (
                "provider_recovered_evaluator_reclassified_pass"
                if corrected_passed and controls_rejected
                else "hold_new_authorization_evaluator_repair_failed"
            ),
        },
        "negative_controls": controls,
        "all_negative_controls_rejected": controls_rejected,
        "evaluator_repair_passed": corrected_passed and controls_rejected,
        "classification": "probe_evaluator_false_negative",
        "minecraft_process_started": False,
        "provider_request_made": False,
        "authorization_created": False,
        "automatic_retry_attempted": False,
        "live_authorization": False,
        "separate_authorization_permitted_after_commit_push": (
            corrected_passed and controls_rejected
        ),
        "counts_toward_baseline_success": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def main() -> int:
    args = parse_args()
    probe = base.repo_path(args.probe)
    source = base.repo_path(args.source)
    output = base.repo_path(args.output)
    if not probe.is_file():
        raise RuntimeError(f"probe evidence not found: {probe}")
    if not source.is_file():
        raise RuntimeError(f"source evidence not found: {source}")
    audit = build_audit(probe, source)
    base.write_evidence(output, audit)
    print(
        json.dumps(
            {
                "output": base.repo_relative(output),
                "evaluator_repair_passed": audit["evaluator_repair_passed"],
                "decision": audit["corrected_evaluation"]["decision"],
            },
            sort_keys=True,
        )
    )
    return 0 if audit["evaluator_repair_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
