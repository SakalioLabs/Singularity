"""Planner - LLM-powered goal decomposition and action planning with Minecraft knowledge injection."""
import json
import logging
import time
from typing import Optional

from singularity.core.task_system import TaskSystem, Task, TaskStatus
from singularity.data.knowledge_base import KnowledgeBase
from singularity.llm.provider import LLMProvider

logger = logging.getLogger("singularity.planner")

_CRAFTING_KNOWLEDGE = ""
try:
    _KB = KnowledgeBase()
    _CRAFTING_KNOWLEDGE = _KB.format_for_prompt()
except Exception as e:
    logger.warning(f"Could not build planner knowledge summary: {e}")
    _CRAFTING_KNOWLEDGE = "Key recipes unavailable"


class Planner:
    def __init__(self, llm: LLMProvider, task_system: TaskSystem):
        self.llm = llm
        self.task_system = task_system

    def plan_from_goal(self, goal: str, world_state: dict, memory_context: str = "") -> dict:
        prompt = self._build_planning_prompt(goal, world_state, memory_context)
        response = self.llm.chat([
            {"role": "system", "content": self._planner_system_prompt()},
            {"role": "user", "content": prompt},
        ], response_format={"type": "json_object"})
        try:
            plan = json.loads(response)
        except json.JSONDecodeError:
            plan = {"status": "error", "subtasks": [], "actions": [], "reasoning": "Failed to parse LLM output"}
        self._create_tasks_from_plan(plan)
        return plan

    def replan(self, failed_task: Task, world_state: dict, failure_reason: str) -> dict:
        prompt = f"""Task '{failed_task.title}' failed: {failure_reason}
Attempts so far: {failed_task.attempts}
Current state: {json.dumps(world_state, default=str)[:1000]}
Suggest a new plan. Output JSON: {{"status":"replan","subtasks":[...],"actions":[...],"reasoning":"..."}}"""
        response = self.llm.chat([
            {"role": "system", "content": "You are a replanning system. Analyze failures and propose alternative approaches."},
            {"role": "user", "content": prompt},
        ], response_format={"type": "json_object"})
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"status": "error", "subtasks": [], "actions": [], "reasoning": "Parse error"}

    def _planner_system_prompt(self) -> str:
        return f"""You are a Minecraft survival planner. Given a goal and current world state, decompose it into subtasks and immediate actions.

Available actions: move_to, look_at, dig, place, craft, attack, equip, use_item, chat, wait.

MINECRAFT KNOWLEDGE SUMMARY:
{_CRAFTING_KNOWLEDGE}

TOOL PROGRESSION: hand -> wooden -> stone -> iron -> diamond
To mine stone/cobblestone you need at least a wooden pickaxe.
To mine iron_ore you need at least a stone pickaxe.
To get oak_planks, craft them from oak_log (1 log = 4 planks).
To get sticks, craft from 2 planks (2 planks = 4 sticks).
You can punch trees to get oak_log without any tools.

Output JSON:
{{
  "status": "planning" or "complete" or "blocked",
  "reasoning": "brief strategic explanation",
  "subtasks": [
    {{
      "title": "...",
      "type": "...",
      "priority": 1-5,
      "success_criteria": {{}},
      "preconditions": {{"inventory": {{"item_name": count}}, "flags": []}},
      "depends_on": ["earlier subtask title"],
      "opportunity_triggers": ["nearby block/entity/item that makes this task worth doing now"],
      "tags": ["resource", "crafting"],
      "deadline_seconds": optional seconds from now,
      "assigned_skill": "optional skill name",
      "rationale": "why this subtask matters"
    }}
  ],
  "actions": [
    {{"type": "action_name", "parameters": {{...}}}}
  ]
}}

Be practical and safe. Check inventory before crafting. Follow tool progression."""

    def _build_planning_prompt(self, goal: str, world_state: dict, memory_context: str) -> str:
        return f"""Goal: {goal}

World state:
{json.dumps(world_state, indent=2, default=str)[:2000]}

{f'Relevant memory: {memory_context}' if memory_context else ''}

Plan the steps to achieve this goal."""

    def _create_tasks_from_plan(self, plan: dict):
        """Create task records from LLM subtasks, preserving dependencies and scheduling hints."""
        subtasks = plan.get("subtasks", [])
        title_to_id = {}
        pending_dependencies: list[tuple[str, list[str]]] = []
        for st in subtasks:
            title = st.get("title", "unnamed")
            task = self.task_system.create_task(
                title=title,
                task_type=st.get("type", "general"),
                success_criteria=st.get("success_criteria", {}),
                failure_criteria=st.get("failure_criteria", {}),
                preconditions=st.get("preconditions", {}),
                priority=self._safe_priority(st.get("priority", 3)),
                assigned_skill=st.get("assigned_skill"),
                tags=st.get("tags", []),
                opportunity_triggers=st.get("opportunity_triggers", []),
                deadline=self._deadline_from_seconds(st.get("deadline_seconds")),
                rationale=st.get("rationale", ""),
            )
            title_to_id[title.lower()] = task.id
            dependencies = st.get("depends_on", [])
            if dependencies:
                pending_dependencies.append((task.id, dependencies))
        for task_id, dependencies in pending_dependencies:
            task = self.task_system.tasks.get(task_id)
            if not task:
                continue
            task.depends_on = [
                title_to_id[dep.lower()]
                for dep in dependencies
                if isinstance(dep, str) and dep.lower() in title_to_id
            ]

    def _safe_priority(self, value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 3

    def _deadline_from_seconds(self, seconds) -> float | None:
        if seconds is None:
            return None
        try:
            return time.time() + float(seconds)
        except (TypeError, ValueError):
            return None
