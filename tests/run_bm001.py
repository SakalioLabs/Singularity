"""Run BM-001: Chop 3 oak logs - live benchmark test."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from singularity.core.config import Config, BotConfig, LLMConfig
from singularity.core.agent import Agent

config = Config(bot=BotConfig(host='localhost', port=25565, username='Singularity'))
agent = Agent(config)

if not agent.connect():
    print("FAIL: Connection failed")
    sys.exit(1)

print("BM-001: Chop 3 oak logs")
print("=" * 40)

start = time.time()
result = agent.run_goal("Gather 3 oak logs")
elapsed = time.time() - start

# Check inventory
inv_items = agent.bot.get_inventory()
inv = {}
for item in inv_items:
    name = item.get("name", "unknown")
    inv[name] = inv.get(name, 0) + item.get("count", 1)

oak_logs = inv.get("oak_log", 0)
passed = oak_logs >= 3

print(f"Cycles: {result.get('cycles')}")
print(f"Duration: {elapsed:.1f}s")
print(f"Inventory: {json.dumps(inv)}")
print(f"Oak logs: {oak_logs}")
print(f"Status: {'PASS' if passed else 'FAIL'}")
print(f"Completed flag: {result.get('completed')}")

agent.disconnect()
