"""Skill extractor - extracts reusable skills from successful task traces."""
import json
import logging
from typing import Optional

logger = logging.getLogger("singularity.skill_extractor")


class SkillExtractor:
    """Extracts reusable skills from successful session logs."""

    def __init__(self, skill_library):
        self.skill_library = skill_library

    def extract_from_session(self, session_log_path: str) -> list:
        """Extract skills from a successful session log."""
        skills = []
        try:
            events = []
            with open(session_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    events.append(json.loads(line.strip()))
            actions = [e for e in events if e.get("type") == "action"]
            if not actions:
                return skills
            goal_event = next((e for e in events if e.get("type") == "goal_start"), None)
            goal = goal_event.get("data", {}).get("goal", "unknown") if goal_event else "unknown"
            action_sequence = []
            for a in actions:
                action_data = a.get("data", {}).get("action", {})
                result = a.get("data", {}).get("result", {})
                if result.get("success"):
                    action_sequence.append({
                        "type": action_data.get("type"),
                        "parameters": action_data.get("parameters", {}),
                    })
            if action_sequence:
                skill_name = self._generate_skill_name(goal)
                skill = self.skill_library.create_skill(
                    name=skill_name,
                    description=f"Extracted from goal: {goal}",
                    implementation=json.dumps(action_sequence),
                    layer="composite",
                )
                skills.append(skill)
                logger.info(f"Extracted skill '{skill_name}' with {len(action_sequence)} actions")
        except Exception as e:
            logger.error(f"Skill extraction failed: {e}")
        return skills

    def extract_failure_case(self, session_log_path: str) -> dict:
        """Extract failure analysis from a failed session."""
        try:
            events = []
            with open(session_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    events.append(json.loads(line.strip()))
            errors = [e for e in events if e.get("type") == "error"]
            reflections = [e for e in events if e.get("type") == "reflection"]
            return {
                "errors": [e.get("data", {}) for e in errors],
                "reflections": [e.get("data", {}) for e in reflections],
                "total_events": len(events),
            }
        except Exception as e:
            logger.error(f"Failure extraction failed: {e}")
            return {}

    def _generate_skill_name(self, goal: str) -> str:
        words = goal.lower().split()[:4]
        return "_".join(words).replace(",", "").replace(".", "")
