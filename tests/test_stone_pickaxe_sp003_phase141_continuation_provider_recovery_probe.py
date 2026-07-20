"""Offline gate checks for the Phase 141 continuation-provider recovery probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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
    assert request == {
        "request_sha256": base.EXPECTED_REQUEST_SHA256,
        "request_payload_byte_count": base.EXPECTED_REQUEST_PAYLOAD_BYTE_COUNT,
        "system_message_byte_count": base.EXPECTED_SYSTEM_MESSAGE_BYTE_COUNT,
        "user_message_byte_count": base.EXPECTED_USER_MESSAGE_BYTE_COUNT,
    }


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


def test_phase141_tooling_does_not_open_phase140_live_gate() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    gate = ledger["next_required_gate"]

    assert gate["id"] == (
        "sp003_phase_140_continuation_provider_transport_recovery_gate"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
