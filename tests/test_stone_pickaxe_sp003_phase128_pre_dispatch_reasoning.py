from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from singularity.core.agent import Agent
from singularity.core.goal_verifier import GoalVerification
from singularity.core.planner import (
    Planner,
    SP003_REASONING_MAX_CHARS,
    SP003_REASONING_NORMALIZATION_POLICY_ID,
)
from singularity.core.task_system import TaskSystem
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    SP003_GOAL,
    SP003_PRE_DISPATCH_REPLAN_POLICY_ID,
    SP003_PRE_DISPATCH_REPLANS_PER_EPISODE_MAX,
    StonePickaxeSP003RuntimeAgent,
    _empty_progress,
    verify_sp003_policy_identity,
)


REPO = Path(__file__).resolve().parents[1]
PHASE127_RUN = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_064839_abb7c5cb"
)
PHASE128_AUDIT = (
    REPO
    / "workspace/evals/stone_pickaxe_sp003_pre_dispatch_replan_and_reasoning_normalization_repair.json"
)


class LogStub:
    def __init__(self):
        self.events = []
        self.session_id = "phase128-test-session"

    def log(self, event_type, data, level="INFO"):
        self.events.append({"type": event_type, "data": data, "level": level})

    def log_goal_start(self, goal):
        self.log("goal_start", {"goal": goal})

    def log_goal_end(self, goal, result):
        self.log("goal_end", {"goal": goal, "result": result})

    def log_observation(self, observation):
        self.log("observation", observation)

    def log_plan(self, plan):
        self.log("plan", plan)

    def log_error(self, error, context=None):
        self.log("error", {"error": error, "context": context or {}})

    def get_summary(self):
        return {
            "action_count": sum(
                event["type"] == "action" for event in self.events
            )
        }


class PlannerLLMStub:
    def __init__(self, response: str):
        self.response = response
        self.last_call_metadata = {}
        self.calls = 0

    def chat(self, _messages, **kwargs):
        self.calls += 1
        self.last_call_metadata = {
            "provider": "phase128-test-provider",
            "model": "phase128-test-model",
            "request_sha256": "a" * 64,
            "response_sha256": hashlib.sha256(
                self.response.encode("utf-8")
            ).hexdigest(),
            "timeout_s": kwargs.get("timeout_s"),
            "max_retries": 0,
            "finish_reason": "stop",
        }
        return self.response


def _table_stage_progress() -> dict:
    progress = _empty_progress()
    progress.update({
        "log_source_ids": {
            "dark_oak_log:1:64:0",
            "dark_oak_log:1:65:0",
            "dark_oak_log:1:66:0",
        },
        "log_item": "dark_oak_log",
        "plank_craft_count": 1,
        "stick_craft_count": 1,
    })
    return progress


def _table_stage_observation(planks: int = 6) -> dict:
    return {
        "position": {"x": 0.5, "y": 64.0, "z": 0.5},
        "inventory": {"dark_oak_planks": planks, "stick": 4},
        "equipment": [],
        "nearby_blocks": [],
        "nearby_entities": [],
        "health": 20,
        "hunger": 20,
        "game_mode": "survival",
        "dimension": "overworld",
        "ground_block": "grass_block",
    }


def _bare_sp003_agent() -> StonePickaxeSP003RuntimeAgent:
    agent = StonePickaxeSP003RuntimeAgent.__new__(
        StonePickaxeSP003RuntimeAgent
    )
    agent.sp003_arm = "baseline"
    agent.sp003_progress = _table_stage_progress()
    agent.session_logger = LogStub()
    agent.config = SimpleNamespace(
        planner_protocol="stone-pickaxe-skill-fixed-v1",
        enable_action_verification=False,
    )
    agent._episode_deadline_monotonic = None
    agent._sp003_pre_dispatch_replan_fingerprints = set()
    agent._sp003_pre_dispatch_replan_count = 0
    return agent


def test_phase128_long_reasoning_is_bounded_without_rewriting_execution_fields():
    original = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "continuation",
        "goal": SP003_GOAL,
        "status": "planning",
        "reasoning": "R" * 450,
        "subtasks": [],
        "actions": [
            {
                "type": "craft",
                "parameters": {"item": "crafting_table", "count": 1},
            }
        ],
    }
    direct = Planner._validate_stone_pickaxe_plan_envelope(
        copy.deepcopy(original),
        SP003_GOAL,
        "continuation",
        "sp003",
    )
    assert direct["issues"] == ["reasoning_too_long"]

    response = json.dumps(original, separators=(",", ":"))
    llm = PlannerLLMStub(response)
    planner = Planner(
        llm,
        TaskSystem(),
        protocol="stone-pickaxe-skill-fixed-v1",
    )
    planner.start_episode(SP003_GOAL, "phase128-planner")
    planner.set_deadline(time.monotonic() + 60.0, 0.0)
    plan = planner._call_planner(
        SP003_GOAL,
        {"stone_pickaxe_runtime_mode": "sp003"},
        "",
        "continuation",
    )

    assert plan["status"] == original["status"]
    assert plan["subtasks"] == original["subtasks"]
    assert plan["actions"] == original["actions"]
    assert len(plan["reasoning"]) == SP003_REASONING_MAX_CHARS
    assert plan["reasoning"].endswith("...")
    assert plan["schema_validation"]["passed"] is True
    report = plan["schema_validation"]["reasoning_normalization"]
    assert report["policy_id"] == SP003_REASONING_NORMALIZATION_POLICY_ID
    assert report["applied"] is True
    assert report["original_char_count"] == 450
    assert report["normalized_char_count"] == SP003_REASONING_MAX_CHARS
    assert report["original_sha256"] == hashlib.sha256(
        original["reasoning"].encode("utf-8")
    ).hexdigest()
    assert report["normalized_sha256"] == hashlib.sha256(
        plan["reasoning"].encode("utf-8")
    ).hexdigest()
    assert report["executable_fields_preserved"] is True
    assert report["provider_response_preserved"] is True
    assert report["action_rewrite"] is False
    assert planner.last_call_evidence["response_sha256"] == hashlib.sha256(
        response.encode("utf-8")
    ).hexdigest()
    assert planner.last_call_evidence["response_byte_count"] == len(
        response.encode("utf-8")
    )
    assert planner.last_call_evidence["transport_evidence"]["attempt_count"] == 1
    assert planner.last_call_evidence["transport_evidence"]["retry_count"] == 0
    assert llm.calls == 1


def test_phase128_reasoning_at_limit_is_unchanged_and_missing_still_fails_closed():
    plan = {"reasoning": "x" * SP003_REASONING_MAX_CHARS, "actions": []}
    normalized, report = Planner._normalize_sp003_reasoning(plan)
    assert normalized == plan
    assert normalized is not plan
    assert report["applied"] is False
    assert report["original_sha256"] == report["normalized_sha256"]

    missing, missing_report = Planner._normalize_sp003_reasoning(
        {"reasoning": " " * 400}
    )
    assert missing["reasoning"] == " " * 400
    assert missing_report["applied"] is False


def test_phase128_pre_dispatch_replans_once_per_semantic_fingerprint():
    agent = _bare_sp003_agent()
    observation = _table_stage_observation()
    action = {
        "type": "craft",
        "parameters": {"item": "dark_oak_planks", "count": 2},
    }
    original = copy.deepcopy(action)

    first = agent._pre_dispatch_replan_for_action(
        action,
        observation,
        SP003_GOAL,
        {"cycle": 1, "mode": "goal"},
    )
    assert first["requires_replan"] is True
    assert first["policy_id"] == SP003_PRE_DISPATCH_REPLAN_POLICY_ID
    assert action == original
    first_event = agent.session_logger.events[-1]["data"]
    assert first_event["granted"] is True
    assert first_event["guard"]["issues"] == [
        "sp003_exact_one_table_craft_required"
    ]
    assert first_event["action_suppressed_before_dispatch"] is True
    assert first_event["action_budget_consumed"] is False
    assert first_event["backend_invoked"] is False
    assert first_event["world_mutation"] is False
    assert first_event["same_call_retry_count"] == 0

    duplicate = agent._pre_dispatch_replan_for_action(
        action,
        observation,
        SP003_GOAL,
        {"cycle": 2, "mode": "goal"},
    )
    assert duplicate is None
    duplicate_event = agent.session_logger.events[-1]["data"]
    assert duplicate_event["granted"] is False
    assert duplicate_event["limit_reason"] == "fingerprint_limit_exhausted"
    verification, rejection = agent._verify_action_for_execution(
        action,
        observation,
        SP003_GOAL,
    )
    assert verification["status"] == "reject"
    assert rejection["verification_blocked"] is True
    assert rejection["success"] is False


def test_phase128_pre_dispatch_total_bound_and_nonsemantic_safety_rejection():
    agent = _bare_sp003_agent()
    observation = _table_stage_observation()
    for count in range(2, 2 + SP003_PRE_DISPATCH_REPLANS_PER_EPISODE_MAX):
        request = agent._pre_dispatch_replan_for_action(
            {
                "type": "craft",
                "parameters": {"item": "dark_oak_planks", "count": count},
            },
            observation,
            SP003_GOAL,
        )
        assert request["requires_replan"] is True
    exhausted = agent._pre_dispatch_replan_for_action(
        {
            "type": "craft",
            "parameters": {"item": "dark_oak_planks", "count": 99},
        },
        observation,
        SP003_GOAL,
    )
    assert exhausted is None
    assert agent.session_logger.events[-1]["data"]["limit_reason"] == (
        "episode_limit_exhausted"
    )

    unsafe = _bare_sp003_agent()
    unsafe.sp003_progress = _empty_progress()
    wrong_target = unsafe._pre_dispatch_replan_for_action(
        {
            "type": "dig",
            "parameters": {"block": "oak_log", "x": 40, "y": 64, "z": 40},
        },
        _table_stage_observation(),
        SP003_GOAL,
    )
    assert wrong_target is None
    assert unsafe._sp003_pre_dispatch_replan_count == 0


def test_phase128_run_goal_reobserves_without_counting_or_dispatching_bad_action(
    monkeypatch,
):
    class PlannerStub:
        def __init__(self):
            self.replan_reasons = []

        def start_episode(self, _goal, _session_id):
            return None

        def set_deadline(self, _deadline, _guard):
            return None

        def request_replan(self, reason):
            self.replan_reasons.append(reason)

    class ControllerStub:
        def __init__(self):
            self.calls = []

        def execute(self, action, _observation):
            self.calls.append(copy.deepcopy(action))
            return {"success": True}

    class TasksStub:
        def get_next_task(self, _state):
            return None

    class RuntimeStub:
        def evaluate_interrupt(self, _observation, *, goal, active_task):
            return SimpleNamespace(
                should_interrupt=False,
                reason="",
                goal=goal,
                active_task=active_task,
            )

    class ExplorerStub:
        def record_position(self, _position):
            return None

    class RuntimeFixture(StonePickaxeSP003RuntimeAgent):
        def __init__(self):
            self.config = SimpleNamespace(
                planner_protocol="stone-pickaxe-skill-fixed-v1",
                health_critical_threshold=4.0,
                enable_action_candidate_selection=False,
                enable_action_verification=False,
            )
            self.planner = PlannerStub()
            self.action_controller = ControllerStub()
            self.session_logger = LogStub()
            self.task_system = TasksStub()
            self.runtime = RuntimeStub()
            self.explorer = ExplorerStub()
            self.current_goal = ""
            self.running = False
            self._episode_deadline_monotonic = None
            self._last_plan_cache_signature = ""
            self._skill_episode_start_index = 0
            self._active_skill_execution = {}
            self._skill_fallback_goals = set()
            self._m2_root_plan_valid = False
            self._m2_skill_contribution_complete = False
            self.sp003_arm = "baseline"
            self.sp003_progress = _table_stage_progress()
            self.sp003_local_attributions = []
            self.observation_count = 0
            self.plan_count = 0

        def _observe(self):
            self.observation_count += 1
            return _table_stage_observation()

        def _think(self, _observation, override_goal=None):
            self.plan_count += 1
            item = "dark_oak_planks" if self.plan_count == 1 else "crafting_table"
            count = 2 if self.plan_count == 1 else 1
            plan = {
                "status": "planning",
                "reasoning": "phase128 fixture",
                "actions": [
                    {"type": "craft", "parameters": {"item": item, "count": count}}
                ],
            }
            self._sp003_pending_pre_dispatch_action = copy.deepcopy(
                plan["actions"][0]
            )
            return plan

        def _goal_is_verified(
            self,
            goal,
            _observation,
            context=None,
            recent_actions=None,
        ):
            achieved = bool(self.action_controller.calls)
            return achieved, GoalVerification(
                goal=goal,
                achieved=achieved,
                status="passed" if achieved else "failed",
            )

        def _accept_planned_tasks(self):
            return None

        def _record_task_continuity(self, *args, **kwargs):
            return None

        def _state_with_causal_context(self, observation, _goal):
            return observation

        def _record_m4_hostile_safe_state_grounding(self, *args, **kwargs):
            return None

        def _record_action_value(self, *args, **kwargs):
            return None

        def _apply_action_feedback(self, _action, _result, observation, _context):
            return observation

        def _log_action_event(self, action, result, **kwargs):
            self.session_logger.log(
                "action",
                {"action": action, "result": result, **kwargs},
            )

        def _record_skill_usage(self, *args, **kwargs):
            return None

        def _evaluate_episode_abort(self, *args, **kwargs):
            return False

        def _write_memory_episode(self, *args, **kwargs):
            return None

        def _write_memory_context(self, *args, **kwargs):
            return None

        def _complete_verified_m2_task_paths(self, *args, **kwargs):
            return []

        def _finalize_skill_learning_episode(self, *args, **kwargs):
            return None

    monkeypatch.setattr("singularity.core.agent.time.sleep", lambda _seconds: None)
    agent = RuntimeFixture()
    result = agent.run_goal(SP003_GOAL, max_cycles=3, max_actions=2)

    assert result["completed"] is True
    assert result["action_count"] == 1
    assert agent.observation_count == 2
    assert agent.plan_count == 2
    assert agent.planner.replan_reasons and len(agent.planner.replan_reasons) == 1
    assert agent.action_controller.calls == [
        {
            "type": "craft",
            "parameters": {"item": "crafting_table", "count": 1},
        }
    ]
    generic = next(
        event["data"]
        for event in agent.session_logger.events
        if event["type"] == "action_pre_dispatch_replan"
    )
    assert generic["action_count_before"] == 0
    assert generic["action_budget_consumed"] is False
    assert generic["backend_invoked"] is False
    assert generic["same_call_retry_count"] == 0
    assert generic["resume_policy"] == "fresh_observation_next_planner_cycle"
    action_events = [
        event for event in agent.session_logger.events if event["type"] == "action"
    ]
    assert len(action_events) == 1


def test_phase128_policy_and_phase127_evidence_remain_bound():
    identity = verify_sp003_policy_identity()
    assert identity["passed"], identity
    assert identity["checks"]["planner_reasoning_normalization_contract"] is True
    assert identity["checks"]["pre_dispatch_semantic_replan_contract"] is True

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    retained = next(
        failure
        for failure in ledger["failures"]
        if failure["id"]
        == "sp003-baseline-026-stage-action-and-reasoning-envelope"
    )
    assert hashlib.sha256((PHASE127_RUN / "manifest.json").read_bytes()).hexdigest() == (
        "de2d72cd3963224106aba081e8a13d71c9a7ca1c65857f7fb16546d2d6bba9a2"
    )
    for record in retained["evidence"]:
        path = REPO / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase128_audit_binds_implementation_and_protected_identities():
    audit = json.loads(PHASE128_AUDIT.read_text(encoding="utf-8"))
    assert audit["phase"] == 128
    assert audit["base_commit"] == (
        "e84155054003185cad1b84e24b06afbf8d860c38"
    )
    assert audit["policy_ids"] == [
        SP003_REASONING_NORMALIZATION_POLICY_ID,
        SP003_PRE_DISPATCH_REPLAN_POLICY_ID,
    ]
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["behavioral_empty_hand_to_stone_pickaxe_loop_completed"] is False
    assert audit["strict_sp003_baseline_passed"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
    evolved_paths = {
        "src/singularity/core/agent.py",
        "src/singularity/core/planner.py",
        "src/singularity/evaluation/stone_pickaxe_sp003_runtime.py",
        "src/singularity/evaluation/stone_pickaxe_sp003_phase122_runtime.py",
        "tests/test_stone_pickaxe_sp003_phase126_target_source_grounding.py",
        "tests/test_stone_pickaxe_sp003_phase128_pre_dispatch_reasoning.py",
        "workspace/evals/stone_pickaxe_sp003_harness_policy.json",
    }
    for record in [
        *audit["implementation"],
        *audit["protected_identities"],
        *audit["retained_phase_127_identities"],
    ]:
        if record["path"] in evolved_paths:
            retained = subprocess.check_output(
                [
                    "git",
                    "show",
                    f"599fc76e2210cbe2ef925be715d83c225ffade33:{record['path']}",
                ],
                cwd=REPO,
            )
        else:
            retained = (REPO / record["path"]).read_bytes()
        assert hashlib.sha256(retained).hexdigest() == record["sha256"]
