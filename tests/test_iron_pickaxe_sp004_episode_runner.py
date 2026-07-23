from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import hashlib

from singularity.evaluation.iron_pickaxe_sp004_runtime import (
    empty_sp004_progress,
    record_sp004_success,
)


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "iron_pickaxe_sp004_episode_runner",
    REPO / "scripts/iron_pickaxe_sp004_episode_runner.py",
)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


def test_initial_audit_requires_exact_clean_stone_pickaxe_start():
    valid = {
        "inventory": {"stone_pickaxe": 1, "oak_planks": 3},
        "position": {"x": 1.5, "y": 64.0, "z": 2.5},
        "nearby_blocks": [],
        "held_item": "stone_pickaxe",
    }

    assert runner.audit_initial_state(valid)["passed"] is True
    contaminated = copy.deepcopy(valid)
    contaminated["inventory"]["coal"] = 1
    report = runner.audit_initial_state(contaminated)
    assert report["passed"] is False
    assert "episode_resources_absent" in report["issues"]


def test_base_url_normalization_is_openai_compatible():
    assert runner.normalize_base_url("http://192.168.3.27:8317") == (
        "http://192.168.3.27:8317/v1"
    )
    assert runner.normalize_base_url("http://example.test/v1/") == (
        "http://example.test/v1"
    )


def test_sp004_bridge_is_isolated_from_frozen_shared_bridge():
    shared = REPO / "src/bot/bot_server.js"
    sp004 = REPO / "src/bot/sp004_bot_server.js"

    assert hashlib.sha256(shared.read_bytes()).hexdigest() == (
        "f1677b32fc726d6d983d4646d47cda80d57f49949f0759d8e735e59e18765f60"
    )
    assert sp004.is_file()
    assert hashlib.sha256(sp004.read_bytes()).hexdigest() != (
        hashlib.sha256(shared.read_bytes()).hexdigest()
    )


def test_runner_config_binds_requested_model_without_recording_key():
    args = SimpleNamespace(
        host="127.0.0.1",
        port=25565,
        username="Singularity",
        bridge_host="127.0.0.1",
        bridge_port=30000,
        model="grok-4.5",
        base_url="http://192.168.3.27:8317",
    )

    config = runner.build_config(
        args,
        "test-only-secret",
        REPO / "workspace/evals/sp004_runs/test-only",
    )

    assert config.llm.model == "grok-4.5"
    assert config.llm.base_url == "http://192.168.3.27:8317/v1"
    assert config.llm.api_key == "test-only-secret"
    assert config.planner_protocol == "stone-pickaxe-skill-fixed-v1"
    assert config.require_llm_root_plan is True


def test_episode_builder_extracts_actions_without_provider_secret():
    action = {
        "type": "dig",
        "parameters": {"block": "stone", "x": 1, "y": 60, "z": 2},
    }
    result = {
        "success": True,
        "sp004_stage": "acquire_cobblestone",
        "block_removed": True,
        "pickup_observed": True,
        "pickup_inventory_delta": {"cobblestone": 1},
    }
    progress = record_sp004_success(empty_sp004_progress(), action, result)
    events = [
        {"id": 1, "type": "observation", "data": {"inventory": {"stone_pickaxe": 1}}},
        {"id": 2, "type": "action", "data": {"action": action, "result": result}},
    ]

    episode = runner.build_episode(
        episode_id="sp004_test",
        initial={"inventory": {"stone_pickaxe": 1}},
        terminal={"inventory": {"stone_pickaxe": 1, "cobblestone": 1}},
        events=events,
        result={"success": False},
        progress=progress,
    )

    assert len(episode["actions"]) == 1
    assert episode["actions"][0]["event_id"] == 2
    assert episode["progress"]["stone_sources"] == ["1,60,2"]
    assert "api_key" not in str(episode).lower()
