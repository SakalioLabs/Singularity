"""M2 Integration Test - tests LLM planning pipeline.
Requires OPENAI_API_KEY env var and bot bridge running on port 3000.
Usage: python tests/test_m2_integration.py"""
import json, socket, sys, os
sys.path.insert(0, "src")

def send_cmd(sock, cmd, params=None):
    sock.sendall(json.dumps({"command": cmd, "params": params or {}}).encode() + b"\n")
    r = b""
    while b"\n" not in r: r += sock.recv(4096)
    return json.loads(r.decode().strip())

def test_m2():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("SKIP M2: No OPENAI_API_KEY set")
        return
    from singularity.core.config import LLMConfig
    from singularity.llm.provider import LLMProvider
    from singularity.core.task_system import TaskSystem
    from singularity.core.planner import Planner
    llm = LLMProvider(LLMConfig(provider="openai", model="gpt-4o-mini", api_key=api_key))
    ts = TaskSystem()
    planner = Planner(llm, ts)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    try:
        s.connect(("127.0.0.1", 3000))
        state = send_cmd(s, "get_player_state")
        inv = send_cmd(s, "get_inventory")
        world = {"position": state.get("position"), "health": state.get("health"),
                 "inventory": {i["name"]: i["count"] for i in inv.get("items", [])}}
    finally:
        s.close()
    plan = planner.plan_from_goal("Gather 3 oak logs", world)
    print(f"Plan: {json.dumps(plan, indent=2, default=str)[:500]}")
    print(f"Tasks created: {len(ts.tasks)}")
    print("M2-TEST-001 PASS" if plan.get("status") in ("planning","in_progress","complete") else "M2-TEST-001 FAIL")

if __name__ == "__main__":
    test_m2()
