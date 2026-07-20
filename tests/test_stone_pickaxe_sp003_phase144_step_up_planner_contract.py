from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from singularity.core.planner import Planner
from singularity.core.task_system import TaskSystem
from singularity.evaluation.stone_pickaxe_sp003_phase122_runtime import (
    SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
    StonePickaxeSP003Phase122RuntimeAgent,
)
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    SP003_EXACT_MOVE_CONTINUOUS_TOLERANCE,
    SP003_GOAL,
    SP003_PRE_DISPATCH_RECOVERABLE_ISSUES,
    SP003_PRE_DISPATCH_REPLAN_POLICY_ID,
    verify_sp003_policy_identity,
)


REPO = Path(__file__).resolve().parents[1]
RUN_DIR = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_173513_afba21cd"
)
STEP_UP_SOURCE_ID = "sp003_clearance_shaft_step_up_egress:120:141:-37"
SCRIPT_PATH = (
    REPO / "scripts/stone_pickaxe_sp003_phase144_step_up_planner_contract_repair.py"
)
SCHEMA_PATH = (
    REPO
    / "workspace/evals/schemas/"
    "stone_pickaxe_sp003_step_up_planner_contract_repair.schema.json"
)
AUDIT_PATH = (
    REPO
    / "workspace/evals/"
    "stone_pickaxe_sp003_phase144_step_up_planner_contract_repair.json"
)
AUDIT_SHA256 = "77f94ee98318f38f9706763ebd2279dd036d031c21c0682c81942c1e9f88975a"
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


def _module():
    spec = importlib.util.spec_from_file_location(
        "phase144_step_up_planner_contract_repair", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _phase143_step_up_observation() -> dict:
    events = json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))
    return next(
        event["data"]
        for event in events
        if event.get("type") == "observation"
        and event["data"].get("sp003_targets")
        and event["data"]["sp003_targets"][0].get(
            "stone_clearance_shaft_step_up_egress"
        )
        is True
    )


def _bare_agent(observation: dict) -> StonePickaxeSP003Phase122RuntimeAgent:
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


def test_phase144_preserves_exact_step_up_semantics_in_compact_state_and_prompts():
    observation = copy.deepcopy(_phase143_step_up_observation())
    compact = Planner._compact_stone_pickaxe_state(observation)

    assert compact["sp003_stage"] == "place_crafting_table"
    assert len(compact["sp003_targets"]) == 1
    target = compact["sp003_targets"][0]
    assert target["source_id"] == STEP_UP_SOURCE_ID
    assert target["navigation_only"] is True
    assert "stone_clearance_shaft_egress" not in target
    assert target["stone_clearance_shaft_step_up_egress"] is True
    assert target["stand_position"] == {"x": 120.5, "y": 141, "z": -36.5}
    assert "shaft_step_up_egress_proof" not in target
    assert "shaft_step_up_egress_proof_fingerprint" not in target

    planner = Planner(
        object(),
        TaskSystem(),
        protocol="stone-pickaxe-skill-fixed-v1",
    )
    planner._expected_plan_kind = "continuation"
    user_prompt = planner._build_planning_prompt(SP003_GOAL, observation, "")
    system_prompt = planner._stone_pickaxe_system_prompt()

    assert '"stone_clearance_shaft_step_up_egress":true' in user_prompt
    assert '"stand_position":{"x":120.5,"y":141,"z":-36.5}' in user_prompt
    assert "navigation_only=true" in user_prompt
    assert "use exact stand_position x/y/z when present" in user_prompt
    assert "Never place, dig, or wait on a navigation-only target" in user_prompt
    assert "navigation_only=true requires move_to and forbids place, dig, or wait" in (
        system_prompt
    )
    assert "stone_clearance_shaft_egress" in system_prompt
    assert "stone_clearance_shaft_step_up_egress" in system_prompt


def test_phase144_replans_the_phase143_wrong_place_once_then_fails_closed():
    observation = copy.deepcopy(_phase143_step_up_observation())
    agent = _bare_agent(observation)
    wrong_place = {
        "type": "place",
        "parameters": {
            "item": "crafting_table",
            "x": 120.5,
            "y": 141,
            "z": -36.5,
        },
    }

    guard = agent._effective_sp003_action_guard(wrong_place, observation)
    assert guard["policy_id"] == SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID
    assert guard["allowed"] is False
    assert guard["issues"] == [
        "sp003_partial_shaft_step_up_navigation_required",
        "sp003_partial_shaft_step_up_parameters_unexpected",
    ]

    first = agent._pre_dispatch_replan_for_action(
        wrong_place,
        observation,
        SP003_GOAL,
        {"cycle": 13, "mode": "goal"},
    )
    duplicate = agent._pre_dispatch_replan_for_action(
        wrong_place,
        observation,
        SP003_GOAL,
        {"cycle": 14, "mode": "goal"},
    )
    assert first["requires_replan"] is True
    assert first["policy_id"] == SP003_PRE_DISPATCH_REPLAN_POLICY_ID
    assert duplicate is None

    reports = [event["data"] for event in agent.session_logger.events]
    assert [report["granted"] for report in reports] == [True, False]
    assert reports[0]["action_suppressed_before_dispatch"] is True
    assert reports[0]["action_budget_consumed"] is False
    assert reports[0]["backend_invoked"] is False
    assert reports[0]["world_mutation"] is False
    assert reports[0]["same_call_retry_count"] == 0
    assert reports[0]["fresh_observation_required"] is True
    assert reports[1]["limit_reason"] == "fingerprint_limit_exhausted"


def test_phase144_exact_step_up_move_is_guard_normalized_without_replan():
    observation = copy.deepcopy(_phase143_step_up_observation())
    agent = _bare_agent(observation)
    action = {
        "type": "move_to",
        "parameters": copy.deepcopy(
            observation["sp003_targets"][0]["stand_position"]
        ),
    }

    guard = agent._effective_sp003_action_guard(action, observation)
    assert guard["allowed"] is True
    assert guard["issues"] == []
    assert guard["action"] == {
        "type": "move_to",
        "parameters": {
            "x": 120.5,
            "y": 141,
            "z": -36.5,
            "tolerance": SP003_EXACT_MOVE_CONTINUOUS_TOLERANCE,
            "preserve_inventory": True,
        },
    }
    assert agent._pre_dispatch_replan_for_action(
        action,
        observation,
        SP003_GOAL,
        {"cycle": 13, "mode": "goal"},
    ) is None
    assert agent.session_logger.events == []


def test_phase144_recovery_scope_is_exact_and_policy_bound():
    assert SHAFT_REPLAN_ISSUES <= SP003_PRE_DISPATCH_RECOVERABLE_ISSUES
    identity = verify_sp003_policy_identity()
    assert identity["passed"], identity
    assert identity["checks"]["bounded_planner_state_contract"] is True
    assert identity["checks"]["pre_dispatch_semantic_replan_contract"] is True

    observation = copy.deepcopy(_phase143_step_up_observation())
    agent = _bare_agent(observation)
    unsafe = {
        "type": "move_to",
        "parameters": copy.deepcopy(
            observation["sp003_targets"][0]["stand_position"]
        ),
        "skill_context": {"skill_id": "forged"},
    }
    guard = agent._effective_sp003_action_guard(unsafe, observation)
    assert guard["allowed"] is False
    assert guard["issues"] == [
        "sp003_partial_shaft_step_up_skill_context_forbidden"
    ]
    assert agent._pre_dispatch_replan_for_action(
        unsafe,
        observation,
        SP003_GOAL,
        {"cycle": 13, "mode": "goal"},
    ) is None
    assert agent.session_logger.events == []


def test_phase144_generator_replays_the_repair_without_external_execution():
    module = _module()
    audit = module.build_audit(module.repo_path(module.DEFAULT_SOURCE))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(audit)
    assert audit["repair_passed"] is True
    assert all(
        value
        for group in audit["checks"].values()
        for value in group.values()
    )
    assert audit["minecraft_process_started"] is False
    assert audit["provider_request_made"] is False
    assert audit["authorization_created"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_skill_gate"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False


def test_phase144_retained_audit_is_hash_bound_and_schema_valid():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )

    assert hashlib.sha256(AUDIT_PATH.read_bytes()).hexdigest() == AUDIT_SHA256
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(audit)
    assert audit["predecessor_commit"] == (
        "1ebbb35a97e187aa76922a6efc0beb1193f2d13a"
    )
    assert audit["source_evidence"]["sha256"] == (
        "3c978d47dbfc0ab6d12fef535577c7399b773ec358dba2fd968bdda01ff1e681"
    )
    assert audit["source_evidence"]["observation_canonical_sha256"] == (
        "54098503b80234cb15e3c49f69066392f89180afb6bbeb496d45ee2f7e95f41e"
    )
    for record in audit["implementation"]:
        assert hashlib.sha256((REPO / record["path"]).read_bytes()).hexdigest() == (
            record["sha256"]
        )
    gate = ledger["next_required_gate"]
    assert gate["id"] == (
        "sp003_phase_145_probe_evidence_commit_push_then_phase_146_parent_bound_one_use_baseline_authorization"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert ledger["live_authorization"] is False


def test_phase144_generator_has_no_provider_or_minecraft_execution_path():
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "LLMProvider" not in text
    assert "plan_from_goal" not in text
    assert "Start-Process" not in text
    assert '"provider_request_made": False' in text
    assert '"minecraft_process_started": False' in text
