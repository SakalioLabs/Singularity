from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from singularity.evaluation import stone_pickaxe_sp003_runtime as base
from singularity.evaluation import stone_pickaxe_sp003_phase116_runtime as phase116
from singularity.evaluation.stone_pickaxe_sp003_phase118_runtime import (
    SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID,
    StonePickaxeSP003Phase118RuntimeAgent,
    guard_sp003_phase118_action,
)


REPO = Path(__file__).resolve().parents[1]
PHASE118_FIX_COMMIT = "b77f7fe5642df3588964c8860d2000837e54f9b1"
RUN_DIR = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_011038_c6886c53"
)


@pytest.fixture(scope="module")
def events():
    return json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))


def _navigation_cases(events):
    cases = []
    for index, event in enumerate(events):
        if event.get("type") != "stone_pickaxe_sp003_action_guard":
            continue
        data = event.get("data", {})
        issues = data.get("issues", [])
        if "sp003_table_staging_move_requires_exact_xz" not in issues:
            continue
        observation = next(
            prior["data"]
            for prior in reversed(events[:index])
            if prior.get("type") == "observation"
            and isinstance(prior.get("data"), dict)
        )
        snapshot = data["progress"]
        progress = base._empty_progress()
        for key, default in list(progress.items()):
            if key not in snapshot:
                continue
            progress[key] = (
                set(snapshot[key]) if isinstance(default, set) else copy.deepcopy(snapshot[key])
            )
        cases.append((copy.deepcopy(data["action"]), copy.deepcopy(observation), progress))
    return cases


def test_phase118_replays_all_exact_xyz_targets_without_planner_retry(events):
    cases = _navigation_cases(events)
    exact = [
        case
        for case in cases
        if case[0]["parameters"] == {"x": 121.0, "y": 137.0, "z": -33.0}
    ]
    assert len(exact) == 5

    for action, observation, progress in exact:
        guard = guard_sp003_phase118_action(action, observation, progress)
        assert guard["allowed"], guard
        assert guard["policy_id"] == SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID
        assert guard["parent_policy_id"] == phase116.SP003_TABLE_STAGING_POLICY_ID
        assert guard["parameter_normalization"] == {
            "type": "sp003_phase118_exact_navigation_parameter_normalization",
            "schema_version": 1,
            "policy_id": SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID,
            "applicable": True,
            "applied": True,
            "original_parameter_keys": ["x", "y", "z"],
            "removed_parameter_keys": ["y"],
            "exact_xyz_bound": True,
            "world_mutation": False,
            "planner_retry": False,
            "machine_target_source_id": "stone:121:137:-33",
            "machine_target_position": {"x": 121.0, "y": 137.0, "z": -33.0},
        }
        assert guard["action"]["parameters"] == {
            "x": 121.5,
            "z": -32.5,
            "tolerance": base.SP003_MOVE_TO_CONTINUOUS_TOLERANCE,
            "preserve_inventory": True,
        }
        assert guard["action_repair"]["attempt_limit"] == 1
        assert guard["action_repair"]["failure_reclassification_allowed"] is True


def test_phase118_keeps_all_wrong_y_targets_fail_closed(events):
    cases = _navigation_cases(events)
    wrong_y = [
        case
        for case in cases
        if case[0]["parameters"] == {"x": 121.0, "y": 140.0, "z": -33.0}
    ]
    assert len(wrong_y) == 3

    for action, observation, progress in wrong_y:
        guard = guard_sp003_phase118_action(action, observation, progress)
        assert guard["allowed"] is False
        assert guard["parameter_normalization"]["applied"] is False
        assert guard["parameter_normalization"]["exact_xyz_bound"] is False
        assert "sp003_table_staging_move_requires_exact_xz" in guard["issues"]
        assert "sp003_table_staging_navigation_target_mismatch" in guard["issues"]


def test_phase118_rejects_near_target_extras_and_skill_context(events):
    action, observation, progress = _navigation_cases(events)[0]
    near = copy.deepcopy(action)
    near["parameters"]["x"] += 0.02
    extra = copy.deepcopy(action)
    extra["parameters"]["tolerance"] = 0.5
    skill_bound = copy.deepcopy(action)
    skill_bound["skill_context"] = {
        "skill_id": "learned:acquire_cobblestone",
        "version": "1.1.0",
    }

    near_guard = guard_sp003_phase118_action(near, observation, progress)
    extra_guard = guard_sp003_phase118_action(extra, observation, progress)
    skill_guard = guard_sp003_phase118_action(
        skill_bound,
        observation,
        progress,
        arm="candidate",
    )
    assert near_guard["allowed"] is False
    assert near_guard["parameter_normalization"]["applied"] is False
    assert "sp003_table_staging_navigation_target_mismatch" in near_guard["issues"]
    assert extra_guard["allowed"] is False
    assert extra_guard["parameter_normalization"]["applied"] is False
    assert "sp003_table_staging_move_requires_exact_xz" in extra_guard["issues"]
    assert skill_guard["allowed"] is False
    assert skill_guard["parameter_normalization"]["applied"] is True
    assert "sp003_table_staging_skill_context_forbidden" in skill_guard["issues"]


def test_phase118_preserves_original_xz_only_binding(events):
    _, observation, progress = _navigation_cases(events)[0]
    guard = guard_sp003_phase118_action(
        {"type": "move_to", "parameters": {"x": 121, "z": -33}},
        observation,
        progress,
    )
    assert guard["allowed"], guard
    assert guard["parameter_normalization"]["applicable"] is True
    assert guard["parameter_normalization"]["applied"] is False
    assert guard["action"]["parameters"] == {
        "x": 121.5,
        "z": -32.5,
        "tolerance": base.SP003_MOVE_TO_CONTINUOUS_TOLERANCE,
        "preserve_inventory": True,
    }


def test_phase118_agent_executes_only_the_phase116_normalized_action(
    monkeypatch,
    events,
):
    action, observation, progress = _navigation_cases(events)[0]
    logged = []
    delegated = []

    def fake_verify(_self, normalized, _observation, _goal, _context=None):
        delegated.append(copy.deepcopy(normalized))
        return {"status": "accept"}, {"success": True}

    monkeypatch.setattr(base.Agent, "_verify_action_for_execution", fake_verify)
    agent = StonePickaxeSP003Phase118RuntimeAgent.__new__(
        StonePickaxeSP003Phase118RuntimeAgent
    )
    agent.sp003_progress = progress
    agent.sp003_arm = "baseline"
    agent.session_logger = SimpleNamespace(
        log=lambda event_type, data, level="INFO": logged.append(
            (event_type, copy.deepcopy(data), level)
        )
    )

    verification, result = agent._verify_action_for_execution(
        action,
        observation,
        "SP-003",
        {"cycle": 8},
    )
    assert verification == {"status": "accept"}
    assert result == {"success": True}
    assert delegated == [
        {
            "type": "move_to",
            "parameters": {
                "x": 121.5,
                "z": -32.5,
                "tolerance": base.SP003_MOVE_TO_CONTINUOUS_TOLERANCE,
                "preserve_inventory": True,
            },
        }
    ]
    assert action == delegated[0]
    assert logged[0][0] == "stone_pickaxe_sp003_action_guard"
    assert logged[0][1]["policy_id"] == SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID
    assert logged[0][1]["parameter_normalization"]["exact_xyz_bound"] is True


def test_phase118_runner_is_process_local_and_preserves_frozen_phase116_runner():
    phase116_audit = json.loads(
        (
            REPO
            / "workspace/evals/stone_pickaxe_sp003_local_table_staging_repair.json"
        ).read_text(encoding="utf-8")
    )
    protected_runner = next(
        item
        for item in phase116_audit["implementation"]
        if item["path"] == "scripts/stone_pickaxe_sp003_episode_runner.py"
    )
    runner_path = REPO / protected_runner["path"]
    assert hashlib.sha256(runner_path.read_bytes()).hexdigest() == (
        protected_runner["sha256"]
    )

    wrapper = (
        REPO / "scripts/stone_pickaxe_sp003_phase118_episode_runner.py"
    ).read_text(encoding="utf-8")
    launcher = subprocess.check_output(
        [
            "git",
            "show",
            f"{PHASE118_FIX_COMMIT}:scripts/stone-pickaxe-sp003-runtime.ps1",
        ],
        cwd=REPO,
        text=True,
        encoding="utf-8",
    )
    assert "frozen_runner.StonePickaxeSP003Phase116RuntimeAgent" in wrapper
    assert "StonePickaxeSP003Phase118RuntimeAgent" in wrapper
    assert launcher.count("stone_pickaxe_sp003_phase118_episode_runner.py") == 2
    assert "stone_pickaxe_sp003_episode_runner.py run" not in launcher


def test_phase118_audit_binds_repair_evidence_and_protected_identities():
    audit = json.loads(
        (
            REPO
            / "workspace/evals/stone_pickaxe_sp003_exact_navigation_parameter_normalization_repair.json"
        ).read_text(encoding="utf-8")
    )
    assert audit["phase"] == 118
    assert audit["base_commit"] == (
        "271a188f020a9e78a88b6c4443a7a6ee7404c56a"
    )
    assert audit["policy_id"] == SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID
    assert audit["status"] == "offline_verified"
    assert audit["retained_failure"]["manifest_sha256"] == (
        "a7580b5b0c1a563c3e36425070913cf10c9bcbeea0051008f9a921b9c415965c"
    )
    for record in audit["implementation"]:
        historical = subprocess.check_output(
            ["git", "show", f"{PHASE118_FIX_COMMIT}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(historical).hexdigest() == record["sha256"]
    for record in [
        *audit["protected_phase_116_identities"],
        *audit["protected_runtime_identities"],
    ]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["automatic_retry_allowed"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
