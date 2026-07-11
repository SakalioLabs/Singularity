"""Unit tests for runtime interrupt supervision."""
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.runtime import RuntimeSupervisor
from singularity.core.task_system import TaskStatus, TaskSystem


class FakeExplorer:
    landmarks = []

    def should_return(self, position, inventory_count):
        return inventory_count >= 36, "Inventory full"

    def get_return_direction(self, position):
        return {"x": 0, "z": 0}

    def record_position(self, position):
        pass

    def set_base(self, x, y, z):
        self.base = (x, y, z)


class FakeLogger:
    def __init__(self):
        self.events = []
        self.actions = []
        self.observations = []
        self.session_id = "runtime-supervisor-fixture"

    def log(self, event_type, data, level="INFO"):
        self.events.append({"type": event_type, "data": data, "level": level})

    def log_action(self, action, result):
        self.actions.append({"action": action, "result": result})

    def log_observation(self, observation):
        self.observations.append(observation)
        self.log("observation", observation)

    def log_plan(self, plan):
        self.log("plan", plan)

    def log_goal_start(self, goal):
        self.log("goal_start", {"goal": goal})

    def log_goal_end(self, goal, result):
        self.log("goal_end", {"goal": goal, "result": result})

    def log_error(self, error, context=None):
        self.log("error", {"error": error, "context": context or {}}, level="ERROR")

    def get_summary(self):
        return {"event_count": len(self.events)}


class FakeMemory:
    def __init__(self):
        self.episodes = []
        self.contexts = []

    def write_episode(self, event_type, data):
        self.episodes.append({"type": event_type, "data": data})

    def write_context(self, data):
        self.contexts.append(data)


class FakeActionController:
    def __init__(self):
        self.actions = []
        self.deadline_calls = []

    def execute(self, action, observation):
        self.actions.append(action)
        return {"success": True, "action_type": action.get("type")}

    def set_episode_deadline(self, deadline_monotonic, action_timeout_limit_s=None):
        self.deadline_calls.append((deadline_monotonic, action_timeout_limit_s))


class FakeObserver:
    def observe(self):
        return {"health": 20, "inventory": {}, "inventory_count": 0, "nearby_entities": [], "position": {}}


class FakeGoalGenerator:
    last_decision = {
        "selection_source": "goal_generator",
        "selection_reason": "wood_reserve_below_target",
        "priority": 6,
        "priority_class": "tool_resource_progression",
    }

    def next_goal(self, observation):
        return "Gather 6 oak logs for tools and shelter"


class FakeCurriculum:
    def __init__(self):
        self.outcomes = []

    def record_goal_outcome(self, goal, success, cycles):
        self.outcomes.append((goal, success, cycles))

    def summary(self):
        return {"outcome_count": len(self.outcomes)}


def runtime_agent(config=None):
    config = config or Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.task_system = TaskSystem()
    agent.runtime = RuntimeSupervisor(config)
    agent.session_logger = FakeLogger()
    agent.memory = FakeMemory()
    agent.action_controller = FakeActionController()
    agent.observer = FakeObserver()
    agent.explorer = FakeExplorer()
    return agent


def test_runtime_interrupts_on_health_and_hostiles():
    supervisor = RuntimeSupervisor(Config())

    health = supervisor.evaluate_interrupt({"health": 1, "inventory": {"bread": 1}, "nearby_entities": []})
    assert health.should_interrupt
    assert health.reason == "health_critical"
    assert health.emergency_action["type"] == "use_item"

    hostile = supervisor.evaluate_interrupt({
        "health": 20,
        "inventory": {"stone_sword": 1},
        "nearby_entities": [{"type": "zombie", "hostile": True, "distance": 4}],
    })
    assert hostile.should_interrupt
    assert hostile.reason == "hostile_nearby"
    assert hostile.emergency_action["parameters"]["item"] == "stone_sword"
    print("PASS: RuntimeSupervisor interrupts health and hostile threats")


def test_runtime_interrupts_deadlines_and_return_to_base():
    tasks = TaskSystem()
    task = tasks.create_task(
        "Reach shelter before night",
        status=TaskStatus.ACCEPTED,
        deadline=time.time() - 1,
    )
    supervisor = RuntimeSupervisor(Config(), FakeExplorer())

    deadline = supervisor.evaluate_interrupt({"health": 20, "inventory": {}, "nearby_entities": []}, active_task=task)
    assert deadline.should_interrupt
    assert deadline.reason == "task_deadline_elapsed"
    assert deadline.evidence["deadline_wallclock"] == task.deadline
    assert deadline.evidence["evaluated_at_wallclock"] >= task.deadline

    returning = supervisor.evaluate_interrupt({
        "health": 20,
        "inventory": {},
        "inventory_count": 36,
        "nearby_entities": [],
        "position": {"x": 40, "z": 40},
    })
    assert returning.should_interrupt
    assert returning.reason == "return_to_base"
    assert returning.emergency_action["type"] == "move_to"
    print("PASS: RuntimeSupervisor interrupts deadlines and return-to-base")


def test_agent_handles_runtime_interrupt_with_emergency_action():
    agent = runtime_agent()

    interrupted, observation = agent._handle_runtime_interrupt(
        {"health": 1, "inventory": {"bread": 1}, "inventory_count": 1, "nearby_entities": [], "position": {}},
        "Gather wood",
        {"cycle": 1},
    )

    assert interrupted
    assert observation["health"] == 20
    assert agent.session_logger.events[0]["type"] == "runtime_interrupt"
    assert agent.action_controller.actions[0]["type"] == "use_item"
    assert any(event["type"] == "runtime_emergency_action" for event in agent.memory.episodes)
    print("PASS: Agent handles runtime interrupt and emergency action")


def test_agent_expires_all_overdue_tasks_and_interrupts_once():
    agent = runtime_agent()
    now = time.time()
    trigger = agent.task_system.create_task(
        "Find and move to oak logs",
        status=TaskStatus.ACTIVE,
        priority=1,
        deadline=now - 2,
    )
    stale = agent.task_system.create_task(
        "Move to oak log",
        status=TaskStatus.ACCEPTED,
        priority=2,
        deadline=now - 1,
    )
    future = agent.task_system.create_task(
        "Gather another oak log",
        status=TaskStatus.ACCEPTED,
        priority=3,
        deadline=now + 60,
    )
    agent.task_system.drain_transition_events()
    observation = {
        "health": 20,
        "inventory": {"oak_log": 1},
        "inventory_count": 1,
        "nearby_entities": [],
        "position": {"x": 103, "y": 140, "z": -28},
    }

    interrupted, _ = agent._handle_runtime_interrupt(
        observation,
        "Gather 6 oak logs for tools and shelter",
        {"cycle": 6, "mode": "autonomous"},
    )

    assert interrupted
    assert trigger.status == TaskStatus.FAILED
    assert stale.status == TaskStatus.FAILED
    assert future.status == TaskStatus.ACCEPTED
    assert trigger.result["failed_by"] == "task_deadline_elapsed"
    assert stale.result["failed_by"] == "task_deadline_elapsed"
    transitions = [event for event in agent.session_logger.events if event["type"] == "task_state_transition"]
    assert len(transitions) == 2
    assert all(event["data"]["reason"] == "task_deadline_elapsed" for event in transitions)
    recovery = next(event for event in agent.session_logger.events if event["type"] == "runtime_interrupt_recovery")
    assert recovery["data"]["trigger_task_id"] == trigger.id
    assert recovery["data"]["expired_task_count"] == 2
    assert set(recovery["data"]["expired_task_ids"]) == {trigger.id, stale.id}
    assert recovery["data"]["resume_policy"] == "replan_next_cycle"
    assert recovery["data"]["recovered"] is True

    repeated, _ = agent._handle_runtime_interrupt(
        observation,
        "Gather 6 oak logs for tools and shelter",
        {"cycle": 7, "mode": "autonomous"},
    )
    assert not repeated
    interrupts = [event for event in agent.session_logger.events if event["type"] == "runtime_interrupt"]
    assert len(interrupts) == 1
    print("PASS: Agent expires every overdue task and does not repeat the interrupt")


def test_autonomous_loop_replans_once_then_resumes_actions():
    agent = runtime_agent(Config(planner_protocol="m4-fixed-v1"))
    agent.goal_generator = FakeGoalGenerator()
    agent.curriculum = FakeCurriculum()
    agent.planner = None
    class CountingReflector:
        def __init__(self):
            self.calls = []

        def analyze_failure(self, goal, action, result, state):
            self.calls.append((goal, action, result, state))
            return {"analysis": "fixture reflection"}

    agent.reflector = CountingReflector()
    agent._use_llm = True
    agent._active_skill_execution = {}
    agent._skill_fallback_goals = set()
    agent._skill_episode_start_index = 0
    observation = {
        "health": 20,
        "hunger": 20,
        "inventory": {"oak_log": 1},
        "inventory_count": 1,
        "nearby_entities": [],
        "position": {"x": 103, "y": 140, "z": -28},
    }
    agent._observe = lambda: dict(observation)
    agent._select_autonomous_goal = lambda state, fallback: fallback
    plan_calls = []

    def plan(state, override_goal=None):
        plan_calls.append(override_goal)
        if len(plan_calls) == 1:
            deadline = time.time() - 1
            agent.task_system.create_task(
                "Expired active route",
                status=TaskStatus.PROPOSED,
                priority=1,
                deadline=deadline,
            )
            agent.task_system.create_task(
                "Expired accepted route",
                status=TaskStatus.PROPOSED,
                priority=2,
                deadline=deadline,
            )
        return {
            "status": "planning",
            "reasoning": "continue gathering after task recovery",
            "actions": [{"type": "wait", "parameters": {"ms": 1}}],
        }

    agent._think = plan
    action_results = [
        {"success": False, "action_type": "wait", "error": "fixture action failure"},
        {"success": True, "action_type": "wait"},
    ]

    def execute(action, state):
        agent.action_controller.actions.append(action)
        return action_results.pop(0)

    agent.action_controller.execute = execute
    agent._record_task_continuity = lambda *args, **kwargs: None
    agent._state_with_causal_context = lambda state, goal="": state
    agent._goal_is_verified = lambda *args, **kwargs: (False, None)
    agent._select_action_for_execution = lambda action, *args, **kwargs: (action, None)
    agent._verify_action_for_execution = lambda *args, **kwargs: (None, None)
    agent._record_action_value = lambda *args, **kwargs: None
    agent._apply_action_feedback = lambda action, result, state, context=None: state
    agent._attempt_failure_correction = lambda *args, **kwargs: (False, observation)
    agent._record_skill_usage = lambda *args, **kwargs: None
    agent._evaluate_episode_abort = lambda *args, **kwargs: False
    agent._record_frontier_budget_outcome = lambda *args, **kwargs: None
    agent._finalize_skill_learning_episode = lambda *args, **kwargs: None
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent._write_memory_context = lambda *args, **kwargs: None

    with patch("singularity.core.agent.time.sleep", lambda _seconds: None):
        result = agent.run_autonomous(
            max_goals=1,
            max_cycles_per_goal=3,
            max_duration_s=30.0,
        )

    event_types = [event["type"] for event in agent.session_logger.events]
    assert len(plan_calls) == 3
    assert len(agent.action_controller.actions) == 2
    assert agent.action_controller.actions[0]["type"] == "wait"
    assert agent.reflector.calls == []
    assert event_types.count("runtime_interrupt") == 1
    assert event_types.count("runtime_interrupt_recovery") == 1
    assert event_types.count("failure_reflection_suppressed") == 1
    assert event_types.count("action") == 2
    suppression = next(
        event["data"]
        for event in agent.session_logger.events
        if event["type"] == "failure_reflection_suppressed"
    )
    assert suppression["reason"] == "m4_fixed_profile_immediate_replan"
    assert suppression["context"] == {"cycle": 2, "mode": "autonomous"}
    assert suppression["action"]["type"] == "wait"
    assert suppression["error"] == "fixture action failure"
    assert suppression["episode_deadline_monotonic"] is not None
    assert all(task.status == TaskStatus.FAILED for task in agent.task_system.tasks.values())
    assert result["total_cycles"] == 3
    print("PASS: Autonomous loop recovers tasks, suppresses reflection, and resumes actions")


def test_non_m4_reflection_behavior_is_preserved():
    agent = runtime_agent()
    agent._use_llm = True

    class CountingReflector:
        def __init__(self):
            self.calls = []

        def analyze_failure(self, goal, action, result, state):
            self.calls.append((goal, action, result, state))
            return {"analysis": "non-M4 reflection", "should_retry": True}

    agent.reflector = CountingReflector()
    reflection = agent._reflect(
        {"health": 20},
        {"type": "wait", "parameters": {"ms": 1}},
        {"success": False, "error": "fixture"},
        "Explore",
    )

    assert reflection["analysis"] == "non-M4 reflection"
    assert len(agent.reflector.calls) == 1
    print("PASS: Non-M4 profiles retain LLM failure reflection")


if __name__ == "__main__":
    test_runtime_interrupts_on_health_and_hostiles()
    test_runtime_interrupts_deadlines_and_return_to_base()
    test_agent_handles_runtime_interrupt_with_emergency_action()
    test_agent_expires_all_overdue_tasks_and_interrupts_once()
    test_autonomous_loop_replans_once_then_resumes_actions()
    test_non_m4_reflection_behavior_is_preserved()
    print("\nRuntime supervisor tests PASSED")
