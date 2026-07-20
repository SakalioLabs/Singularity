"""Offline gate checks for the Phase 138 no-Minecraft root-provider probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/stone_pickaxe_sp003_phase138_root_provider_probe.py"
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"


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


def test_phase138_probe_preserves_the_closed_phase137_live_gate() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    gate = ledger["next_required_gate"]

    assert gate["id"] == "sp003_phase_137_provider_transport_recovery_gate"
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
