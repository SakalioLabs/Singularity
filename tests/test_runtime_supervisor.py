"""Unit tests for runtime interrupt supervision."""
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.goal_generator import GoalGenerator
from singularity.core.runtime import RuntimeSupervisor
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.evaluation.m4_shelter import (
    M4_SHELTER_CONTRACT_SHA256,
    M4_SHELTER_REQUIRED_CHECKS,
    M4_SHELTER_VERIFIER_ID,
)


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


def verified_shelter_report(player_cell=None, nearby_hostile_count=0):
    player_cell = dict(player_cell or {"x": 0, "y": 64, "z": 0})
    return {
        "type": "m4_shelter_state_verification",
        "schema_version": 1,
        "verifier_id": M4_SHELTER_VERIFIER_ID,
        "contract_sha256": M4_SHELTER_CONTRACT_SHA256,
        "source": "machine_state",
        "strategy": "sealed_cell_v1",
        "passed": True,
        "safe_state": True,
        "issues": [],
        "checks": [{"name": "machine_snapshot", "passed": True}] + [
            {"name": name, "passed": True}
            for name in M4_SHELTER_REQUIRED_CHECKS
        ],
        "episode_block_delta": {
            "required_position_count": 9,
            "matched_position_count": 9,
        },
        "coordinate_evidence": {
            "player_position": dict(player_cell),
            "player_cell": player_cell,
            "entrance": {
                "state": "fully_sealed",
                "sealed_boundary_columns": [{}, {}, {}, {}],
            },
        },
        "hostile_path_risk": {
            "method": "complete_local_collision_enclosure",
            "direct_reachability": "blocked",
            "nearby_hostile_count": nearby_hostile_count,
            "hostiles_inside": [],
        },
    }


def probe_13_verified_shelter_hostile_state():
    player_cell = {"x": 107, "y": 140, "z": -29}
    return {
        "health": 20,
        "hunger": 20,
        "inventory": {"oak_planks": 3, "oak_log": 5},
        "inventory_count": 8,
        "equipment": [],
        "position": {"x": 107.50014079218245, "y": 140, "z": -28.400022268365202},
        "time_of_day": 21672,
        "nearby_entities": [{
            "id": 1789,
            "type": "skeleton",
            "distance": 5.1,
            "hostile": True,
            "position": {"x": 110.52123561046339, "y": 136, "z": -27.273706617652422},
        }],
        "shelter_verification": verified_shelter_report(player_cell, nearby_hostile_count=1),
    }


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


def test_m4_runtime_interrupt_priority_matrix_and_grounded_actions():
    supervisor = RuntimeSupervisor(Config())
    base = {
        "health": 20,
        "hunger": 20,
        "inventory": {},
        "equipment": [],
        "nearby_entities": [],
        "position": {"x": 0, "y": 64, "z": 0},
        "time_of_day": 5000,
    }

    hostile_state = dict(base, inventory={"stone_sword": 1}, nearby_entities=[{
        "id": 17,
        "type": "zombie",
        "hostile": True,
        "distance": 4,
        "position": {"x": 4, "y": 64, "z": 0},
    }])
    hostile = supervisor.evaluate_interrupt(hostile_state)
    assert hostile.reason == "hostile_nearby"
    assert hostile.priority == 120
    assert hostile.emergency_action["type"] == "equip"

    armed = supervisor.evaluate_interrupt(dict(hostile_state, equipment=[{"name": "stone_sword"}]))
    assert armed.emergency_action == {"type": "attack", "parameters": {"entity_id": 17}}

    flee = supervisor.evaluate_interrupt(dict(hostile_state, inventory={}))
    assert flee.emergency_action["type"] == "move_to"
    assert flee.emergency_action["parameters"]["x"] < 0

    health = supervisor.evaluate_interrupt(dict(base, health=2, inventory={"bread": 1}))
    assert health.reason == "health_critical"
    assert health.emergency_action["type"] == "use_item"

    hunger = supervisor.evaluate_interrupt(dict(base, hunger=5, inventory={"bread": 1}))
    assert hunger.reason == "hunger_critical"
    assert hunger.emergency_action["type"] == "use_item"

    dusk = supervisor.evaluate_interrupt(dict(base, time_of_day=11000))
    assert dusk.reason == "dusk_shelter_required"
    assert dusk.recommended_goal == "Build verified shelter before nightfall"

    night = supervisor.evaluate_interrupt(dict(
        base,
        time_of_day=15000,
        shelter_verification=verified_shelter_report(),
    ))
    assert night.reason == "night_safety_maintenance"
    assert night.recommended_goal == "Remain in verified shelter until dawn"

    combined = supervisor.evaluate_interrupt(dict(hostile_state, health=1, hunger=1, time_of_day=15000))
    assert combined.reason == "hostile_nearby"
    assert not supervisor.goal_is_aligned(
        "dusk_shelter_required",
        "Gather 6 oak logs for tools and shelter",
    )
    assert supervisor.goal_is_aligned(
        "night_shelter_required",
        "Build verified shelter before nightfall",
    )
    print("PASS: G4 priority matrix covers hostile, health, hunger, dusk, and night")


def test_m4_probe_13_verified_shelter_suppresses_outward_hostile_flee():
    supervisor = RuntimeSupervisor(Config(planner_protocol="m4-fixed-v1"))
    observation = probe_13_verified_shelter_hostile_state()

    decision = supervisor.evaluate_interrupt(
        observation,
        goal="Remain in verified shelter until dawn",
    )

    assert decision.should_interrupt is True
    assert decision.reason == "night_safety_maintenance"
    assert decision.emergency_action is None
    grounding = decision.evidence["m4_hostile_safe_state_grounding"]
    assert grounding["policy_scope"] == "strict_m4_verified_shelter"
    assert grounding["direct_reachability"] == "blocked"
    assert grounding["hostiles_inside"] == []
    assert grounding["hostile_entity"]["id"] == 1789
    assert grounding["observed_player_cell"] == {"x": 107, "y": 140, "z": -29}
    assert grounding["verified_player_cell"] == grounding["observed_player_cell"]
    assert grounding["hostile_cell"] != grounding["observed_player_cell"]
    assert grounding["suppressed_emergency_action"]["type"] == "move_to"
    assert grounding["outward_move_suppressed"] is True
    print("PASS: Probe 13 outside-hostile flee is suppressed inside the verified M4 shelter")


def test_m4_verified_shelter_hostile_grounding_fails_closed():
    supervisor = RuntimeSupervisor(Config(planner_protocol="m4-fixed-v1"))
    observation = probe_13_verified_shelter_hostile_state()

    spoofed = dict(observation, shelter_verification={
        "passed": True,
        "safe_state": True,
        "source": "machine_state",
    })
    stale = dict(observation, position={"x": 108.1, "y": 140, "z": -28.4})
    reachable_report = verified_shelter_report(
        {"x": 107, "y": 140, "z": -29},
        nearby_hostile_count=1,
    )
    reachable_report["hostile_path_risk"]["direct_reachability"] = "not_proven_blocked"
    reachable = dict(observation, shelter_verification=reachable_report)
    inside = dict(observation, nearby_entities=[{
        "id": 1789,
        "type": "skeleton",
        "distance": 0.3,
        "hostile": True,
        "position": {"x": 107.7, "y": 140, "z": -28.3},
    }])

    for state in (spoofed, stale, reachable, inside):
        decision = supervisor.evaluate_interrupt(state)
        assert decision.should_interrupt is True
        assert decision.reason == "hostile_nearby"
        assert decision.emergency_action["type"] == "move_to"

    legacy = RuntimeSupervisor(Config()).evaluate_interrupt(observation)
    assert legacy.reason == "hostile_nearby"
    assert legacy.emergency_action["type"] == "move_to"
    print("PASS: unproven, stale, inside-hostile, and non-M4 states retain hostile handling")


def test_m4_verified_shelter_hostile_grounding_preserves_health_priority():
    supervisor = RuntimeSupervisor(Config(planner_protocol="m4-fixed-v1"))
    observation = dict(
        probe_13_verified_shelter_hostile_state(),
        health=2,
        inventory={"bread": 1},
    )

    decision = supervisor.evaluate_interrupt(observation)

    assert decision.reason == "health_critical"
    assert decision.emergency_action == {
        "type": "use_item",
        "parameters": {"item": "bread", "destination": "hand"},
    }
    assert decision.evidence["m4_hostile_safe_state_grounding"]["outward_move_suppressed"] is True
    print("PASS: safe-state grounding suppresses only hostile reaction and preserves health priority")


def test_agent_records_probe_13_safe_state_grounding_without_leaving_shelter():
    agent = runtime_agent(Config(planner_protocol="m4-fixed-v1"))
    goal = "Remain in verified shelter until dawn"
    task = agent.task_system.create_task(goal, status=TaskStatus.ACTIVE, priority=3)
    agent.task_system.drain_transition_events()
    observation = probe_13_verified_shelter_hostile_state()

    first, first_observation = agent._handle_runtime_interrupt(
        observation,
        goal,
        {"cycle": 6, "mode": "autonomous"},
    )
    repeated, repeated_observation = agent._handle_runtime_interrupt(
        observation,
        goal,
        {"cycle": 7, "mode": "autonomous"},
    )

    assert first is False and repeated is False
    assert first_observation is observation and repeated_observation is observation
    assert task.status == TaskStatus.ACTIVE
    assert agent.action_controller.actions == []
    assert getattr(agent, "_active_runtime_interrupt", {}) == {}
    grounding_events = [
        event for event in agent.session_logger.events
        if event["type"] == "m4_hostile_safe_state_grounding"
    ]
    assert len(grounding_events) == 1
    payload = grounding_events[0]["data"]
    assert payload["selected_interrupt_reason"] == "night_safety_maintenance"
    assert payload["outward_move_suppressed"] is True
    assert len(payload["hostile_safe_state_fingerprint"]) == 64
    assert not any(event["type"] == "runtime_emergency_action" for event in agent.memory.episodes)
    print("PASS: Agent audits one suppression event and executes no outward emergency action")


def test_m4_survival_interrupt_lifecycle_preserves_frontier():
    base = {
        "health": 20,
        "hunger": 20,
        "inventory": {},
        "inventory_count": 0,
        "equipment": [],
        "nearby_entities": [],
        "position": {"x": 0, "y": 64, "z": 0},
        "time_of_day": 5000,
    }
    cases = [
        (
            "hostile_nearby",
            dict(base, inventory={"stone_sword": 1}, nearby_entities=[{
                "id": 17,
                "type": "zombie",
                "hostile": True,
                "distance": 4,
                "position": {"x": 4, "y": 64, "z": 0},
            }]),
            "Attack nearest hostile mob",
            base,
            "equip",
        ),
        (
            "health_critical",
            dict(base, health=2, inventory={"bread": 1}),
            "Eat available food to recover critical health",
            base,
            "use_item",
        ),
        (
            "hunger_critical",
            dict(base, hunger=5, inventory={"bread": 1}),
            "Eat available food to restore hunger",
            base,
            "use_item",
        ),
        (
            "dusk_shelter_required",
            dict(base, time_of_day=11000),
            "Build verified shelter before nightfall",
            base,
            None,
        ),
        (
            "night_safety_maintenance",
            dict(base, time_of_day=15000, shelter_verification=verified_shelter_report()),
            "Remain in verified shelter until dawn",
            dict(base, time_of_day=23000, shelter_verification=verified_shelter_report()),
            None,
        ),
    ]

    for reason, triggered, aligned_goal, cleared, emergency_type in cases:
        agent = runtime_agent(Config(planner_protocol="m4-fixed-v1"))
        task = agent.task_system.create_task(
            "Gather 6 oak logs for tools and shelter",
            status=TaskStatus.ACTIVE,
            priority=3,
        )
        agent.task_system.drain_transition_events()
        agent._apply_action_feedback = lambda action, result, state, context=None: state
        agent._log_action_event = lambda *args, **kwargs: None
        agent._record_action_value = lambda *args, **kwargs: None
        agent._write_memory_episode = lambda *args, **kwargs: None

        first, _ = agent._handle_runtime_interrupt(triggered, task.title, {"cycle": 1, "mode": "autonomous"})
        second, _ = agent._handle_runtime_interrupt(triggered, task.title, {"cycle": 2, "mode": "autonomous"})
        aligned, _ = agent._handle_runtime_interrupt(triggered, aligned_goal, {"cycle": 3, "mode": "autonomous"})
        recovered, _ = agent._handle_runtime_interrupt(cleared, task.title, {"cycle": 4, "mode": "autonomous"})

        assert first is True and second is True
        assert aligned is False and recovered is False
        assert task.status == TaskStatus.ACTIVE
        triggers = [event for event in agent.session_logger.events if event["type"] == "runtime_interrupt"]
        maintenance = [event for event in agent.session_logger.events if event["type"] == "runtime_interrupt_maintenance"]
        recoveries = [event for event in agent.session_logger.events if event["type"] == "runtime_interrupt_recovery"]
        assert len(triggers) == 1, reason
        assert len(maintenance) == 1, reason
        assert len(recoveries) == 1, reason
        assert triggers[0]["data"]["reason"] == reason
        assert recoveries[0]["data"]["trigger_id"] == triggers[0]["data"]["trigger_id"]
        assert recoveries[0]["data"]["frontier_preserved"] is True
        assert recoveries[0]["data"]["paused_task_id"] == task.id
        assert recoveries[0]["data"]["resume_policy"] == "resume_preserved_frontier"
        if emergency_type:
            assert agent.action_controller.actions
            assert agent.action_controller.actions[0]["type"] == emergency_type
        else:
            assert not agent.action_controller.actions

    print("PASS: every G4 interrupt has one trigger, aligned takeover, and matching frontier recovery")


def test_m4_dusk_to_night_escalates_without_root_oscillation():
    agent = runtime_agent(Config(planner_protocol="m4-fixed-v1"))
    task = agent.task_system.create_task(
        "Gather 6 oak logs for tools and shelter",
        status=TaskStatus.ACTIVE,
        priority=3,
    )
    agent.task_system.drain_transition_events()
    agent._apply_action_feedback = lambda action, result, state, context=None: state
    agent._log_action_event = lambda *args, **kwargs: None
    agent._record_action_value = lambda *args, **kwargs: None
    agent._write_memory_episode = lambda *args, **kwargs: None
    dusk = {
        "health": 20,
        "hunger": 20,
        "inventory": {},
        "inventory_count": 0,
        "nearby_entities": [],
        "position": {"x": 0, "y": 64, "z": 0},
        "time_of_day": 11000,
    }
    night = dict(dusk, time_of_day=15000)
    dawn = dict(dusk, time_of_day=23000)

    interrupted, _ = agent._handle_runtime_interrupt(dusk, task.title, {"cycle": 1})
    aligned, _ = agent._handle_runtime_interrupt(
        night,
        "Build verified shelter before nightfall",
        {"cycle": 2},
    )
    cleared, _ = agent._handle_runtime_interrupt(dawn, task.title, {"cycle": 3})

    assert interrupted is True and aligned is False and cleared is False
    event_types = [event["type"] for event in agent.session_logger.events]
    assert event_types.count("runtime_interrupt") == 1
    assert event_types.count("runtime_interrupt_escalation") == 1
    assert event_types.count("runtime_interrupt_recovery") == 1
    escalation = next(event["data"] for event in agent.session_logger.events if event["type"] == "runtime_interrupt_escalation")
    assert escalation["from_reason"] == "dusk_shelter_required"
    assert escalation["to_reason"] == "night_shelter_required"
    assert task.status == TaskStatus.ACTIVE
    print("PASS: dusk-to-night escalation keeps one shelter root and one preserved frontier")


def test_m4_clears_survival_lifecycle_before_processing_task_deadline():
    agent = runtime_agent(Config(planner_protocol="m4-fixed-v1"))
    task = agent.task_system.create_task(
        "Gather 6 oak logs for tools and shelter",
        status=TaskStatus.ACTIVE,
        priority=3,
    )
    agent.task_system.drain_transition_events()
    agent._write_memory_episode = lambda *args, **kwargs: None
    dusk = {
        "health": 20,
        "hunger": 20,
        "inventory": {},
        "inventory_count": 0,
        "nearby_entities": [],
        "position": {"x": 0, "y": 64, "z": 0},
        "time_of_day": 11000,
    }
    safe_dusk = dict(dusk, shelter_verification=verified_shelter_report())

    triggered, _ = agent._handle_runtime_interrupt(dusk, task.title, {"cycle": 1})
    task.deadline = time.time() - 1
    deadline, _ = agent._handle_runtime_interrupt(safe_dusk, task.title, {"cycle": 2})

    assert triggered is True and deadline is True
    recoveries = [event["data"] for event in agent.session_logger.events if event["type"] == "runtime_interrupt_recovery"]
    assert recoveries[0]["reason"] == "dusk_shelter_required"
    assert recoveries[0]["resolution"] == "condition_cleared"
    assert recoveries[0]["frontier_preserved"] is True
    assert recoveries[1]["reason"] == "task_deadline_elapsed"
    assert task.status == TaskStatus.FAILED
    assert agent._active_runtime_interrupt == {}
    print("PASS: resolved survival state closes before an overdue task is terminalized")


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


def test_m4_autonomous_interrupt_suspends_then_resumes_root_frontier():
    agent = runtime_agent(Config(planner_protocol="m4-fixed-v1"))
    agent.goal_generator = GoalGenerator()
    agent.curriculum = FakeCurriculum()
    agent.planner = None
    agent.reflector = None
    agent._use_llm = True
    agent._active_skill_execution = {}
    agent._skill_fallback_goals = set()
    agent._skill_episode_start_index = 0
    resource_goal = "Gather 6 oak logs for tools and shelter"
    resource_task = agent.task_system.create_task(
        resource_goal,
        status=TaskStatus.ACTIVE,
        priority=3,
    )
    agent.task_system.drain_transition_events()

    day = {
        "health": 20,
        "hunger": 20,
        "inventory": {},
        "inventory_count": 0,
        "equipment": [],
        "nearby_entities": [],
        "position": {"x": 0, "y": 64, "z": 0},
        "time_of_day": 5000,
    }
    dusk = dict(day, time_of_day=11000)
    safe_day = dict(day, shelter_verification=verified_shelter_report())
    state = {"value": day, "observe_count": 0}

    def observe():
        state["observe_count"] += 1
        if state["observe_count"] == 2:
            state["value"] = dusk
        return dict(state["value"])

    agent._observe = observe
    agent._select_autonomous_goal = lambda current, fallback: fallback
    agent._think = lambda current, override_goal=None: {
        "status": "planning",
        "reasoning": "controlled G4 action",
        "actions": [{"type": "wait", "parameters": {"ms": 1}}],
    }
    agent._record_task_continuity = lambda *args, **kwargs: None
    agent._state_with_causal_context = lambda current, goal="": current
    agent._select_action_for_execution = lambda action, *args, **kwargs: (action, None)
    agent._verify_action_for_execution = lambda *args, **kwargs: (None, None)
    agent._record_action_value = lambda *args, **kwargs: None
    agent._record_skill_usage = lambda *args, **kwargs: None
    agent._attempt_failure_correction = lambda *args, **kwargs: (False, state["value"])
    agent._evaluate_episode_abort = lambda *args, **kwargs: False
    agent._record_frontier_budget_outcome = lambda *args, **kwargs: None
    agent._finalize_skill_learning_episode = lambda *args, **kwargs: None
    agent._complete_verified_m2_task_paths = lambda *args, **kwargs: []
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent._write_memory_context = lambda *args, **kwargs: None

    class Verification:
        def to_dict(self):
            return {"achieved": True, "source": "controlled_g4_fixture"}

    def verify(goal, current, context, recent_actions=None):
        return (context.get("phase") == "post_action", Verification())

    agent._goal_is_verified = verify

    def feedback(action, result, current, context=None):
        if str((context or {}).get("goal") or "").startswith("Build verified shelter"):
            state["value"] = safe_day
        return dict(state["value"])

    agent._apply_action_feedback = feedback

    with patch("singularity.core.agent.time.sleep", lambda _seconds: None):
        result = agent.run_autonomous(
            max_goals=3,
            max_cycles_per_goal=1,
            max_duration_s=30.0,
        )

    events = agent.session_logger.events
    auto_goals = [event["data"]["goal"] for event in events if event["type"] == "auto_goal"]
    assert auto_goals == [
        resource_goal,
        "Build verified shelter before nightfall",
        resource_goal,
    ]
    assert result["goals_interrupted"] == 1
    assert result["goals_completed"] == 2
    assert result["goals_failed"] == 0
    assert [event["type"] for event in events].count("auto_goal_interrupted") == 1
    assert not any(event["type"] == "auto_goal_failed" for event in events)
    recovery = next(event["data"] for event in events if event["type"] == "runtime_interrupt_recovery")
    assert recovery["paused_task_id"] == resource_task.id
    assert recovery["frontier_preserved"] is True
    assert len(agent.action_controller.actions) == 2
    assert resource_task.status == TaskStatus.ACTIVE

    open_roots = 0
    for event in events:
        if event["type"] == "goal_start":
            open_roots += 1
        elif event["type"] == "goal_end":
            open_roots -= 1
        assert open_roots in {0, 1}
    assert open_roots == 0
    print("PASS: autonomous G4 takeover suspends one root, resolves shelter, and resumes its frontier")


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
    test_m4_runtime_interrupt_priority_matrix_and_grounded_actions()
    test_m4_survival_interrupt_lifecycle_preserves_frontier()
    test_m4_dusk_to_night_escalates_without_root_oscillation()
    test_m4_clears_survival_lifecycle_before_processing_task_deadline()
    test_agent_handles_runtime_interrupt_with_emergency_action()
    test_agent_expires_all_overdue_tasks_and_interrupts_once()
    test_autonomous_loop_replans_once_then_resumes_actions()
    test_m4_autonomous_interrupt_suspends_then_resumes_root_frontier()
    test_non_m4_reflection_behavior_is_preserved()
    print("\nRuntime supervisor tests PASSED")
