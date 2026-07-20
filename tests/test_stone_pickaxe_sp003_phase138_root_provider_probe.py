"""Offline gate checks for the Phase 138 no-Minecraft root-provider probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/stone_pickaxe_sp003_phase138_root_provider_probe.py"
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"
PROBE_PATH = ROOT / "workspace/evals/stone_pickaxe_sp003_phase138_root_provider_probe.json"
PROBE_SHA256 = "8cd727c130b8d9522a097a141164584fed85b1e3afc07d9c75723bc35e45d0be"


def _module():
    spec = importlib.util.spec_from_file_location("phase138_root_probe", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase138_probe_binds_exact_phase137_root_failure_source() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, call = module.retained_observation_before_call(
        source, module.SOURCE_CALL_ID
    )

    assert module.PHASE == 138
    assert module.POLICY_ID == "sp003-root-provider-recovery-gate-v1"
    assert module.file_sha256(source) == (
        "f6cb7ec7e821c938bf00facff676d730a6f1273dd1ba4825cd30f4c36415cc7f"
    )
    assert observation["line_number"] == 5
    assert call["data"]["call_index"] == 0
    assert call["data"]["plan_kind"] == "root"
    transport = call["data"]["transport_evidence"]
    assert transport["attempt_count"] == 1
    assert transport["retry_count"] == 0
    assert transport["attempts"][0]["error_chain"] == [
        "APIConnectionError",
        "ConnectError",
        "ConnectError",
        "SSLEOFError",
    ]
    assert call["data"]["response_byte_count"] == 0


def test_phase138_probe_is_single_request_zero_retry_and_no_minecraft() -> None:
    module = _module()

    assert module.REQUEST_TIMEOUT_S == 12.0
    assert module.MAX_ACCEPTABLE_DURATION_MS == 7500
    assert module.MIN_REPRESENTATIVE_PROMPT_TOKENS == 2500
    assert module.MIN_REPRESENTATIVE_REQUEST_BYTES == 10_000
    assert module.EXPECTED_SUBTASK_COUNT == 5
    assert module.EXPECTED_ACTION == {
        "type": "move_to",
        "parameters": {"x": 121, "y": 142, "z": -36},
    }
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "minecraft_process_started\": False" in text
    assert "authorization_created\": False" in text
    assert "automatic_retry_attempted\": False" in text
    assert "write_evidence(output, evidence)" in text
    assert "Start-Process" not in text


def test_phase138_probe_remains_bound_after_phase139_failure() -> None:
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


def test_phase138_probe_passes_exact_single_request_root_gate() -> None:
    probe = json.loads(PROBE_PATH.read_text(encoding="utf-8"))

    assert _module().file_sha256(PROBE_PATH) == PROBE_SHA256
    assert probe["type"] == "stone_pickaxe_sp003_root_provider_probe"
    assert probe["phase"] == 138
    assert probe["predecessor_commit"] == (
        "bef42a1fc826bb21eb85154c30ca6e3d4c3106c9"
    )
    assert probe["passed"] is True
    assert probe["decision"] == "permit_one_new_authorization"
    assert all(probe["criteria"].values())
    assert probe["request_count"] == 1
    assert probe["retry_count"] == 0
    assert probe["duration_ms"] == 5625
    assert probe["duration_ms"] <= probe["thresholds"][
        "max_acceptable_duration_ms"
    ]
    assert probe["prompt_tokens"] == 3228
    assert probe["request"]["request_payload_byte_count"] == 13525
    assert probe["request"]["request_sha256"] == probe["request"][
        "provider_request_sha256"
    ]
    assert probe["response_sha256"] == (
        "d0fed36bc616a042c0331516e3a788ae17cd857de23382c9fe756edd7bee5d87"
    )
    assert probe["real_llm_call"] is True
    assert probe["schema_valid"] is True
    assert probe["schema_validation"]["passed"] is True
    assert probe["returned_plan"] == {
        "plan_kind": "root",
        "status": "planning",
        "subtask_count": 5,
        "actions": [
            {
                "type": "move_to",
                "parameters": {"x": 121, "y": 142, "z": -36},
            }
        ],
    }
    assert probe["minecraft_process_started"] is False
    assert probe["authorization_created"] is False
    assert probe["automatic_retry_attempted"] is False
    assert probe["counts_toward_baseline_success"] is False
    assert probe["counts_toward_capability"] is False
    assert probe["counts_toward_m4"] is False
