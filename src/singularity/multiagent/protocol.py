"""Communication protocol for multi-agent coordination in Minecraft."""
import json
import time
import uuid
import os
import logging
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("singularity.multiagent.protocol")


class AgentRole(Enum):
    LEADER = "leader"
    WORKER = "worker"
    OBSERVER = "observer"


class MessageType(Enum):
    ROLE_ASSIGN = "role_assign"
    TASK_REQUEST = "task_request"
    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"
    STATUS_UPDATE = "status_update"
    RESOURCE_NEED = "resource_need"
    HELP_REQUEST = "help_request"
    POSITION_UPDATE = "position_update"


@dataclass
class AgentMessage:
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    msg_type: MessageType = MessageType.STATUS_UPDATE
    sender: str = ""
    target: str = ""
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class SharedState:
    """File-based shared state for multi-agent coordination.
    Implements Approach A from M7 plan: shared JSON file with locking."""

    def __init__(self, state_path: str = "workspace/multiagent/shared_state.json"):
        self.state_path = state_path
        self.messages: list[AgentMessage] = []
        self.max_messages = 100
        import os
        os.makedirs(os.path.dirname(state_path), exist_ok=True)

    def register_agent(self, agent_id: str, role: AgentRole) -> dict:
        state = self._read_state()
        if "agents" not in state:
            state["agents"] = {}
        state["agents"][agent_id] = {
            "id": agent_id,
            "role": role.value,
            "last_seen": time.time(),
            "status": "idle",
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory": {},
            "health": 20,
            "current_task": "",
        }
        self._write_state(state)
        return state["agents"][agent_id]

    def update_shared(self, updates: dict) -> dict:
        """Update benchmark/shared coordination keys."""
        state = self._read_state()
        if "shared" not in state:
            state["shared"] = {}
        state["shared"].update(updates)
        self._write_state(state)
        return state["shared"]

    def get_shared(self) -> dict:
        return self._read_state().get("shared", {})

    def update_agent_state(self, agent_id: str, **kwargs) -> dict:
        state = self._read_state()
        if agent_id not in state.get("agents", {}):
            return {}
        agent = state["agents"][agent_id]
        for k, v in kwargs.items():
            if k in agent:
                agent[k] = v
        agent["last_seen"] = time.time()
        self._write_state(state)
        return agent

    def get_agent(self, agent_id: str) -> dict:
        state = self._read_state()
        return state.get("agents", {}).get(agent_id, {})

    def list_agents(self) -> list[dict]:
        state = self._read_state()
        return list(state.get("agents", {}).values())

    def get_leader(self) -> Optional[str]:
        for aid, info in self._read_state().get("agents", {}).items():
            if info.get("role") == "leader":
                return aid
        return None

    def assign_task(self, agent_id: str, task: dict) -> bool:
        state = self._read_state()
        if agent_id not in state.get("agents", {}):
            return False
        if "tasks" not in state:
            state["tasks"] = {}
        task_id = f"task_{uuid.uuid4().hex[:6]}"
        task["task_id"] = task_id
        task["assigned_to"] = agent_id
        task["status"] = "assigned"
        task["created_at"] = time.time()
        state["tasks"][task_id] = task
        self._write_state(state)
        return True

    def start_task(self, task_id: str) -> bool:
        state = self._read_state()
        if task_id not in state.get("tasks", {}):
            return False
        if state["tasks"][task_id].get("status") != "assigned":
            return False
        state["tasks"][task_id]["status"] = "in_progress"
        state["tasks"][task_id]["started_at"] = time.time()
        self._write_state(state)
        return True

    def complete_task(self, task_id: str, result: dict = None) -> bool:
        state = self._read_state()
        if task_id not in state.get("tasks", {}):
            return False
        state["tasks"][task_id]["status"] = "completed"
        state["tasks"][task_id]["completed_at"] = time.time()
        state["tasks"][task_id]["result"] = result or {}
        self._write_state(state)
        return True

    def fail_task(self, task_id: str, reason: str = "") -> bool:
        state = self._read_state()
        if task_id not in state.get("tasks", {}):
            return False
        state["tasks"][task_id]["status"] = "failed"
        state["tasks"][task_id]["error"] = reason
        self._write_state(state)
        return True

    def get_pending_tasks(self) -> list[dict]:
        state = self._read_state()
        return [t for t in state.get("tasks", {}).values() if t.get("status") == "assigned"]

    def get_agent_tasks(self, agent_id: str) -> list[dict]:
        state = self._read_state()
        return [t for t in state.get("tasks", {}).values() if t.get("assigned_to") == agent_id]

    def clear_old_agents(self, max_age: float = 60.0):
        state = self._read_state()
        now = time.time()
        if "agents" in state:
            state["agents"] = {aid: info for aid, info in state["agents"].items()
                               if now - info.get("last_seen", 0) < max_age}
        self._write_state(state)

    def _read_state(self) -> dict:
        try:
            with open(self.state_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"agents": {}, "tasks": {}}

    def _write_state(self, state: dict):
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.state_path))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            import shutil
            shutil.move(tmp, self.state_path)
        except Exception:
            os.unlink(tmp)
            raise
