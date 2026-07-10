"""Offline tests for verifier-calibrated skill soft retirement."""

import json
import os
import tempfile

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.runtime_profile import build_runtime_profile_payload, build_runtime_profile_report
from singularity.core.skill_library import SkillLibrary
from singularity.evaluation.skill_retirement import (
    BUILTIN_SKILL_CONTRIBUTION_CASES,
    BUILTIN_VERIFIER_CALIBRATION_CASES,
    build_skill_contribution_report,
    build_skill_retirement_gate,
    build_verifier_calibration_report,
)


def _calibration_cases(*, false_pass: bool = False) -> list[dict]:
    cases = []
    for index in range(1, 4):
        cases.append({
            "id": f"calibration-defect-{index}",
            "truth_success": False,
            "judge_pass": false_pass,
            "defect_injected": True,
            "judge_id": "reward_judge_v2",
            "verifier_id": "deterministic_goal_verifier_v3",
            "task_stream_id": "live-calibration-stream",
            "session_id": f"calibration-session-{index}",
            "seed": str(100 + index),
            "source": f"logs/session-{index}.jsonl",
            "evidence_kind": "live_trace",
            "non_verifier_modules_fixed": True,
        })
    cases.append({
        "id": "calibration-control-pass",
        "truth_success": True,
        "judge_pass": True,
        "defect_injected": False,
        "judge_id": "reward_judge_v2",
        "verifier_id": "deterministic_goal_verifier_v3",
        "task_stream_id": "live-calibration-stream",
        "session_id": "calibration-session-4",
        "seed": "104",
        "source": "logs/session-4.jsonl",
        "evidence_kind": "live_trace",
        "non_verifier_modules_fixed": True,
    })
    return cases


def _contribution_cases(skill: str, *, candidate_success: bool = False) -> list[dict]:
    return [
        {
            "id": f"contribution-{index}",
            "skill": skill,
            "task_family": "crafting",
            "baseline_successes": 1,
            "baseline_trials": 1,
            "candidate_successes": 1 if candidate_success else 0,
            "candidate_trials": 1,
            "candidate_failure_verified_count": 0 if candidate_success else 1,
            "baseline_session_id": f"baseline-session-{index}",
            "candidate_session_id": f"candidate-session-{index}",
            "judge_id": "reward_judge_v2",
            "verifier_id": "deterministic_goal_verifier_v3",
            "planner_id": "fixed-planner-v5",
            "action_backend": "mineflayer-bridge-v2",
            "task_stream_id": "live-crafting-stream",
            "seed": str(200 + index),
            "source": f"logs/contribution-{index}.jsonl",
            "evidence_kind": "live_trace",
            "no_skill_baseline": True,
            "non_skill_modules_fixed": True,
            "built_in": False,
        }
        for index in range(1, 4)
    ]


def _failure_skill_implementation() -> str:
    return json.dumps({
        "type": "failure_correction_skill",
        "avoid_action_template": {"type": "craft", "parameters": {"item": "torch"}},
        "primary_correction": {"type": "dig", "parameters": {"block": "coal_ore"}},
        "correction_sequence": [{"type": "dig", "parameters": {"block": "coal_ore"}}],
        "evidence": {"failure_why": "missing coal"},
    })


def _runtime_default_gate(skill: str) -> dict:
    return {
        "readiness": "approved",
        "decision": "allow_task_family_runtime_default_skills",
        "target_task_family": "crafting",
        "approved_candidate_count": 1,
        "candidates": [{
            "skill": skill,
            "task_family": "crafting",
            "candidate_readiness": "approved",
        }],
    }


def test_verifier_calibration_rejects_false_pass_bias():
    reliable = build_verifier_calibration_report(_calibration_cases())
    biased = build_verifier_calibration_report(_calibration_cases(false_pass=True))
    second_judge = []
    for case in _calibration_cases(false_pass=True):
        item = dict(case)
        item["id"] = "biased-" + item["id"]
        item["judge_id"] = "biased_reward_judge"
        item["session_id"] = "biased-" + item["session_id"]
        second_judge.append(item)
    mixed = build_verifier_calibration_report(_calibration_cases() + second_judge)

    assert reliable["readiness"] == "approved"
    assert reliable["runtime_eligible"] is True
    assert reliable["false_pass_rate"] == 0.0
    assert reliable["failure_detection_recall"] == 1.0
    assert reliable["approved_judge_ids"] == ["reward_judge_v2"]
    assert biased["readiness"] == "rejected"
    assert biased["runtime_eligible"] is False
    assert biased["false_pass_rate"] == 1.0
    assert biased["approved_judge_ids"] == []
    assert mixed["readiness"] == "rejected"
    assert {item["readiness"] for item in mixed["judges"]} == {"approved", "rejected"}
    assert mixed["approved_judge_ids"] == []
    print("PASS: verifier calibration rejects false-pass bias")


def test_skill_contribution_separates_harmful_and_helpful_skills():
    harmful = build_skill_contribution_report(_contribution_cases("harmful_torch_shortcut"))
    helpful = build_skill_contribution_report(
        _contribution_cases("reliable_torch_recovery", candidate_success=True)
    )

    harmful_skill = harmful["skills"][0]
    helpful_skill = helpful["skills"][0]
    assert harmful["readiness"] == "ready"
    assert harmful["soft_quarantine_candidate_count"] == 1
    assert harmful_skill["candidate_readiness"] == "ready"
    assert harmful_skill["contribution_delta"] == -1.0
    assert harmful_skill["verified_candidate_failure_count"] == 3
    assert helpful["readiness"] == "ready"
    assert helpful["soft_quarantine_candidate_count"] == 0
    assert helpful_skill["candidate_readiness"] == "retain"
    assert helpful_skill["contribution_delta"] == 0.0
    print("PASS: skill contribution keeps non-negative skills active")


def test_skill_retirement_gate_requires_live_calibrated_evidence():
    calibration = build_verifier_calibration_report(_calibration_cases())
    contribution = build_skill_contribution_report(_contribution_cases("harmful_torch_shortcut"))
    approved = build_skill_retirement_gate(
        calibration_reports=[calibration],
        contribution_reports=[contribution],
    )
    conflicting = build_skill_retirement_gate(
        calibration_reports=[
            calibration,
            build_verifier_calibration_report(_calibration_cases(false_pass=True)),
        ],
        contribution_reports=[contribution],
    )

    builtin_calibration = build_verifier_calibration_report(
        BUILTIN_VERIFIER_CALIBRATION_CASES,
        require_live_evidence=False,
    )
    builtin_contribution = build_skill_contribution_report(
        BUILTIN_SKILL_CONTRIBUTION_CASES,
        require_live_evidence=False,
    )
    builtin_gate = build_skill_retirement_gate(
        calibration_reports=[builtin_calibration],
        contribution_reports=[builtin_contribution],
    )

    assert approved["readiness"] == "approved"
    assert approved["soft_quarantine_allowed"] is True
    assert approved["automatic_delete_allowed"] is False
    assert approved["candidates"][0]["candidate_readiness"] == "approved"
    assert conflicting["readiness"] == "rejected"
    assert conflicting["soft_quarantine_allowed"] is False
    assert conflicting["approved_judge_ids"] == []
    assert builtin_calibration["runtime_eligible"] is False
    assert builtin_contribution["runtime_eligible"] is False
    assert builtin_gate["readiness"] == "review"
    assert builtin_gate["soft_quarantine_allowed"] is False
    assert builtin_gate["automatic_delete_allowed"] is False
    print("PASS: skill retirement gate rejects builtin synthetic evidence")


def test_skill_library_applies_read_only_soft_quarantine():
    tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills")
    skill_name = "harmful_torch_shortcut"
    skills = SkillLibrary(storage_path=skill_dir, persist=True)
    skills.create_skill(skill_name, "Unsafe torch correction", _failure_skill_implementation())
    skills.record_skill_runtime_default_gate(_runtime_default_gate(skill_name))
    custom_path = os.path.join(skill_dir, "custom_skills.jsonl")
    before = open(custom_path, "rb").read()

    world_state = {
        "inventory": {"stick": 1},
        "nearby_blocks": [{"name": "coal_ore"}],
        "nearby_entities": [],
    }
    assert skills.find_failure_correction(
        {"type": "craft", "parameters": {"item": "torch"}},
        {"success": False, "error": "Missing coal"},
        world_state,
    )

    calibration = build_verifier_calibration_report(_calibration_cases())
    contribution = build_skill_contribution_report(_contribution_cases(skill_name))
    gate = build_skill_retirement_gate(
        calibration_reports=[calibration],
        contribution_reports=[contribution],
    )
    gate["candidates"].append({
        "skill": "craft_item",
        "task_family": "crafting",
        "candidate_readiness": "approved",
    })
    applied = skills.record_skill_retirement_gate(gate)
    after = open(custom_path, "rb").read()

    assert applied == 1
    assert skills.find_failure_correction(
        {"type": "craft", "parameters": {"item": "torch"}},
        {"success": False, "error": "Missing coal"},
        world_state,
    ) is None
    profile = skills.skill_retirement_profile()
    assert profile["quarantined_skill_families"][skill_name] == ["crafting"]
    assert "craft_item" not in profile["quarantined_skills"]
    assert skills._runtime_default_skill_allowed("craft_item", "crafting", built_in=True)
    assert profile["automatic_delete_allowed"] is False
    assert before == after

    review_only = SkillLibrary()
    review_only.create_skill(skill_name, "Unsafe torch correction", _failure_skill_implementation())
    review_only.record_skill_runtime_default_gate(_runtime_default_gate(skill_name))
    review_only.record_skill_retirement_gate({
        "readiness": "review",
        "soft_quarantine_allowed": False,
        "automatic_delete_allowed": False,
        "candidates": [{"skill": skill_name, "candidate_readiness": "review"}],
    })
    assert review_only._runtime_default_skill_allowed(skill_name, "crafting")

    forged_gate = dict(gate)
    forged_gate.pop("deletion_policy")
    assert review_only.record_skill_retirement_gate(forged_gate) == 0
    assert review_only._runtime_default_skill_allowed(skill_name, "crafting")
    print("PASS: SkillLibrary soft quarantine is runtime-only and preserves files")


def test_agent_loads_only_live_skill_retirement_gate():
    tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills")
    skill_name = "harmful_torch_shortcut"
    writer = SkillLibrary(storage_path=skill_dir, persist=True)
    writer.create_skill(skill_name, "Unsafe torch correction", _failure_skill_implementation())

    runtime_default_path = os.path.join(tmpdir, "runtime_default.json")
    retirement_path = os.path.join(tmpdir, "retirement.json")
    with open(runtime_default_path, "w", encoding="utf-8") as handle:
        json.dump(_runtime_default_gate(skill_name), handle)
    gate = build_skill_retirement_gate(
        calibration_reports=[build_verifier_calibration_report(_calibration_cases())],
        contribution_reports=[build_skill_contribution_report(_contribution_cases(skill_name))],
    )
    with open(retirement_path, "w", encoding="utf-8") as handle:
        json.dump(gate, handle)

    agent = Agent(Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        log_dir=os.path.join(tmpdir, "logs"),
        skill_dir=skill_dir,
        skill_runtime_default_gate_paths=[runtime_default_path],
        skill_retirement_gate_paths=[retirement_path],
    ))
    match = agent.skill_library.find_failure_correction(
        {"type": "craft", "parameters": {"item": "torch"}},
        {"success": False, "error": "Missing coal"},
        {"inventory": {"stick": 1}, "nearby_blocks": [{"name": "coal_ore"}]},
    )

    assert agent.skill_retirement_gate_report["gate_approved"] is True
    assert agent.skill_retirement_gate_report["gate_readiness"] == "approved"
    assert agent.skill_retirement_gate_report["quarantined_skill_count"] == 1
    assert agent.skill_retirement_gate_report["automatic_delete_allowed"] is False
    assert match is None
    assert os.path.isfile(os.path.join(skill_dir, "custom_skills.jsonl"))

    synthetic_path = os.path.join(tmpdir, "synthetic_retirement.json")
    synthetic_gate = dict(gate)
    synthetic_gate["thresholds"] = dict(gate["thresholds"])
    synthetic_gate["thresholds"]["require_live_evidence"] = False
    with open(synthetic_path, "w", encoding="utf-8") as handle:
        json.dump(synthetic_gate, handle)
    review_agent = Agent(Config(
        memory_dir=os.path.join(tmpdir, "memory-review"),
        log_dir=os.path.join(tmpdir, "logs-review"),
        skill_dir=skill_dir,
        skill_runtime_default_gate_paths=[runtime_default_path],
        skill_retirement_gate_paths=[synthetic_path],
    ))
    review_match = review_agent.skill_library.find_failure_correction(
        {"type": "craft", "parameters": {"item": "torch"}},
        {"success": False, "error": "Missing coal"},
        {"inventory": {"stick": 1}, "nearby_blocks": [{"name": "coal_ore"}]},
    )
    assert review_agent.skill_retirement_gate_report["gate_approved"] is False
    assert review_agent.skill_retirement_gate_report["gate_readiness"] == "rejected"
    assert review_match and review_match[0].name == skill_name
    print("PASS: Agent loads only live-evidence skill retirement gates")


def test_runtime_profile_carries_skill_retirement_gate():
    tmpdir = tempfile.mkdtemp()
    gate_path = os.path.join(tmpdir, "skill_retirement_gate.json")
    profile_path = os.path.join(tmpdir, "runtime_profile.json")
    gate = build_skill_retirement_gate(
        calibration_reports=[build_verifier_calibration_report(_calibration_cases())],
        contribution_reports=[build_skill_contribution_report(_contribution_cases("harmful_torch_shortcut"))],
    )
    with open(gate_path, "w", encoding="utf-8") as handle:
        json.dump(gate, handle)
    profile = build_runtime_profile_payload(
        name="retirement-overlay-fixture",
        path_fields={"skill_retirement_gate_paths": [gate_path]},
    )
    with open(profile_path, "w", encoding="utf-8") as handle:
        json.dump(profile, handle)

    report = build_runtime_profile_report([profile_path])
    assert profile["gates"]["skill_retirement"] == [gate_path]
    assert report["readiness"] == "approved"
    assert report["approved_gate_count"] == 1
    assert report["gate_reports"][0]["field"] == "skill_retirement_gate_paths"
    print("PASS: runtime profiles carry skill retirement gates")


if __name__ == "__main__":
    test_verifier_calibration_rejects_false_pass_bias()
    test_skill_contribution_separates_harmful_and_helpful_skills()
    test_skill_retirement_gate_requires_live_calibrated_evidence()
    test_skill_library_applies_read_only_soft_quarantine()
    test_agent_loads_only_live_skill_retirement_gate()
    test_runtime_profile_carries_skill_retirement_gate()
    print("\nSkill retirement tests PASSED")
