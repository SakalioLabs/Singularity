"""Core agent loop - the main brain of the Singularity Minecraft agent.

Integrates MemorySystem, SkillLibrary, TaskSystem, GoalGenerator, and Explorer
for both goal-directed and autonomous survival modes.
"""
import os
import json
import time
import logging
from typing import Optional

from singularity.core.config import Config
from singularity.core.memory import MemorySystem
from singularity.core.skill_library import SkillLibrary
from singularity.core.task_system import TaskSystem, TaskStatus
from singularity.core.goal_generator import GoalGenerator
from singularity.core.explorer import Explorer
from singularity.observation.observer import Observer
from singularity.action.controller import ActionController
from singularity.bot.bridge import BotBridge
from singularity.logging.session_logger import SessionLogger

logger = logging.getLogger("singularity")


class Agent:
    """Main agent that orchestrates observe-think-act cycles.

    Supports two modes:
    - Goal-directed: pursue a specific natural-language goal
    - Autonomous: self-direct survival goals using GoalGenerator (M4) and Explorer (M5)
    """

    def __init__(self, config: Config):
        self.config = config
        self.bot = BotBridge(config.bot)
        self.observer = Observer(self.bot)
        self.action_controller = ActionController(self.bot, config)
        self.running = False
        self.session_log: list[dict] = []
        self.current_goal: Optional[str] = None
        self.session_logger = SessionLogger(log_dir=config.log_dir)

        # Integrated modules
        self.memory = MemorySystem(memory_dir=config.memory_dir)
        self.skill_library = SkillLibrary()
        self.task_system = TaskSystem()
        self.goal_generator = GoalGenerator()
        self.explorer = Explorer()

        self._use_llm = bool(config.llm.api_key or os.environ.get("OPENAI_API_KEY"))
        if self._use_llm:
            from singularity.llm.provider import LLMProvider
            from singularity.core.reflector import Reflector
            self.llm = LLMProvider(config.llm)
            self.reflector = Reflector(self.llm)
            logger.info("Using LLM planner with full module integration")
        else:
            from singularity.core.rule_planner import RuleBasedPlanner
            self.rule_planner = RuleBasedPlanner()
            self.reflector = None
            logger.info("No API key - using rule-based planner")

    def connect(self) -> bool:
        logger.info(f"Connecting to {self.config.bot.host}:{self.config.bot.port}")
        success = self.bot.connect()
        self.session_logger.log_connect(self.config.bot.host, self.config.bot.port, success)
        if success:
            logger.info("Connected successfully")
            # Set explorer base to spawn position
            state = self.bot.get_player_state()
            pos = state.get("position", {})
            self.explorer.set_base(pos.get("x", 0), pos.get("y", 64), pos.get("z", 0))
        else:
            logger.error("Connection failed")
        return success

    def disconnect(self):
        self.running = False
        self.memory.save_session(self.session_logger.session_id)
        self.bot.disconnect()
        self.session_logger.close()

    # ── Goal-directed mode ──────────────────────────────────────────────

    def run_goal(self, goal: str) -> dict:
        """Pursue a specific natural-language goal."""
        self.current_goal = goal
        self.running = True
        logger.info(f"Starting goal: {goal}")
        self.session_logger.log_goal_start(goal)
        self.memory.write_episode("goal_start", {"goal": goal})

        max_cycles = 100
        cycle = 0
        success = False

        while self.running and cycle < max_cycles:
            cycle += 1
            try:
                observation = self.observer.observe()
                self.session_logger.log_observation(observation)
                self.memory.write_context({"cycle": cycle, "observation_summary": self._obs_summary(observation)})
                self.explorer.record_position(observation.get("position", {}))

                plan = self._think(observation)
                self.session_logger.log_plan(plan)
                self.memory.write_context({"plan_status": plan.get("status"), "reasoning": plan.get("reasoning", "")[:200]})

                if plan.get("status") == "complete":
                    logger.info("Goal completed!")
                    success = True
                    break

                actions = plan.get("actions", [])
                for action in actions:
                    if not self.running:
                        break
                    result = self.action_controller.execute(action, observation)
                    self.session_logger.log_action(action, result)
                    self.memory.write_episode("action", {"action": action, "result": result})

                    if result.get("success"):
                        self._record_skill_usage(action, True)
                    else:
                        self._record_skill_usage(action, False)
                        reflection = self._reflect(observation, action, result, goal)
                        self.session_logger.log_reflection(reflection)
                        self.memory.write_episode("failure", {"action": action, "error": result.get("error"), "reflection": reflection})
                        break

                if observation.get("health", 20) < self.config.health_critical_threshold:
                    logger.warning("Health critical - aborting goal")
                    self.session_logger.log_error("Health critical", {"health": observation["health"]})
                    break
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error in cycle {cycle}: {e}")
                self.session_logger.log_error(str(e), {"cycle": cycle})

        result = {
            "goal": goal,
            "cycles": cycle,
            "completed": success,
            "summary": self.session_logger.get_summary(),
        }
        self.session_logger.log_goal_end(goal, result)
        self.memory.write_episode("goal_end", {"goal": goal, "success": success, "cycles": cycle})
        return result

    # ── Autonomous mode (M4 + M5) ──────────────────────────────────────

    def run_autonomous(self, max_goals: int = 10, max_cycles_per_goal: int = 80) -> dict:
        """Run autonomously: generate survival goals, pursue them, explore when idle.

        This is the M4 (autonomous survival) + M5 (exploration) integration loop.
        """
        self.running = True
        goals_completed = 0
        goals_failed = 0
        total_cycles = 0

        logger.info("Starting autonomous survival mode")
        self.session_logger.log_goal_start("AUTONOMOUS_MODE")
        self.memory.write_episode("autonomous_start", {"max_goals": max_goals})

        # Set base on first observation
        observation = self.observer.observe()
        pos = observation.get("position", {})
        self.explorer.set_base(pos.get("x", 0), pos.get("y", 64), pos.get("z", 0))

        while self.running and (goals_completed + goals_failed) < max_goals:
            # Generate next goal from world state
            goal = self.goal_generator.next_goal(observation)
            logger.info(f"[Autonomous] Goal {goals_completed + goals_failed + 1}/{max_goals}: {goal}")
            self.memory.write_episode("auto_goal", {"goal": goal})

            # Check if we should return to base (M5)
            should_ret, reason = self.explorer.should_return(
                observation.get("position", {}),
                observation.get("inventory_count", 0)
            )
            if should_ret:
                logger.info(f"[Explorer] Returning to base: {reason}")
                return_dir = self.explorer.get_return_direction(observation.get("position", {}))
                self.action_controller.execute(
                    {"type": "move_to", "parameters": {"x": return_dir["x"], "z": return_dir["z"]}},
                    observation
                )

            # Pursue the goal
            cycle = 0
            goal_success = False
            while self.running and cycle < max_cycles_per_goal:
                cycle += 1
                total_cycles += 1
                try:
                    observation = self.observer.observe()
                    self.explorer.record_position(observation.get("position", {}))
                    self.memory.write_context({"auto_cycle": total_cycles, "goal": goal[:80]})

                    plan = self._think(observation, override_goal=goal)

                    if plan.get("status") == "complete":
                        goal_success = True
                        break

                    if plan.get("status") == "blocked":
                        logger.info(f"[Autonomous] Goal blocked: {plan.get('reasoning', '')}")
                        break

                    actions = plan.get("actions", [])
                    for action in actions:
                        if not self.running:
                            break
                        result = self.action_controller.execute(action, observation)
                        self.session_logger.log_action(action, result)

                        if result.get("success"):
                            self._record_skill_usage(action, True)
                        else:
                            self._record_skill_usage(action, False)
                            # Reflect on failure if LLM available
                            if self.reflector:
                                reflection = self.reflector.analyze_failure(
                                    goal, action, result, observation
                                )
                                self.memory.write_episode("failure_reflection", reflection)
                            break

                    if observation.get("health", 20) < self.config.health_critical_threshold:
                        logger.warning("[Autonomous] Health critical - emergency survival")
                        break

                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error in autonomous cycle {total_cycles}: {e}")
                    self.session_logger.log_error(str(e), {"cycle": total_cycles})

            if goal_success:
                goals_completed += 1
                logger.info(f"[Autonomous] Goal completed: {goal}")
                self.memory.write_episode("auto_goal_complete", {"goal": goal, "cycles": cycle})
            else:
                goals_failed += 1
                logger.info(f"[Autonomous] Goal failed/blocked: {goal}")
                self.memory.write_episode("auto_goal_failed", {"goal": goal, "cycles": cycle})

        result = {
            "mode": "autonomous",
            "goals_completed": goals_completed,
            "goals_failed": goals_failed,
            "total_cycles": total_cycles,
            "landmarks_discovered": len(self.explorer.landmarks),
            "summary": self.session_logger.get_summary(),
        }
        self.session_logger.log_goal_end("AUTONOMOUS_MODE", result)
        self.memory.write_episode("autonomous_end", result)
        logger.info(f"Autonomous mode ended: {goals_completed} completed, {goals_failed} failed, {total_cycles} total cycles")
        return result

    # ── Thinking / Planning ────────────────────────────────────────────

    def _think(self, observation: dict, override_goal: str = None) -> dict:
        goal = override_goal or self.current_goal or "explore"
        if self._use_llm:
            return self._think_llm(observation, goal)
        else:
            return self._think_rule(observation, goal)

    def _think_llm(self, observation: dict, goal: str) -> dict:
        # Gather memory context for planning
        memory_context = self.memory.get_relevant_memory(goal)
        context_window = self.memory.get_context_window()

        # Get skill recommendations
        recommended = self.skill_library.get_recommended_skills(goal, observation)
        skill_hint = ""
        if recommended:
            skill_hint = "\nRecommended skills (by success rate): " + ", ".join(
                f"{s.name} ({s.success_rate:.0%})" for s in recommended[:5]
            )

        prompt = self._build_planning_prompt(observation, goal, memory_context, skill_hint)

        try:
            response = self.llm.chat([
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ], response_format={"type": "json_object"})
            plan = json.loads(response)
        except json.JSONDecodeError:
            plan = {"status": "error", "actions": [], "reasoning": "LLM output was not valid JSON"}
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            self.session_logger.log_error(f"LLM call failed: {e}")
            plan = {"status": "error", "actions": [], "reasoning": str(e)}
        return plan

    def _think_rule(self, observation: dict, goal: str) -> dict:
        plan = self.rule_planner.plan_from_goal(goal, observation)
        return plan

    def _reflect(self, observation: dict, action: dict, result: dict, goal: str) -> dict:
        if not self._use_llm or not self.reflector:
            return {"analysis": "Rule planner - no reflection available", "suggestion": "retry", "should_retry": True}
        return self.reflector.analyze_failure(goal, action, result, observation)

    # ── Helpers ────────────────────────────────────────────────────────

    def _record_skill_usage(self, action: dict, success: bool):
        """Record skill usage for actions that map to known skills."""
        action_type = action.get("type", "")
        skill_mapping = {
            "dig": "dig_block",
            "craft": "craft_item",
            "move_to": "move_to",
            "attack": "attack_entity",
            "place": "place_block",
            "equip": None,
            "use_item": None,
            "look_at": None,
            "chat": None,
            "wait": None,
        }
        skill_name = skill_mapping.get(action_type)
        if skill_name:
            self.skill_library.record_use(skill_name, success)

    def _obs_summary(self, obs: dict) -> dict:
        """Compact observation summary for memory."""
        return {
            "pos": obs.get("position", {}),
            "hp": obs.get("health"),
            "food": obs.get("hunger"),
            "inv_count": obs.get("inventory_count"),
            "trees": len(obs.get("trees_found", [])),
            "hostiles": len([e for e in obs.get("nearby_entities", []) if e.get("hostile")]),
            "time": obs.get("time_of_day"),
        }

    def _system_prompt(self) -> str:
        return """You are a Minecraft agent planner. Given the current game state observation, decide the next actions to achieve the goal.
Available actions: move_to, look_at, dig, place, craft, attack, equip, use_item, chat, wait
Output JSON format:
{"status": "in_progress" or "complete" or "blocked", "reasoning": "...", "actions": [{"type": "action_name", "parameters": {...}}]}
Be practical. Prefer simple, safe actions. Check inventory before crafting."""

    def _build_planning_prompt(self, observation: dict, goal: str, memory_context: str = "", skill_hint: str = "") -> str:
        parts = [f"Current goal: {goal}", f"\nCurrent observation:\n{json.dumps(observation, indent=2, default=str)[:2000]}"]
        if memory_context:
            parts.append(f"\nRelevant memory:\n{memory_context[:500]}")
        if skill_hint:
            parts.append(skill_hint)
        parts.append("\nWhat actions should I take next? Output JSON.")
        return "\n".join(parts)
