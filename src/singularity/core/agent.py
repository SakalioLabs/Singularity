"""Core agent loop - the main brain of the Singularity Minecraft agent.

Integrates MemorySystem, SkillLibrary, TaskSystem, GoalGenerator, and Explorer
for both goal-directed and autonomous survival modes.
"""
import os
import json
import time
import logging
from dataclasses import asdict
from typing import Optional

from singularity.core.config import Config
from singularity.core.runtime import RuntimeSupervisor
from singularity.core.memory import MemorySystem
from singularity.core.skill_library import SkillLibrary
from singularity.core.task_system import TaskSystem, TaskStatus
from singularity.core.goal_generator import GoalGenerator
from singularity.core.curriculum import CurriculumManager
from singularity.core.goal_verifier import GoalVerifier
from singularity.core.explorer import Explorer
from singularity.observation.observer import Observer
from singularity.action.controller import ActionController
from singularity.bot.bridge import BotBridge
from singularity.logging.session_logger import SessionLogger
from singularity.vision.analyzer import VisionAnalyzer
from singularity.vision.action_advisor import VisualActionAdvisor
from singularity.vision.visual_memory import VisualMemory

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
        self.skill_library = SkillLibrary(storage_path=config.skill_dir, persist=True)
        self.task_system = TaskSystem()
        self.goal_generator = GoalGenerator()
        self.curriculum = CurriculumManager()
        self.goal_verifier = GoalVerifier(skill_library=self.skill_library)
        self.explorer = Explorer()
        self.runtime = RuntimeSupervisor(config, self.explorer)
        self.vision_analyzer = VisionAnalyzer(
            api_key=config.llm.api_key,
            provider=config.llm.provider,
            model=config.llm.model,
        )
        self.visual_memory = VisualMemory()
        self.visual_action_advisor = VisualActionAdvisor()
        self._last_screenshot_at = 0.0

        self._use_llm = bool(config.llm.api_key or os.environ.get("OPENAI_API_KEY"))
        if self._use_llm:
            from singularity.llm.provider import LLMProvider
            from singularity.core.planner import Planner
            from singularity.core.reflector import Reflector
            from singularity.core.goal_verifier import GoalVerificationCritic
            self.llm = LLMProvider(config.llm)
            self.planner = Planner(self.llm, self.task_system)
            self.reflector = Reflector(self.llm)
            if getattr(config, "enable_goal_critic", False):
                self.goal_verifier.goal_critic = GoalVerificationCritic(self.llm)
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
                observation = self._observe()
                self.session_logger.log_observation(observation)
                self.memory.write_context({"cycle": cycle, "observation_summary": self._obs_summary(observation)})
                self.explorer.record_position(observation.get("position", {}))

                plan = self._think(observation)
                self.session_logger.log_plan(plan)
                self.memory.write_context({"plan_status": plan.get("status"), "reasoning": plan.get("reasoning", "")[:200]})
                self._accept_planned_tasks()
                scheduling_state = self._state_with_causal_context(observation, goal)

                verified, verification = self._goal_is_verified(
                    goal,
                    observation,
                    {"cycle": cycle, "mode": "goal", "phase": "pre_plan"},
                )
                if verified:
                    logger.info("Goal verified complete before planning")
                    success = True
                    next_task = self.task_system.get_next_task(scheduling_state)
                    if next_task:
                        self.task_system.complete_task(next_task.id, {"goal": goal, "verification": verification.to_dict()})
                    break

                if plan.get("status") == "complete":
                    accepted, verification = self._accept_plan_completion(
                        goal,
                        observation,
                        plan,
                        {"cycle": cycle, "mode": "goal", "phase": "planner_complete"},
                    )
                    if accepted:
                        logger.info("Goal completed!")
                        success = True
                        next_task = self.task_system.get_next_task(scheduling_state)
                        if next_task:
                            result = {"goal": goal, "reasoning": plan.get("reasoning", "")}
                            if verification:
                                result["verification"] = verification.to_dict()
                            self.task_system.complete_task(next_task.id, result)
                        break
                    logger.info("Planner reported complete, but goal verifier needs more evidence")
                    continue

                actions = plan.get("actions", [])
                for action in actions:
                    if not self.running:
                        break
                    interrupted, observation = self._handle_runtime_interrupt(observation, goal, {"cycle": cycle, "mode": "goal"})
                    if interrupted:
                        break
                    before_action_observation = observation
                    result = self.action_controller.execute(action, observation)
                    self.session_logger.log_action(action, result)
                    self.memory.write_episode("action", {"action": action, "result": result})
                    observation = self._apply_action_feedback(action, result, observation, {"cycle": cycle, "goal": goal})

                    if result.get("success"):
                        self._record_skill_usage(action, True)
                        verified, verification = self._goal_is_verified(
                            goal,
                            observation,
                            {"cycle": cycle, "mode": "goal", "phase": "post_action"},
                            recent_actions=[{
                                "action": action,
                                "result": result,
                                "before_observation": before_action_observation,
                                "after_observation": observation,
                            }],
                        )
                        if verified:
                            success = True
                            break
                    else:
                        self._record_skill_usage(action, False)
                        corrected, observation = self._attempt_failure_correction(
                            action,
                            result,
                            observation,
                            goal,
                            {"cycle": cycle, "mode": "goal"},
                        )
                        if corrected:
                            continue
                        reflection = self._reflect(observation, action, result, goal)
                        self.session_logger.log_reflection(reflection)
                        self.memory.write_episode("failure", {"action": action, "error": result.get("error"), "reflection": reflection})
                        break

                if success:
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
        observation = self._observe()
        pos = observation.get("position", {})
        self.explorer.set_base(pos.get("x", 0), pos.get("y", 64), pos.get("z", 0))

        while self.running and (goals_completed + goals_failed) < max_goals:
            # Generate next goal from world state
            goal = self.goal_generator.next_goal(observation)
            goal = self._select_autonomous_goal(observation, goal)
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
                    observation = self._observe()
                    self.explorer.record_position(observation.get("position", {}))
                    self.memory.write_context({"auto_cycle": total_cycles, "goal": goal[:80]})

                    plan = self._think(observation, override_goal=goal)
                    self._accept_planned_tasks()
                    scheduling_state = self._state_with_causal_context(observation, goal)
                    next_task = self.task_system.get_next_task(scheduling_state)
                    if next_task and next_task.title != goal:
                        logger.info(f"[Autonomous] Opportunistic task selected: {next_task.title}")
                        self.memory.write_episode("opportunity_task", {"from_goal": goal, "task": next_task.title})
                        goal = next_task.title

                    verified, verification = self._goal_is_verified(
                        goal,
                        observation,
                        {"cycle": total_cycles, "mode": "autonomous", "phase": "pre_plan"},
                    )
                    if verified:
                        goal_success = True
                        if next_task:
                            self.task_system.complete_task(next_task.id, {"goal": goal, "cycle": total_cycles, "verification": verification.to_dict()})
                        break

                    if plan.get("status") == "complete":
                        accepted, verification = self._accept_plan_completion(
                            goal,
                            observation,
                            plan,
                            {"cycle": total_cycles, "mode": "autonomous", "phase": "planner_complete"},
                        )
                        if accepted:
                            goal_success = True
                            if next_task:
                                result = {"goal": goal, "cycle": total_cycles}
                                if verification:
                                    result["verification"] = verification.to_dict()
                                self.task_system.complete_task(next_task.id, result)
                            break
                        logger.info("[Autonomous] Planner reported complete, but verifier needs more evidence")
                        continue

                    if plan.get("status") == "blocked":
                        logger.info(f"[Autonomous] Goal blocked: {plan.get('reasoning', '')}")
                        break

                    actions = plan.get("actions", [])
                    for action in actions:
                        if not self.running:
                            break
                        interrupted, observation = self._handle_runtime_interrupt(
                            observation,
                            goal,
                            {"cycle": total_cycles, "mode": "autonomous"},
                        )
                        if interrupted:
                            break
                        before_action_observation = observation
                        result = self.action_controller.execute(action, observation)
                        self.session_logger.log_action(action, result)
                        self.memory.write_episode("action", {"action": action, "result": result})
                        observation = self._apply_action_feedback(
                            action,
                            result,
                            observation,
                            {"cycle": total_cycles, "goal": goal, "mode": "autonomous"},
                        )

                        if result.get("success"):
                            self._record_skill_usage(action, True)
                            verified, verification = self._goal_is_verified(
                                goal,
                                observation,
                                {"cycle": total_cycles, "mode": "autonomous", "phase": "post_action"},
                                recent_actions=[{
                                    "action": action,
                                    "result": result,
                                    "before_observation": before_action_observation,
                                    "after_observation": observation,
                                }],
                            )
                            if verified:
                                goal_success = True
                                break
                        else:
                            self._record_skill_usage(action, False)
                            corrected, observation = self._attempt_failure_correction(
                                action,
                                result,
                                observation,
                                goal,
                                {"cycle": total_cycles, "mode": "autonomous"},
                            )
                            if corrected:
                                continue
                            # Reflect on failure if LLM available
                            if self.reflector:
                                reflection = self.reflector.analyze_failure(
                                    goal, action, result, observation
                                )
                                self.memory.write_episode("failure_reflection", reflection)
                            break

                    if goal_success:
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
                self.curriculum.record_goal_outcome(goal, True, cycle)
            else:
                goals_failed += 1
                logger.info(f"[Autonomous] Goal failed/blocked: {goal}")
                self.memory.write_episode("auto_goal_failed", {"goal": goal, "cycles": cycle})
                self.curriculum.record_goal_outcome(goal, False, cycle)

        result = {
            "mode": "autonomous",
            "goals_completed": goals_completed,
            "goals_failed": goals_failed,
            "total_cycles": total_cycles,
            "landmarks_discovered": len(self.explorer.landmarks),
            "curriculum": self.curriculum.summary(),
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
            plan = self._think_llm(observation, goal)
        else:
            plan = self._think_rule(observation, goal)
        return self._apply_visual_action_grounding(plan, observation, goal)

    def _think_llm(self, observation: dict, goal: str) -> dict:
        # Gather memory context for planning
        memory_context = self.memory.get_relevant_memory(goal)
        context_window = self.memory.get_context_window()

        # Get skill recommendations
        recommended = self.skill_library.get_recommended_skills(goal, observation)
        policy_hints = []
        if self.config.enable_policy_skills:
            policy_hints = self.skill_library.get_policy_skill_hints(goal, observation)
        skill_hint = ""
        if recommended:
            skill_hint = "\nRecommended skills (by success rate): " + ", ".join(
                f"{s.name} ({s.success_rate:.0%})" for s in recommended[:5]
            )
        if policy_hints:
            skill_hint += "\nReviewed causal/correction skills:\n- " + "\n- ".join(policy_hints)
            self._log_policy_intervention("hint", {
                "goal": goal,
                "hints": policy_hints[:5],
            })

        try:
            visual_context = self._visual_memory_context(goal)
            visual_action_context = self._visual_action_context(goal, observation)
            combined_memory = "\n".join(part for part in (memory_context, context_window, visual_context, visual_action_context, skill_hint) if part)
            plan = self.planner.plan_from_goal(goal, observation, combined_memory)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            self.session_logger.log_error(f"LLM call failed: {e}")
            plan = {"status": "error", "actions": [], "reasoning": str(e)}
        return plan

    def _think_rule(self, observation: dict, goal: str) -> dict:
        plan = self.rule_planner.plan_from_goal(goal, observation)
        return plan

    def _visual_action_context(self, goal: str, observation: dict, limit: int = 3) -> str:
        suggestions = self._visual_action_suggestions(goal, observation, limit=limit)
        if not suggestions:
            return ""
        lines = []
        for suggestion in suggestions[:limit]:
            action = suggestion.get("action", {})
            lines.append(
                f"- {suggestion.get('kind')}: prefer {action.get('type')} "
                f"{action.get('parameters', {})} because {suggestion.get('reason')}"
            )
        return "Visual action grounding hints:\n" + "\n".join(lines)

    def _apply_visual_action_grounding(self, plan: dict, observation: dict, goal: str) -> dict:
        if not getattr(getattr(self, "config", None), "enable_visual_action_grounding", True):
            return plan
        suggestions = self._visual_action_suggestions(goal, observation)
        if suggestions:
            self._log_visual_action_suggestions(goal, suggestions)
        if not suggestions or not isinstance(plan, dict):
            return plan

        grounded = dict(plan)
        actions = list(grounded.get("actions", []) or [])
        danger = next((item for item in suggestions if str(item.get("kind", "")).startswith("danger_")), None)
        if danger and not self._action_in_sequence(danger.get("action", {}), actions):
            grounded["actions"] = [danger["action"]] + actions
            grounded["status"] = "in_progress"
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding inserted safety action: {danger.get('reason')}",
            )
            self._log_visual_action_intervention(goal, danger, "prepend_danger")
            return grounded

        if not actions:
            best = suggestions[0]
            grounded["actions"] = [best["action"]]
            grounded["status"] = "in_progress"
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding supplied action: {best.get('reason')}",
            )
            self._log_visual_action_intervention(goal, best, "fill_empty_plan")
            return grounded

        approach = self._visual_approach_for_action(actions[0], suggestions)
        if approach and not self._action_in_sequence(approach.get("action", {}), actions):
            grounded["actions"] = [approach["action"]] + actions
            grounded["status"] = "in_progress"
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding inserted approach action: {approach.get('reason')}",
            )
            self._log_visual_action_intervention(goal, approach, "prepend_approach")
            return grounded

        focus = self._visual_focus_for_action(actions[0], suggestions)
        if focus and not self._action_in_sequence(focus.get("action", {}), actions):
            grounded["actions"] = [focus["action"]] + actions
            grounded["status"] = "in_progress"
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding inserted focus action: {focus.get('reason')}",
            )
            self._log_visual_action_intervention(goal, focus, "prepend_focus")
            return grounded

        replacement = self._visual_coordinate_replacement(actions[0], suggestions)
        if replacement:
            actions[0] = replacement["action"]
            grounded["actions"] = actions
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding filled action coordinates: {replacement.get('reason')}",
            )
            self._log_visual_action_intervention(goal, replacement, "fill_coordinates")
            approach = self._visual_approach_for_action(actions[0], suggestions)
            if approach and not self._action_in_sequence(approach.get("action", {}), actions):
                grounded["actions"] = [approach["action"]] + actions
                grounded["status"] = "in_progress"
                grounded["reasoning"] = self._append_reasoning(
                    grounded.get("reasoning", ""),
                    f"Visual grounding inserted approach action: {approach.get('reason')}",
                )
                self._log_visual_action_intervention(goal, approach, "prepend_approach")
                return grounded
            focus = self._visual_focus_for_action(actions[0], suggestions)
            if focus and not self._action_in_sequence(focus.get("action", {}), actions):
                grounded["actions"] = [focus["action"]] + actions
                grounded["status"] = "in_progress"
                grounded["reasoning"] = self._append_reasoning(
                    grounded.get("reasoning", ""),
                    f"Visual grounding inserted focus action: {focus.get('reason')}",
                )
                self._log_visual_action_intervention(goal, focus, "prepend_focus")
        return grounded

    def _visual_action_suggestions(self, goal: str, observation: dict, limit: int = 4) -> list[dict]:
        advisor = getattr(self, "visual_action_advisor", None)
        if not advisor:
            return []
        try:
            return advisor.suggest(goal, observation or {}, limit=limit)
        except Exception as e:
            logger.warning(f"Visual action advisor failed: {e}")
            return []

    def _visual_coordinate_replacement(self, action: dict, suggestions: list[dict]) -> Optional[dict]:
        if not isinstance(action, dict) or action.get("type") != "dig":
            return None
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        if all(key in params for key in ("x", "y", "z")):
            return None
        return next(
            (
                suggestion for suggestion in suggestions
                if suggestion.get("action", {}).get("type") == "dig"
                and all(key in suggestion.get("action", {}).get("parameters", {}) for key in ("x", "y", "z"))
            ),
            None,
        )

    def _visual_approach_for_action(self, action: dict, suggestions: list[dict]) -> Optional[dict]:
        if not isinstance(action, dict) or action.get("type") != "dig":
            return None
        action_pos = self._action_position_tuple(action)
        if not action_pos:
            return None
        for suggestion in suggestions:
            if suggestion.get("kind") != "resource_approach":
                continue
            resource = suggestion.get("target", {}).get("resource", {})
            resource_pos = {"parameters": resource.get("position", {})}
            if self._action_position_tuple(resource_pos) == action_pos:
                return suggestion
        return None

    def _visual_focus_for_action(self, action: dict, suggestions: list[dict]) -> Optional[dict]:
        if not isinstance(action, dict) or action.get("type") != "dig":
            return None
        action_pos = self._action_position_tuple(action)
        if not action_pos:
            return None
        for suggestion in suggestions:
            if suggestion.get("kind") != "resource_focus":
                continue
            if self._action_position_tuple(suggestion.get("action", {})) == action_pos:
                return suggestion
        return None

    def _action_position_tuple(self, action: dict) -> Optional[tuple]:
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        if not all(key in params for key in ("x", "y", "z")):
            return None
        try:
            return tuple(round(float(params[key]), 3) for key in ("x", "y", "z"))
        except (TypeError, ValueError):
            return None

    def _append_reasoning(self, reasoning: str, addition: str) -> str:
        return (str(reasoning or "").rstrip() + ("\n" if reasoning else "") + addition).strip()

    def _action_in_sequence(self, action: dict, actions: list[dict]) -> bool:
        if not isinstance(action, dict):
            return False
        return any(existing == action for existing in actions if isinstance(existing, dict))

    def _log_visual_action_suggestions(self, goal: str, suggestions: list[dict]):
        payload = {"goal": goal, "suggestions": suggestions[:4]}
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("visual_action_suggestion", payload)
        if hasattr(self, "memory") and self.memory and hasattr(self.memory, "write_episode"):
            self.memory.write_episode("visual_action_suggestion", payload)

    def _log_visual_action_intervention(self, goal: str, suggestion: dict, phase: str):
        payload = {"goal": goal, "phase": phase, "suggestion": suggestion}
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("visual_action_intervention", payload)
        if hasattr(self, "memory") and self.memory and hasattr(self.memory, "write_episode"):
            self.memory.write_episode("visual_action_intervention", payload)

    def _reflect(self, observation: dict, action: dict, result: dict, goal: str) -> dict:
        if not self._use_llm or not self.reflector:
            return {"analysis": "Rule planner - no reflection available", "suggestion": "retry", "should_retry": True}
        return self.reflector.analyze_failure(goal, action, result, observation)

    # ── Helpers ────────────────────────────────────────────────────────

    def _goal_is_verified(
        self,
        goal: str,
        observation: dict,
        context: dict = None,
        recent_actions: list[dict] = None,
    ) -> tuple[bool, object]:
        """Return whether observation proves the goal, logging decisive checks."""
        if not getattr(getattr(self, "config", None), "enable_goal_verification", True):
            return False, None
        if not hasattr(self, "goal_verifier"):
            return False, None
        verification = self.goal_verifier.verify(goal, observation, recent_actions=recent_actions or [])
        if verification.achieved:
            self._log_goal_verification(verification, {**(context or {}), "accepted": True})
        return verification.achieved, verification

    def _accept_plan_completion(
        self,
        goal: str,
        observation: dict,
        plan: dict,
        context: dict = None,
        recent_actions: list[dict] = None,
    ) -> tuple[bool, object]:
        """Gate planner-reported completion through deterministic verification."""
        if not getattr(getattr(self, "config", None), "enable_goal_verification", True):
            return True, None
        if not hasattr(self, "goal_verifier"):
            return True, None
        verification = self.goal_verifier.verify(goal, observation, recent_actions=recent_actions or [])
        accepted = verification.achieved or verification.status == "unknown"
        payload = {
            **(context or {}),
            "accepted": accepted,
            "planner_status": plan.get("status"),
            "planner_reasoning": plan.get("reasoning", "")[:300],
        }
        critic_matched = "goal_critic" in getattr(verification, "matched_rules", [])
        if verification.status == "unknown" and accepted:
            payload["acceptance_reason"] = "no_deterministic_rule_matched"
        elif not accepted:
            payload["acceptance_reason"] = "critic_evidence_missing" if critic_matched else "deterministic_evidence_missing"
        else:
            payload["acceptance_reason"] = "critic_evidence_satisfied" if critic_matched else "deterministic_evidence_satisfied"
        self._log_goal_verification(verification, payload)
        return accepted, verification

    def _log_goal_verification(self, verification, context: dict = None):
        """Record self-verification outcomes for debugging and benchmark analysis."""
        payload = verification.to_dict()
        payload["context"] = context or {}
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("goal_verification", payload)
        if hasattr(self, "memory") and hasattr(self.memory, "write_episode"):
            self.memory.write_episode("goal_verification", payload)

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

    def _attempt_failure_correction(
        self,
        failed_action: dict,
        failed_result: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ) -> tuple[bool, dict]:
        """Run an approved correction sequence for a failed action when one matches."""
        if hasattr(self, "config") and not getattr(self.config, "enable_policy_skills", True):
            return False, observation
        match = self.skill_library.find_failure_correction(failed_action, failed_result, observation)
        if not match:
            return False, observation

        skill, payload = match
        sequence = payload.get("correction_sequence", [])
        if not sequence:
            return False, observation

        self.memory.write_episode("failure_correction_selected", {
            "skill": skill.name,
            "failed_action": failed_action,
            "failed_error": failed_result.get("error"),
            "goal": goal,
        })
        self._log_policy_intervention("selected", {
            "kind": "failure_correction",
            "skill": skill.name,
            "failed_action": failed_action,
            "failed_error": failed_result.get("error"),
            "goal": goal,
        })

        current_observation = observation
        for idx, correction_action in enumerate(sequence):
            if not isinstance(correction_action, dict):
                continue
            interrupted, current_observation = self._handle_runtime_interrupt(
                current_observation,
                goal,
                {**(context or {}), "correction_skill": skill.name, "correction_index": idx},
            )
            if interrupted:
                self.skill_library.record_use(skill.name, False)
                self._log_policy_intervention("failed", {
                    "kind": "failure_correction",
                    "skill": skill.name,
                    "reason": "runtime_interrupt",
                    "step": idx,
                })
                return False, current_observation

            result = self.action_controller.execute(correction_action, current_observation)
            self.session_logger.log_action(correction_action, result)
            self.memory.write_episode("failure_correction_action", {
                "skill": skill.name,
                "action": correction_action,
                "result": result,
            })
            self._log_policy_intervention("action", {
                "kind": "failure_correction",
                "skill": skill.name,
                "step": idx,
                "action": correction_action,
                "result": result,
            })
            current_observation = self._apply_action_feedback(
                correction_action,
                result,
                current_observation,
                {**(context or {}), "goal": goal, "correction_skill": skill.name, "correction_index": idx},
            )

            self._record_skill_usage(correction_action, bool(result.get("success")))
            if not result.get("success"):
                self.skill_library.record_use(skill.name, False)
                self.memory.write_episode("failure_correction_failed", {
                    "skill": skill.name,
                    "failed_step": idx,
                    "error": result.get("error"),
                })
                self._log_policy_intervention("failed", {
                    "kind": "failure_correction",
                    "skill": skill.name,
                    "step": idx,
                    "error": result.get("error"),
                })
                return False, current_observation

        self.skill_library.record_use(skill.name, True)
        self.memory.write_episode("failure_correction_completed", {
            "skill": skill.name,
            "steps": len(sequence),
            "goal": goal,
        })
        self._log_policy_intervention("completed", {
            "kind": "failure_correction",
            "skill": skill.name,
            "steps": len(sequence),
            "goal": goal,
        })
        return True, current_observation

    def _log_policy_intervention(self, phase: str, payload: dict):
        """Record online use of reviewed causal/correction skills for benchmark metrics."""
        if not hasattr(self, "session_logger") or not hasattr(self.session_logger, "log"):
            return
        event_type = "policy_hint" if phase == "hint" else "policy_intervention"
        data = {"phase": phase}
        data.update(payload or {})
        self.session_logger.log(event_type, data)

    def _accept_planned_tasks(self):
        """Move newly proposed planner tasks into the scheduler queue."""
        for task in self.task_system.tasks.values():
            if task.status == TaskStatus.PROPOSED:
                self.task_system.update_task(task.id, status=TaskStatus.ACCEPTED)

    def _select_autonomous_goal(self, observation: dict, fallback_goal: str) -> str:
        """Let ready tasks and open-ended curriculum override generated goals."""
        scheduling_state = self._state_with_causal_context(observation, fallback_goal)
        next_task = self.task_system.get_next_task(scheduling_state)
        if next_task:
            return next_task.title
        if (
            getattr(getattr(self, "config", None), "enable_autocurriculum", True)
            and hasattr(self, "curriculum")
        ):
            goal = self.curriculum.next_goal(
                observation,
                fallback_goal,
                getattr(self, "memory", None),
                getattr(self, "skill_library", None),
            )
            if hasattr(self, "memory") and goal != fallback_goal:
                self.memory.write_episode("curriculum_goal", {
                    "fallback": fallback_goal,
                    "selected": goal,
                    "decision": getattr(self.curriculum, "last_decision", {}),
                })
            return goal
        return fallback_goal

    def _state_with_causal_context(self, observation: dict, goal: str = "") -> dict:
        """Augment world state with compact causal event tags for scheduling."""
        if not hasattr(self, "memory") or not hasattr(self.memory, "get_causal_opportunity_context"):
            return observation
        context = self.memory.get_causal_opportunity_context(self._causal_scheduling_query(goal), observation)
        if not context.get("causal_tags") and not context.get("causal_events"):
            return observation

        enriched = dict(observation)
        existing_tags = set(str(tag).lower() for tag in enriched.get("causal_tags", []))
        existing_tags.update(context.get("causal_tags", []))
        enriched["causal_tags"] = sorted(tag for tag in existing_tags if tag)
        enriched["causal_events"] = list(enriched.get("causal_events", [])) + context.get("causal_events", [])
        return enriched

    def _causal_scheduling_query(self, goal: str = "") -> str:
        parts = [goal]
        if not hasattr(self, "task_system"):
            return goal
        for task in self.task_system.tasks.values():
            if task.status in (TaskStatus.ACCEPTED, TaskStatus.ACTIVE):
                parts.append(task.title)
                parts.extend(task.tags)
                parts.extend(task.opportunity_triggers)
        return " ".join(str(part) for part in parts if part)

    def _observe(self) -> dict:
        """Observe world state and attach lightweight visual grounding when enabled."""
        observation = self.observer.observe()
        if not getattr(getattr(self, "config", None), "enable_vision_analysis", True):
            return observation
        observation = self._maybe_capture_screenshot(observation)
        if not hasattr(self, "vision_analyzer") or not self.vision_analyzer:
            return observation
        try:
            screenshot_path = self._screenshot_path_from_observation(observation)
            analysis = self.vision_analyzer.analyze(observation, screenshot_path=screenshot_path)
        except Exception as e:
            logger.warning(f"Vision analysis failed: {e}")
            return observation
        if not isinstance(analysis, dict):
            return observation
        enriched = self._merge_visual_analysis(observation, analysis)
        self._log_vision_analysis(analysis, screenshot_path=screenshot_path)
        return enriched

    def _maybe_capture_screenshot(self, observation: dict) -> dict:
        """Attach a screenshot path when an optional bridge renderer can provide one."""
        if not getattr(getattr(self, "config", None), "enable_screenshot_capture", False):
            return observation
        if self._screenshot_path_from_observation(observation or {}):
            return observation
        capture = getattr(getattr(self, "bot", None), "capture_screenshot", None)
        if not callable(capture):
            return observation

        now = time.time()
        min_interval = float(getattr(self.config, "screenshot_min_interval_s", 0.0) or 0.0)
        last_capture = float(getattr(self, "_last_screenshot_at", 0.0) or 0.0)
        if min_interval > 0 and now - last_capture < min_interval:
            return observation

        output_path = self._next_screenshot_path()
        self._last_screenshot_at = now
        try:
            result = capture(output_path)
        except Exception as e:
            logger.warning(f"Screenshot capture failed: {e}")
            return observation
        if not isinstance(result, dict) or not result.get("success"):
            return observation

        screenshot_path = self._screenshot_path_from_observation(result)
        if not screenshot_path:
            screenshot_path = result.get("path", "") or result.get("file", "")
        if not isinstance(screenshot_path, str) or not screenshot_path.strip():
            return observation

        enriched = dict(observation or {})
        enriched["screenshot_path"] = screenshot_path.strip()
        enriched["screenshot_capture"] = {
            "source": result.get("source", "bridge_renderer"),
            "supported": result.get("supported", True),
        }
        return enriched

    def _next_screenshot_path(self) -> str:
        screenshot_dir = getattr(getattr(self, "config", None), "screenshot_dir", "logs/screenshots") or "logs/screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        session_id = str(getattr(getattr(self, "session_logger", None), "session_id", "session") or "session")
        safe_session = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in session_id)[:80] or "session"
        return os.path.join(screenshot_dir, f"{safe_session}_{int(time.time() * 1000)}.png")

    def _screenshot_path_from_observation(self, observation: dict) -> str:
        for key in ("screenshot_path", "screenshot", "image_path", "frame_path"):
            value = observation.get(key) if isinstance(observation, dict) else ""
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _merge_visual_analysis(self, observation: dict, analysis: dict) -> dict:
        enriched = dict(observation or {})
        if analysis.get("grounded_resources"):
            enriched["grounded_resources"] = analysis["grounded_resources"]
        if analysis.get("resources"):
            enriched["visual_resources"] = analysis["resources"]
        if analysis.get("dangers"):
            enriched["dangers"] = analysis["dangers"]
        if analysis.get("visual_analysis"):
            enriched["visual_analysis"] = analysis["visual_analysis"]
        return enriched

    def _log_vision_analysis(self, analysis: dict, screenshot_path: str = ""):
        payload = {
            key: value
            for key, value in analysis.items()
            if key in {"position", "health", "grounded_resources", "resources", "dangers", "nearby_entities", "visual_analysis"}
            and value not in (None, "", [], {})
        }
        if screenshot_path:
            payload["screenshot_path"] = screenshot_path
        if not payload:
            return
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("vision", payload)
        if hasattr(self, "visual_memory") and self.visual_memory:
            self.visual_memory.add(payload, "observation")

    def _visual_memory_context(self, goal: str = "", limit: int = 3) -> str:
        if not hasattr(self, "visual_memory") or not self.visual_memory:
            return ""
        try:
            entries = self.visual_memory.search(goal) if goal else []
            if not entries:
                entries = self.visual_memory.get_recent(limit)
        except Exception:
            return ""
        lines = []
        for entry in entries[-limit:]:
            data = entry.get("data", {}) if isinstance(entry.get("data", {}), dict) else {}
            parts = []
            resources = data.get("grounded_resources") or data.get("resources") or []
            if resources:
                names = [
                    str(item.get("name", item.get("type", "")))
                    for item in resources[:4]
                    if isinstance(item, dict) and (item.get("name") or item.get("type"))
                ]
                if names:
                    parts.append("resources=" + ",".join(names))
            dangers = data.get("dangers") or []
            if dangers:
                names = [
                    str(item.get("type", item.get("name", "")))
                    for item in dangers[:3]
                    if isinstance(item, dict) and (item.get("type") or item.get("name"))
                ]
                if names:
                    parts.append("dangers=" + ",".join(names))
            if data.get("visual_analysis"):
                parts.append("analysis=" + str(data["visual_analysis"])[:160])
            if parts:
                lines.append("- " + "; ".join(parts))
        return "Recent visual memory:\n" + "\n".join(lines) if lines else ""

    def _apply_action_feedback(self, action: dict, result: dict, fallback_observation: dict, context: dict = None) -> dict:
        """Observe after an action and let TaskSystem update state from evidence."""
        observation = fallback_observation
        try:
            observation = self._observe()
            self.session_logger.log_observation(observation)
            self.memory.write_context({
                "post_action": context or {},
                "observation_summary": self._obs_summary(observation),
            })
            self.explorer.record_position(observation.get("position", {}))
        except Exception as e:
            logger.warning(f"Post-action observation failed: {e}")

        task = self.task_system.apply_action_result(action, result, observation)
        if task:
            self.memory.write_episode("task_state_update", {
                "task_id": task.id,
                "task": task.title,
                "status": task.status.value,
                "action": action.get("type"),
                "success": bool(result.get("success")),
            })
        if hasattr(self.memory, "record_causal_transition"):
            causal_context = dict(context or {})
            if task:
                causal_context.update({"task_id": task.id, "task_status": task.status.value})
            self.memory.record_causal_transition(
                fallback_observation,
                action,
                result,
                observation,
                goal=causal_context.get("goal", ""),
                task=task.title if task else "",
                context=causal_context,
            )
        return observation

    def _handle_runtime_interrupt(self, observation: dict, goal: str, context: dict = None) -> tuple[bool, dict]:
        """Let the actor loop yield when fast runtime safety checks fire."""
        task = self.task_system.get_next_task(observation)
        decision = self.runtime.evaluate_interrupt(observation, goal=goal, active_task=task)
        if not decision.should_interrupt:
            return False, observation

        payload = asdict(decision)
        payload["goal"] = goal
        payload["context"] = context or {}
        logger.warning(f"Runtime interrupt: {decision.reason}")
        self.session_logger.log("runtime_interrupt", payload, level="WARNING")
        self.memory.write_episode("runtime_interrupt", payload)

        if decision.emergency_action:
            result = self.action_controller.execute(decision.emergency_action, observation)
            self.session_logger.log_action(decision.emergency_action, result)
            self.memory.write_episode("runtime_emergency_action", {"action": decision.emergency_action, "result": result})
            observation = self._apply_action_feedback(decision.emergency_action, result, observation, context or {})

        return True, observation

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
