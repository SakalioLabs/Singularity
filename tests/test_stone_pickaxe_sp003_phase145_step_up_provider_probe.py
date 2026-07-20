"""Offline gates for the Phase 145 step-up provider probe tooling."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    ROOT / "scripts/stone_pickaxe_sp003_phase145_step_up_provider_probe.py"
)
SCHEMA_PATH = (
    ROOT
    / "workspace/evals/schemas/"
    "stone_pickaxe_sp003_step_up_provider_probe.schema.json"
)
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"
EVIDENCE_PATH = (
    ROOT
    / "workspace/evals/stone_pickaxe_sp003_phase145_step_up_provider_probe.json"
)
EVIDENCE_SHA256 = (
    "3e1168119679c91e219d270c241960e340200279914a66f5a3c3c396f75619ac"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "phase145_step_up_provider_probe", SCRIPT_PATH
    )
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
    planner._call_index = module.SOURCE_CALL_INDEX
    planner._active_root_plan_id = module.SOURCE_ROOT_PLAN_ID
    planner._last_call_id = module.SOURCE_CALL_ID
    return planner


def test_phase145_tooling_binds_exact_phase143_step_up_source_chain() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, call, plan = module.retained_step_up_source(source)
    checks = module.source_identity_checks(observation, call, plan)

    assert module.PHASE == 145
    assert module.POLICY_ID == "sp003-step-up-provider-probe-v1"
    assert module.file_sha256(source) == module.EXPECTED_SOURCE_SHA256
    assert observation["line_number"] == 270
    assert call["line_number"] == 273
    assert plan["line_number"] == 274
    assert all(checks.values()), checks
    assert plan["event"]["data"]["actions"] == [module.EXPECTED_SOURCE_ACTION]


def test_phase145_tooling_reconstructs_repaired_exact_request_offline() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, _, _ = module.retained_step_up_source(source)
    world_state = observation["event"]["data"]
    planner = _offline_planner(module, world_state)
    request = module.request_payload_metadata(
        module.exact_probe_messages(planner, world_state)
    )

    assert module.compact_source_state(planner, world_state) == (
        module.EXPECTED_SOURCE_STATE
    )
    assert request == {
        "request_sha256": module.EXPECTED_REQUEST_SHA256,
        "request_payload_byte_count": module.EXPECTED_REQUEST_PAYLOAD_BYTE_COUNT,
        "system_message_byte_count": module.EXPECTED_SYSTEM_MESSAGE_BYTE_COUNT,
        "user_message_byte_count": module.EXPECTED_USER_MESSAGE_BYTE_COUNT,
    }
    assert request["request_sha256"] != module.EXPECTED_SOURCE_REQUEST_SHA256


def test_phase145_tooling_uses_production_effective_guard() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, _, _ = module.retained_step_up_source(source)
    world_state = observation["event"]["data"]

    evidence = module.effective_guard_action_evidence(
        module.EXPECTED_RAW_ACTION, world_state
    )
    assert evidence["allowed"] is True
    assert evidence["issues"] == []
    assert evidence["raw_action_exact_expected"] is True
    assert evidence["normalized_action_exact_expected"] is True
    assert evidence["normalized_action"] == module.EXPECTED_NORMALIZED_ACTION

    rejected = module.effective_guard_action_evidence(
        module.EXPECTED_SOURCE_ACTION, world_state
    )
    assert rejected["allowed"] is False
    assert rejected["raw_action_exact_expected"] is False
    assert rejected["normalized_action_exact_expected"] is False
    assert rejected["issues"] == [
        "sp003_partial_shaft_step_up_navigation_required",
        "sp003_partial_shaft_step_up_parameters_unexpected",
    ]


def test_phase145_tooling_is_one_request_zero_retry_and_no_minecraft() -> None:
    module = _module()
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert module.REQUEST_TIMEOUT_S == 12.0
    assert module.MAX_ACCEPTABLE_DURATION_MS == 7_500
    assert module.MIN_REPRESENTATIVE_PROMPT_TOKENS == 2_500
    assert module.MIN_REPRESENTATIVE_REQUEST_BYTES == 10_000
    assert "provider_chat_call_count > 1" in text
    assert '"max_provider_chat_call_count": 1' in text
    assert '"max_transport_request_count": 1' in text
    assert '"max_retry_count": 0' in text
    assert '"minecraft_process_started": False' in text
    assert '"authorization_created": False' in text
    assert '"automatic_retry_attempted": False' in text
    assert 'newline="\\n"' in text
    assert "write_evidence(output, evidence)" in text
    assert "Start-Process" not in text


def test_phase145_probe_schema_is_draft_2020_12_and_gate_remains_closed() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["phase"] == {"const": 145}
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


def test_phase145_retained_probe_passes_schema_and_all_bounded_gates() -> None:
    module = _module()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest() == (
        EVIDENCE_SHA256
    )
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(evidence)
    assert evidence["predecessor_commit"] == (
        "154380e70ac4a30d4bc215d75069bec1c57c5a02"
    )
    assert evidence["passed"] is True
    assert all(evidence["criteria"].values())
    assert evidence["provider_chat_call_count"] == 1
    assert evidence["request_count"] == 1
    assert evidence["retry_count"] == 0
    assert evidence["duration_ms"] == evidence["wall_duration_ms"] == 2858
    assert evidence["request"]["request_sha256"] == (
        module.EXPECTED_REQUEST_SHA256
    )
    assert evidence["real_llm_call"] is True
    assert evidence["schema_valid"] is True
    assert evidence["returned_plan"]["actions"] == [
        module.EXPECTED_RAW_ACTION
    ]
    guard = evidence["effective_guard_action_evidence"]
    assert guard["allowed"] is True
    assert guard["issues"] == []
    assert guard["normalized_action"] == module.EXPECTED_NORMALIZED_ACTION
    assert evidence["minecraft_process_started"] is False
    assert evidence["authorization_created"] is False
    assert evidence["automatic_retry_attempted"] is False
    assert evidence["live_authorization"] is False
    assert evidence["counts_toward_baseline_success"] is False
    assert evidence["counts_toward_skill_gate"] is False
    assert evidence["counts_toward_capability"] is False
    assert evidence["counts_toward_m4"] is False
