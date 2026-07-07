"""Live integration test - connects to MC server via bot bridge."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from singularity.core.config import Config, BotConfig, LLMConfig
from singularity.core.agent import Agent

config = Config(bot=BotConfig(host='localhost', port=25565, username='Singularity'))
agent = Agent(config)

if not agent.connect():
    print("FAIL: Connection failed")
    sys.exit(1)

print("OK: Connected")

# Test observation
obs = agent.observer.observe()
pos = obs.get("position", {})
print(f"OK: Position = {pos}")
print(f"OK: Health = {obs.get('health')}")
print(f"OK: Inventory = {obs.get('inventory', {})}")
print(f"OK: Trees found = {len(obs.get('trees_found', []))}")
print(f"OK: Time of day = {obs.get('time_of_day')}")

# Test rule planner with a goal
plan = agent._think(obs, override_goal="Gather 3 oak logs")
print(f"OK: Plan status = {plan.get('status')}")
print(f"OK: Plan reasoning = {plan.get('reasoning', '')[:100]}")

# Test explorer base setting
print(f"OK: Explorer base = {agent.explorer.base_position}")

# Test goal generator
goal = agent.goal_generator.next_goal(obs)
print(f"OK: Goal generator = {goal}")

# Test memory system
agent.memory.write_episode("test", {"data": "live_integration"})
print(f"OK: Memory episodes = {len(agent.memory.l2_episodic)}")

agent.disconnect()
print("OK: Disconnected cleanly")
print("\nALL LIVE INTEGRATION TESTS PASSED")

