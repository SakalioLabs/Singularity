from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from singularity.core.agent import Agent
from singularity.core.goal_verifier import GoalVerification
from singularity.evaluation.stone_pickaxe_sp003_phase122_runtime import (
    SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
    StonePickaxeSP003Phase122RuntimeAgent,
)
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    SP003_ACTIONLESS_PLANNING_REPLAN_POLICY_ID,
    SP003_ACTIONLESS_PLANNING_REPLANS_PER_EPISODE_MAX,
    SP003_EFFECTIVE_GUARD_DISPATCH_POLICY_ID,
    SP003_GOAL,
    guard_sp003_action,
    verify_sp003_policy_identity,
)


REPO = Path(__file__).resolve().parents[1]
RUN_DIR = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_081826_aeafcafc"
)
AUDIT_PATH = (
    REPO
    / "workspace/evals/stone_pickaxe_sp003_effective_guard_actionless_replan_repair.json"
)


class LogStub:
    def __init__(self):
        self.events = []
        self.session_id = "phase130-test-session"

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


def _events():
    return json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))


def _terminal_observation():
    return copy.deepcopy(
        [event["data"] for event in _events() if event.get("type") == "observation"][-1]
    )


def _phase129_false_replan_case():
    events = _events()
    for index, event in enumerate(events):
        if (
            event.get("type") == "stone_pickaxe_sp003_pre_dispatch_replan"
            and event["data"].get("granted") is True
        ):
            observation = next(
                prior["data"]
                for prior in reversed(events[:index])
                if prior.get("type") == "observation"
            )
            return (
                copy.deepcopy(observation),
                copy.deepcopy(event["data"]["guard"]["action"]),
            )
    raise AssertionError("Phase 129 granted pre-dispatch event not found")


def _actionless_plan(call_id="llm-phase130-actionless"):
    validation = {
        "type": "stone_pickaxe_plan_envelope_validation",
        "schema_version": 1,
        "passed": False,
        "status": "planning",
        "action_count": 0,
        "issues": ["planning_action_count_must_equal_one"],
    }
    return {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "continuation",
        "goal": SP003_GOAL,
        "status": "error",
        "reasoning": (
            "Planner output rejected before execution: "
            "planning_action_count_must_equal_one"
        ),
        "subtasks": [],
        "actions": [],
        "planner_call_id": call_id,
        "schema_validation": validation,
        "planner_evidence": {
            "real_llm_call": True,
            "schema_valid": False,
            "response_sha256": "a" * 64,
            "schema_validation": copy.deepcopy(validation),
        },
    }


def _bare_phase122_agent(observation):
    agent = StonePickaxeSP003Phase122RuntimeAgent.__new__(
        StonePickaxeSP003Phase122RuntimeAgent
    )
    agent.sp003_arm = "baseline"
    agent.sp003_progress = copy.deepcopy(observation["sp003_progress"])
    agent._sp003_phase120_egress_attempted_fingerprints = set()
    agent._sp003_pre_dispatch_replan_fingerprints = set()
    agent._sp003_pre_dispatch_replan_count = 0
    agent._sp003_actionless_replan_fingerprints = set()
    agent._sp003_actionless_replan_count = 0
    agent.session_logger = LogStub()
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent.replan_reasons = []
    agent._request_m2_replan = agent.replan_reasons.append
    return agent


def test_phase130_pre_dispatch_uses_the_phase122_effective_guard():
    observation, action = _phase129_false_replan_case()
    agent = _bare_phase122_agent(observation)

    base_guard = guard_sp003_action(
        action,
        observation,
        agent.sp003_progress,
        arm="baseline",
    )
    effective_guard = agent._effective_sp003_action_guard(action, observation)

    assert base_guard["allowed"] is False
    assert base_guard["issues"] == [
        "sp003_action_forbidden_for_stage:prepare_wooden_pickaxe:dig"
    ]
    assert effective_guard["allowed"] is True
    assert effective_guard["policy_id"] == SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID
    assert agent._pre_dispatch_replan_for_action(
        action,
        observation,
        SP003_GOAL,
        {"cycle": 8, "mode": "goal"},
    ) is None
    assert not any(
        event["type"] == "stone_pickaxe_sp003_pre_dispatch_replan"
        for event in agent.session_logger.events
    )


def test_phase130_actionless_replan_is_exact_bounded_and_fail_closed():
    observation = _terminal_observation()
    agent = _bare_phase122_agent(observation)
    plan = _actionless_plan()

    assert agent._recover_actionless_plan(
        plan,
        observation,
        SP003_GOAL,
        {"cycle": 13, "mode": "goal"},
    ) is True
    assert agent._sp003_actionless_replan_count == 1
    assert len(agent.replan_reasons) == 1

    assert agent._recover_actionless_plan(
        plan,
        observation,
        SP003_GOAL,
        {"cycle": 14, "mode": "goal"},
    ) is False
    reports = [
        event["data"]
        for event in agent.session_logger.events
        if event["type"] == "stone_pickaxe_sp003_actionless_planning_replan"
    ]
    assert [report["granted"] for report in reports] == [True, False]
    assert reports[1]["limit_reason"] == "fingerprint_limit_exhausted"
    assert reports[0]["action_budget_consumed"] is False
    assert reports[0]["backend_invoked"] is False
    assert reports[0]["world_mutation"] is False
    assert reports[0]["same_call_retry_count"] == 0
    assert reports[0]["action_rewrite"] is False

    different = copy.deepcopy(observation)
    different["sp003_targets"][0]["source_id"] = "phase130:second-target"
    assert agent._recover_actionless_plan(
        _actionless_plan("llm-phase130-second"),
        different,
        SP003_GOAL,
        {"cycle": 15, "mode": "goal"},
    ) is True
    exhausted = copy.deepcopy(observation)
    exhausted["sp003_targets"][0]["source_id"] = "phase130:third-target"
    assert agent._recover_actionless_plan(
        _actionless_plan("llm-phase130-third"),
        exhausted,
        SP003_GOAL,
        {"cycle": 16, "mode": "goal"},
    ) is False
    assert agent._sp003_actionless_replan_count == (
        SP003_ACTIONLESS_PLANNING_REPLANS_PER_EPISODE_MAX
    )
    assert [
        event["data"]["limit_reason"]
        for event in agent.session_logger.events
        if event["type"] == "stone_pickaxe_sp003_actionless_planning_replan"
    ][-1] == "episode_limit_exhausted"

    ineligible = _bare_phase122_agent(observation)
    wrong_issue = _actionless_plan("llm-phase130-wrong-issue")
    wrong_issue["schema_validation"]["issues"] = ["reasoning_too_long"]
    assert ineligible._recover_actionless_plan(
        wrong_issue,
        observation,
        SP003_GOAL,
        {"cycle": 17, "mode": "goal"},
    ) is False
    assert ineligible._sp003_actionless_replan_count == 0
    assert ineligible.session_logger.events == []


def test_phase130_non_sp003_agent_keeps_actionless_plan_fail_closed():
    agent = Agent.__new__(Agent)
    assert agent._recover_actionless_plan(
        _actionless_plan(),
        _terminal_observation(),
        SP003_GOAL,
        {"cycle": 1, "mode": "goal"},
    ) is False


def test_phase130_run_goal_reobserves_then_executes_without_hidden_action():
    observation = _terminal_observation()
    target = observation["sp003_table_staging"]["target"]["stand_position"]

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

    class RuntimeFixture(StonePickaxeSP003Phase122RuntimeAgent):
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
            self.explorer = SimpleNamespace(record_position=lambda _position: None)
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
            self.sp003_progress = copy.deepcopy(observation["sp003_progress"])
            self.sp003_local_attributions = []
            self._sp003_phase120_egress_attempted_fingerprints = set()
            self.observation_count = 0
            self.plan_count = 0

        def _observe(self):
            self.observation_count += 1
            return copy.deepcopy(observation)

        def _think(self, _observation, override_goal=None):
            self.plan_count += 1
            if self.plan_count == 1:
                plan = _actionless_plan()
            else:
                plan = {
                    "status": "planning",
                    "reasoning": "use the current machine target",
                    "actions": [
                        {
                            "type": "move_to",
                            "parameters": copy.deepcopy(target),
                        }
                    ],
                }
            actions = plan.get("actions") or []
            self._sp003_pending_pre_dispatch_action = (
                copy.deepcopy(actions[0]) if len(actions) == 1 else None
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

        def _state_with_causal_context(self, current, _goal):
            return current

        def _record_m4_hostile_safe_state_grounding(self, *args, **kwargs):
            return None

        def _record_action_value(self, *args, **kwargs):
            return None

        def _apply_action_feedback(self, _action, _result, current, _context):
            return current

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

    agent = RuntimeFixture()
    result = agent.run_goal(SP003_GOAL, max_cycles=3, max_actions=2)

    assert result["completed"] is True
    assert result["action_count"] == 1
    assert agent.observation_count == 2
    assert agent.plan_count == 2
    assert len(agent.planner.replan_reasons) == 1
    assert len(agent.action_controller.calls) == 1
    assert agent.action_controller.calls[0]["type"] == "move_to"
    assert not any(
        event["type"] == "empty_plan" for event in agent.session_logger.events
    )
    generic = next(
        event["data"]
        for event in agent.session_logger.events
        if event["type"] == "actionless_plan_replan"
    )
    assert generic["policy_id"] == SP003_ACTIONLESS_PLANNING_REPLAN_POLICY_ID
    assert generic["action_count_before"] == 0
    assert generic["action_budget_consumed"] is False
    assert generic["backend_invoked"] is False
    assert generic["resume_policy"] == "fresh_observation_next_planner_cycle"

    class DuplicateFixture(RuntimeFixture):
        def _think(self, _observation, override_goal=None):
            self.plan_count += 1
            self._sp003_pending_pre_dispatch_action = None
            return _actionless_plan("llm-phase130-duplicate")

    duplicate = DuplicateFixture()
    failed = duplicate.run_goal(SP003_GOAL, max_cycles=3, max_actions=2)
    assert failed["completed"] is False
    assert failed["termination_reason"] == "empty_plan"
    assert failed["action_count"] == 0
    assert duplicate.observation_count == 2
    assert duplicate.plan_count == 2
    assert duplicate.action_controller.calls == []
    duplicate_reports = [
        event["data"]
        for event in duplicate.session_logger.events
        if event["type"] == "stone_pickaxe_sp003_actionless_planning_replan"
    ]
    assert [report["granted"] for report in duplicate_reports] == [True, False]
    assert duplicate_reports[-1]["limit_reason"] == "fingerprint_limit_exhausted"
    assert sum(
        event["type"] == "actionless_plan_replan"
        for event in duplicate.session_logger.events
    ) == 1
    assert sum(
        event["type"] == "empty_plan" for event in duplicate.session_logger.events
    ) == 1


def test_phase130_policy_contracts_are_machine_bound():
    identity = verify_sp003_policy_identity()
    assert identity["passed"], identity
    assert identity["checks"]["effective_runtime_guard_dispatch_contract"] is True
    assert identity["checks"]["actionless_planning_replan_contract"] is True

    policy = json.loads(
        (
            REPO / "workspace/evals/stone_pickaxe_sp003_harness_policy.json"
        ).read_text(encoding="utf-8")
    )
    contract = policy["episode_contract"]
    assert contract["effective_runtime_guard_dispatch_policy_id"] == (
        SP003_EFFECTIVE_GUARD_DISPATCH_POLICY_ID
    )
    assert contract["actionless_planning_replan_policy_id"] == (
        SP003_ACTIONLESS_PLANNING_REPLAN_POLICY_ID
    )


def test_phase130_audit_binds_implementation_and_retained_failure():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert audit["phase"] == 130
    assert audit["base_commit"] == (
        "f9bd709cbcf5f80ca82c6d055a5a58c296c5383e"
    )
    assert audit["policy_ids"] == [
        SP003_EFFECTIVE_GUARD_DISPATCH_POLICY_ID,
        SP003_ACTIONLESS_PLANNING_REPLAN_POLICY_ID,
    ]
    assert audit["status"] == "offline_verified"
    assert audit["retained_phase_129_failure"]["manifest_sha256"] == (
        "32e7c5c67088f2c03d66c8603ab0cc6cf7386d35e0abf637ab99d24bdfbe9fc2"
    )
    assert audit["counterfactual_tests"]["focused_cases"] == "6/6"
    assert audit["repair_contract"]["action_rewrite_allowed"] is False
    assert audit["repair_contract"]["same_call_retry_allowed"] is False
    assert audit["repair_contract"]["backend_invocation_on_replan"] is False
    assert audit["repair_contract"]["action_budget_consumed_on_replan"] is False
    assert audit["repair_contract"]["non_sp003_behavior_unchanged"] is True
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_skill_gate"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
    evolved_paths = {
        "src/singularity/evaluation/stone_pickaxe_sp003_runtime.py",
        "tests/test_stone_pickaxe_sp003_phase130_replan_dispatch.py",
        "workspace/evals/stone_pickaxe_sp003_harness_policy.json",
    }
    for record in [
        *audit["implementation"],
        *audit["protected_identities"],
        *audit["retained_phase_129_identities"],
    ]:
        if record["path"] in evolved_paths:
            retained = subprocess.check_output(
                [
                    "git",
                    "show",
                    f"a7f8cc140a2bc7b037595a980f6ef8512370c9f1:{record['path']}",
                ],
                cwd=REPO,
            )
        else:
            retained = (REPO / record["path"]).read_bytes()
        assert hashlib.sha256(retained).hexdigest() == record["sha256"]
