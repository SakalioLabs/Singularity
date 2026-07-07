import sys, os, json, time, subprocess, pathlib

ROOT = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity")
os.chdir(ROOT)

# Kill old processes
for proc in ["java", "node"]:
    subprocess.run(f"taskkill /f /im {proc}.exe 2>nul", shell=True)
time.sleep(3)

# Start MC server
subprocess.Popen(
    [r"jdk-17\jdk-17.0.19+10\bin\java.exe", "-Xmx2G", "-Xms1G", "-jar", "server.jar", "nogui"],
    cwd=ROOT / "mc-server",
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
print("MC Server starting...")

# Wait for server ready
while True:
    try:
        log = (ROOT / "mc-server" / "logs" / "latest.log").read_text(encoding="utf-8", errors="ignore")
        if "Done" in log:
            break
    except: pass
    time.sleep(2)
print("MC Server ready!")

# Start bridge with logging
bridge_log = ROOT / "bridge_out.log"
bridge_log.write_text("")
bridge = subprocess.Popen(
    ["node", "src/bot/bot_server.js"],
    cwd=ROOT,
    stdout=open(bridge_log, "w"), stderr=open(ROOT / "bridge_err.log", "w")
)
print(f"Bridge started (PID {bridge.pid}), waiting for connection...")

# Wait for bot to spawn
for i in range(60):
    time.sleep(1)
    log = bridge_log.read_text(encoding="utf-8", errors="ignore") if bridge_log.exists() else ""
    if "Spawned" in log:
        print(f"Bot spawned! ({log[:100]})")
        break
    if i == 59:
        print("Bridge failed to connect (timeout)")
        print(f"Bridge log: {log}")

# Run BM-001
sys.path.insert(0, str(ROOT / "src"))
from singularity.core.config import Config, BotConfig
from singularity.core.agent import Agent

config = Config(bot=BotConfig(host="localhost", port=25565, username="Singularity"))
agent = Agent(config)
if not agent.connect():
    print("Agent connection failed!")
    sys.exit(1)

import time as t
start = t.time()
result = agent.run_goal("Gather 3 oak logs")
elapsed = t.time() - start

inv = agent.bot.get_inventory()
inv_summary = {}
for item in inv:
    name = item.get("name", "unknown")
    inv_summary[name] = inv_summary.get(name, 0) + item.get("count", 1)

oak_logs = inv_summary.get("oak_log", 0)
print(f"\nBM-001: {'PASS' if oak_logs >= 3 else 'FAIL'}")
print(f"  Cycles: {result.get('cycles')}")
print(f"  Duration: {elapsed:.1f}s")
print(f"  Oak logs: {oak_logs}")
print(f"  Inventory: {json.dumps(inv_summary)}")
agent.disconnect()
