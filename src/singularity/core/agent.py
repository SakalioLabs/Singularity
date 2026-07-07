"""Core agent loop - the main brain of the Singularity Minecraft agent."""
import json
import time
import logging
from typing import Optional

from singularity.core.config import Config
from singularity.observation.observer import Observer
from singularity.action.controller import ActionController
from singularity.llm.provider import LLMProvider
from singularity.bot.bridge import BotBridge
from singularity.logging.session_logger import SessionLogger

logger = logging.getLogger("singularity")


class Agent:
    """Main agent that orchestrates observe-think-act cycles."""

    def __init__(self, config: Config):
        self.config = config
        self.bot = BotBridge(config.bot)
        self.observer = Observer(self.bot)
        self.action_controller = ActionController(self.bot, config)
        self.llm = LLMProvider(config.llm)
        self.running = False
        self.session_log: list[dict] = []
        self.current_goal: Optional[str] = None
        self.task_stack: list[dict] = []
        self.session_logger = SessionLogger(log_dir=config.log_dir)

    def connect(self) -> bool:
        """Connect to Minecraft server."""
        logger.info(f"Connecting to {self.config.bot.host}:{self.config.bot.port}")
        success = self.bot.connect()
        self.session_logger.log_connect(
            self.config.bot.host, self.config.bot.port, success
        )
        if success:
            logger.info("Connected successfully")
        else:
            logger.error("Connection failed")
        return success

    def disconnect(self):
        """Disconnect from server."""
        self.running = False
        self.bot.disconnect()
        self.session_logger.close()

    def run_goal(self, goal: str) -> dict:
        """Execute a natural-language goal and return the result."""
        self.current_goal = goal
        self.running = True
        logger.info(f"Starting goal: {goal}")
        self.session_logger.log_goal_start(goal)

        max_cycles = 100
        cycle = 0

        while self.running and cycle < max_cycles:
            cycle += 1
            try:
                # Observe
                observation = self.observer.observe()
                self.session_logger.log_observation(observation)

                # Think (LLM planning)
                plan = self._think(observation)
                self.session_logger.log_plan(plan)

                if plan.get("status") == "complete":
                    logger.info("Goal completed!")
                    break

                # Act
                actions = plan.get("actions", [])
                for action in actions:
                    if not self.running:
                        break
                    result = self.action_controller.execute(action, observation)
                    self.session_logger.log_action(action, result)

                    if not result.get("success"):
                        # Failure - trigger reflection
                        reflection = self._reflect(observation, action, result)
                        self.session_logger.log_reflection(reflection)
                        break

                # Check health safety
                if observation.get("health", 20) < self.config.health_critical_threshold:
                    logger.warning("Health critical - aborting goal")
                    self.session_logger.log_error(
                        "Health critical", {"health": observation["health"]}
                    )
                    break

                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error in cycle {cycle}: {e}")
                self.session_logger.log_error(str(e), {"cycle": cycle})

        result = {
            "goal": goal,
            "cycles": cycle,
            "completed": plan.get("status") == "complete" if "plan" in dir() else False,
            "summary": self.session_logger.get_summary(),
        }
        self.session_logger.log_goal_end(goal, result)
        return result

    def _think(self, observation: dict) -> dict:
        """Use LLM to decide the next action based on current observation."""
        prompt = self._build_planning_prompt(observation)
        try:
            response = self.llm.chat([
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ], response_format={"type": "json_object"})
            plan = json.loads(response)
        except json.JSONDecodeError:
            plan = {"status": "error", "actions": [], "reason": "LLM output was not valid JSON"}
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            self.session_logger.log_error(f"LLM call failed: {e}")
            plan = {"status": "error", "actions": [], "reason": str(e)}
        return plan

    def _reflect(self, observation: dict, action: dict, result: dict) -> dict:
        """Analyze failure and determine next steps."""
        prompt = f"""The following action failed:
Action: {json.dumps(action)}
Result: {json.dumps(result)}
Current observation: {json.dumps(observation)}

Analyze the failure and suggest what to do next. Output JSON:
{{"analysis": "...", "suggestion": "...", "should_retry": true/false}}"""

        try:
            response = self.llm.chat([
                {"role": "system", "content": "You are a failure analysis system for a Minecraft agent. Be concise."},
                {"role": "user", "content": prompt},
            ], response_format={"type": "json_object"})
            return json.loads(response)
        except Exception as e:
            logger.error(f"Reflection failed: {e}")
            return {"analysis": "Reflection failed", "suggestion": "retry", "should_retry": True}

    def _system_prompt(self) -> str:
        return """You are a Minecraft agent planner. Given the current game state observation, decide the next actions to achieve the goal.

Available actions: move_to, look_at, dig, place, craft, attack, equip, use_item, chat, wait

Output JSON format:
{
  "status": "in_progress" or "complete" or "blocked",
  "reasoning": "brief explanation",
  "actions": [
    {"type": "action_name", "parameters": {...}}
  ]
}

Be practical. Prefer simple, safe actions. Check inventory before crafting."""

    def _build_planning_prompt(self, observation: dict) -> str:
        goal = self.current_goal or "no goal set"
        return f"""Current goal: {goal}

Current observation:
{json.dumps(observation, indent=2)}

What actions should I take next? Output JSON."""
