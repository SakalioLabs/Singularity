"""Deterministic runtime tests for the shared M4 absolute episode deadline."""

import json
import os
import socket
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.action.controller import ActionController
from singularity.action.verifier import ActionVerifier
from singularity.bot.bridge import BotBridge
from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.goal_verifier import GoalVerification
from singularity.core.planner import Planner
from singularity.core.task_system import TaskStatus, TaskSystem
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
        self.replan_reasons = []

    def set_deadline(self, deadline_monotonic, action_guard_s=0.0):
        self.deadline_calls.append((deadline_monotonic, action_guard_s))

    def start_episode(self, goal, episode_id=""):
        self.episodes.append((goal, episode_id))

    def request_replan(self, reason):
        self.replan_reasons.append(reason)


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


def test_m4_planner_rejects_empty_planning_response_and_marks_replan():
    clock = FakeClock()

    class SequencePlannerLLM(PlannerLLM):
        def __init__(self, responses):
            super().__init__(clock)
            self.responses = list(responses)

        def chat(self, messages, **kwargs):
            super().chat(messages, **kwargs)
            return json.dumps(self.responses.pop(0))

    llm = SequencePlannerLLM([
        {
            "status": "planning",
            "reasoning": "dark oak can substitute, so the exact oak goal is complete",
            "subtasks": [],
            "actions": [],
        },
        {
            "status": "planning",
            "reasoning": "continue gathering the exact named item",
            "subtasks": [],
            "actions": [{"type": "wait", "parameters": {"ms": 1}}],
        },
    ])
    planner = Planner(llm, TaskSystem(), protocol="m4-fixed-v1")
    planner.start_episode("Gather 6 oak logs", "m4-envelope-fixture")
    planner.set_deadline(200.0, 0.0)

    with patch("singularity.core.planner.time.monotonic", clock.monotonic):
        rejected = planner.plan_from_goal(
            "Gather 6 oak logs",
            {"inventory": {"dark_oak_log": 6}},
        )
        planner.request_replan("planning response omitted executable actions")
        recovered = planner.plan_from_goal(
            "Gather 6 oak logs",
            {"inventory": {"dark_oak_log": 6}},
        )

    assert rejected["status"] == "error"
    assert rejected["actions"] == []
    assert rejected["schema_validation"]["type"] == "m4_plan_envelope_validation"
    assert rejected["schema_validation"]["issues"] == ["planning_actions_missing"]
    assert rejected["planner_evidence"]["schema_valid"] is False
    assert recovered["status"] == "planning"
    assert recovered["schema_validation"]["passed"] is True
    assert recovered["planner_evidence"]["plan_kind"] == "replan"
    system_prompt = llm.calls[0]["messages"][0]["content"]
    assert "Do not substitute one item species" in system_prompt
    assert "prose never completes a goal" in system_prompt
    print("PASS: M4 rejects planning-status empty output and grounds the next replan")


def test_m4_planner_canonicalizes_equivalent_dig_aliases_before_execution():
    clock = FakeClock()

    class AliasPlannerLLM(PlannerLLM):
        def chat(self, messages, **kwargs):
            super().chat(messages, **kwargs)
            return json.dumps({
                "status": "planning",
                "reasoning": "dig the observed oak log",
                "subtasks": [],
                "actions": [{
                    "type": "dig",
                    "parameters": {
                        "block_name": "oak_log",
                        "position": {"x": 103, "y": 139, "z": -30},
                    },
                }],
            })

    llm = AliasPlannerLLM(clock)
    planner = Planner(llm, TaskSystem(), protocol="m4-fixed-v1")
    planner.start_episode("Gather 6 oak logs", "m4-grounding-fixture")
    planner.set_deadline(200.0, 0.0)
    with patch("singularity.core.planner.time.monotonic", clock.monotonic):
        plan = planner.plan_from_goal(
            "Gather 6 oak logs",
            {"inventory": {"oak_log": 1}, "nearby_blocks": [{"name": "oak_log"}]},
        )

    assert plan["status"] == "planning"
    action = plan["actions"][0]
    assert action == {
        "type": "dig",
        "parameters": {"x": 103, "y": 139, "z": -30, "block": "oak_log"},
    }
    grounding = plan["action_parameter_grounding"]
    assert grounding["passed"] is True
    assert grounding["dig_action_count"] == 1
    assert grounding["normalized_action_count"] == 1
    assert grounding["normalizations"][0]["aliases"] == [
        "block_name->block",
        "position->x,y,z",
    ]
    assert len(grounding["normalizations"][0]["original_parameters_sha256"]) == 64
    assert planner.last_call_evidence["schema_valid"] is True
    decision = ActionVerifier().verify(
        action,
        {"inventory": {}, "nearby_blocks": [{"name": "oak_log"}]},
        goal="Gather 6 oak logs",
    )
    assert decision.status == "accept"
    system_prompt = llm.calls[0]["messages"][0]["content"]
    assert "top-level finite x, y, and z" in system_prompt
    assert "never use block_name, position, target, or block_position aliases" in system_prompt
    print("PASS: M4 canonicalizes the exact Probe 6 dig alias before ActionVerifier")


def test_m4_planner_rejects_conflicting_missing_or_unknown_dig_parameters():
    base = {
        "status": "planning",
        "reasoning": "fixture",
        "subtasks": [],
    }
    fixtures = [
        (
            {
                **base,
                "actions": [{
                    "type": "dig",
                    "parameters": {
                        "x": 104,
                        "y": 139,
                        "z": -30,
                        "position": {"x": 103, "y": 139, "z": -30},
                    },
                }],
            },
            "action[0]:dig_position_conflict:x",
        ),
        (
            {
                **base,
                "actions": [{"type": "dig", "parameters": {"block": "oak_log", "x": 103}}],
            },
            "action[0]:dig_coordinates_missing:y,z",
        ),
        (
            {
                **base,
                "actions": [{
                    "type": "dig",
                    "parameters": {"x": 103, "y": 139, "z": -30, "target": "oak_log"},
                }],
            },
            "action[0]:dig_unknown_parameters:target",
        ),
        (
            {
                **base,
                "actions": [{
                    "type": "dig",
                    "parameters": {
                        "x": 103,
                        "y": 139,
                        "z": -30,
                        "block": "oak_log",
                        "block_name": "dark_oak_log",
                    },
                }],
            },
            "action[0]:dig_block_conflict",
        ),
    ]

    for response, expected_issue in fixtures:
        grounded, report = Planner._ground_m4_action_parameters(response)
        validation = Planner._validate_m4_plan_envelope(
            grounded,
            expected_goal="Gather 6 oak logs",
            expected_kind="continuation",
        )
        combined = sorted(set(validation["issues"] + report["issues"]))
        assert report["passed"] is False
        assert expected_issue in combined

    canonical, canonical_report = Planner._ground_m4_action_parameters({
        **base,
        "actions": [{
            "type": "dig",
            "parameters": {"x": 103, "y": 139, "z": -30, "block": "oak_log"},
        }],
    })
    assert canonical["actions"][0]["parameters"] == {
        "x": 103,
        "y": 139,
        "z": -30,
        "block": "oak_log",
    }
    assert canonical_report["passed"] is True
    assert canonical_report["normalized_action_count"] == 0
    print("PASS: M4 dig grounding fails closed on conflicts, missing coordinates, and unknown aliases")


def test_m4_planner_canonicalizes_probe_8_craft_recipe_alias():
    grounded, report = Planner._ground_m4_action_parameters({
        "status": "planning",
        "reasoning": "craft planks",
        "subtasks": [],
        "actions": [{
            "type": "craft",
            "parameters": {"recipe": "oak_planks", "count": 4},
        }],
    })

    assert grounded["actions"] == [{
        "type": "craft",
        "parameters": {"item": "oak_planks", "count": 4},
    }]
    assert report["passed"] is True
    assert report["craft_action_count"] == 1
    assert report["normalized_action_count"] == 1
    assert report["normalizations"][0]["aliases"] == ["recipe->item"]
    decision = ActionVerifier().verify(
        grounded["actions"][0],
        {"inventory": {"oak_log": 6}},
        goal="Build verified shelter before nightfall",
    )
    assert decision.status == "accept"


def test_m4_planner_canonicalizes_probe_2_place_block_alias():
    grounded, report = Planner._ground_m4_action_parameters({
        "status": "planning",
        "reasoning": "place the inventory crafting table on observed ground",
        "subtasks": [],
        "actions": [{
            "type": "place",
            "parameters": {"x": 106, "y": 135, "z": -29, "block": "crafting_table"},
        }],
    })

    action = grounded["actions"][0]
    assert action == {
        "type": "place",
        "parameters": {"item": "crafting_table", "x": 106, "y": 135, "z": -29},
    }
    assert report["passed"] is True
    assert report["place_action_count"] == 1
    assert report["normalized_action_count"] == 1
    assert report["normalizations"][0]["aliases"] == ["block->item"]
    decision = ActionVerifier().verify(
        action,
        {"inventory": {"crafting_table": 1}, "nearby_blocks": [{"name": "grass_block"}]},
        goal="Place crafting table for tool progression",
    )
    assert decision.status == "accept"
    prompt = Planner(PlannerLLM(FakeClock()), TaskSystem(), protocol="m4-fixed-v1")._planner_system_prompt()
    assert "place action must use item plus top-level finite x, y, and z" in prompt
    assert "never use block as an alias" in prompt
    print("PASS: M4 canonicalizes the exact Probe 2 place alias before ActionVerifier")


def test_m4_planner_rejects_unexecutable_place_parameters():
    fixtures = [
        ({"block": "crafting_table", "x": 106, "y": 135}, "action[0]:place_coordinates_missing:z"),
        ({"item": "crafting_table", "block": "oak_planks", "x": 106, "y": 135, "z": -29}, "action[0]:place_item_conflict"),
        ({"item": "crafting_table", "x": 106, "y": 135, "z": -29, "position": {}}, "action[0]:place_unknown_parameters:position"),
    ]
    for parameters, expected_issue in fixtures:
        _, report = Planner._ground_m4_action_parameters({
            "status": "planning",
            "reasoning": "fixture",
            "subtasks": [],
            "actions": [{"type": "place", "parameters": parameters}],
        })
        assert report["passed"] is False
        assert expected_issue in report["issues"]
    print("PASS: M4 place grounding fails closed on missing coordinates, conflicts, and unknown aliases")


def test_m4_place_target_occupancy_gate_replays_probe_7_and_controls():
    verifier = ActionVerifier()
    action = {
        "type": "place",
        "parameters": {
            "item": "crafting_table",
            "x": 93,
            "y": 134,
            "z": -38,
        },
    }
    inventory = {"crafting_table": 1, "oak_log": 6}

    for occupied_by in ("dark_oak_log", "grass_block"):
        decision = verifier.verify(
            action,
            {
                "inventory": inventory,
                "nearby_blocks": [
                    {"name": "dirt", "position": {"x": 93, "y": 134, "z": -38}},
                    {"name": occupied_by, "position": {"x": 93, "y": 135, "z": -38}},
                ],
            },
            goal="Place the crafting table nearby",
            protocol="m4-fixed-v1",
        )
        assert decision.status == "reject"
        assert decision.policy_id == "m4-place-target-occupancy-v1"
        assert f"observed_target:{occupied_by}" in decision.evidence
        assert decision.required == {
            "target_position": {"x": 93, "y": 135, "z": -38},
            "target_state": "air_or_replaceable",
        }

    replaceable = verifier.verify(
        action,
        {
            "inventory": inventory,
            "nearby_blocks": [{
                "name": "short_grass",
                "position": {"x": 93, "y": 135, "z": -38},
            }],
        },
        protocol="m4-fixed-v1",
    )
    unobserved = verifier.verify(
        action,
        {
            "inventory": inventory,
            "nearby_blocks": [{
                "name": "grass_block",
                "position": {"x": 94, "y": 135, "z": -38},
            }],
        },
        protocol="m4-fixed-v1",
    )
    non_m4 = verifier.verify(
        action,
        {
            "inventory": inventory,
            "nearby_blocks": [{
                "name": "grass_block",
                "position": {"x": 93, "y": 135, "z": -38},
            }],
        },
    )
    assert replaceable.status == "accept"
    assert "target:short_grass" in replaceable.evidence
    assert unobserved.status == "accept"
    assert "target:not_observed_occupied" in unobserved.evidence
    assert non_m4.status == "accept"

    prompt = Planner(PlannerLLM(FakeClock()), TaskSystem(), protocol="m4-fixed-v1")._planner_system_prompt()
    assert "actual target is the block cell at floor(x), floor(y)+1, floor(z)" in prompt
    assert "choose a different reference after an occupied-target rejection" in prompt
    print("PASS: M4 rejects the exact Probe 7 occupied targets while controls remain executable")


def test_m4_occupied_place_rejection_requests_grounded_replan():
    clock = FakeClock()
    planner = RuntimePlanner()
    agent = object.__new__(Agent)
    agent.config = Config(
        planner_protocol="m4-fixed-v1",
        enable_action_verification=True,
        enforce_action_verification=True,
    )
    agent.action_verifier = ActionVerifier()
    agent.planner = planner
    agent.session_logger = RuntimeSessionLogger(clock)
    agent._episode_deadline_monotonic = None
    agent._write_memory_episode = lambda *args, **kwargs: None

    verification, result = agent._verify_action_for_execution(
        {
            "type": "place",
            "parameters": {
                "item": "crafting_table",
                "x": 93,
                "y": 134,
                "z": -36,
            },
        },
        {
            "inventory": {"crafting_table": 1},
            "nearby_blocks": [{
                "name": "grass_block",
                "position": {"x": 93, "y": 135, "z": -36},
            }],
        },
        "Place the crafting table nearby",
        {"cycle": 6, "mode": "autonomous"},
    )

    assert verification["status"] == "reject"
    assert verification["policy_id"] == "m4-place-target-occupancy-v1"
    assert verification["replan_requested"] is True
    assert result["success"] is False
    assert result["verification_blocked"] is True
    assert result["duration_ms"] == 0
    assert result["requires_replan"] is True
    assert len(planner.replan_reasons) == 1
    assert "occupied by grass_block" in planner.replan_reasons[0]
    assert "cell above is air or replaceable" in planner.replan_reasons[0]
    event = agent.session_logger.events[-1]
    assert event["type"] == "action_verification"
    assert event["data"]["verification"]["replan_requested"] is True
    print("PASS: occupied M4 place targets fail before execution and ground the next replan")


def test_m4_craft_grounding_fails_closed_on_drift():
    fixtures = [
        ({"item": "oak_planks", "recipe": "stick", "count": 4}, "craft_item_conflict"),
        ({"count": 4}, "craft_item_missing"),
        ({"recipe": "oak_planks", "count": 0}, "craft_count_invalid"),
        ({"recipe": "oak_planks", "count": 4, "table": True}, "craft_unknown_parameters:table"),
    ]
    for parameters, suffix in fixtures:
        grounded, report = Planner._ground_m4_action_parameters({
            "status": "planning",
            "reasoning": "fixture",
            "subtasks": [],
            "actions": [{"type": "craft", "parameters": parameters}],
        })
        assert report["passed"] is False
        assert any(issue.endswith(suffix) for issue in report["issues"])
        assert grounded["actions"][0]["type"] == "craft"


def test_m4_planner_normalizes_exact_probe_3_subtask_inventory_aliases():
    clock = FakeClock()

    class Probe3PlannerLLM(PlannerLLM):
        def chat(self, messages, **kwargs):
            super().chat(messages, **kwargs)
            return json.dumps({
                "status": "planning",
                "reasoning": "place the table, then craft more planks",
                "subtasks": [
                    {
                        "title": "Place crafting_table",
                        "type": "place",
                        "priority": 1,
                        "success_criteria": {"block_placed": "crafting_table"},
                        "preconditions": {"inventory": {"crafting_table": 1}, "flags": []},
                        "depends_on": [],
                    },
                    {
                        "title": "Craft oak_planks from oak_log",
                        "type": "craft",
                        "priority": 1,
                        "success_criteria": {"inventory": {"oak_planks": ">=8"}},
                        "preconditions": {
                            "inventory": {"oak_log": ">=1", "crafting_table": 1},
                            "flags": ["crafting_table_placed"],
                        },
                        "depends_on": ["Place crafting_table"],
                    },
                ],
                "actions": [{
                    "type": "place",
                    "parameters": {"item": "crafting_table", "x": 106, "y": 135, "z": -29},
                }],
            })

    tasks = TaskSystem()
    llm = Probe3PlannerLLM(clock)
    planner = Planner(llm, tasks, protocol="m4-fixed-v1")
    planner.start_episode("Craft oak_planks from oak_log", "m4-probe-3-numeric-fixture")
    planner.set_deadline(200.0, 0.0)
    with patch("singularity.core.planner.time.monotonic", clock.monotonic):
        plan = planner.plan_from_goal(
            "Craft oak_planks from oak_log",
            {"inventory": {"oak_log": 4, "oak_planks": 4, "crafting_table": 1}},
        )

    assert plan["status"] == "planning"
    assert plan["schema_validation"]["passed"] is True
    grounding = plan["subtask_numeric_criteria_grounding"]
    assert grounding["passed"] is True
    assert grounding["subtask_count"] == 2
    assert grounding["inventory_requirement_count"] == 4
    assert grounding["normalized_requirement_count"] == 2
    assert [item["canonical_count"] for item in grounding["normalizations"]] == [1, 8]
    assert all(item["alias"] == ">=N->N" for item in grounding["normalizations"])
    assert all(len(item["original_value_sha256"]) == 64 for item in grounding["normalizations"])
    craft_task = next(task for task in tasks.tasks.values() if task.title.startswith("Craft oak_planks"))
    assert craft_task.preconditions["inventory"]["oak_log"] == 1
    assert craft_task.success_criteria["inventory"]["oak_planks"] == 8
    assert "every count must be a positive integer" in llm.calls[0]["messages"][0]["content"]
    assert "never emit comparator strings" in llm.calls[0]["messages"][0]["content"]
    print("PASS: M4 normalizes the exact Probe 3 subtask numeric aliases before TaskSystem")


def test_m4_subtask_numeric_grounding_rejects_non_equivalent_counts():
    invalid_counts = [True, 0, -1, 1.5, "8", ">8", "at least 8", ">=0"]
    for count in invalid_counts:
        grounded, report = Planner._ground_m4_subtask_numeric_criteria({
            "status": "planning",
            "subtasks": [{
                "title": "fixture",
                "preconditions": {"inventory": {"oak_log": count}},
                "success_criteria": {"inventory": {"oak_planks": 8}},
            }],
            "actions": [{"type": "wait", "parameters": {"ms": 1}}],
        })
        assert report["passed"] is False
        assert report["issues"] == [
            "subtask[0]:preconditions_inventory_count_invalid:oak_log"
        ]
        assert grounded["subtasks"][0]["preconditions"]["inventory"]["oak_log"] == count

    for field_name in ("preconditions", "success_criteria"):
        _, report = Planner._ground_m4_subtask_numeric_criteria({
            "subtasks": [{field_name: {"inventory": []}}],
        })
        assert report["passed"] is False
        assert report["issues"] == [f"subtask[0]:{field_name}_inventory_not_object"]

    class InvalidCountLLM(PlannerLLM):
        def chat(self, messages, **kwargs):
            super().chat(messages, **kwargs)
            return json.dumps({
                "status": "planning",
                "subtasks": [{
                    "title": "unsafe fixture",
                    "success_criteria": {"inventory": {"oak_planks": ">8"}},
                }],
                "actions": [{"type": "wait", "parameters": {"ms": 1}}],
            })

    clock = FakeClock()
    tasks = TaskSystem()
    planner = Planner(InvalidCountLLM(clock), tasks, protocol="m4-fixed-v1")
    planner.start_episode("Craft oak_planks", "m4-invalid-numeric-fixture")
    planner.set_deadline(200.0, 0.0)
    with patch("singularity.core.planner.time.monotonic", clock.monotonic):
        rejected = planner.plan_from_goal("Craft oak_planks", {"inventory": {"oak_log": 1}})
    assert rejected["status"] == "error"
    assert rejected["schema_validation"]["issues"] == [
        "subtask[0]:success_criteria_inventory_count_invalid:oak_planks"
    ]
    assert tasks.tasks == {}
    print("PASS: M4 subtask numeric grounding fails closed on non-equivalent counts")


def test_m4_planner_grounds_probe_5_place_success_criterion_to_machine_state():
    clock = FakeClock()

    class Probe5PlannerLLM(PlannerLLM):
        def chat(self, messages, **kwargs):
            super().chat(messages, **kwargs)
            return json.dumps({
                "status": "planning",
                "reasoning": "place the inventory crafting table nearby",
                "subtasks": [{
                    "title": "Place crafting table for tool progression",
                    "type": "place",
                    "priority": 1,
                    "success_criteria": {"inventory": {"crafting_table": 0}},
                    "preconditions": {
                        "inventory": {"crafting_table": 1},
                        "flags": [],
                    },
                    "depends_on": [],
                }],
                "actions": [{
                    "type": "place",
                    "parameters": {
                        "item": "crafting_table",
                        "x": 106,
                        "y": 135,
                        "z": -29,
                    },
                }],
            })

    tasks = TaskSystem()
    llm = Probe5PlannerLLM(clock)
    planner = Planner(llm, tasks, protocol="m4-fixed-v1")
    goal = "Place crafting table for tool progression"
    planner.start_episode(goal, "m4-probe-5-place-criterion-fixture")
    planner.set_deadline(200.0, 0.0)
    with patch("singularity.core.planner.time.monotonic", clock.monotonic):
        plan = planner.plan_from_goal(
            goal,
            {"inventory": {"oak_log": 5, "crafting_table": 1}},
        )

    assert plan["status"] == "planning"
    assert plan["schema_validation"]["passed"] is True
    assert plan["schema_validation"]["issues"] == []
    grounding = plan["place_success_criteria_grounding"]
    assert grounding["passed"] is True
    assert grounding["policy_id"] == "m4-place-success-criteria-grounding-v1"
    assert grounding["place_action_items"] == ["crafting_table"]
    assert grounding["grounded_subtask_count"] == 1
    assert grounding["removed_inventory_requirement_count"] == 1
    assert len(grounding["normalizations"]) == 1
    assert len(grounding["original_subtasks_sha256"]) == 64
    assert len(grounding["grounded_subtasks_sha256"]) == 64
    assert grounding["original_subtasks_sha256"] != grounding["grounded_subtasks_sha256"]
    normalization = grounding["normalizations"][0]
    assert normalization["source_count_was_positive_integer"] is False
    assert len(normalization["source_value_sha256"]) == 64
    assert normalization["canonical_value"] == "crafting_table"
    assert plan["subtask_numeric_criteria_grounding"]["passed"] is True
    assert plan["subtask_numeric_criteria_grounding"]["inventory_requirement_count"] == 1

    task = next(iter(tasks.tasks.values()))
    assert task.success_criteria == {
        "nearby_block_present": "crafting_table",
    }
    assert task.preconditions == {
        "inventory": {"crafting_table": 1},
        "flags": [],
    }
    tasks.update_task(task.id, status=TaskStatus.ACCEPTED)
    tasks.apply_action_result(
        plan["actions"][0],
        {"success": True, "item": "crafting_table"},
        {
            "inventory": {"oak_log": 5},
            "nearby_blocks": [{"name": "crafting_table"}],
        },
        task_id=task.id,
    )
    assert task.status == TaskStatus.COMPLETED
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "nearby_block_present" in prompt
    assert "never use inventory of the placed item as placement proof" in prompt
    print("PASS: M4 grounds the Probe 5 placement criterion in machine world state")


def test_m4_place_success_criteria_grounding_is_narrow_and_fails_closed():
    def fixture(
        *,
        goal="Place crafting table for tool progression",
        title="Place crafting table",
        task_type="place",
        action_item="crafting_table",
        inventory_item="crafting_table",
        inventory_count=0,
        nearby=None,
        precondition_count=1,
    ):
        criteria = {"inventory": {inventory_item: inventory_count}}
        if nearby is not None:
            criteria["nearby_block_present"] = nearby
        return {
            "goal": goal,
            "plan": {
                "status": "planning",
                "subtasks": [{
                    "title": title,
                    "type": task_type,
                    "success_criteria": criteria,
                    "preconditions": {
                        "inventory": {"crafting_table": precondition_count},
                    },
                }],
                "actions": [{
                    "type": "place",
                    "parameters": {
                        "item": action_item,
                        "x": 106,
                        "y": 135,
                        "z": -29,
                    },
                }],
            },
        }

    positive = fixture(inventory_count=1)
    grounded, report = Planner._ground_m4_place_success_criteria(
        positive["plan"],
        goal=positive["goal"],
    )
    assert report["passed"] is True
    assert report["normalizations"][0]["source_count_was_positive_integer"] is True
    assert grounded["subtasks"][0]["success_criteria"] == {
        "nearby_block_present": "crafting_table",
    }

    controls = [
        (
            fixture(goal="Craft crafting table"),
            "subtask[0]:place_success_criteria_goal_mismatch:crafting_table",
        ),
        (
            fixture(title="Verify tool progression", task_type="verify"),
            "subtask[0]:place_success_criteria_intent_missing:crafting_table",
        ),
        (
            fixture(nearby="oak_planks"),
            "subtask[0]:place_success_criteria_nearby_block_conflict",
        ),
    ]
    for case, expected_issue in controls:
        unchanged, report = Planner._ground_m4_place_success_criteria(
            case["plan"],
            goal=case["goal"],
        )
        assert report["passed"] is False
        assert expected_issue in report["issues"]
        assert unchanged["subtasks"][0]["success_criteria"]["inventory"] == {
            "crafting_table": 0,
        }

    unrelated = fixture(action_item="oak_planks")
    unchanged, report = Planner._ground_m4_place_success_criteria(
        unrelated["plan"],
        goal=unrelated["goal"],
    )
    assert report["passed"] is True
    assert report["grounded_subtask_count"] == 0
    _, numeric_report = Planner._ground_m4_subtask_numeric_criteria(unchanged)
    assert numeric_report["passed"] is False
    assert numeric_report["issues"] == [
        "subtask[0]:success_criteria_inventory_count_invalid:crafting_table",
    ]

    item_alias = fixture(inventory_item="crafting_table ")
    unchanged, report = Planner._ground_m4_place_success_criteria(
        item_alias["plan"],
        goal=item_alias["goal"],
    )
    assert report["passed"] is True
    assert report["grounded_subtask_count"] == 0
    assert unchanged["subtasks"][0]["success_criteria"] == {
        "inventory": {"crafting_table ": 0},
    }

    invalid_precondition = fixture(precondition_count=0)
    grounded, report = Planner._ground_m4_place_success_criteria(
        invalid_precondition["plan"],
        goal=invalid_precondition["goal"],
    )
    assert report["passed"] is True
    _, numeric_report = Planner._ground_m4_subtask_numeric_criteria(grounded)
    assert numeric_report["passed"] is False
    assert numeric_report["issues"] == [
        "subtask[0]:preconditions_inventory_count_invalid:crafting_table",
    ]
    print("PASS: M4 placement criterion grounding is intent-bound and fail-closed")


def test_m4_autonomous_loop_recovers_invalid_planner_envelope_and_transport_failure():
    clock = FakeClock()
    planner = RuntimePlanner()
    action_controller = RuntimeActionController()
    agent = object.__new__(Agent)
    agent.config = Config(planner_protocol="m4-fixed-v1")
    agent.session_logger = RuntimeSessionLogger(clock)
    agent.planner = planner
    agent.task_system = TaskSystem()
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
        "inventory": {"dark_oak_log": 6},
        "inventory_count": 1,
        "health": 20,
    }
    agent._select_autonomous_goal = lambda observation, fallback: fallback
    plans = iter([
        {
            "status": "error",
            "reasoning": "Planner output rejected before execution: planning_actions_missing",
            "actions": [],
            "planner_call_id": "m4-empty-fixture",
            "schema_validation": {
                "passed": False,
                "status": "planning",
                "action_count": 0,
                "issues": ["planning_actions_missing"],
            },
        },
        {
            "status": "error",
            "reasoning": "Planner output rejected before execution: Connection error.",
            "actions": [],
            "planner_call_id": "m4-transport-fixture",
            "schema_validation": {"passed": False, "issues": ["Connection error."]},
            "planner_evidence": {
                "call_id": "m4-transport-fixture",
                "protocol": "m4-fixed-v1",
                "real_llm_call": False,
                "schema_valid": False,
                "error": "Connection error.",
                "transport_evidence": {
                    "policy_id": "single-attempt",
                    "attempt_count": 1,
                    "retry_count": 0,
                    "attempts": [{
                        "attempt_index": 0,
                        "success": False,
                        "error_type": "APIConnectionError",
                        "error_chain": ["APIConnectionError", "ConnectError", "SSLEOFError"],
                    }],
                },
            },
        },
        {
            "status": "complete",
            "reasoning": "machine verifier must decide",
            "actions": [],
            "schema_validation": {"passed": True, "issues": []},
        },
    ])
    agent._think = lambda observation, override_goal=None: next(plans)
    agent._accept_planned_tasks = lambda: None
    agent._record_task_continuity = lambda *args, **kwargs: None
    agent._state_with_causal_context = lambda observation, goal="": observation
    agent._goal_is_verified = lambda *args, **kwargs: (False, None)
    accepted = GoalVerification(
        goal="Prepare shelter before night",
        achieved=True,
        status="achieved",
        confidence=1.0,
        evidence=["fixture verifier accepted exact goal"],
    )
    agent._accept_plan_completion = lambda *args, **kwargs: (True, accepted)
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent._write_memory_context = lambda *args, **kwargs: None
    agent._record_frontier_budget_outcome = lambda *args, **kwargs: None
    agent._finalize_skill_learning_episode = lambda *args, **kwargs: None

    with patch("singularity.core.agent.time.monotonic", clock.monotonic):
        result = agent.run_autonomous(
            max_goals=1,
            max_cycles_per_goal=3,
            max_duration_s=5.0,
        )

    event_types = [event["type"] for event in agent.session_logger.events]
    assert result["goals_completed"] == 1
    assert result["goals_failed"] == 0
    assert result["total_cycles"] == 3
    assert len(planner.replan_reasons) == 1
    assert "planning status requires an executable action" in planner.replan_reasons[0]
    assert "m4_planner_output_recovery" in event_types
    assert "m4_planner_transport_recovery" in event_types
    assert "empty_plan" not in event_types
    recovery = next(
        event for event in agent.session_logger.events
        if event["type"] == "m4_planner_output_recovery"
    )
    assert recovery["data"]["rejected_status"] == "planning"
    assert recovery["data"]["action_count"] == 0
    transport_recovery = next(
        event for event in agent.session_logger.events
        if event["type"] == "m4_planner_transport_recovery"
    )
    assert transport_recovery["data"]["planner_call_id"] == "m4-transport-fixture"
    assert transport_recovery["data"]["error_type"] == "APIConnectionError"
    assert transport_recovery["data"]["same_call_retry_count"] == 0
    assert transport_recovery["data"]["goal_preserved"] is True
    assert transport_recovery["data"]["resume_policy"] == "retry_planner_next_cycle_same_goal"
    print("PASS: M4 keeps the same autonomous goal active after recoverable planner failures")


def test_m4_planner_transport_recovery_fails_closed_for_non_transport_errors():
    base = {
        "status": "error",
        "actions": [],
        "planner_call_id": "m4-nontransport-fixture",
        "planner_evidence": {
            "call_id": "m4-nontransport-fixture",
            "protocol": "m4-fixed-v1",
            "real_llm_call": False,
            "schema_valid": False,
            "error": "fixture failure",
            "transport_evidence": {
                "policy_id": "single-attempt",
                "attempt_count": 1,
                "retry_count": 0,
                "attempts": [{
                    "success": False,
                    "error_type": "AuthenticationError",
                    "error_chain": ["AuthenticationError"],
                }],
            },
        },
    }
    assert Agent._m4_planner_transport_failure(base) == {}

    schema_error = dict(base)
    schema_error["planner_evidence"] = {
        **base["planner_evidence"],
        "real_llm_call": True,
        "error": "planner response is not valid JSON",
    }
    assert Agent._m4_planner_transport_failure(schema_error) == {}

    deadline_error = dict(base)
    deadline_error["planner_evidence"] = {
        **base["planner_evidence"],
        "error": "m4_total_deadline_exhausted_before_planner_call",
        "transport_evidence": {},
    }
    assert Agent._m4_planner_transport_failure(deadline_error) == {}

    malformed_transport = dict(base)
    malformed_transport["planner_call_id"] = "m4-nontransport-fixture"
    malformed_transport["planner_evidence"] = {
        **base["planner_evidence"],
        "transport_evidence": [],
    }
    assert Agent._m4_planner_transport_failure(malformed_transport) == {}


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
    test_m4_planner_rejects_empty_planning_response_and_marks_replan()
    test_m4_planner_normalizes_exact_probe_3_subtask_inventory_aliases()
    test_m4_subtask_numeric_grounding_rejects_non_equivalent_counts()
    test_m4_planner_grounds_probe_5_place_success_criterion_to_machine_state()
    test_m4_place_success_criteria_grounding_is_narrow_and_fails_closed()
    test_m4_autonomous_loop_recovers_invalid_planner_envelope_and_transport_failure()
    test_m4_planner_transport_recovery_fails_closed_for_non_transport_errors()
    test_m4_action_controller_enforces_episode_and_action_deadlines()
    test_m4_bridge_uses_remaining_budget_without_replay()
    test_m4_verifier_return_after_deadline_is_rejected()
    test_session_logger_records_absolute_monotonic_event_time()
    test_m4_autonomous_loop_shares_deadline_and_suppresses_plan_suffix()
    print("\nM4 deadline runtime tests PASSED")
