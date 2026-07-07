"""AgentCoordinator and LeaderAgent for multi-agent coordination."""
import time
import logging
from typing import Optional

from singularity.multiagent.protocol import SharedState, AgentRole, MessageType

logger = logging.getLogger("singularity.multiagent.coordinator")


class AgentCoordinator:
    """Coordinates multiple agents through shared state.
    Implements the Leader-Follower pattern from M7 plan."""

    def __init__(self, agent_id: str, role: AgentRole, state: Optional[SharedState] = None):
        self.agent_id = agent_id
        self.role = role
        self.state = state or SharedState()
        self.state.register_agent(agent_id, role)
        logger.info(f"Coordinator {agent_id} registered as {role.value}")

    def update_status(self, status: str = "idle", position: dict = None,
                      inventory: dict = None, health: int = 20, task: str = ""):
        kwargs = {"status": status}
        if position: kwargs["position"] = position
        if inventory: kwargs["inventory"] = inventory
        if health: kwargs["health"] = health
        if task: kwargs["current_task"] = task
        self.state.update_agent_state(self.agent_id, **kwargs)

    def get_all_agents(self) -> list[dict]:
        return self.state.list_agents()

    def get_agent_info(self, agent_id: str) -> dict:
        return self.state.get_agent(agent_id)

    def get_leader_id(self) -> Optional[str]:
        return self.state.get_leader()

    def disconnect(self):
        self.state.update_agent_state(self.agent_id, status="disconnected")

    def cleanup_stale_agents(self, max_age: float = 60.0):
        self.state.clear_old_agents(max_age)


class LeaderAgent(AgentCoordinator):
    """Leader agent that assigns tasks to workers."""

    def __init__(self, agent_id: str = "leader", state: Optional[SharedState] = None):
        super().__init__(agent_id, AgentRole.LEADER, state)

    def assign_task(self, worker_id: str, task: dict) -> bool:
        return self.state.assign_task(worker_id, task)

    def get_worker_statuses(self) -> list[dict]:
        return [a for a in self.state.list_agents()
                if a.get("role") == "worker"]

    def get_available_workers(self) -> list[str]:
        return [a.get("id", "") for a in self.state.list_agents()
                if a.get("role") == "worker" and a.get("status") == "idle"]

    def get_all_tasks(self) -> dict:
        state = self.state._read_state()
        return state.get("tasks", {})

    def check_all_complete(self) -> bool:
        all_tasks = self.get_all_tasks()
        if not all_tasks:
            return False
        return all(t.get("status") == "completed" for t in all_tasks.values())

    def get_failed_tasks(self) -> list[dict]:
        return [t for t in self.get_all_tasks().values() if t.get("status") == "failed"]


class AgentWorker(AgentCoordinator):
    """Worker agent that executes tasks assigned by the leader."""

    def __init__(self, agent_id: str = "worker", state: Optional[SharedState] = None):
        super().__init__(agent_id, AgentRole.WORKER, state)

    def get_next_task(self) -> Optional[dict]:
        pending = self.state.get_agent_tasks(self.agent_id)
        pending = [t for t in pending if t.get("status") == "assigned"]
        if pending:
            return sorted(pending, key=lambda t: t.get("priority", 3))[0]
        return None

    def complete_current_task(self, task_id: str, result: dict = None) -> bool:
        return self.state.complete_task(task_id, result)

    def fail_current_task(self, task_id: str, reason: str = "") -> bool:
        return self.state.fail_task(task_id, reason)
