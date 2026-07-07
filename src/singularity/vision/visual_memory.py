"""Visual memory for storing and retrieving visual observations."""
import time
import logging
from typing import Optional

logger = logging.getLogger("singularity.vision.memory")


class VisualMemory:
    """Stores and retrieves visual observations of the Minecraft world."""

    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self.observations: list[dict] = []

    def add(self, analysis: dict, obs_type: str = "general") -> dict:
        entry = {"timestamp": time.time(), "type": obs_type, "data": analysis}
        self.observations.append(entry)
        if len(self.observations) > self.max_entries:
            self.observations = self.observations[-self.max_entries:]
        return entry

    def get_recent(self, count: int = 5) -> list[dict]:
        return self.observations[-count:]

    def search(self, query: str = "", obs_type: str = "") -> list[dict]:
        results = []
        for obs in self.observations:
            if obs_type and obs.get("type") != obs_type:
                continue
            if query and query.lower() not in str(obs.get("data", {})).lower():
                continue
            results.append(obs)
        return results

    def clear(self):
        self.observations.clear()

    def count(self) -> int:
        return len(self.observations)
