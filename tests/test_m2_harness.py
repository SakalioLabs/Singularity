"""Offline-only M2 harness tests; no result here is eligible live evidence."""

import os
import sys
import copy
import time
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.agent import Agent
from singularity.core.config import Config, LLMConfig
from singularity.core.planner import Planner
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.evaluation.benchmark_runner import (
    M2_BENCHMARKS,
    M2_PROTOCOL,
    M2_PROTOCOL_SHA256,
    BenchmarkResult,
    BenchmarkRunner,
    m2_convergence_config,
    m2_runtime_profile,
)
from singularity.evaluation.m2_protocol import validate_root_plan, verify_task_outcome
from singularity.evaluation.capability_evidence import _build_m2_pairing_gate


def root_plan(goal="Gather wood and craft workbench", kind="root"):
    return {
        "schema_version": "m2-root-plan-v1",
        "plan_kind": kind,
        "goal": goal,
        "status": "planning",
        "reasoning": "Gather the input before crafting the requested output.",
        "subtasks": [
            {
                "id": "gather_log",
                "title": "Gather one oak log",
                "type": "gather",
                "priority": 1,
                "depends_on": [],
                "preconditions": {},
                "success_criteria": {"inventory": {"oak_log": 1}},
                "rationale": "A log supplies the planks.",
            },
            {
                "id": "craft_table",
                "title": "Craft one crafting table",
                "type": "craft",
                "priority": 2,
                "depends_on": ["gather_log"],
                "preconditions": {"inventory": {"oak_log": 1}},
                "success_criteria": {"inventory": {"crafting_table": 1}},
                "rationale": "The table is the requested terminal item.",
            },
        ],
        "actions": [{"type": "dig", "parameters": {"block": "dark_oak_log", "x": 3, "y": 64, "z": 0}}],
    }


class EvidenceLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.config = LLMConfig(
            provider="openai",
            base_url="https://opencode.ai/zen/go/v1",
            model="deepseek-v4-flash",
            api_key="offline-contract-key",
            max_tokens=4096,
            temperature=0.0,
        )
        self.last_call_metadata = {}
        self.calls = 0
        self.message_batches = []
        self.timeouts = []
        self.client_resets = 0

    def reset_client(self):
        self.client_resets += 1

    def chat(
        self,
        messages,
        response_format=None,
        timeout_s=None,
        extra_body=None,
    ):
        import hashlib
        import json

        self.calls += 1
        self.message_batches.append(messages)
        self.timeouts.append(timeout_s)
        response = json.dumps(self.responses.pop(0))
        self.last_call_metadata = {
            "provider": "openai",
            "base_url": "https://opencode.ai/zen/go/v1",
            "model": "deepseek-v4-flash",
            "temperature": 0.0,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
            "extra_body": dict(extra_body or {}),
            "request_sha256": hashlib.sha256(str(messages).encode()).hexdigest(),
            "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "duration_ms": 25,
            "timeout_s": round(float(timeout_s), 3) if timeout_s is not None else None,
            "max_retries": 0 if timeout_s is not None else None,
            "finish_reason": "stop",
            "reasoning_content_byte_count": 0,
        }
        return response


class M2ProtocolBridge:
    def __init__(self, config):
        self.config = config

    def connect(self):
        return True

    def disconnect(self):
        pass

    def benchmark_protocol(self, profile=""):
        return {
            "success": True,
            "configured": True,
            "profile": M2_PROTOCOL["profile"],
            "protocol_sha256": M2_PROTOCOL_SHA256,
            "minecraft_version": M2_PROTOCOL["minecraft_version"],
            "observed_minecraft_version": M2_PROTOCOL["minecraft_version"],
            "server_type": M2_PROTOCOL["server_type"],
            "server_build": M2_PROTOCOL["server_build"],
            "server_jar_policy": M2_PROTOCOL["server_jar_policy"],
            "agent_id": M2_PROTOCOL["agent_id"],
            "planner_id": M2_PROTOCOL["planner_id"],
            "planner_schema_id": M2_PROTOCOL["planner_schema_id"],
            "planner_schema_sha256": M2_PROTOCOL["planner_schema_sha256"],
            "action_backend_id": M2_PROTOCOL["action_backend_id"],
            "verifier_id": M2_PROTOCOL["verifier_id"],
            "skill_runtime_profile_id": M2_PROTOCOL["skill_runtime_profile_id"],
            "reset_protocol_sha256": M2_PROTOCOL["reset_protocol_sha256"],
            "validation_protocol_sha256": M2_PROTOCOL["validation_protocol_sha256"],
            "seed": M2_PROTOCOL["world_seed"],
            "episode_strategy": M2_PROTOCOL["episode_strategy"],
            "episode_id": "offline-contract-episode",
            "level_name": "offline-contract-episode_bm006",
            "server_jar_sha256": M2_PROTOCOL["server_jar_sha256"],
            "server_brand": "Paper",
            "llm": M2_PROTOCOL["llm"],
            "dependencies": M2_PROTOCOL["dependencies"],
            "runtime_versions": M2_PROTOCOL["runtime_versions"],
            "tasks": M2_PROTOCOL["tasks"],
            "errors": [],
        }


class M2SmokeBridge(M2ProtocolBridge):
    def __init__(self, config):
        super().__init__(config)
        self.built = False

    def reset_benchmark(self, task_id):
        setup = setup_evidence(task_id)
        setup["after_state"]["inventory"] = {"cobblestone": 64}
        setup["structure_baseline"] = empty_structure_snapshot()
        return setup

    def verify_benchmark(self, task_id):
        terminal = terminal_evidence(task_id)
        terminal["inventory"] = {"cobblestone": 9 if self.built else 64}
        terminal["player_position"] = {"x": 5.5, "y": 64, "z": 5.5} if self.built else {"x": 0, "y": 64, "z": 0}
        terminal["structure_post"] = built_structure_snapshot() if self.built else empty_structure_snapshot()
        return terminal

    def build_shelter_5x5(self, params):
        self.built = True
        return {
            "success": True,
            "required_block_count": 55,
            "placed_count": 55,
            "already_present_count": 0,
            "material": "cobblestone",
        }


def empty_structure_snapshot():
    return {
        "origin": {"x": 3, "y": 64, "z": 3},
        "size": {"x": 5, "y": 3, "z": 5},
        "blocks": [
            {"name": "air", "position": {"x": x, "y": y, "z": z}}
            for x in range(3, 8)
            for y in range(64, 67)
            for z in range(3, 8)
        ],
    }


def built_structure_snapshot():
    snapshot = empty_structure_snapshot()
    for block in snapshot["blocks"]:
        position = block["position"]
        x, y, z = position["x"], position["y"], position["z"]
        perimeter = x in {3, 7} or z in {3, 7}
        entrance = x == 5 and z == 3 and y in {64, 65}
        if (perimeter and y in {64, 65} and not entrance) or y == 66:
            block["name"] = "cobblestone"
    return snapshot


def action_event(action_type, parameters=None, **result):
    return {
        "type": "action",
        "data": {
            "action": {"type": action_type, "parameters": parameters or {}},
            "result": {"success": True, "action_type": action_type, **result},
            "pre_observation": {"inventory": {}},
            "post_observation": {"inventory": {"crafting_table": 1}},
        },
    }


def setup_evidence(task_id="BM-006"):
    return {
        "success": True,
        "profile": M2_PROTOCOL["profile"],
        "protocol_sha256": M2_PROTOCOL_SHA256,
        "reset_protocol_sha256": M2_PROTOCOL["reset_protocol_sha256"],
        "validation_protocol_sha256": M2_PROTOCOL["validation_protocol_sha256"],
        "task_id": task_id,
        "seed": M2_PROTOCOL["world_seed"],
        "server_jar_sha256": M2_PROTOCOL["server_jar_sha256"],
        "after_state": {"inventory": {}},
        "checks": {
            "inventory_exact": True,
            "position_at_spawn": True,
            "position_distance": 0.0,
            "game_mode": True,
            "difficulty": True,
            "dimension": True,
            "daytime": True,
            "time_initialized": True,
            "weather": True,
            "health": True,
            "food": True,
            "fixture": True,
        },
    }


def terminal_evidence(task_id="BM-006"):
    return {
        "success": True,
        "profile": M2_PROTOCOL["profile"],
        "protocol_sha256": M2_PROTOCOL_SHA256,
        "validation_protocol_sha256": M2_PROTOCOL["validation_protocol_sha256"],
        "task_id": task_id,
        "inventory": {"crafting_table": 1},
    }


def test_m2_runtime_is_fixed_and_refuses_missing_llm():
    missing = m2_runtime_profile(m2_convergence_config(Config()))
    assert not missing["eligible_configuration"]
    assert not missing["settings"]["llm_configured"]

    configured = m2_convergence_config(Config(llm=LLMConfig(api_key="offline-contract-key")))
    profile = m2_runtime_profile(configured)
    assert profile["eligible_configuration"]
    assert profile["settings"]["base_url"] == "https://opencode.ai/zen/go/v1"
    assert profile["settings"]["temperature"] == 0.0
    assert not profile["settings"]["plan_cache"]
    assert not profile["settings"]["blocked_plan_rule_fallback"]
    assert profile["settings"]["require_llm_root_plan"]
    assert profile["deadline_policy_id"] == "m2-hard-total-deadline-v1"
    assert profile["settings"]["planner_max_retries"] == 0
    assert profile["settings"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert profile["settings"]["llm_transport_policy_id"] == "m2-bounded-transport-retry-v1"
    print("PASS: M2 runtime fixes the LLM contract and refuses a missing real-provider credential")


def test_m2_prompt_pins_priority_and_equip_criteria_contracts():
    planner = Planner(EvidenceLLM([]), TaskSystem(), protocol="m2-fixed-v1")
    planner._expected_plan_kind = "root"
    prompt = planner._m2_system_prompt()

    assert "integer from 1 through 5" in prompt
    assert "set priority=1 on every subtask; dependencies alone encode order" in prompt
    assert 'success_criteria {"action": {"type": "equip"}, "result": {"success": true}}' in prompt
    assert "do not invent equipment or equipped criteria" in prompt
    assert "do not\ncreate a subtask whose success criteria are already satisfied" in prompt
    assert "A successful move_to to an unchanged target must not be repeated" in prompt
    assert "already within 4.5 blocks" in prompt
    assert "successful-action summary has move_to=0" in prompt
    assert "does not require a crafting table" in prompt
    user_prompt = planner._build_planning_prompt(
        "Craft wooden pickaxe and get cobblestone",
        {
            "inventory": {"oak_log": 2},
            "nearby_blocks": [
                {"name": "crafting_table", "position": {"x": 1, "y": 64, "z": 0}},
                {"name": "stone", "position": {"x": 4, "y": 64, "z": 0}},
            ],
        },
        "",
    )
    assert "two initial logs yield eight planks" in user_prompt
    assert "do not gather extra logs or craft/place another table" in user_prompt
    assert "after that first successful move" in user_prompt
    assert "direct dig actions without moving between them" in user_prompt
    assert '"verified_initial_inventory": {"oak_log": 2}' in user_prompt
    torch_prompt = planner._build_planning_prompt(
        "Craft a torch",
        {"inventory": {"coal": 1, "oak_planks": 2}},
        "",
    )
    assert "2x2 inventory craft" in torch_prompt
    assert "one coal plus one stick then crafts four torches" in torch_prompt
    assert "do not gather logs, craft a table, or place blocks" in torch_prompt
    assert '"verified_initial_inventory": {"coal": 1, "oak_planks": 2}' in torch_prompt
    shelter_prompt = planner._build_planning_prompt(
        "Build a simple 5x5 shelter",
        {
            "inventory": {"cobblestone": 64},
            "benchmark_context": {
                "construction_zone": {
                    "origin": {"x": 3, "y": 64, "z": 3},
                    "size": {"x": 5, "y": 3, "z": 5},
                },
            },
        },
        "",
    )
    assert "at least two auditable nodes" in shelter_prompt
    assert "second node depending on the first" in shelter_prompt
    assert "exactly one immediate build_shelter_5x5 action" in shelter_prompt
    assert "Do not emit move_to or individual place actions" in shelter_prompt
    assert '"verified_initial_inventory": {"cobblestone": 64}' in shelter_prompt
    print("PASS: M2 prompt states priority bounds, equip evidence, and satisfied-state reuse explicitly")


def test_strict_planner_gates_tasks_and_preserves_root_identity():
    continuation = root_plan(kind="continuation")
    llm = EvidenceLLM([root_plan(), continuation, root_plan(kind="replan")])
    tasks = TaskSystem()
    planner = Planner(llm, tasks, protocol="m2-fixed-v1")
    planner.start_episode("Gather wood and craft workbench", "offline-contract-session")
    planner.set_deadline(time.monotonic() + 300.0, 30.0)

    first = planner.plan_from_goal("Gather wood and craft workbench", {"inventory": {}})
    assert first["schema_validation"]["passed"]
    assert '"required":["block","x","y","z"]' in llm.message_batches[0][0]["content"]
    assert "do not use\nblock_name, target, position, or block_position aliases" in llm.message_batches[0][0]["content"]
    assert planner.last_call_evidence["real_llm_call"]
    assert planner.last_call_evidence["plan_kind"] == "root"
    assert 0 < llm.timeouts[0] <= 270.0
    assert planner.last_call_evidence["provider_metadata"]["max_retries"] == 0
    assert planner.last_call_evidence["provider_metadata"]["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert planner.last_call_evidence["transport_evidence"]["attempt_count"] == 1
    assert len(tasks.tasks) == 2
    root_id = first["root_plan_id"]

    action_summary = {
        "profile": "m2-successful-action-summary-v1",
        "successful_action_count": 1,
        "successful_action_types": {"dig": 1},
        "included_action_count": 1,
        "truncated": False,
        "actions": [{"type": "dig", "block": "dark_oak_log", "inventory_delta": {"dark_oak_log": 1}}],
    }
    second = planner.plan_from_goal(
        "Gather wood and craft workbench",
        {"inventory": {"oak_log": 1}, "m2_successful_action_summary": action_summary},
    )
    assert second["schema_validation"]["passed"]
    assert second["root_plan_id"] == root_id
    assert planner.last_call_evidence["plan_kind"] == "continuation"
    assert planner.last_call_evidence["successful_action_summary"] == action_summary
    assert '"successful_action_types": {"dig": 1}' in llm.message_batches[1][1]["content"]
    assert len(tasks.tasks) == 2

    planner.request_replan("navigation target was not reached")
    third = planner.plan_from_goal("Gather wood and craft workbench", {"inventory": {"oak_log": 1}})
    assert third["schema_validation"]["passed"]
    assert planner.last_call_evidence["plan_kind"] == "replan"
    assert len(tasks.tasks) == 2

    invalid_llm = EvidenceLLM([{**root_plan(), "actions": []}])
    invalid_tasks = TaskSystem()
    invalid = Planner(invalid_llm, invalid_tasks, protocol="m2-fixed-v1")
    invalid.set_deadline(time.monotonic() + 300.0, 30.0)
    rejected = invalid.plan_from_goal("Gather wood and craft workbench", {})
    assert rejected["status"] == "error"
    assert "planning_actions_missing" in rejected["schema_validation"]["issues"]
    assert len(invalid_tasks.tasks) == 0

    expired_llm = EvidenceLLM([root_plan()])
    expired = Planner(expired_llm, TaskSystem(), protocol="m2-fixed-v1")
    expired.set_deadline(time.monotonic() + 29.0, 30.0)
    expired_plan = expired.plan_from_goal("Gather wood and craft workbench", {})
    assert expired_plan["status"] == "error"
    assert expired_llm.calls == 0
    assert "m2_total_deadline_exhausted_before_planner_call" in expired_plan["schema_validation"]["issues"]

    class FailingLLM(EvidenceLLM):
        def chat(
            self,
            messages,
            response_format=None,
            timeout_s=None,
            extra_body=None,
        ):
            self.last_call_metadata = {"timeout_s": round(float(timeout_s), 3), "max_retries": 0}
            try:
                raise TimeoutError("offline transport probe")
            except TimeoutError as cause:
                raise ConnectionError("offline connection failure") from cause

    failing = Planner(FailingLLM([]), TaskSystem(), protocol="m2-fixed-v1")
    failing.set_deadline(time.monotonic() + 300.0, 30.0)
    failed_plan = failing.plan_from_goal("Gather wood and craft workbench", {})
    assert failed_plan["status"] == "error"
    assert failing.last_call_evidence["provider_metadata"]["error_chain"] == [
        "ConnectionError",
        "TimeoutError",
    ]

    class APIConnectionError(Exception):
        pass

    class FlakyLLM(EvidenceLLM):
        def chat(self, *args, **kwargs):
            if self.calls == 0:
                self.calls += 1
                self.last_call_metadata = {
                    "timeout_s": round(float(kwargs["timeout_s"]), 3),
                    "max_retries": 0,
                }
                raise APIConnectionError("offline remote disconnect")
            return super().chat(*args, **kwargs)

    flaky = Planner(FlakyLLM([root_plan()]), TaskSystem(), protocol="m2-fixed-v1")
    flaky.set_deadline(time.monotonic() + 300.0, 30.0)
    recovered_plan = flaky.plan_from_goal("Gather wood and craft workbench", {})
    assert recovered_plan["schema_validation"]["passed"]
    assert flaky.llm.client_resets == 1
    assert flaky.last_call_evidence["transport_evidence"]["attempt_count"] == 2
    assert flaky.last_call_evidence["transport_evidence"]["retry_count"] == 1
    assert flaky.last_call_evidence["transport_evidence"]["attempts"][0]["success"] is False
    assert flaky.last_call_evidence["transport_evidence"]["attempts"][1]["success"] is True
    print("PASS: Strict planner creates no executable tasks before schema validation and deduplicates replans")


def test_agent_suppresses_actions_when_planning_crosses_goal_deadline():
    class LoggerStub:
        def __init__(self):
            self.events = []
            self.session_id = "offline-deadline-session"

        def log(self, event_type, data, level="INFO"):
            self.events.append({"type": event_type, "data": data, "level": level})

        def log_goal_start(self, goal):
            self.log("goal_start", {"goal": goal})

        def log_plan(self, plan):
            self.log("plan", plan)

        def log_observation(self, observation):
            self.log("observation", observation)

        def log_error(self, error, context=None):
            self.log("error", {"error": error, "context": context or {}}, level="ERROR")

        def log_goal_end(self, goal, result):
            self.log("goal_end", {"goal": goal, "result": result})

        def get_summary(self):
            return {"session_id": self.session_id}

    class PlannerStub:
        def start_episode(self, goal, episode_id):
            self.episode = (goal, episode_id)

        def set_deadline(self, deadline, action_guard_s):
            self.deadline = deadline
            self.action_guard_s = action_guard_s

    class ActionControllerStub:
        calls = 0

        def execute(self, action, observation):
            self.calls += 1
            return {"success": True}

    agent = object.__new__(Agent)
    agent.config = Config(planner_protocol="m2-fixed-v1")
    agent.session_logger = LoggerStub()
    agent.planner = PlannerStub()
    agent.action_controller = ActionControllerStub()
    agent.explorer = type("ExplorerStub", (), {"record_position": lambda self, position: None})()
    agent._skill_fallback_goals = set()
    agent._goal_fingerprint = lambda goal: goal
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent._write_memory_context = lambda *args, **kwargs: None
    agent._record_task_continuity = lambda *args, **kwargs: None
    agent._finalize_skill_learning_episode = lambda *args, **kwargs: None
    agent._obs_summary = lambda observation: observation
    agent._observe = lambda: {"position": {}, "inventory": {}, "health": 20}

    def slow_plan(observation):
        time.sleep(0.03)
        return {
            "status": "planning",
            "reasoning": "This plan arrived after the total deadline.",
            "actions": [{"type": "wait", "parameters": {"ms": 1}}],
        }

    agent._think = slow_plan
    result = agent.run_goal("Gather wood and craft workbench", max_cycles=2, max_duration_s=0.01)
    assert result["termination_reason"] == "max_duration"
    assert not result["completed"]
    assert agent.action_controller.calls == 0
    assert agent.planner.action_guard_s == 30.0
    assert any(event["type"] == "goal_deadline_exceeded" for event in agent.session_logger.events)
    print("PASS: Agent preserves late planner evidence but suppresses every post-deadline action")


def test_task_system_records_proposed_active_terminal_paths():
    tasks = TaskSystem()
    first = tasks.create_task(
        "Gather one oak log",
        success_criteria={"inventory": {"oak_log": 1}},
        plan_node_id="gather_log",
        root_plan_id="root-test",
    )
    second = tasks.create_task(
        "Craft one crafting table",
        success_criteria={"inventory": {"crafting_table": 1}},
        depends_on=[first.id],
        plan_node_id="craft_table",
        root_plan_id="root-test",
    )
    tasks.update_task(first.id, status=TaskStatus.ACCEPTED)
    tasks.update_task(second.id, status=TaskStatus.ACCEPTED)
    tasks.apply_action_result(
        {"type": "dig", "parameters": {}},
        {"success": True},
        {"inventory": {"oak_log": 1}},
    )
    tasks.apply_action_result(
        {"type": "craft", "parameters": {"item": "crafting_table"}},
        {"success": True, "item": "crafting_table"},
        {"inventory": {"crafting_table": 1}},
    )
    assert [row["to_status"] for row in first.status_history] == ["proposed", "accepted", "active", "completed"]
    assert [row["to_status"] for row in second.status_history] == ["proposed", "accepted", "active", "completed"]
    print("PASS: Task state evidence preserves proposed, active, and terminal transitions")


def test_machine_verified_plan_closes_dependent_state_paths():
    tasks = TaskSystem()
    first = tasks.create_task(
        "Build the fixed shelter",
        success_criteria={"structure": "shelter-outer-5x5-v1"},
        plan_node_id="build_shelter",
        root_plan_id="root-shelter",
    )
    second = tasks.create_task(
        "Verify shelter occupancy",
        success_criteria={"structure": "shelter-outer-5x5-v1"},
        depends_on=[first.id],
        plan_node_id="verify_shelter",
        root_plan_id="root-shelter",
    )
    tasks.update_task(first.id, status=TaskStatus.ACCEPTED)
    tasks.update_task(second.id, status=TaskStatus.ACCEPTED)
    tasks.apply_action_result(
        {"type": "build_shelter_5x5", "parameters": {}},
        {"success": True, "template_id": "shelter-outer-5x5-v1"},
        {"inventory": {"cobblestone": 9}},
        task_id=first.id,
    )
    assert first.status == TaskStatus.ACTIVE
    completed = tasks.complete_verified_plan(
        "root-shelter",
        {"verification": {"matched_rules": ["m2:machine_verifier"]}},
    )
    assert completed == [first.id, second.id]
    assert [row["to_status"] for row in first.status_history] == ["proposed", "accepted", "active", "completed"]
    assert [row["to_status"] for row in second.status_history] == ["proposed", "accepted", "active", "completed"]
    assert first.result["completed_by"] == "machine_goal_verifier"
    assert second.result["completed_by"] == "machine_goal_verifier"
    print("PASS: machine-verified M2 goals close dependent task paths without inventing actions")


def test_m2_action_feedback_binds_consumptive_action_to_pre_action_task():
    tasks = TaskSystem()
    task = tasks.create_task(
        "Craft planks from log",
        status=TaskStatus.ACCEPTED,
        preconditions={"inventory": {"dark_oak_log": 1}},
        success_criteria={"inventory": {"dark_oak_planks": 4}},
        plan_node_id="craft_planks",
        root_plan_id="root-consumptive-action",
    )

    agent = object.__new__(Agent)
    agent.config = Config(planner_protocol="m2-fixed-v1")
    agent.task_system = tasks
    agent.current_goal = "Gather wood and craft workbench"
    agent._observe = lambda: {"inventory": {"dark_oak_planks": 4}}
    agent._write_memory_context = lambda *args, **kwargs: None
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent._record_task_continuity = lambda *args, **kwargs: None
    agent._flush_task_state_transitions = lambda *args, **kwargs: None
    agent._obs_summary = lambda observation: observation
    agent.explorer = type("ExplorerStub", (), {"record_position": lambda self, position: None})()
    agent.memory = object()
    agent.session_logger = type("LoggerStub", (), {"log_observation": lambda self, value: None})()

    observation = agent._apply_action_feedback(
        {"type": "craft", "parameters": {"item": "dark_oak_planks", "count": 1}},
        {"success": True, "item": "dark_oak_planks", "count": 1},
        {"inventory": {"dark_oak_log": 1}},
        {"cycle": 4, "goal": agent.current_goal},
    )

    assert observation["inventory"] == {"dark_oak_planks": 4}
    assert task.status == TaskStatus.COMPLETED
    assert task.status_history[-2]["to_status"] == "active"
    assert task.status_history[-1]["to_status"] == "completed"
    print("PASS: M2 action feedback preserves task ownership across consumptive post-state changes")


def test_m2_successful_action_summary_is_current_goal_bounded_and_typed():
    agent = object.__new__(Agent)
    agent._skill_episode_start_index = 1
    agent.session_logger = type("LoggerStub", (), {})()
    agent.session_logger.events = [
        {"type": "action", "data": {"action": {"type": "wait"}, "result": {"success": True}}},
        {
            "type": "action",
            "data": {
                "action": {
                    "type": "dig",
                    "parameters": {"block": "dark_oak_log", "x": 94, "y": 142, "z": -31},
                },
                "result": {"success": True, "block": "dark_oak_log"},
                "pre_observation": {"inventory": {}},
                "post_observation": {"inventory": {"dark_oak_log": 1}},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "dark_oak_planks", "count": 1}},
                "result": {"success": False, "item": "dark_oak_planks"},
            },
        },
    ]

    summary = agent._m2_successful_action_summary()
    assert summary["profile"] == "m2-successful-action-summary-v1"
    assert summary["successful_action_count"] == 1
    assert summary["successful_action_types"] == {"dig": 1}
    assert summary["actions"] == [{
        "type": "dig",
        "block": "dark_oak_log",
        "position": {"x": 94.0, "y": 142.0, "z": -31.0},
        "inventory_delta": {"dark_oak_log": 1},
    }]
    print("PASS: M2 planner action history includes only bounded typed successes from the current goal")


def test_m2_harness_preflight_and_session_evidence_contract():
    config = Config(llm=LLMConfig(api_key="offline-contract-key"))
    runner = BenchmarkRunner(config, bridge_factory=M2ProtocolBridge)
    assert runner._check_m2_llm_configuration().status == "pass"
    assert runner._check_m2_harness().status == "pass"

    plan = root_plan()
    schema = validate_root_plan(plan, expected_goal=plan["goal"])
    root_id = "root-contract"
    call = {
        "plan_kind": "root",
        "real_llm_call": True,
        "schema_valid": True,
        "schema_validation": schema,
        "root_plan_id": root_id,
        "response_sha256": "b" * 64,
        "provider_metadata": {
            "provider": "openai",
            "base_url": "https://opencode.ai/zen/go/v1",
            "model": "deepseek-v4-flash",
            "temperature": 0.0,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
            "extra_body": {"thinking": {"type": "disabled"}},
            "request_sha256": "a" * 64,
            "total_tokens": 150,
            "duration_ms": 25,
            "timeout_s": 200.0,
            "max_retries": 0,
            "finish_reason": "stop",
            "reasoning_content_byte_count": 0,
        },
        "deadline_policy": {
            "policy_id": M2_PROTOCOL["deadline_policy"]["id"],
            "remaining_before_call_s": 230.0,
            "action_guard_s": 30.0,
            "request_timeout_s": 200.0,
            "max_retries": 0,
        },
        "transport_evidence": {
            "policy_id": M2_PROTOCOL["llm_transport_policy"]["id"],
            "attempt_count": 1,
            "retry_count": 0,
            "attempts": [{
                "attempt_index": 0,
                "success": True,
                "timeout_s": 200.0,
                "sdk_max_retries": 0,
                "finish_reason": "stop",
            }],
        },
    }
    plan.update({
        "root_plan_id": root_id,
        "schema_validation": schema,
    })
    actions = [
        action_event("dig", {"x": 3, "y": 64, "z": 0}, block="oak_log", block_removed=True, pickup_observed=True),
        action_event("craft", {"item": "oak_planks"}, item="oak_planks"),
        action_event("craft", {"item": "crafting_table"}, item="crafting_table"),
    ]
    setup = setup_evidence()
    terminal = terminal_evidence()
    outcome = verify_task_outcome(
        "BM-006",
        setup_evidence=setup,
        terminal_evidence=terminal,
        action_events=actions,
    )
    base_ts = 1000.0
    events = [
        {"type": "benchmark_runtime_profile", "data": m2_runtime_profile(m2_convergence_config(config))},
        {"type": "benchmark_reset", "data": setup},
        {"type": "goal_start", "ts": base_ts, "elapsed_s": 1.0, "data": {"goal": plan["goal"]}},
        {
            "type": "goal_limits",
            "ts": base_ts + 0.01,
            "elapsed_s": 1.01,
            "data": {
                "max_cycles": M2_BENCHMARKS[0].timeout_cycles,
                "max_duration_s": M2_BENCHMARKS[0].max_duration_s,
                "deadline_policy_id": M2_PROTOCOL["deadline_policy"]["id"],
                "action_guard_ms": M2_PROTOCOL["deadline_policy"]["action_guard_ms"],
            },
        },
        {"type": "llm_planner_call", "data": call},
        {"type": "plan", "data": plan},
    ]
    for node_id in ("gather_log", "craft_table"):
        for status in ("proposed", "accepted", "active", "completed"):
            events.append({
                "type": "task_state_transition",
                "data": {
                    "root_plan_id": root_id,
                    "plan_node_id": node_id,
                    "to_status": status,
                },
            })
    for offset, action in enumerate(actions, start=10):
        action["ts"] = base_ts + offset
        action["elapsed_s"] = 1.0 + offset
    events.extend(actions)
    events.extend([
        {
            "type": "goal_verification",
            "data": {
                "achieved": True,
                "status": "achieved",
                "matched_rules": ["m2:machine_verifier"],
            },
        },
        {
            "type": "goal_end",
            "ts": base_ts + 20.0,
            "elapsed_s": 21.0,
            "data": {
                "goal": plan["goal"],
                "result": {
                    "completed": True,
                    "termination_reason": "goal_verified",
                    "max_duration_s": M2_BENCHMARKS[0].max_duration_s,
                    "elapsed_s": 20.0,
                },
            },
        },
        {"type": "benchmark_terminal_evidence", "data": terminal},
    ])
    report = runner._validate_m2_session_evidence(
        M2_BENCHMARKS[0],
        events,
        setup,
        terminal,
        outcome,
        True,
    )
    assert report["passed"], report["issues"]
    assert report["valid_root_call_count"] == 1
    assert report["complete_task_transition_node_count"] == 2

    missing_root = runner._validate_m2_session_evidence(
        M2_BENCHMARKS[0],
        [event for event in events if event["type"] != "llm_planner_call"],
        setup,
        terminal,
        outcome,
        True,
    )
    assert not missing_root["passed"]
    assert "single_valid_llm_root_call_missing" in missing_root["issues"]

    overrun_events = copy.deepcopy(events)
    overrun_goal_end = next(event for event in overrun_events if event["type"] == "goal_end")
    overrun_goal_end["data"]["result"]["elapsed_s"] = 240.5
    overrun_events.append({
        "type": "goal_deadline_exceeded",
        "ts": base_ts + 240.1,
        "elapsed_s": 241.1,
        "data": {"max_duration_s": 240.0, "elapsed_s": 240.1},
    })
    overrun_action = copy.deepcopy(actions[0])
    overrun_action["ts"] = base_ts + 240.2
    overrun_action["elapsed_s"] = 241.2
    overrun_events.append(overrun_action)
    overrun = runner._validate_m2_session_evidence(
        M2_BENCHMARKS[0],
        overrun_events,
        setup,
        terminal,
        outcome,
        True,
    )
    assert not overrun["passed"]
    assert "m2_goal_duration_exceeded" in overrun["issues"]
    assert "m2_deadline_exceeded_event_present" in overrun["issues"]
    assert "m2_post_deadline_action_present" in overrun["issues"]
    print("PASS: M2 harness accepts a complete contract and rejects post-hoc plans without a real root call")


def test_m2_result_serialization_preserves_goal_deadline_fields():
    with tempfile.TemporaryDirectory() as output_dir:
        runner = BenchmarkRunner(Config(), output_dir=output_dir)
        runner.results = [BenchmarkResult(
            task_id="BM-006",
            task_name="Gather wood and craft workbench",
            status="fail",
            duration_s=23.5,
            goal_elapsed_s=20.25,
            max_duration_s=240.0,
        )]
        runner.save_results("deadline-fields.json")
        row = json.loads(
            open(os.path.join(output_dir, "deadline-fields.json"), encoding="utf-8").read()
        )[0]
        assert row["duration_s"] == 23.5
        assert row["goal_elapsed_s"] == 20.25
        assert row["max_duration_s"] == 240.0
    print("PASS: M2 result artifacts preserve independently auditable goal deadline fields")


def test_m2_pairing_gate_requires_skill_off_and_executed_skill_on_arms():
    records = []
    for task_id in ("BM-006", "BM-007"):
        for replicate in range(1, 4):
            pair_id = f"{task_id.lower()}-pair-{replicate}"
            for arm in ("baseline", "candidate"):
                records.append({
                    "task_id": task_id,
                    "outcome": "success",
                    "protocol_hash": M2_PROTOCOL_SHA256,
                    "session_id": f"{task_id}-{arm}-{replicate}",
                    "episode_id": f"episode-{task_id}-{arm}-{replicate}",
                    "experiment_metadata": {
                        "arm": arm,
                        "pair_id": pair_id,
                        "replicate_id": str(replicate),
                        "skill_execution_mode": "off" if arm == "baseline" else "runtime",
                        "target_skill_id": "" if arm == "baseline" else "learned:test",
                    },
                    "m2_metrics": {
                        "planner_call_count": 2,
                        "skill_selected_count": 0 if arm == "baseline" else 1,
                        "skill_action_success_count": 0 if arm == "baseline" else 1,
                        "failure_replan_proved": task_id == "BM-007" and replicate == 1 and arm == "candidate",
                    },
                })
    approved = _build_m2_pairing_gate(records, 3)
    assert approved["approved"]
    assert approved["tasks"]["BM-006"]["eligible_pair_count"] == 3

    broken = [dict(record) for record in records]
    broken[-1] = {
        **broken[-1],
        "m2_metrics": {"skill_selected_count": 0, "skill_action_success_count": 0},
    }
    rejected = _build_m2_pairing_gate(broken, 3)
    assert not rejected["approved"]
    assert "BM-007:needs_1_more_eligible_skill_pairs" in rejected["missing"]
    print("PASS: M2 pairing gate requires three comparable skill-off/skill-executed pairs per composite task")


def test_m2_harness_smoke_rejects_empty_live_structure():
    runner = BenchmarkRunner(Config(), bridge_factory=M2SmokeBridge)
    report = runner.run_m2_harness_smoke("BM-010")
    assert report["ok"], report
    assert report["checks"]["construction_baseline_empty"]
    assert report["checks"]["empty_structure_still_rejected"]
    assert report["false_positive_probe"]["passed"] is False
    assert report["counts_toward_live_observed"] is False
    print("PASS: Harness smoke accepts live reset evidence only when the empty BM-010 false positive is rejected")


def test_m2_template_smoke_requires_verified_55_block_delta():
    runner = BenchmarkRunner(Config(), bridge_factory=M2SmokeBridge)
    report = runner.run_m2_harness_smoke("BM-010", execute_template=True)
    assert report["ok"], report
    assert report["checks"]["template_action_success"]
    assert report["checks"]["template_outcome_verified"]
    assert report["template_outcome"]["shelter_proof"]["episode_delta_block_count"] == 55
    assert report["counts_toward_repeat_verified"] is False
    print("PASS: Template smoke requires all 55 episode-delta blocks and an independently verified shelter")


if __name__ == "__main__":
    test_m2_runtime_is_fixed_and_refuses_missing_llm()
    test_m2_prompt_pins_priority_and_equip_criteria_contracts()
    test_strict_planner_gates_tasks_and_preserves_root_identity()
    test_agent_suppresses_actions_when_planning_crosses_goal_deadline()
    test_task_system_records_proposed_active_terminal_paths()
    test_machine_verified_plan_closes_dependent_state_paths()
    test_m2_action_feedback_binds_consumptive_action_to_pre_action_task()
    test_m2_successful_action_summary_is_current_goal_bounded_and_typed()
    test_m2_harness_preflight_and_session_evidence_contract()
    test_m2_result_serialization_preserves_goal_deadline_fields()
    test_m2_pairing_gate_requires_skill_off_and_executed_skill_on_arms()
    test_m2_harness_smoke_rejects_empty_live_structure()
    test_m2_template_smoke_requires_verified_55_block_delta()
    print("M2 harness tests PASSED")
