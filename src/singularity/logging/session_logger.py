"""Session logger — structured JSON logging for all agent sessions."""
import json
import os
import time
import uuid
import logging
from typing import Optional

logger = logging.getLogger("singularity.session")


class SessionLogger:
    """Records all observations, actions, plans, and reflections as structured JSON."""

    def __init__(self, log_dir: str = "logs", session_id: Optional[str] = None):
        self.log_dir = log_dir
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.start_time = time.time()
        self.events: list[dict] = []
        os.makedirs(log_dir, exist_ok=True)
        self._log_path = os.path.join(log_dir, f"session_{self.session_id}.jsonl")
        logger.info(f"Session {self.session_id} logging to {self._log_path}")

    def log(self, event_type: str, data: dict, level: str = "INFO"):
        """Append one structured event to the session log."""
        entry = {
            "ts": time.time(),
            "elapsed_s": round(time.time() - self.start_time, 2),
            "session": self.session_id,
            "type": event_type,
            "level": level,
            "data": data,
        }
        self.events.append(entry)
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write session log: {e}")

    def log_observation(self, observation: dict):
        self.log("observation", observation)

    def log_plan(self, plan: dict):
        self.log("plan", plan)

    def log_action(self, action: dict, result: dict):
        self.log("action", {"action": action, "result": result})

    def log_reflection(self, reflection: dict):
        self.log("reflection", reflection)

    def log_error(self, error: str, context: dict = None):
        self.log("error", {"error": error, "context": context or {}}, level="ERROR")

    def log_goal_start(self, goal: str):
        self.log("goal_start", {"goal": goal})

    def log_goal_end(self, goal: str, result: dict):
        self.log("goal_end", {"goal": goal, "result": result})

    def log_connect(self, host: str, port: int, success: bool):
        self.log("connect", {"host": host, "port": port, "success": success})

    def get_summary(self) -> dict:
        """Return a summary of the session."""
        elapsed = time.time() - self.start_time
        action_count = sum(1 for e in self.events if e["type"] == "action")
        error_count = sum(1 for e in self.events if e["type"] == "error")
        return {
            "session_id": self.session_id,
            "duration_s": round(elapsed, 2),
            "total_events": len(self.events),
            "action_count": action_count,
            "error_count": error_count,
            "log_path": self._log_path,
        }

    def close(self):
        """Write session summary."""
        summary = self.get_summary()
        summary_path = os.path.join(self.log_dir, f"session_{self.session_id}_summary.json")
        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write session summary: {e}")
        logger.info(f"Session {self.session_id} ended: {summary}")
