"""Deterministic runtime tests for the shared M4 absolute episode deadline."""

import json
import os
import socket
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.action.controller import ActionController
from singularity.bot.bridge import BotBridge
from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.goal_verifier import GoalVerification
from singularity.core.planner import Planner
from singularity.core.task_system import TaskSystem
from singularity.evaluation.m4_protocol import PROTOCOL
from singularity.logging.session_logger import SessionLogger


class FakeClock:
    def __init__(self, value: float = 100.0):
        self.value = float(value)

    def monotonic(self) -> float:
        return self.value

    def advance(self, seconds: float):
        self.value += float(seconds)


class PlannerLLM:
    def __init__(self, clock: FakeClock, advance_s: float = 0.0):
        self.clock = clock
        self.advance_s = advance_s
        self.calls = []
        self.last_call_metadata = {}

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        self.last_call_metadata = {
            "provider": "fixture",
            "model": "fixture-planner",
            "request_sha256": "1" * 64,
            "timeout_s": kwargs.get("timeout_s"),
            "max_retries": 0,
            "finish_reason": "stop",
            "extra_body": dict(kwargs.get("extra_body", {})),
            "reasoning_content_byte_count": 0,
        }
        self.clock.advance(self.advance_s)
        return json.dumps({
            "status": "planning",
            "reasoning": "prepare before night",
            "subtasks": [],
            "actions": [{"type": "wait", "parameters": {"ms": 1}}],
        })


class DeadlineBot:
    def __init__(self):
        self.deadline_calls = []
        self.dig_calls = []

    def set_action_deadline(self, deadline_monotonic, action_timeout_limit_s=None):
        self.deadline_calls.append((deadline_monotonic, action_timeout_limit_s))

    def dig(self, x, y, z, timeout_ms=None):
        self.dig_calls.append((x, y, z, timeout_ms))
        return {"success": True}


class ScriptedSocket:
    def __init__(self, response=b'{"success": true}\n', timeout=10.0):
        self.response = response
        self.timeout = timeout
        self.timeout_history = []
        self.sent = []

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value
        self.timeout_history.append(value)

    def sendall(self, payload):
        self.sent.append(payload)

    def recv(self, _size):
        response, self.response = self.response, b""
        return response

    def close(self):
        pass


class TimeoutSocket(ScriptedSocket):
    def recv(self, _size):
        raise socket.timeout("fixture timeout")


class RuntimePlanner:
    def __init__(self):
        self.deadline_calls = []
        self.episodes = []

    def set_deadline(self, deadline_monotonic, action_guard_s=0.0):
        self.deadline_calls.append((deadline_monotonic, action_guard_s))

    def start_episode(self, goal, episode_id=""):
        self.episodes.append((goal, episode_id))


class RuntimeActionController:
    def __init__(self):
        self.deadline_calls = []
        self.actions = []

    def set_episode_deadline(self, deadline_monotonic, action_timeout_limit_s=None):
        self.deadline_calls.append((deadline_monotonic, action_timeout_limit_s))

    def execute(self, action, observation):
        self.actions.append((action, observation))
        return {"success": True}


class RuntimeSessionLogger:
    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.events = []
        self.session_id = "m4-deadline-fixture"

    def log(self, event_type, data, level="INFO"):
        self.events.append({
            "type": event_type,
            "monotonic_s": self.clock.monotonic(),
            "data": data,
            "level": level,
        })

    def log_observation(self, observation):
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


class RuntimeGoalGenerator:
    def next_goal(self, observation):
        return "Prepare shelter before night"


class RuntimeExplorer:
    landmarks = []

    def set_base(self, x, y, z):
        self.base = (x, y, z)

    def should_return(self, position, inventory_count):
        return False, ""

    def record_position(self, position):
        pass


class RuntimeCurriculum:
    def __init__(self):
        self.outcomes = []

    def record_goal_outcome(self, goal, success, cycles):
        self.outcomes.append((goal, success, cycles))

    def summary(self):
        return {"outcome_count": len(self.outcomes)}


def test_m4_planner_bounds_call_and_rejects_inflight_return():
    clock = FakeClock()
    llm = PlannerLLM(clock)
    planner = Planner(llm, TaskSystem(), protocol="m4-fixed-v1")
    planner.start_episode("Prepare shelter", "episode-1")
    planner.set_deadline(150.0, 0.0)

    with patch("singularity.core.planner.time.monotonic", clock.monotonic):
        plan = planner.plan_from_goal("Prepare shelter", {"inventory": {}})

    assert plan["status"] == "planning"
    assert len(llm.calls) == 1
    assert llm.calls[0]["timeout_s"] == 50.0
    assert llm.calls[0]["timeout_s"] <= PROTOCOL["deadline_policy"]["llm_call_timeout_s"]
    assert llm.calls[0]["extra_body"] == PROTOCOL["llm"]["extra_body"]
    evidence = planner.last_call_evidence
    assert evidence["planner_id"] == PROTOCOL["identities"]["planner"]
    assert evidence["deadline_policy"]["policy_id"] == PROTOCOL["deadline_policy"]["id"]
    assert evidence["transport_evidence"]["attempt_count"] == 1
    assert evidence["transport_evidence"]["retry_count"] == 0

    late_llm = PlannerLLM(clock, advance_s=6.0)
    late_planner = Planner(late_llm, TaskSystem(), protocol="m4-fixed-v1")
    late_planner.start_episode("Prepare shelter", "episode-2")
    late_planner.set_deadline(105.0, 0.0)
    clock.value = 100.0
    with patch("singularity.core.planner.time.monotonic", clock.monotonic):
        late_plan = late_planner.plan_from_goal("Prepare shelter", {"inventory": {}})

    assert late_plan["status"] == "error"
    assert late_plan["actions"] == []
    assert late_planner.last_call_evidence["error"] == "m4_planner_response_missed_action_window"
    print("PASS: M4 planner bounds calls and discards in-flight responses after deadline")


def test_m4_planner_suppresses_call_after_deadline():
    clock = FakeClock(106.0)
    llm = PlannerLLM(clock)
    planner = Planner(llm, TaskSystem(), protocol="m4-fixed-v1")
    planner.start_episode("Prepare shelter", "episode-expired")
    planner.set_deadline(105.0, 0.0)

    with patch("singularity.core.planner.time.monotonic", clock.monotonic):
        plan = planner.plan_from_goal("Prepare shelter", {"inventory": {}})

    assert llm.calls == []
    assert plan["status"] == "error"
    assert plan["actions"] == []
    assert planner.last_call_evidence["error"] == "m4_total_deadline_exhausted_before_planner_call"
    print("PASS: M4 planner never starts a call after the episode deadline")


def test_m4_action_controller_enforces_episode_and_action_deadlines():
    clock = FakeClock()
    bot = DeadlineBot()
    controller = ActionController(bot, Config())
    captured = []

    def immediate_wait(params):
        captured.append(dict(params))
        return {"success": True}

    controller._action_handlers["wait"] = immediate_wait
    with patch("singularity.action.controller.time.monotonic", clock.monotonic):
        controller.set_episode_deadline(110.0, 3.0)
        result = controller.execute(
            {"type": "wait", "parameters": {"ms": 9000}},
            {"health": 20},
        )

        assert result["success"] is True
        assert captured[0]["ms"] == 3000
        assert captured[0]["timeout_ms"] == 3000
        assert result["accepted_within_episode_deadline"] is True
        assert result["accepted_within_action_deadline"] is True

        clock.value = 111.0
        suppressed = controller.execute(
            {"type": "wait", "parameters": {"ms": 1000}},
            {"health": 20},
        )
        assert suppressed["deadline_suppressed"] is True
        assert len(captured) == 1

        clock.value = 100.0
        controller.set_episode_deadline(200.0, 60.0)
        dig = controller.execute(
            {"type": "dig", "parameters": {"x": 3, "y": 64, "z": 4}},
            {"health": 20, "inventory": {}},
        )
        assert dig["success"] is True
        assert dig["backend_params"]["timeout_ms"] == 60000
        assert bot.dig_calls == [(3, 64, 4, 60000)]

        def late_wait(params):
            clock.advance(3.1)
            return {"success": True}

        controller._action_handlers["wait"] = late_wait
        controller.set_episode_deadline(200.0, 3.0)
        late = controller.execute(
            {"type": "wait", "parameters": {"ms": 1000}},
            {"health": 20},
        )

    assert late["success"] is False
    assert late["accepted_within_episode_deadline"] is True
    assert late["accepted_within_action_deadline"] is False
    assert late["error"] == "action deadline exceeded during action"
    assert bot.deadline_calls[0] == (110.0, 3.0)
    print("PASS: M4 action controller clamps starts, waits, and in-flight results")


def test_m4_bridge_uses_remaining_budget_without_replay():
    clock = FakeClock()
    bridge = object.__new__(BotBridge)
    bridge._connected = True
    bridge._socket = ScriptedSocket()
    bridge._action_deadline_monotonic = 102.0
    bridge._action_timeout_limit_s = 60.0

    with patch("singularity.bot.bridge.time.monotonic", clock.monotonic):
        result = bridge._send_command("craft", {"item": "oak_planks", "count": 4})

    assert result["success"] is True
    assert len(bridge._socket.sent) == 1
    assert bridge._socket.timeout_history == [2.0, 10.0]

    bridge._socket = ScriptedSocket()
    clock.value = 103.0
    with patch("singularity.bot.bridge.time.monotonic", clock.monotonic):
        suppressed = bridge._send_command("craft", {"item": "oak_planks", "count": 4})

    assert suppressed["deadline_suppressed"] is True
    assert suppressed["command_replayed"] is False
    assert bridge._socket.sent == []

    bridge._socket = ScriptedSocket()
    bridge._action_deadline_monotonic = 160.0
    clock.value = 100.0
    with patch("singularity.bot.bridge.time.monotonic", clock.monotonic):
        dig = bridge._send_command("dig", {"x": 3, "y": 64, "z": 4, "timeout_ms": 60000})

    assert dig["success"] is True
    assert bridge._socket.timeout_history == [60.0, 10.0]
    assert len(bridge._socket.sent) == 1

    reconnect_calls = []
    bridge._connected = True
    bridge._socket = TimeoutSocket()
    bridge._reconnect = lambda: reconnect_calls.append(True)
    clock.value = 100.0
    with patch("singularity.bot.bridge.time.monotonic", clock.monotonic):
        timed_out = bridge._send_command("get_player_state")

    assert timed_out["success"] is False
    assert timed_out["deadline_bound"] is True
    assert timed_out["command_replayed"] is False
    assert timed_out["bridge_reconnected"] is False
    assert reconnect_calls == []
    assert bridge._connected is False
    print("PASS: M4 bridge clamps transport waits without replay or synchronous reconnect")


def test_m4_verifier_return_after_deadline_is_rejected():
    clock = FakeClock()
    agent = object.__new__(Agent)
    agent.config = Config(planner_protocol="m4-fixed-v1")
    agent._episode_deadline_monotonic = 105.0
    agent.session_logger = RuntimeSessionLogger(clock)
    agent._write_memory_episode = lambda *args, **kwargs: None

    class LateVerifier:
        def verify(self, goal, observation, recent_actions=None):
            clock.advance(6.0)
            return GoalVerification(
                goal=goal,
                achieved=True,
                status="achieved",
                confidence=1.0,
                evidence=["fixture would otherwise pass"],
            )

    agent.goal_verifier = LateVerifier()
    with patch("singularity.core.agent.time.monotonic", clock.monotonic):
        achieved, verification = agent._goal_is_verified(
            "Survive until dawn",
            {"health": 20},
            {"mode": "autonomous"},
        )

    assert achieved is False
    assert verification.achieved is False
    assert verification.matched_rules == ["m4:episode_deadline"]
    deadline_event = agent.session_logger.events[-1]
    assert deadline_event["type"] == "goal_verification"
    assert deadline_event["data"]["context"]["deadline_suppressed"] is True
    print("PASS: M4 verifier results cannot revive execution after deadline")


def test_session_logger_records_absolute_monotonic_event_time():
    clock = FakeClock(321.5)
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SessionLogger(tmpdir, session_id="m4-monotonic-fixture")
        with patch("singularity.logging.session_logger.time.monotonic", clock.monotonic):
            logger.log("plan", {"status": "planning"})

    assert logger.events[0]["monotonic_s"] == 321.5
    assert logger.events[0]["type"] == "plan"
    print("PASS: Session evidence records absolute monotonic event time")


def test_m4_autonomous_loop_shares_deadline_and_suppresses_plan_suffix():
    clock = FakeClock()
    planner = RuntimePlanner()
    action_controller = RuntimeActionController()
    agent = object.__new__(Agent)
    agent.config = Config(planner_protocol="m4-fixed-v1")
    agent.session_logger = RuntimeSessionLogger(clock)
    agent.planner = planner
    agent.action_controller = action_controller
    agent.goal_generator = RuntimeGoalGenerator()
    agent.explorer = RuntimeExplorer()
    agent.curriculum = RuntimeCurriculum()
    agent._episode_deadline_monotonic = None
    agent._skill_episode_start_index = 0
    agent._active_skill_execution = {}
    agent._skill_fallback_goals = set()
    agent._observe = lambda: {
        "position": {"x": 0, "y": 64, "z": 0},
        "inventory": {},
        "inventory_count": 0,
        "health": 20,
    }
    agent._select_autonomous_goal = lambda observation, fallback: fallback

    def late_plan(observation, override_goal=None):
        clock.advance(6.0)
        return {
            "status": "planning",
            "reasoning": "late plan must not execute",
            "actions": [{"type": "wait", "parameters": {"ms": 1}}],
        }

    agent._think = late_plan
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent._write_memory_context = lambda *args, **kwargs: None
    agent._record_frontier_budget_outcome = lambda *args, **kwargs: None
    agent._record_task_continuity = lambda *args, **kwargs: None
    agent._finalize_skill_learning_episode = lambda *args, **kwargs: None

    with patch("singularity.core.agent.time.monotonic", clock.monotonic):
        result = agent.run_autonomous(
            max_goals=999,
            max_cycles_per_goal=999,
            max_duration_s=5.0,
        )

    expected_deadline = 105.0
    start_event = next(event for event in agent.session_logger.events if event["type"] == "autonomous_start")
    goal_event = next(event for event in agent.session_logger.events if event["type"] == "auto_goal")
    deadline_event = next(event for event in agent.session_logger.events if event["type"] == "episode_deadline_exceeded")
    assert start_event["data"]["episode_deadline_monotonic"] == expected_deadline
    assert start_event["data"]["max_goals"] == PROTOCOL["limits"]["max_autonomous_goals"]
    assert start_event["data"]["max_cycles_per_goal"] == PROTOCOL["limits"]["max_cycles_per_goal"]
    assert goal_event["data"]["selection_source"] == "goal_generator"
    assert goal_event["data"]["selection_reason"] == "rule_generator"
    assert goal_event["data"]["priority"] == 6
    assert goal_event["data"]["priority_class"] == "tool_resource_progression"
    assert planner.deadline_calls[:2] == [(expected_deadline, 0.0), (expected_deadline, 0.0)]
    assert planner.deadline_calls[-1] == (None, 0.0)
    assert action_controller.deadline_calls[0] == (
        expected_deadline,
        PROTOCOL["deadline_policy"]["action_timeout_s"],
    )
    assert action_controller.deadline_calls[-1] == (None, None)
    assert action_controller.actions == []
    assert deadline_event["data"]["phase"] == "post_planner"
    assert result["termination_reason"] == "episode_deadline"
    assert result["deadline_eligible"] is False
    assert result["episode_deadline_monotonic"] == expected_deadline
    assert agent._episode_deadline_monotonic is None
    print("PASS: M4 autonomous loop shares one deadline and suppresses late plan suffixes")


if __name__ == "__main__":
    test_m4_planner_bounds_call_and_rejects_inflight_return()
    test_m4_planner_suppresses_call_after_deadline()
    test_m4_action_controller_enforces_episode_and_action_deadlines()
    test_m4_bridge_uses_remaining_budget_without_replay()
    test_m4_verifier_return_after_deadline_is_rejected()
    test_session_logger_records_absolute_monotonic_event_time()
    test_m4_autonomous_loop_shares_deadline_and_suppresses_plan_suffix()
    print("\nM4 deadline runtime tests PASSED")
