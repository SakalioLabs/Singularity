"""Offline-only tests for the fixed M1 benchmark harness."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.evaluation.benchmark_runner import (
    M1_BENCHMARKS,
    M1_PROTOCOL,
    M1_PROTOCOL_SHA256,
    BenchmarkRunner,
    m1_convergence_config,
    m1_runtime_profile,
)
from singularity.logging.session_logger import SessionLogger


def protocol_response(**overrides):
    response = {
        "success": True,
        "configured": True,
        "profile": M1_PROTOCOL["profile"],
        "protocol_sha256": M1_PROTOCOL_SHA256,
        "minecraft_version": M1_PROTOCOL["minecraft_version"],
        "observed_minecraft_version": M1_PROTOCOL["minecraft_version"],
        "server_type": M1_PROTOCOL["server_type"],
        "server_jar_policy": M1_PROTOCOL["server_jar_policy"],
        "agent_id": M1_PROTOCOL["agent_id"],
        "planner_id": M1_PROTOCOL["planner_id"],
        "action_backend_id": M1_PROTOCOL["action_backend_id"],
        "verifier_id": M1_PROTOCOL["verifier_id"],
        "server_brand": "Paper",
        "seed": M1_PROTOCOL["world_seed"],
        "episode_id": "offline-test-episode",
        "level_name": "offline-test-episode_bm002",
        "server_jar_sha256": "a" * 64,
        "episode_strategy": M1_PROTOCOL["episode_strategy"],
        "dependencies": M1_PROTOCOL["dependencies"],
        "tasks": M1_PROTOCOL["tasks"],
        "reset_supported": True,
        "errors": [],
    }
    response.update(overrides)
    return response


class ProtocolBridge:
    def __init__(self, config, protocol=None):
        self.config = config
        self.protocol = protocol or protocol_response()

    def connect(self):
        return True

    def disconnect(self):
        pass

    def benchmark_protocol(self):
        return self.protocol


class FakeExplorer:
    def __init__(self):
        self.base = None

    def set_base(self, x, y, z):
        self.base = (x, y, z)


class FakeBenchmarkBot:
    def __init__(self, task, reset_success=True):
        self.task = task
        self.reset_success = reset_success
        self.inventory = dict(task.initial_inventory)

    def reset_benchmark(self, task_id):
        checks = {
            "inventory_exact": self.reset_success,
            "position_at_spawn": self.reset_success,
            "position_distance": 0.0,
            "game_mode": self.reset_success,
            "difficulty": self.reset_success,
            "dimension": self.reset_success,
            "daytime": self.reset_success,
            "time_initialized": self.reset_success,
            "weather": self.reset_success,
            "health": self.reset_success,
            "food": self.reset_success,
            "fixture": self.reset_success,
        }
        return {
            "success": self.reset_success,
            "error": "" if self.reset_success else "reset postconditions failed",
            "profile": M1_PROTOCOL["profile"],
            "protocol_sha256": M1_PROTOCOL_SHA256,
            "episode_id": "offline-test-episode",
            "level_name": "offline-test-episode_bm002",
            "seed": "12345",
            "server_jar_sha256": "a" * 64,
            "server_brand": "Paper",
            "observed_minecraft_version": M1_PROTOCOL["minecraft_version"],
            "task_id": task_id,
            "before_state": {"position": {"x": 4, "y": 64, "z": 4}, "inventory": {"dirt": 2}},
            "after_state": {"position": {"x": 0, "y": 64, "z": 0}, "inventory": dict(self.task.initial_inventory)},
            "checks": checks,
            "failed_checks": [] if self.reset_success else ["inventory_exact"],
        }

    def get_inventory(self):
        return [
            {"name": name, "count": count}
            for name, count in self.inventory.items()
            if count > 0
        ]


class FakeBenchmarkAgent:
    created = []
    task = None
    reset_success = True
    goal_verified = True
    connect_success = True

    def __init__(self, config):
        self.config = config
        self.task = type(self).task
        self.bot = FakeBenchmarkBot(self.task, type(self).reset_success)
        self.explorer = FakeExplorer()
        self.session_logger = SessionLogger(log_dir=config.log_dir)
        self.run_limits = None
        type(self).created.append(self)

    def connect(self):
        success = type(self).connect_success
        self.session_logger.log_connect(self.config.bot.host, self.config.bot.port, success)
        return success

    def run_goal(self, goal, max_cycles=100, max_duration_s=None):
        self.run_limits = (max_cycles, max_duration_s)
        expected_item, expected_count = next(iter(self.task.success_criteria.items()))
        before_inventory = dict(self.bot.inventory)
        self.bot.inventory[expected_item] = expected_count
        action_type = "dig" if self.task.id in {"BM-001", "BM-004"} else "craft"
        self.session_logger.log("action", {
            "action": {"type": action_type, "parameters": {"item": expected_item}},
            "result": {"success": True, "action_type": action_type, "item": expected_item},
            "pre_observation": {
                "position": {"x": 0, "y": 64, "z": 0},
                "inventory": before_inventory,
                "nearby_blocks": [{"name": "oak_log", "position": {"x": 1, "y": 64, "z": 0}}],
            },
            "post_observation": {
                "position": {"x": 0, "y": 64, "z": 0},
                "inventory": dict(self.bot.inventory),
                "nearby_blocks": [],
            },
            "action_context": {"cycle": 1, "goal": goal},
        })
        self.session_logger.log("goal_verification", {
            "goal": goal,
            "achieved": type(self).goal_verified,
            "status": "achieved" if type(self).goal_verified else "failed",
        })
        result = {
            "goal": goal,
            "cycles": 1,
            "completed": type(self).goal_verified,
            "termination_reason": "goal_verified" if type(self).goal_verified else "max_cycles",
        }
        self.session_logger.log_goal_end(goal, result)
        result["summary"] = self.session_logger.get_summary()
        return result

    def disconnect(self):
        self.session_logger.close()


def run_fake_task(task, *, reset_success=True, goal_verified=True, connect_success=True):
    FakeBenchmarkAgent.created = []
    FakeBenchmarkAgent.task = task
    FakeBenchmarkAgent.reset_success = reset_success
    FakeBenchmarkAgent.goal_verified = goal_verified
    FakeBenchmarkAgent.connect_success = connect_success
    tmpdir = tempfile.mkdtemp()
    config = Config(log_dir=tmpdir)
    runner = BenchmarkRunner(config, output_dir=tmpdir, agent_factory=FakeBenchmarkAgent)
    result = runner.run_task(task)
    return runner, result, FakeBenchmarkAgent.created[-1], tmpdir


def test_m1_protocol_definitions_are_canonical():
    tasks = {task.id: task for task in M1_BENCHMARKS}
    assert list(tasks) == ["BM-001", "BM-002", "BM-003", "BM-004", "BM-005"]
    assert tasks["BM-001"].initial_inventory == {}
    assert tasks["BM-002"].initial_inventory == {"oak_planks": 4}
    assert tasks["BM-003"].initial_inventory == {"oak_planks": 3, "stick": 2}
    assert tasks["BM-004"].initial_inventory == {"wooden_pickaxe": 1}
    assert tasks["BM-004"].success_criteria == {"cobblestone": 5}
    assert tasks["BM-005"].initial_inventory == {"cobblestone": 3, "stick": 2}
    assert all(task.world_seed == "12345" for task in tasks.values())
    assert all(task.reset_profile == "m1-fixed-v1" for task in tasks.values())
    print("PASS: Shared M1 protocol defines canonical inventory, limits, seed, and BM-004 threshold")


def test_m1_runtime_profile_is_deterministic_and_isolated():
    tmpdir = tempfile.mkdtemp()
    config = m1_convergence_config(Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
    ))
    profile = m1_runtime_profile(config)
    assert profile["isolated"]
    assert profile["settings"]["ungated_artifact_path_count"] == 0
    assert not any(profile["settings"][name] for name in (
        "llm_planner", "skill_frontier_routing", "autocurriculum", "memory_policy",
        "task_memory", "task_continuity", "task_readiness", "skill_memory",
        "screenshot_capture", "world_model_curriculum", "multiagent",
    ))
    assert config.force_rule_planner
    assert not config.enable_planning_memory_context
    assert not config.enable_memory_persistence
    assert not config.enable_policy_skills
    assert not config.enable_plan_cache
    assert config.episode_abort_mode == "off"
    assert config.frontier_budget_mode == "off"
    assert not config.enable_vision_analysis
    assert not config.enable_goal_critic
    assert config.enable_goal_verification
    assert config.enable_action_verification and config.enforce_action_verification
    previous_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "offline-test-key"
    try:
        agent = Agent(config)
        assert not agent._use_llm
        agent.session_logger.close()
    finally:
        if previous_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous_key
    print("PASS: M1 runtime forces RuleBasedPlanner and isolates all excluded modules")


def test_m1_harness_preflight_matches_shared_protocol():
    runner = BenchmarkRunner(Config(), bridge_factory=ProtocolBridge)
    passed = runner._check_m1_harness()
    assert passed.status == "pass"

    class DriftedBridge(ProtocolBridge):
        def __init__(self, config):
            super().__init__(config, protocol_response(tasks=[]))

    failed = BenchmarkRunner(Config(), bridge_factory=DriftedBridge)._check_m1_harness()
    assert failed.status == "fail"
    assert "task definitions" in failed.detail
    print("PASS: M1 preflight rejects bridge protocol drift")


def test_m1_runner_requires_reset_goal_verifier_and_session_evidence():
    task = next(task for task in M1_BENCHMARKS if task.id == "BM-002")
    runner, result, agent, tmpdir = run_fake_task(task)
    assert result.status == "pass"
    assert result.protocol_eligible
    assert result.goal_verified and result.criteria_verified
    assert result.evidence_validation["passed"]
    assert result.evidence_validation["transition_proof_count"] == 1
    assert agent.run_limits == (task.timeout_cycles, task.max_duration_s)
    assert m1_runtime_profile(agent.config)["isolated"]
    assert len(result.session_sha256) == 64
    with open(result.session_log_path, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == result.session_sha256

    output = os.path.join(tmpdir, "m1-result.json")
    runner.save_results(output)
    with open(output, "r", encoding="utf-8") as f:
        saved = json.load(f)[0]
    assert saved["protocol_eligible"] is True
    assert saved["goal_verified"] is True
    assert saved["session_sha256"] == result.session_sha256
    try:
        runner.save_results(output)
        overwrite_blocked = False
    except FileExistsError:
        overwrite_blocked = True
    assert overwrite_blocked

    _, reset_failed, failed_agent, _ = run_fake_task(task, reset_success=False)
    assert reset_failed.status == "error"
    assert reset_failed.failure_reason == "benchmark_reset_failed"
    assert failed_agent.run_limits is None

    _, verifier_failed, _, _ = run_fake_task(task, goal_verified=False)
    assert verifier_failed.status == "fail"
    assert verifier_failed.criteria_verified
    assert not verifier_failed.goal_verified
    assert not verifier_failed.protocol_eligible

    _, connection_failed, _, _ = run_fake_task(task, connect_success=False)
    assert connection_failed.status == "error"
    assert connection_failed.failure_reason == "bridge_connection_failed"
    assert connection_failed.session_log_path
    assert connection_failed.session_sha256
    print("PASS: M1 runner gates success on reset, limits, verifier, trace validation, and immutable evidence")


def test_m1_session_validator_rejects_dependent_action_after_unreached_navigation():
    task = M1_BENCHMARKS[0]
    runtime = m1_runtime_profile(m1_convergence_config(Config()))
    setup = FakeBenchmarkBot(task).reset_benchmark(task.id)
    events = [
        {"type": "benchmark_runtime_profile", "data": runtime},
        {"type": "benchmark_reset", "data": setup},
        {"type": "goal_verification", "data": {"achieved": True, "status": "achieved"}},
        {
            "type": "action",
            "data": {
                "action": {"type": "move_to"},
                "result": {"success": False, "reached": False},
                "action_context": {"cycle": 1},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig"},
                "result": {"success": True},
                "pre_observation": {"position": {"x": 0, "y": 64, "z": 0}},
                "post_observation": {"position": {"x": 0, "y": 64, "z": 0}},
                "action_context": {"cycle": 1},
            },
        },
    ]
    report = BenchmarkRunner(Config())._validate_m1_session_evidence(
        task,
        events,
        setup,
        {"oak_log": 3},
        True,
    )
    assert not report["passed"]
    assert report["dependent_after_unreached_count"] == 1
    assert "dependent_action_after_unreached_navigation" in report["issues"]
    print("PASS: M1 evidence validator rejects dependent world actions after unreached navigation")


def test_m1_session_validator_requires_real_action_state_delta():
    task = M1_BENCHMARKS[0]
    runtime = m1_runtime_profile(m1_convergence_config(Config()))
    setup = FakeBenchmarkBot(task).reset_benchmark(task.id)
    unchanged = {
        "position": {"x": 0, "y": 64, "z": 0},
        "inventory": {},
        "nearby_blocks": [{"name": "oak_log", "position": {"x": 1, "y": 64, "z": 0}}],
    }
    events = [
        {"type": "benchmark_runtime_profile", "data": runtime},
        {"type": "benchmark_reset", "data": setup},
        {"type": "goal_verification", "data": {"achieved": True, "status": "achieved"}},
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"x": 1, "y": 64, "z": 0}},
                "result": {"success": True, "block": "oak_log"},
                "pre_observation": unchanged,
                "post_observation": unchanged,
                "action_context": {"cycle": 1},
            },
        },
    ]
    report = BenchmarkRunner(Config())._validate_m1_session_evidence(
        task,
        events,
        setup,
        {"oak_log": 3},
        True,
    )
    assert not report["passed"]
    assert report["transition_proof_count"] == 0
    assert "dig_state_transition_unverified" in report["issues"]
    proof = report["transition_proofs"][0]
    assert "target_inventory_did_not_increase" in proof["issues"]
    assert "source_block_unchanged_after_dig" in proof["issues"]
    print("PASS: M1 evidence validator rejects backend success without world-state delta")


def test_m1_cli_refuses_multiple_tasks_in_one_episode():
    result = subprocess.run(
        [sys.executable, "-m", "singularity.main", "benchmark", "--suite", "m1"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "exactly one --task-id per fresh episode" in result.stdout
    print("PASS: M1 CLI refuses a multi-task acceptance run in one world episode")


def test_dig_target_observations_survive_compact_logging():
    agent = Agent.__new__(Agent)
    tmpdir = tempfile.mkdtemp()
    agent.session_logger = SessionLogger(log_dir=tmpdir)
    agent._log_action_event(
        {"type": "dig", "parameters": {"x": 1, "y": 64, "z": 0}},
        {
            "success": True,
            "target_block_before": {"name": "stone", "position": {"x": 1, "y": 64, "z": 0}},
            "target_block_after": {"name": "air", "position": {"x": 1, "y": 64, "z": 0}},
        },
        pre_observation={"position": {"x": 0, "y": 64, "z": 0}, "inventory": {}},
        post_observation={"position": {"x": 0, "y": 64, "z": 0}, "inventory": {"cobblestone": 1}},
    )
    event = agent.session_logger.events[-1]["data"]
    assert event["pre_observation"]["action_target_block"]["name"] == "stone"
    assert event["post_observation"]["action_target_block"]["name"] == "air"
    agent.session_logger.close()
    print("PASS: Compact action logging preserves direct dig-target observations")


if __name__ == "__main__":
    test_m1_protocol_definitions_are_canonical()
    test_m1_runtime_profile_is_deterministic_and_isolated()
    test_m1_harness_preflight_matches_shared_protocol()
    test_m1_runner_requires_reset_goal_verifier_and_session_evidence()
    test_m1_session_validator_rejects_dependent_action_after_unreached_navigation()
    test_m1_session_validator_requires_real_action_state_delta()
    test_m1_cli_refuses_multiple_tasks_in_one_episode()
    test_dig_target_observations_survive_compact_logging()
    print("\nM1 harness tests PASSED")
