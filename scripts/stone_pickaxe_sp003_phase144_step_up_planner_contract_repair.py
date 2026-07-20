"""Replay the Phase 143 step-up failure through the Phase 144 offline repair."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from singularity.core.planner import Planner
from singularity.core.task_system import TaskSystem
from singularity.evaluation.stone_pickaxe_protocol import canonical_sha256
from singularity.evaluation.stone_pickaxe_sp003_phase122_runtime import (
    StonePickaxeSP003Phase122RuntimeAgent,
)
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    SP003_GOAL,
    SP003_PRE_DISPATCH_RECOVERABLE_ISSUES,
    verify_sp003_policy_identity,
)


PHASE = 144
POLICY_ID = "sp003-step-up-planner-contract-repair-v1"
PREDECESSOR_COMMIT = "1ebbb35a97e187aa76922a6efc0beb1193f2d13a"
SOURCE_EPISODE_ID = "sp003_baseline_20260720_173513_afba21cd"
SOURCE_SESSION_SHA256 = (
    "3c978d47dbfc0ab6d12fef535577c7399b773ec358dba2fd968bdda01ff1e681"
)
STEP_UP_SOURCE_ID = "sp003_clearance_shaft_step_up_egress:120:141:-37"
DEFAULT_SOURCE = Path(
    "workspace/evals/sp003_runs/"
    f"{SOURCE_EPISODE_ID}/session.json"
)
DEFAULT_OUTPUT = Path(
    "workspace/evals/stone_pickaxe_sp003_phase144_step_up_planner_contract_repair.json"
)
IMPLEMENTATION_PATHS = (
    "src/singularity/core/planner.py",
    "src/singularity/evaluation/stone_pickaxe_sp003_runtime.py",
    "workspace/evals/stone_pickaxe_sp003_harness_policy.json",
)
SHAFT_REPLAN_ISSUES = {
    "sp003_partial_shaft_egress_navigation_required",
    "sp003_partial_shaft_egress_parameters_unexpected",
    "sp003_partial_shaft_egress_target_mismatch",
    "sp003_partial_shaft_step_up_navigation_required",
    "sp003_partial_shaft_step_up_parameters_unexpected",
    "sp003_partial_shaft_step_up_target_mismatch",
}


class LogStub:
    def __init__(self):
        self.events = []

    def log(self, event_type, data, level="INFO"):
        self.events.append({"type": event_type, "data": data, "level": level})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay the Phase 143 step-up Planner contract offline"
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE.as_posix())
    parser.add_argument("--output", default=DEFAULT_OUTPUT.as_posix())
    return parser.parse_args()


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else REPOSITORY_ROOT / value


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def retained_observation(path: Path) -> dict:
    if file_sha256(path) != SOURCE_SESSION_SHA256:
        raise RuntimeError("Phase 143 session identity mismatch")
    events = json.loads(path.read_text(encoding="utf-8"))
    matches = [
        event["data"]
        for event in events
        if event.get("type") == "observation"
        and event.get("data", {}).get("sp003_targets")
        and event["data"]["sp003_targets"][0].get(
            "stone_clearance_shaft_step_up_egress"
        )
        is True
    ]
    if len(matches) != 21:
        raise RuntimeError(
            f"expected 21 retained Phase 143 step-up observations, got {len(matches)}"
        )
    observation = matches[0]
    target = observation["sp003_targets"][0]
    if (
        target.get("source_id") != STEP_UP_SOURCE_ID
        or target.get("navigation_only") is not True
        or target.get("stand_position") != {"x": 120.5, "y": 141, "z": -36.5}
    ):
        raise RuntimeError("Phase 143 step-up target identity mismatch")
    return observation


def bare_agent(observation: dict) -> StonePickaxeSP003Phase122RuntimeAgent:
    agent = StonePickaxeSP003Phase122RuntimeAgent.__new__(
        StonePickaxeSP003Phase122RuntimeAgent
    )
    agent.sp003_arm = "baseline"
    agent.sp003_progress = copy.deepcopy(observation["sp003_progress"])
    agent._sp003_phase120_egress_attempted_fingerprints = set()
    agent._sp003_pre_dispatch_replan_fingerprints = set()
    agent._sp003_pre_dispatch_replan_count = 0
    agent.session_logger = LogStub()
    return agent


def build_audit(source_path: Path) -> dict:
    observation = retained_observation(source_path)
    raw_target = observation["sp003_targets"][0]
    compact = Planner._compact_stone_pickaxe_state(observation)
    compact_target = compact["sp003_targets"][0]

    planner = Planner(object(), TaskSystem(), protocol="stone-pickaxe-skill-fixed-v1")
    planner._expected_plan_kind = "continuation"
    user_prompt = planner._build_planning_prompt(SP003_GOAL, observation, "")
    system_prompt = planner._stone_pickaxe_system_prompt()

    wrong_place = {
        "type": "place",
        "parameters": {
            "item": "crafting_table",
            "x": 120.5,
            "y": 141,
            "z": -36.5,
        },
    }
    wrong_agent = bare_agent(observation)
    wrong_guard = wrong_agent._effective_sp003_action_guard(
        wrong_place, observation
    )
    first_replan = wrong_agent._pre_dispatch_replan_for_action(
        wrong_place, observation, SP003_GOAL, {"cycle": 13, "mode": "goal"}
    )
    duplicate_replan = wrong_agent._pre_dispatch_replan_for_action(
        wrong_place, observation, SP003_GOAL, {"cycle": 14, "mode": "goal"}
    )
    replan_reports = [event["data"] for event in wrong_agent.session_logger.events]

    exact_move = {
        "type": "move_to",
        "parameters": copy.deepcopy(raw_target["stand_position"]),
    }
    exact_agent = bare_agent(observation)
    exact_guard = exact_agent._effective_sp003_action_guard(exact_move, observation)
    exact_replan = exact_agent._pre_dispatch_replan_for_action(
        exact_move, observation, SP003_GOAL, {"cycle": 13, "mode": "goal"}
    )

    unsafe_move = {
        **copy.deepcopy(exact_move),
        "skill_context": {"skill_id": "forged"},
    }
    unsafe_agent = bare_agent(observation)
    unsafe_guard = unsafe_agent._effective_sp003_action_guard(
        unsafe_move, observation
    )
    unsafe_replan = unsafe_agent._pre_dispatch_replan_for_action(
        unsafe_move, observation, SP003_GOAL, {"cycle": 13, "mode": "goal"}
    )

    identity = verify_sp003_policy_identity()
    checks = {
        "source": {
            "session_sha256": file_sha256(source_path) == SOURCE_SESSION_SHA256,
            "exact_step_up_observation_selected": raw_target.get("source_id")
            == STEP_UP_SOURCE_ID,
            "navigation_only": raw_target.get("navigation_only") is True,
            "exact_stand_position": raw_target.get("stand_position")
            == {"x": 120.5, "y": 141, "z": -36.5},
        },
        "compact_state": {
            "authoritative_stage": compact.get("sp003_stage")
            == "place_crafting_table",
            "single_target": len(compact.get("sp003_targets", [])) == 1,
            "navigation_only_preserved": compact_target.get("navigation_only")
            is True,
            "step_up_marker_preserved": compact_target.get(
                "stone_clearance_shaft_step_up_egress"
            )
            is True,
            "stand_position_preserved": compact_target.get("stand_position")
            == {"x": 120.5, "y": 141, "z": -36.5},
            "proof_omitted": "shaft_step_up_egress_proof" not in compact_target,
        },
        "prompt": {
            "marker_present": '"stone_clearance_shaft_step_up_egress":true'
            in user_prompt,
            "exact_stand_position_present": (
                '"stand_position":{"x":120.5,"y":141,"z":-36.5}'
                in user_prompt
            ),
            "navigation_rule_present": "navigation_only=true" in user_prompt,
            "exact_move_rule_present": (
                "use exact stand_position x/y/z when present" in user_prompt
            ),
            "mutation_forbidden": (
                "Never place, dig, or wait on a navigation-only target"
                in user_prompt
            ),
            "system_contract_present": (
                "navigation_only=true requires move_to and forbids place, dig, or wait"
                in system_prompt
            ),
            "user_prompt_bounded": len(user_prompt.encode("utf-8")) <= 5000,
        },
        "replan": {
            "wrong_place_rejected": wrong_guard.get("allowed") is False,
            "exact_guard_issues": wrong_guard.get("issues")
            == [
                "sp003_partial_shaft_step_up_navigation_required",
                "sp003_partial_shaft_step_up_parameters_unexpected",
            ],
            "first_replan_granted": bool(first_replan)
            and first_replan.get("requires_replan") is True,
            "duplicate_fails_closed": duplicate_replan is None,
            "single_granted_report": [report["granted"] for report in replan_reports]
            == [True, False],
            "no_action_budget_consumed": replan_reports[0].get(
                "action_budget_consumed"
            )
            is False,
            "no_backend_invocation": replan_reports[0].get("backend_invoked")
            is False,
            "no_world_mutation": replan_reports[0].get("world_mutation") is False,
            "no_same_call_retry": replan_reports[0].get("same_call_retry_count")
            == 0,
        },
        "exact_move": {
            "guard_allowed": exact_guard.get("allowed") is True,
            "guard_issues_empty": exact_guard.get("issues") == [],
            "normalized_exact_stand": exact_guard.get("action", {}).get(
                "parameters", {}
            ).get("y")
            == 141,
            "inventory_preserved": exact_guard.get("action", {}).get(
                "parameters", {}
            ).get("preserve_inventory")
            is True,
            "no_replan": exact_replan is None,
        },
        "negative_control": {
            "skill_context_rejected": unsafe_guard.get("allowed") is False,
            "skill_context_issue_exact": unsafe_guard.get("issues")
            == ["sp003_partial_shaft_step_up_skill_context_forbidden"],
            "unsafe_replan_not_granted": unsafe_replan is None,
        },
        "policy": {
            "identity_passed": identity.get("passed") is True,
            "shaft_issue_scope_exact": SHAFT_REPLAN_ISSUES
            <= SP003_PRE_DISPATCH_RECOVERABLE_ISSUES,
        },
    }
    passed = all(
        value
        for group in checks.values()
        for value in group.values()
    )
    return {
        "type": "stone_pickaxe_sp003_step_up_planner_contract_repair",
        "schema_version": 1,
        "phase": PHASE,
        "policy_id": POLICY_ID,
        "task_id": "SP-003",
        "generated_at_utc": utc_now(),
        "predecessor_commit": PREDECESSOR_COMMIT,
        "source_evidence": {
            "episode_id": SOURCE_EPISODE_ID,
            "path": repo_relative(source_path),
            "sha256": file_sha256(source_path),
            "immutable": True,
            "rewritten": False,
            "observation_canonical_sha256": canonical_sha256(observation),
            "target": {
                "source_id": raw_target["source_id"],
                "navigation_only": raw_target["navigation_only"],
                "stone_clearance_shaft_step_up_egress": raw_target[
                    "stone_clearance_shaft_step_up_egress"
                ],
                "stand_position": raw_target["stand_position"],
            },
        },
        "checks": checks,
        "counterfactual": {
            "wrong_action": wrong_place,
            "wrong_guard_issues": wrong_guard["issues"],
            "first_replan": first_replan,
            "duplicate_replan": duplicate_replan,
            "exact_move": exact_move,
            "normalized_exact_move": exact_guard["action"],
            "unsafe_skill_context_issues": unsafe_guard["issues"],
        },
        "implementation": [
            {
                "path": path,
                "sha256": file_sha256(REPOSITORY_ROOT / path),
            }
            for path in IMPLEMENTATION_PATHS
        ],
        "repair_passed": passed,
        "status": "offline_verified" if passed else "offline_failed",
        "next_gate": (
            "commit_and_push_phase_144_then_run_one_bounded_no_minecraft_provider_probe"
            if passed
            else "hold_for_phase_144_offline_repair"
        ),
        "minecraft_process_started": False,
        "provider_request_made": False,
        "authorization_created": False,
        "automatic_retry_attempted": False,
        "live_authorization": False,
        "counts_toward_baseline_success": False,
        "counts_toward_skill_gate": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def main() -> int:
    args = parse_args()
    source = repo_path(args.source)
    output = repo_path(args.output)
    audit = build_audit(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(audit, indent=2, ensure_ascii=True) + "\n")
    print(
        json.dumps(
            {
                "output": repo_relative(output),
                "repair_passed": audit["repair_passed"],
                "next_gate": audit["next_gate"],
            },
            sort_keys=True,
        )
    )
    return 0 if audit["repair_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
