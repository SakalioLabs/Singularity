"""Explorer - handles open-world exploration with landmark tracking and base return."""
import math
import logging

logger = logging.getLogger("singularity.explorer")


class Explorer:
    """Manages exploration state: landmarks, base position, path memory."""

    def __init__(self):
        self.base_position = None
        self.landmarks = []
        self.path_history = []
        self.max_exploration_distance = 200
        self.inventory_full_threshold = 35

    def set_base(self, x: float, y: float, z: float):
        self.base_position = {"x": x, "y": y, "z": z}
        logger.info(f"Base set at ({x}, {y}, {z})")

    def record_position(self, position: dict):
        self.path_history.append(position)
        if len(self.path_history) > 500:
            self.path_history = self.path_history[-250:]

    def add_landmark(self, name: str, position: dict, landmark_type: str = "generic"):
        self.landmarks.append({"name": name, "position": position, "type": landmark_type})
        logger.info(f"Landmark: {name} at {position}")

    def distance_to_base(self, current: dict) -> float:
        if not self.base_position:
            return 0
        dx = current.get("x", 0) - self.base_position["x"]
        dz = current.get("z", 0) - self.base_position["z"]
        return math.sqrt(dx * dx + dz * dz)

    def should_return(self, current: dict, inventory_count: int) -> tuple:
        dist = self.distance_to_base(current)
        if inventory_count >= self.inventory_full_threshold:
            return True, "Inventory full"
        if dist >= self.max_exploration_distance:
            return True, f"Too far from base ({dist:.0f} blocks)"
        return False, ""

    def get_return_direction(self, current: dict) -> dict:
        if not self.base_position:
            return {"x": 0, "z": 0}
        return {
            "x": self.base_position["x"] - current.get("x", 0),
            "z": self.base_position["z"] - current.get("z", 0),
        }

    def find_nearest_landmark(self, current: dict, landmark_type: str = None) -> dict:
        nearest = None
        min_dist = float("inf")
        for lm in self.landmarks:
            if landmark_type and lm["type"] != landmark_type:
                continue
            dx = lm["position"].get("x", 0) - current.get("x", 0)
            dz = lm["position"].get("z", 0) - current.get("z", 0)
            dist = math.sqrt(dx * dx + dz * dz)
            if dist < min_dist:
                min_dist = dist
                nearest = lm
        return nearest

    def get_exploration_target(self, current: dict) -> dict:
        """Generate next exploration target - spiral outward from base."""
        dist = self.distance_to_base(current)
        if dist < 50:
            angle = len(self.path_history) * 0.5
            r = 50 + len(self.path_history) * 0.1
            if self.base_position:
                return {
                    "x": self.base_position["x"] + r * math.cos(angle),
                    "z": self.base_position["z"] + r * math.sin(angle),
                }
        return {"x": current.get("x", 0) + 30, "z": current.get("z", 0) + 30}

