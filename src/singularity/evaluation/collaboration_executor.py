"""Executors that attach collaboration benchmark tasks to live agents."""
import threading
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from singularity.core.config import Config


@dataclass
class CollaborationBridgeCheck:
    role_id: str
    host: str
    port: int
    status: str
    detail: str = ""
    remedy: str = ""


@dataclass
class CollaborationBridgePreflightReport:
    ok: bool
    checks: list[CollaborationBridgeCheck] = field(default_factory=list)


@dataclass
class CollaborationBridgeLaunchCommand:
    role_id: str
    username: str
    host: str
    port: int
    command: str


class CollaborationTaskGoalAdapter:
    """Convert structured M7 collaboration tasks into agent goals."""

    def goal_from_task(self, task: dict, agent_state: dict, shared_state: dict) -> str:
        parts = [
            f"Role {agent_state.get('id', task.get('assigned_to', 'agent'))}: {task.get('title', 'Complete task')}.",
        ]
        if task.get("description"):
            parts.append(task["description"])
        if task.get("success_criteria"):
            parts.append(f"Success criteria: {task['success_criteria']}.")
        if task.get("deadline_s") is not None:
            parts.append(f"Finish before benchmark second {task['deadline_s']}.")
        visible_shared = {
            key: value for key, value in shared_state.items()
            if not str(key).startswith("_")
        }
        if visible_shared:
            parts.append(f"Shared state: {visible_shared}.")
        return " ".join(parts)

    def shared_updates_from_result(self, task: dict, success: bool, agent_result: dict) -> dict:
        if not success:
            return {}
        updates = dict(task.get("success_criteria", {}).get("shared_state", {}))
        for key in task.get("shared_state_updates", []):
            updates.setdefault(key, True)
        return updates


class AgentCollaborationExecutor:
    """Run collaboration tasks by delegating each task to a Singularity Agent."""

    def __init__(
        self,
        config: Config,
        agent_factory: Optional[Callable[[Config], object]] = None,
        goal_adapter: Optional[CollaborationTaskGoalAdapter] = None,
        bridge_port_base: Optional[int] = None,
        role_bridge_ports: Optional[dict[str, int]] = None,
        bridge_factory: Optional[Callable[[object], object]] = None,
    ):
        self.config = config
        self.agent_factory = agent_factory or self._default_agent_factory
        self.goal_adapter = goal_adapter or CollaborationTaskGoalAdapter()
        self.bridge_port_base = bridge_port_base
        self.role_bridge_ports = dict(role_bridge_ports or {})
        self.bridge_factory = bridge_factory or self._default_bridge_factory
        self._role_bridge_ports: dict[str, int] = {}
        self._agents: dict[str, object] = {}
        self._connected: dict[str, bool] = {}
        self._state_lock = threading.RLock()
        self._role_locks: dict[str, threading.RLock] = {}

    def __call__(self, task: dict, agent_state: dict, shared_state: dict) -> dict:
        role_id = agent_state.get("id") or task.get("assigned_to") or "agent"
        with self._lock_for_role(role_id):
            agent = self._agent_for_role(role_id)
            if not self._is_connected(role_id):
                if not agent.connect():
                    return {
                        "success": False,
                        "mode": "agent_goal",
                        "role_id": role_id,
                        "error": "agent failed to connect",
                    }
                self._set_connected(role_id, True)

            goal = self.goal_adapter.goal_from_task(task, agent_state, shared_state)
            result = agent.run_goal(goal)
        success = bool(result.get("completed"))
        return {
            "success": success,
            "mode": "agent_goal",
            "role_id": role_id,
            "goal": goal,
            "shared_state": self.goal_adapter.shared_updates_from_result(task, success, result),
            "agent_result": result,
            "error": "" if success else result.get("error", "agent did not complete goal"),
        }

    def close(self):
        with self._state_lock:
            agents = list(self._agents.values())
            self._connected.clear()
        for agent in agents:
            disconnect = getattr(agent, "disconnect", None)
            if callable(disconnect):
                disconnect()

    def preflight_bridges(self, spec) -> CollaborationBridgePreflightReport:
        launch_plan = self.bridge_launch_plan(spec)
        conflict_checks = self._bridge_launch_port_conflict_checks(launch_plan)
        if conflict_checks:
            return CollaborationBridgePreflightReport(
                ok=False,
                checks=conflict_checks,
            )

        checks = []
        for item in launch_plan:
            role_config = self._config_for_role(item.role_id)
            checks.append(self._check_role_bridge(item.role_id, role_config))
        return CollaborationBridgePreflightReport(
            ok=all(check.status != "fail" for check in checks),
            checks=checks,
        )

    def bridge_launch_plan(self, spec) -> list[CollaborationBridgeLaunchCommand]:
        plan = []
        for role_id in self.role_execution_order(spec):
            role_config = self._config_for_role(role_id)
            bot = role_config.bot
            command = f"node src/bot/bot_server.js --username {bot.username} --bridge-port {bot.bridge_port}"
            if bot.host and bot.host != "localhost":
                command += f" --host {bot.host}"
            if bot.port and bot.port != 25565:
                command += f" --port {bot.port}"
            plan.append(CollaborationBridgeLaunchCommand(
                role_id=role_id,
                username=bot.username,
                host=bot.bridge_host,
                port=bot.bridge_port,
                command=command,
            ))
        return plan

    def print_bridge_launch_plan(self, plan: list[CollaborationBridgeLaunchCommand], title: str = "Collaboration Agent Bridge Launch Plan"):
        if not plan:
            return
        print(f"\n{title}")
        for item in plan:
            print(f"  - {item.role_id}: {item.username} on {item.host}:{item.port}")
            print(f"    {item.command}")
        conflicts = self._bridge_launch_port_conflicts(plan)
        for port, role_ids in sorted(conflicts.items()):
            print(f"  ! port {port} is shared by roles: {', '.join(role_ids)}")

    def bridge_launch_plan_to_dict(self, plan: list[CollaborationBridgeLaunchCommand]) -> dict:
        return {
            "type": "collaboration_agent_bridge_launch_plan",
            "port_conflicts": [
                {"port": port, "role_ids": role_ids}
                for port, role_ids in sorted(self._bridge_launch_port_conflicts(plan).items())
            ],
            "commands": [
                {
                    "role_id": item.role_id,
                    "username": item.username,
                    "host": item.host,
                    "port": item.port,
                    "command": item.command,
                }
                for item in plan
            ],
        }

    def _bridge_launch_port_conflicts(self, plan: list[CollaborationBridgeLaunchCommand]) -> dict[int, list[str]]:
        by_port: dict[int, list[str]] = {}
        for item in plan:
            by_port.setdefault(item.port, []).append(item.role_id)
        return {
            port: role_ids
            for port, role_ids in by_port.items()
            if len(role_ids) > 1
        }

    def _bridge_launch_port_conflict_checks(
        self,
        plan: list[CollaborationBridgeLaunchCommand],
    ) -> list[CollaborationBridgeCheck]:
        checks = []
        for port, role_ids in sorted(self._bridge_launch_port_conflicts(plan).items()):
            host = next((item.host for item in plan if item.port == port), self.config.bot.bridge_host)
            checks.append(CollaborationBridgeCheck(
                role_id=f"port_conflict:{port}",
                host=host,
                port=port,
                status="fail",
                detail=f"bridge port {port} is assigned to multiple roles: {', '.join(role_ids)}",
                remedy="use --bridge-port-base for sequential role ports or repeat --role-bridge-port ROLE=PORT with unique ports",
            ))
        return checks

    def print_bridge_preflight_report(self, report: CollaborationBridgePreflightReport):
        print("\nCollaboration Agent Bridge Preflight")
        for check in report.checks:
            icon = "+" if check.status == "pass" else "!" if check.status == "warn" else "x"
            print(f"  [{icon}] {check.role_id}: {check.status} - {check.host}:{check.port} - {check.detail}")
            if check.remedy:
                print(f"      remedy: {check.remedy}")
        print(f"\nReady: {'yes' if report.ok else 'no'}")

    def bridge_preflight_report_to_dict(self, report: CollaborationBridgePreflightReport) -> dict:
        return {
            "type": "collaboration_agent_bridge_preflight",
            "ok": report.ok,
            "checks": [
                {
                    "role_id": check.role_id,
                    "host": check.host,
                    "port": check.port,
                    "status": check.status,
                    "detail": check.detail,
                    "remedy": check.remedy,
                }
                for check in report.checks
            ],
        }

    def role_execution_order(self, spec) -> list[str]:
        ordered: list[str] = []
        tasks = sorted(
            getattr(spec, "tasks", []),
            key=lambda task: (
                task.priority,
                task.deadline_s if task.deadline_s is not None else getattr(spec, "max_duration_s", 0),
                task.id,
            ),
        )
        for task in tasks:
            if task.assigned_role not in ordered:
                ordered.append(task.assigned_role)
        for role in getattr(spec, "roles", []):
            if role.id not in ordered:
                ordered.append(role.id)
        return ordered

    def _agent_for_role(self, role_id: str):
        with self._state_lock:
            if role_id not in self._agents:
                self._agents[role_id] = self.agent_factory(self._config_for_role(role_id))
            return self._agents[role_id]

    def _lock_for_role(self, role_id: str):
        with self._state_lock:
            if role_id not in self._role_locks:
                self._role_locks[role_id] = threading.RLock()
            return self._role_locks[role_id]

    def _is_connected(self, role_id: str) -> bool:
        with self._state_lock:
            return bool(self._connected.get(role_id, False))

    def _set_connected(self, role_id: str, connected: bool):
        with self._state_lock:
            self._connected[role_id] = connected

    def _config_for_role(self, role_id: str) -> Config:
        safe_role = "".join(ch for ch in role_id if ch.isalnum() or ch in ("_", "-"))[:16] or "agent"
        base_username = self.config.bot.username or "Singularity"
        username = f"{base_username}_{safe_role}"[:32]
        bridge_port = self._bridge_port_for_role(role_id)
        return replace(self.config, bot=replace(self.config.bot, username=username, bridge_port=bridge_port))

    def _bridge_port_for_role(self, role_id: str) -> int:
        with self._state_lock:
            if role_id in self.role_bridge_ports:
                return self.role_bridge_ports[role_id]
            if self.bridge_port_base is not None:
                return self._role_bridge_ports.setdefault(
                    role_id,
                    self.bridge_port_base + len(self._role_bridge_ports),
                )
            return self.config.bot.bridge_port

    def _default_agent_factory(self, config: Config):
        from singularity.core.agent import Agent
        return Agent(config)

    def _default_bridge_factory(self, bot_config):
        from singularity.bot.bridge import BotBridge
        return BotBridge(bot_config)

    def _check_role_bridge(self, role_id: str, role_config: Config) -> CollaborationBridgeCheck:
        bot = role_config.bot
        expected_username = bot.username
        bridge = self.bridge_factory(bot)
        try:
            if not bridge.connect():
                return CollaborationBridgeCheck(
                    role_id,
                    bot.bridge_host,
                    bot.bridge_port,
                    "fail",
                    "could not connect to bridge",
                    f"start node src/bot/bot_server.js --username {expected_username} --bridge-port {bot.bridge_port}",
                )
            health = bridge.health()
            if not health.get("success"):
                return CollaborationBridgeCheck(
                    role_id,
                    bot.bridge_host,
                    bot.bridge_port,
                    "fail",
                    health.get("error", "bridge health command failed"),
                    f"restart node src/bot/bot_server.js --username {expected_username} --bridge-port {bot.bridge_port}",
                )
            if not health.get("bot_ready"):
                detail = health.get("last_error") or "bridge is up but bot has not spawned"
                return CollaborationBridgeCheck(
                    role_id,
                    bot.bridge_host,
                    bot.bridge_port,
                    "fail",
                    detail,
                    f"start the Minecraft server, then restart bridge port {bot.bridge_port}",
                )
            actual_username = health.get("username", "")
            if actual_username and actual_username != expected_username:
                return CollaborationBridgeCheck(
                    role_id,
                    bot.bridge_host,
                    bot.bridge_port,
                    "fail",
                    f"bridge reports username {actual_username}, expected {expected_username}",
                    f"restart bridge port {bot.bridge_port} with --username {expected_username}",
                )
            return CollaborationBridgeCheck(
                role_id,
                bot.bridge_host,
                bot.bridge_port,
                "pass",
                f"bot spawned as {actual_username or expected_username}",
            )
        except Exception as exc:
            return CollaborationBridgeCheck(
                role_id,
                bot.bridge_host,
                bot.bridge_port,
                "fail",
                str(exc),
                f"restart node src/bot/bot_server.js --username {expected_username} --bridge-port {bot.bridge_port}",
            )
        finally:
            disconnect = getattr(bridge, "disconnect", None)
            if callable(disconnect):
                disconnect()
