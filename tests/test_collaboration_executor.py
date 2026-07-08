"""Unit tests for live collaboration task executors."""
from concurrent.futures import ThreadPoolExecutor
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.config import Config
from singularity.evaluation.collaboration_benchmark import CollaborationBenchmarkSpec
from singularity.evaluation.collaboration_executor import (
    AgentCollaborationExecutor,
    CollaborationTaskGoalAdapter,
)


class FakeAgent:
    def __init__(self, config, completed=True, connect_ok=True):
        self.config = config
        self.completed = completed
        self.connect_ok = connect_ok
        self.connected = False
        self.disconnected = False
        self.connect_count = 0
        self.goals = []

    def connect(self):
        self.connect_count += 1
        self.connected = self.connect_ok
        return self.connect_ok

    def run_goal(self, goal):
        self.goals.append(goal)
        return {"completed": self.completed, "goal": goal, "cycles": 1}

    def disconnect(self):
        self.disconnected = True


class FakeBridge:
    def __init__(self, config, health=None, connect_ok=True):
        self.config = config
        self.health_payload = health
        self.connect_ok = connect_ok
        self.disconnected = False

    def connect(self):
        return self.connect_ok

    def health(self):
        if self.health_payload is not None:
            return self.health_payload
        return {
            "success": True,
            "bot_ready": True,
            "username": self.config.username,
        }

    def disconnect(self):
        self.disconnected = True


def sample_task():
    return {
        "task_id": "task_abc",
        "source_task_id": "deliver_wood",
        "assigned_to": "resource_runner",
        "title": "Deliver wood to builder",
        "description": "Transfer enough wood and mark the handoff.",
        "deadline_s": 210,
        "success_criteria": {"shared_state": {"wood_delivered": True}},
        "shared_state_updates": ["wood_delivered"],
    }


def sample_spec():
    return CollaborationBenchmarkSpec.from_dict({
        "id": "BM-TEST",
        "name": "Bridge preflight sample",
        "max_duration_s": 120,
        "roles": [
            {"id": "leader_builder", "capabilities": ["plan"], "required": True},
            {"id": "resource_runner", "capabilities": ["gather"], "required": True},
        ],
        "tasks": [
            {
                "id": "gather_logs",
                "title": "Gather logs",
                "assigned_role": "resource_runner",
                "priority": 1,
                "deadline_s": 30,
            },
            {
                "id": "verify_shelter",
                "title": "Verify shelter",
                "assigned_role": "leader_builder",
                "priority": 2,
                "deadline_s": 90,
            },
        ],
    })


def test_goal_adapter_includes_task_context():
    adapter = CollaborationTaskGoalAdapter()
    goal = adapter.goal_from_task(
        sample_task(),
        {"id": "resource_runner"},
        {"wood_delivered": False, "_benchmark": {"id": "BM-701"}},
    )

    assert "Role resource_runner" in goal
    assert "Deliver wood to builder" in goal
    assert "wood_delivered" in goal
    assert "_benchmark" not in goal
    print("PASS: CollaborationTaskGoalAdapter builds task goal context")


def test_agent_collaboration_executor_runs_goal_and_returns_shared_updates():
    created = []

    def factory(config):
        agent = FakeAgent(config)
        created.append(agent)
        return agent

    executor = AgentCollaborationExecutor(Config(), agent_factory=factory)
    result = executor(sample_task(), {"id": "resource_runner"}, {"wood_delivered": False})

    assert result["success"] is True
    assert result["mode"] == "agent_goal"
    assert result["shared_state"] == {"wood_delivered": True}
    assert created[0].connected is True
    assert created[0].config.bot.username == "Singularity_resource_runner"
    assert created[0].goals and "Deliver wood to builder" in created[0].goals[0]
    executor.close()
    assert created[0].disconnected is True
    print("PASS: AgentCollaborationExecutor runs goal and returns shared updates")


def test_agent_collaboration_executor_assigns_role_bridge_ports():
    created = {}

    def factory(config):
        agent = FakeAgent(config)
        created[config.bot.username] = agent
        return agent

    executor = AgentCollaborationExecutor(Config(), agent_factory=factory, bridge_port_base=4100)
    executor(sample_task(), {"id": "resource_runner"}, {})
    leader_task = sample_task()
    leader_task["source_task_id"] = "verify_shelter"
    leader_task["assigned_to"] = "leader_builder"
    leader_task["title"] = "Verify shelter"
    executor(leader_task, {"id": "leader_builder"}, {})
    executor(sample_task(), {"id": "resource_runner"}, {})

    ports = {username: agent.config.bot.bridge_port for username, agent in created.items()}
    assert ports["Singularity_resource_runner"] == 4100
    assert ports["Singularity_leader_builder"] == 4101
    assert len(created) == 2
    print("PASS: AgentCollaborationExecutor assigns role bridge ports")


def test_agent_collaboration_executor_uses_explicit_role_bridge_ports():
    created = {}

    def factory(config):
        agent = FakeAgent(config)
        created[config.bot.username] = agent
        return agent

    executor = AgentCollaborationExecutor(
        Config(),
        agent_factory=factory,
        bridge_port_base=4100,
        role_bridge_ports={"leader_builder": 4550, "resource_runner": 4551},
    )
    leader_task = sample_task()
    leader_task["source_task_id"] = "verify_shelter"
    leader_task["assigned_to"] = "leader_builder"
    leader_task["title"] = "Verify shelter"
    executor(leader_task, {"id": "leader_builder"}, {})
    executor(sample_task(), {"id": "resource_runner"}, {})

    ports = {username: agent.config.bot.bridge_port for username, agent in created.items()}
    assert ports["Singularity_leader_builder"] == 4550
    assert ports["Singularity_resource_runner"] == 4551
    print("PASS: AgentCollaborationExecutor uses explicit role bridge ports")


def test_agent_collaboration_executor_preserves_mixed_policy_patch_paths():
    created = {}
    config = Config(
        mixed_policy_patch_paths=["logs/benchmarks/mixed_policy_patch.json"],
        mixed_policy_gate_paths=["logs/benchmarks/mixed_policy_gate.json"],
        self_evolution_feedback_paths=["logs/benchmarks/self_evolution.json"],
    )

    def factory(role_config):
        agent = FakeAgent(role_config)
        created[role_config.bot.username] = agent
        return agent

    executor = AgentCollaborationExecutor(config, agent_factory=factory, bridge_port_base=4100)
    executor(sample_task(), {"id": "resource_runner"}, {})

    agent = created["Singularity_resource_runner"]
    assert agent.config.bot.bridge_port == 4100
    assert agent.config.mixed_policy_patch_paths == ["logs/benchmarks/mixed_policy_patch.json"]
    assert agent.config.mixed_policy_gate_paths == ["logs/benchmarks/mixed_policy_gate.json"]
    assert agent.config.self_evolution_feedback_paths == ["logs/benchmarks/self_evolution.json"]
    print("PASS: AgentCollaborationExecutor preserves mixed policy patch paths")


def test_agent_collaboration_executor_builds_bridge_launch_plan():
    executor = AgentCollaborationExecutor(Config(), bridge_port_base=4200)
    plan = executor.bridge_launch_plan(sample_spec())
    payload = executor.bridge_launch_plan_to_dict(plan)

    assert [(item.role_id, item.username, item.port) for item in plan] == [
        ("resource_runner", "Singularity_resource_runner", 4200),
        ("leader_builder", "Singularity_leader_builder", 4201),
    ]
    assert plan[0].command == "node src/bot/bot_server.js --username Singularity_resource_runner --bridge-port 4200"
    assert payload["type"] == "collaboration_agent_bridge_launch_plan"
    assert payload["commands"][1]["role_id"] == "leader_builder"
    assert payload["commands"][1]["command"].endswith("--bridge-port 4201")
    print("PASS: AgentCollaborationExecutor builds bridge launch plan")


def test_agent_collaboration_executor_launch_plan_uses_explicit_ports():
    executor = AgentCollaborationExecutor(
        Config(),
        bridge_port_base=4200,
        role_bridge_ports={"leader_builder": 4601, "resource_runner": 4600},
    )
    plan = executor.bridge_launch_plan(sample_spec())

    assert [(item.role_id, item.port) for item in plan] == [
        ("resource_runner", 4600),
        ("leader_builder", 4601),
    ]
    assert plan[0].command.endswith("--bridge-port 4600")
    assert plan[1].command.endswith("--bridge-port 4601")
    print("PASS: AgentCollaborationExecutor launch plan uses explicit ports")


def test_agent_collaboration_executor_launch_plan_reports_port_conflicts():
    executor = AgentCollaborationExecutor(Config())
    plan = executor.bridge_launch_plan(sample_spec())
    payload = executor.bridge_launch_plan_to_dict(plan)

    assert [(item.role_id, item.port) for item in plan] == [
        ("resource_runner", 3000),
        ("leader_builder", 3000),
    ]
    assert payload["port_conflicts"] == [
        {"port": 3000, "role_ids": ["resource_runner", "leader_builder"]},
    ]
    print("PASS: AgentCollaborationExecutor launch plan reports port conflicts")


def test_agent_collaboration_executor_preflight_fails_on_port_conflicts():
    calls = []

    def bridge_factory(config):
        calls.append(config)
        return FakeBridge(config)

    executor = AgentCollaborationExecutor(Config(), bridge_factory=bridge_factory)
    report = executor.preflight_bridges(sample_spec())
    payload = executor.bridge_preflight_report_to_dict(report)

    assert not report.ok
    assert calls == []
    assert report.checks[0].role_id == "port_conflict:3000"
    assert report.checks[0].status == "fail"
    assert "multiple roles" in report.checks[0].detail
    assert "--bridge-port-base" in report.checks[0].remedy
    assert payload["checks"][0]["role_id"] == "port_conflict:3000"
    print("PASS: AgentCollaborationExecutor preflight fails on port conflicts")


def test_agent_collaboration_executor_runs_different_roles_concurrently():
    active = {"count": 0, "max": 0}
    lock = threading.Lock()
    created = []

    class SlowAgent(FakeAgent):
        def run_goal(self, goal):
            with lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            try:
                time.sleep(0.05)
                return super().run_goal(goal)
            finally:
                with lock:
                    active["count"] -= 1

    def factory(config):
        agent = SlowAgent(config)
        created.append(agent)
        return agent

    executor = AgentCollaborationExecutor(Config(), agent_factory=factory, bridge_port_base=4700)
    leader_task = sample_task()
    leader_task["assigned_to"] = "leader_builder"
    leader_task["source_task_id"] = "verify_shelter"
    leader_task["title"] = "Verify shelter"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda args: executor(*args),
            [
                (sample_task(), {"id": "resource_runner"}, {}),
                (leader_task, {"id": "leader_builder"}, {}),
            ],
        ))

    assert all(result["success"] for result in results)
    assert len(created) == 2
    assert active["max"] == 2
    assert {agent.connect_count for agent in created} == {1}
    print("PASS: AgentCollaborationExecutor runs different roles concurrently")


def test_agent_collaboration_executor_serializes_same_role_calls():
    active = {"count": 0, "max": 0}
    lock = threading.Lock()
    created = []

    class SlowAgent(FakeAgent):
        def run_goal(self, goal):
            with lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            try:
                time.sleep(0.05)
                return super().run_goal(goal)
            finally:
                with lock:
                    active["count"] -= 1

    def factory(config):
        agent = SlowAgent(config)
        created.append(agent)
        return agent

    executor = AgentCollaborationExecutor(Config(), agent_factory=factory)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: executor(sample_task(), {"id": "resource_runner"}, {}),
            range(2),
        ))

    assert all(result["success"] for result in results)
    assert len(created) == 1
    assert created[0].connect_count == 1
    assert len(created[0].goals) == 2
    assert active["max"] == 1
    print("PASS: AgentCollaborationExecutor serializes same-role calls")


def test_agent_collaboration_executor_preflights_role_bridges():
    seen = []
    bridges = []

    def bridge_factory(config):
        bridge = FakeBridge(config)
        bridges.append(bridge)
        seen.append((config.username, config.bridge_port))
        return bridge

    executor = AgentCollaborationExecutor(Config(), bridge_factory=bridge_factory, bridge_port_base=4200)
    report = executor.preflight_bridges(sample_spec())

    assert report.ok
    assert [(check.role_id, check.port, check.status) for check in report.checks] == [
        ("resource_runner", 4200, "pass"),
        ("leader_builder", 4201, "pass"),
    ]
    assert seen == [
        ("Singularity_resource_runner", 4200),
        ("Singularity_leader_builder", 4201),
    ]
    assert all(bridge.disconnected for bridge in bridges)
    print("PASS: AgentCollaborationExecutor preflights role bridges")


def test_agent_collaboration_executor_preflight_uses_explicit_ports():
    seen = []

    def bridge_factory(config):
        seen.append((config.username, config.bridge_port))
        return FakeBridge(config)

    executor = AgentCollaborationExecutor(
        Config(),
        bridge_factory=bridge_factory,
        bridge_port_base=4200,
        role_bridge_ports={"leader_builder": 4601, "resource_runner": 4600},
    )
    report = executor.preflight_bridges(sample_spec())

    assert report.ok
    assert [(check.role_id, check.port) for check in report.checks] == [
        ("resource_runner", 4600),
        ("leader_builder", 4601),
    ]
    assert seen == [
        ("Singularity_resource_runner", 4600),
        ("Singularity_leader_builder", 4601),
    ]
    payload = executor.bridge_preflight_report_to_dict(report)
    assert payload["type"] == "collaboration_agent_bridge_preflight"
    assert payload["checks"][0]["role_id"] == "resource_runner"
    assert payload["checks"][0]["port"] == 4600
    print("PASS: AgentCollaborationExecutor preflight uses explicit role ports")


def test_agent_collaboration_executor_preflight_fails_on_username_mismatch():
    def bridge_factory(config):
        return FakeBridge(config, health={"success": True, "bot_ready": True, "username": "WrongBot"})

    executor = AgentCollaborationExecutor(Config(), bridge_factory=bridge_factory, bridge_port_base=4300)
    report = executor.preflight_bridges(sample_spec())

    assert not report.ok
    assert report.checks[0].status == "fail"
    assert "expected Singularity_resource_runner" in report.checks[0].detail
    print("PASS: AgentCollaborationExecutor preflight catches username mismatch")


def test_agent_collaboration_executor_reports_connect_failure():
    def factory(config):
        return FakeAgent(config, connect_ok=False)

    executor = AgentCollaborationExecutor(Config(), agent_factory=factory)
    result = executor(sample_task(), {"id": "resource_runner"}, {})

    assert result["success"] is False
    assert "failed to connect" in result["error"]
    print("PASS: AgentCollaborationExecutor reports connect failure")


def test_agent_collaboration_executor_reports_incomplete_goal():
    def factory(config):
        return FakeAgent(config, completed=False)

    executor = AgentCollaborationExecutor(Config(), agent_factory=factory)
    result = executor(sample_task(), {"id": "resource_runner"}, {})

    assert result["success"] is False
    assert result["shared_state"] == {}
    assert "did not complete" in result["error"]
    print("PASS: AgentCollaborationExecutor reports incomplete goal")


if __name__ == "__main__":
    test_goal_adapter_includes_task_context()
    test_agent_collaboration_executor_runs_goal_and_returns_shared_updates()
    test_agent_collaboration_executor_assigns_role_bridge_ports()
    test_agent_collaboration_executor_uses_explicit_role_bridge_ports()
    test_agent_collaboration_executor_preserves_mixed_policy_patch_paths()
    test_agent_collaboration_executor_builds_bridge_launch_plan()
    test_agent_collaboration_executor_launch_plan_uses_explicit_ports()
    test_agent_collaboration_executor_launch_plan_reports_port_conflicts()
    test_agent_collaboration_executor_preflight_fails_on_port_conflicts()
    test_agent_collaboration_executor_runs_different_roles_concurrently()
    test_agent_collaboration_executor_serializes_same_role_calls()
    test_agent_collaboration_executor_preflights_role_bridges()
    test_agent_collaboration_executor_preflight_uses_explicit_ports()
    test_agent_collaboration_executor_preflight_fails_on_username_mismatch()
    test_agent_collaboration_executor_reports_connect_failure()
    test_agent_collaboration_executor_reports_incomplete_goal()
    print("\nCollaboration executor tests PASSED")
