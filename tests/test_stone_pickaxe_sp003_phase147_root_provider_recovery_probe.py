"""Offline gates for the Phase 147 no-Minecraft root-provider probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    ROOT / "scripts/stone_pickaxe_sp003_phase147_root_provider_recovery_probe.py"
)
SCHEMA_PATH = (
    ROOT
    / "workspace/evals/schemas/"
    "stone_pickaxe_sp003_phase147_root_provider_recovery_probe.schema.json"
)
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"
EVIDENCE_PATH = (
    ROOT
    / "workspace/evals/stone_pickaxe_sp003_phase147_root_provider_recovery_probe.json"
)
EVIDENCE_SHA256 = (
    "c78d615313f633f7df28d0193b7b402625e3423aecd6a5573a4b035f86e219b8"
)


def _module():
    spec = importlib.util.spec_from_file_location("phase147_root_probe", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offline_planner(module, world_state: dict):
    planner_config = module.PROTOCOL["planner"]
    provider = module.LLMProvider(
        module.LLMConfig(
            provider=planner_config["provider"],
            model=planner_config["model"],
            api_key="offline-only-not-sent",
            base_url=planner_config["base_url"],
            max_tokens=int(planner_config["max_tokens"]),
            temperature=float(planner_config["temperature"]),
        )
    )
    planner = module.Planner(
        provider, module.TaskSystem(), protocol=module.PROTOCOL["id"]
    )
    planner.start_episode(module.SP003_GOAL, module.PROBE_EPISODE_ID)
    return planner


def test_phase147_tooling_binds_exact_phase146_root_transport_failure() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, call = module.retained_observation_before_call(
        source, module.SOURCE_CALL_ID
    )

    assert module.PHASE == 147
    assert module.POLICY_ID == "sp003-phase147-root-provider-recovery-gate-v1"
    assert module.file_sha256(source) == module.EXPECTED_SOURCE_SHA256
    assert observation["line_number"] == 5
    assert module.canonical_sha256(observation["event"]) == (
        module.EXPECTED_OBSERVATION_CANONICAL_SHA256
    )
    assert call["data"]["call_index"] == 0
    assert call["data"]["plan_kind"] == "root"
    assert call["data"]["response_byte_count"] == 0
    transport = call["data"]["transport_evidence"]
    assert transport["attempt_count"] == 1
    assert transport["retry_count"] == 0
    assert transport["attempts"][0]["error_chain"] == [
        "APIConnectionError",
        "ConnectError",
        "ConnectError",
        "SSLEOFError",
    ]


def test_phase147_tooling_reconstructs_exact_bounded_root_request_offline() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, _ = module.retained_observation_before_call(
        source, module.SOURCE_CALL_ID
    )
    world_state = observation["event"]["data"]
    planner = _offline_planner(module, world_state)

    assert module.compact_source_state(planner, world_state) == (
        module.EXPECTED_SOURCE_STATE
    )
    request = module.request_payload_metadata(
        module.exact_probe_messages(planner, world_state)
    )
    assert request == module.EXPECTED_REQUEST_METADATA
    assert request["request_sha256"] != (
        "3fc9246f01af2034bfc460b5a0fffc36e51f77f39f196151a4ff41745d5b034b"
    )


def test_phase147_tooling_is_one_request_zero_retry_and_no_minecraft() -> None:
    module = _module()
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert module.REQUEST_TIMEOUT_S == 12.0
    assert module.MAX_ACCEPTABLE_DURATION_MS == 7_500
    assert module.MIN_REPRESENTATIVE_PROMPT_TOKENS == 2_500
    assert module.MIN_REPRESENTATIVE_REQUEST_BYTES == 10_000
    assert module.EXPECTED_SUBTASK_COUNT == 5
    assert module.EXPECTED_ACTION == {
        "type": "move_to",
        "parameters": {"x": 121, "y": 142, "z": -36},
    }
    assert "provider_chat_call_count > 1" in text
    assert '"max_provider_chat_call_count": 1' in text
    assert '"max_transport_request_count": 1' in text
    assert '"max_retry_count": 0' in text
    assert '"minecraft_process_started": False' in text
    assert '"authorization_created": False' in text
    assert '"automatic_retry_attempted": False' in text
    assert "write_evidence(output, evidence)" in text
    assert "Start-Process" not in text


def test_phase147_schema_and_current_gate_fail_closed_before_probe() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["phase"] == {"const": 147}
    assert schema["properties"]["minecraft_process_started"] == {"const": False}
    assert schema["properties"]["authorization_created"] == {"const": False}
    gate = ledger["next_required_gate"]
    assert gate["id"] == (
        "sp003_phase_148_baseline_evidence_commit_push_then_phase_149_"
        "candidate_r1_parent_bound_one_use_authorization"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False


def test_phase147_retained_probe_passes_schema_and_exact_recovery_gate() -> None:
    module = _module()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert module.file_sha256(EVIDENCE_PATH) == EVIDENCE_SHA256
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(evidence)
    assert evidence["predecessor_commit"] == (
        "d64af344dea5d9689991d59cb593cc6463c67881"
    )
    assert evidence["passed"] is True
    assert evidence["decision"] == (
        "permit_one_new_parent_bound_baseline_authorization"
    )
    assert all(evidence["criteria"].values())
    assert evidence["provider_chat_call_count"] == 1
    assert evidence["request_count"] == 1
    assert evidence["retry_count"] == 0
    assert evidence["duration_ms"] == 5375
    assert evidence["duration_ms"] <= evidence["thresholds"][
        "max_acceptable_duration_ms"
    ]
    assert evidence["request"]["request_sha256"] == (
        module.EXPECTED_REQUEST_METADATA["request_sha256"]
    )
    assert evidence["request"]["provider_request_sha256"] == (
        module.EXPECTED_REQUEST_METADATA["request_sha256"]
    )
    assert evidence["response_sha256"] == (
        "094ba433e8d3ea46916d6941a693acd4df6ca67921e1b34f617063ddd20ad5d7"
    )
    assert evidence["real_llm_call"] is True
    assert evidence["schema_valid"] is True
    assert evidence["returned_plan"] == {
        "plan_kind": "root",
        "status": "planning",
        "subtask_count": 5,
        "actions": [module.EXPECTED_ACTION],
    }
    assert evidence["minecraft_process_started"] is False
    assert evidence["authorization_created"] is False
    assert evidence["automatic_retry_attempted"] is False
    assert evidence["live_authorization"] is False
    assert evidence["counts_toward_baseline_success"] is False
    assert evidence["counts_toward_skill_gate"] is False
    assert evidence["counts_toward_capability"] is False
    assert evidence["counts_toward_m4"] is False
