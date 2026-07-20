"""Offline gate checks for the Phase 141 continuation-provider recovery probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from singularity.evaluation.stone_pickaxe_sp003_runtime import guard_sp003_action


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    ROOT
    / "scripts/"
    "stone_pickaxe_sp003_phase141_continuation_provider_recovery_probe.py"
)
BASE_SCRIPT_PATH = (
    ROOT / "scripts/stone_pickaxe_sp003_phase140_continuation_provider_probe.py"
)
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"
PROBE_PATH = (
    ROOT
    / "workspace/evals/"
    "stone_pickaxe_sp003_phase141_continuation_provider_recovery_probe.json"
)
PROBE_SHA256 = "2c67ac6a3706871a10c42c35d617fad6c0e63879884babf3f2308c5b7a6dbb40"
PHASE144_REQUEST = {
    "request_sha256": "a3c79e2deef02cef79396d8b2daa2ac335529c616338ba608dc8131b5867d25a",
    "request_payload_byte_count": 12305,
    "system_message_byte_count": 9099,
    "user_message_byte_count": 2779,
}


def _module():
    spec = importlib.util.spec_from_file_location(
        "phase141_continuation_recovery_probe", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offline_planner(module, world_state: dict):
    base = module.base
    planner_config = base.PROTOCOL["planner"]
    provider = base.LLMProvider(
        base.LLMConfig(
            provider=planner_config["provider"],
            model=planner_config["model"],
            api_key="offline-only-not-sent",
            base_url=planner_config["base_url"],
            max_tokens=int(planner_config["max_tokens"]),
            temperature=float(planner_config["temperature"]),
        )
    )
    planner = base.Planner(
        provider, base.TaskSystem(), protocol=base.PROTOCOL["id"]
    )
    planner.start_episode(base.SP003_GOAL, module.PROBE_EPISODE_ID)
    planner._call_index = 3
    planner._active_root_plan_id = base.SOURCE_ROOT_PLAN_ID
    planner._last_call_id = base.SOURCE_PARENT_CALL_ID
    return planner


def test_phase141_probe_binds_exact_phase140_failure_evidence() -> None:
    module = _module()
    predecessor = module.base.repo_path(module.DEFAULT_PREDECESSOR)
    artifact, checks = module.exact_phase140_predecessor(predecessor)

    assert module.PHASE == 141
    assert module.POLICY_ID == "sp003-continuation-provider-recovery-gate-v1"
    assert module.base.file_sha256(predecessor) == module.EXPECTED_PHASE140_SHA256
    assert module.PHASE140_EVIDENCE_COMMIT == (
        "c38e09a9e1c95966e87fcca70bfd13f2cad710f8"
    )
    assert all(checks.values())
    assert artifact["request_count"] == 1
    assert artifact["retry_count"] == 0
    assert artifact["response_byte_count"] == 0
    assert artifact["schema_validation"]["issues"] == ["Connection error."]


def test_phase141_probe_reuses_exact_phase139_state_and_request_shape() -> None:
    module = _module()
    base = module.base
    source = base.repo_path(module.DEFAULT_SOURCE)
    observation, call = base.retained_observation_before_call(
        source, base.SOURCE_CALL_ID
    )
    world_state = observation["event"]["data"]
    planner = _offline_planner(module, world_state)
    request = base.request_payload_metadata(
        base.exact_probe_messages(planner, world_state)
    )

    assert base.file_sha256(source) == base.EXPECTED_SOURCE_SHA256
    assert observation["line_number"] == base.EXPECTED_OBSERVATION_LINE_NUMBER
    assert call["data"]["call_index"] == 3
    assert call["data"]["plan_kind"] == "continuation"
    assert base.compact_source_state(planner, world_state) == (
        base.EXPECTED_SOURCE_STATE
    )
    assert request == PHASE144_REQUEST
    assert request["request_sha256"] != base.EXPECTED_REQUEST_SHA256


def test_phase141_probe_retains_safe_transport_evidence() -> None:
    module = _module()
    retained = module.base.retained_transport_evidence(
        {
            "policy_id": "single-attempt",
            "attempt_count": 1,
            "retry_count": 0,
            "attempts": [
                {
                    "attempt_index": 0,
                    "success": False,
                    "timeout_s": 12.0,
                    "sdk_max_retries": 0,
                    "error_type": "APIConnectionError",
                    "error_chain": ["APIConnectionError", "ConnectError"],
                    "raw_error": "must-not-be-retained",
                }
            ],
        }
    )

    assert retained == {
        "policy_id": "single-attempt",
        "attempt_count": 1,
        "retry_count": 0,
        "attempts": [
            {
                "attempt_index": 0,
                "success": False,
                "timeout_s": 12.0,
                "sdk_max_retries": 0,
                "error_type": "APIConnectionError",
                "error_chain": ["APIConnectionError", "ConnectError"],
            }
        ],
    }
    assert "raw_error" not in json.dumps(retained)


def test_phase141_probe_layers_predecessor_into_provider_result(monkeypatch) -> None:
    module = _module()
    predecessor = module.base.repo_path(module.DEFAULT_PREDECESSOR)

    monkeypatch.setattr(
        module.base,
        "run_probe",
        lambda _source: {
            "purpose": "old-purpose",
            "criteria": {"provider_result": True},
            "passed": True,
            "decision": "old-decision",
        },
    )
    evidence = module.run_probe(Path("offline-source-not-read"), predecessor)

    assert module.base.PHASE == 141
    assert module.base.PROBE_EPISODE_ID == module.PROBE_EPISODE_ID
    assert evidence["purpose"] == module.PURPOSE
    assert evidence["criteria"] == {
        "phase_140_failure_is_exact": True,
        "provider_result": True,
    }
    assert evidence["passed"] is True
    assert evidence["decision"] == "permit_one_new_authorization"
    assert evidence["recovery_predecessor"]["evidence_commit"] == (
        module.PHASE140_EVIDENCE_COMMIT
    )
    assert evidence["recovery_predecessor"]["sha256"] == (
        module.EXPECTED_PHASE140_SHA256
    )


def test_phase141_probe_is_single_request_zero_retry_and_no_minecraft() -> None:
    module = _module()
    base = module.base

    assert base.REQUEST_TIMEOUT_S == 12.0
    assert base.MAX_ACCEPTABLE_DURATION_MS == 7500
    assert base.MIN_REPRESENTATIVE_PROMPT_TOKENS == 2500
    assert base.MIN_REPRESENTATIVE_REQUEST_BYTES == 10_000
    assert base.EXPECTED_ACTION["type"] == "dig"
    base_text = BASE_SCRIPT_PATH.read_text(encoding="utf-8")
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'minecraft_process_started": False' in base_text
    assert 'authorization_created": False' in base_text
    assert 'automatic_retry_attempted": False' in base_text
    assert "base.write_evidence(output, evidence)" in text
    assert "Start-Process" not in text


def test_phase141_probe_retains_provider_recovery_false_negative() -> None:
    module = _module()
    probe = json.loads(PROBE_PATH.read_text(encoding="utf-8"))

    assert module.base.file_sha256(PROBE_PATH) == PROBE_SHA256
    assert probe["phase"] == 141
    assert probe["predecessor_commit"] == (
        "009a3cfe56e40fb03e08e8d1eba6d4630cce0c85"
    )
    assert probe["passed"] is False
    assert [name for name, passed in probe["criteria"].items() if not passed] == [
        "exact_expected_action"
    ]
    assert probe["request_count"] == 1
    assert probe["retry_count"] == 0
    assert probe["duration_ms"] == probe["wall_duration_ms"] == 4108
    assert probe["response_byte_count"] == 542
    assert probe["response_sha256"] == (
        "ca946548743600b286599ba1f554fc6388cea927f426292d49de84a1fb84613e"
    )
    assert probe["prompt_tokens"] == 2753
    assert probe["completion_tokens"] == 171
    assert probe["real_llm_call"] is True
    assert probe["schema_valid"] is True
    assert probe["schema_validation"]["passed"] is True
    assert probe["returned_plan"] == {
        "plan_kind": "continuation",
        "status": "planning",
        "subtask_count": 0,
        "actions": [
            {
                "type": "dig",
                "parameters": {
                    "block": "dark_oak_log",
                    "x": 118,
                    "y": 141,
                    "z": -38,
                },
            }
        ],
    }
    assert probe["transport_evidence"] == {
        "policy_id": "single-attempt",
        "attempt_count": 1,
        "retry_count": 0,
        "attempts": [
            {
                "attempt_index": 0,
                "success": True,
                "timeout_s": 12.0,
                "sdk_max_retries": 0,
                "error_type": "",
                "error_chain": [],
            }
        ],
    }
    assert probe["minecraft_process_started"] is False
    assert probe["authorization_created"] is False
    assert probe["automatic_retry_attempted"] is False
    assert probe["counts_toward_baseline_success"] is False
    assert probe["counts_toward_capability"] is False
    assert probe["counts_toward_m4"] is False


def test_phase141_raw_action_normalizes_to_exact_runtime_guard_action() -> None:
    module = _module()
    base = module.base
    probe = json.loads(PROBE_PATH.read_text(encoding="utf-8"))
    source = base.repo_path(module.DEFAULT_SOURCE)
    observation, _ = base.retained_observation_before_call(
        source, base.SOURCE_CALL_ID
    )
    world_state = observation["event"]["data"]
    raw_action = probe["returned_plan"]["actions"][0]

    assert "source_id" not in raw_action["parameters"]
    guarded = guard_sp003_action(
        raw_action,
        world_state,
        world_state["sp003_progress"],
        arm="baseline",
    )

    assert guarded["allowed"] is True
    assert guarded["issues"] == []
    assert guarded["action"] == base.EXPECTED_ACTION
    assert guarded["selected_source"] == {
        "source_id": "dark_oak_log:118:141:-38",
        "name": "dark_oak_log",
        "position": {"x": 118.0, "y": 141.0, "z": -38.0},
        "distance": 1.414214,
    }


def test_phase141_evidence_keeps_live_gate_closed_for_offline_repair() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    gate = ledger["next_required_gate"]

    assert gate["id"] == (
        "sp003_phase_147_probe_tooling_commit_push_then_one_bounded_"
        "no_minecraft_root_provider_recovery_probe"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
