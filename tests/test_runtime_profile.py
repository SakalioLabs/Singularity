"""Unit tests for reusable runtime profiles."""
import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.runtime_profile import (
    build_runtime_profile_report,
    load_runtime_profiles,
    merge_arg_profile_list,
    profile_bool_arg,
    profile_str_arg,
)


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_runtime_profile_validates_approved_goal_critic_gate():
    tmpdir = tempfile.mkdtemp()
    gate_path = os.path.join(tmpdir, "goal_critic_gate.json")
    coach_gate_path = os.path.join(tmpdir, "coach_style_gate.json")
    profile_path = os.path.join(tmpdir, "runtime_profile.json")
    _write_json(gate_path, {
        "type": "goal_verification_critic_gate",
        "readiness": "approved",
        "decision": "allow_goal_critic_runtime_use",
        "reason": "fixture",
    })
    _write_json(coach_gate_path, {
        "type": "coach_style_gate",
        "readiness": "approved",
        "decision": "approve",
        "reason": "fixture",
    })
    _write_json(profile_path, {
        "type": "runtime_profile",
        "name": "m1_visual_goal_critic",
        "settings": {
            "enable_goal_critic": True,
            "coach_style": "explorer",
        },
        "gates": {
            "goal_critic": [gate_path],
            "coach_style": [coach_gate_path],
        },
    })

    profiles, errors = load_runtime_profiles([profile_path])
    assert not errors
    args = argparse.Namespace(goal_critic=False, goal_critic_gate=[], coach_style="")

    assert profile_bool_arg(args, "goal_critic", profiles, "enable_goal_critic", "goal_critic")
    assert profile_str_arg(args, "coach_style", profiles, "coach_style", default="") == "explorer"
    assert merge_arg_profile_list(args, "goal_critic_gate", profiles, "goal_critic_gate_paths") == [gate_path]

    report = build_runtime_profile_report([profile_path])
    assert report["readiness"] == "approved"
    assert report["decision"] == "allow_runtime_profile"
    assert report["approved_gate_count"] == 2
    assert report["settings"]["enable_goal_critic"] is True
    print("PASS: Runtime profile validates approved goal critic gate")


def test_runtime_profile_requires_gate_for_patch_artifacts():
    tmpdir = tempfile.mkdtemp()
    patch_path = os.path.join(tmpdir, "mixed_policy_patch.json")
    profile_path = os.path.join(tmpdir, "runtime_profile_missing_gate.json")
    _write_json(patch_path, {"type": "mixed_policy_patch", "patches": []})
    _write_json(profile_path, {
        "type": "runtime_profile",
        "artifacts": {
            "mixed_policy_patch": [patch_path],
        },
    })

    report = build_runtime_profile_report([profile_path])
    assert report["readiness"] == "review"
    assert report["decision"] == "hold_runtime_profile"
    assert "mixed_policy_gate_paths" in report["missing"]
    assert report["artifact_count"] == 1
    print("PASS: Runtime profile requires gate for patch artifacts")


def test_runtime_profile_rejects_rejected_gate():
    tmpdir = tempfile.mkdtemp()
    gate_path = os.path.join(tmpdir, "skill_runtime_default_gate.json")
    profile_path = os.path.join(tmpdir, "runtime_profile_rejected_gate.json")
    _write_json(gate_path, {
        "type": "skill_runtime_default_gate",
        "readiness": "rejected",
        "decision": "keep_runtime_default_review_only",
        "reason": "fixture rejection",
    })
    _write_json(profile_path, {
        "type": "runtime_profile",
        "gates": {
            "skill_runtime_default": [gate_path],
        },
    })

    report = build_runtime_profile_report([profile_path])
    assert report["readiness"] == "rejected"
    assert report["decision"] == "reject_runtime_profile"
    assert report["gate_reports"][0]["readiness"] == "rejected"
    print("PASS: Runtime profile rejects rejected gate")


if __name__ == "__main__":
    test_runtime_profile_validates_approved_goal_critic_gate()
    test_runtime_profile_requires_gate_for_patch_artifacts()
    test_runtime_profile_rejects_rejected_gate()
    print("\nRuntime profile tests PASSED")
