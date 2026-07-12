"""Run one M4 autonomous episode against an already-started Paper/bridge runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from singularity.bot.bridge import BotBridge
from singularity.core.agent import Agent
from singularity.core.config import BotConfig, Config, LLMConfig
from singularity.evaluation.m4_protocol import PROTOCOL, evaluate_m4_episode
from singularity.evaluation.m4_runtime import (
    attach_m4_evidence_hashes,
    build_m4_episode_progress_report,
    build_m4_preflight,
    build_m4_runtime_manifest,
    runtime_controls_from_config,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Run exactly one m4-fixed-v1 episode")
    parser.add_argument("--task-id", default="BM-011", choices=["BM-011", "BM-012"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--username", default="Singularity")
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=30000)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--level-name", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-duration", type=float)
    parser.add_argument("--max-goals", type=int, default=int(PROTOCOL["limits"]["max_autonomous_goals"]))
    parser.add_argument("--max-cycles", type=int, default=int(PROTOCOL["limits"]["max_cycles_per_goal"]))
    parser.add_argument("--fresh-level", action="store_true")
    args = parser.parse_args()
    task = next(task for task in PROTOCOL["tasks"] if task["id"] == args.task_id)
    if args.max_duration is None:
        args.max_duration = float(task["max_duration_s"])
    return args


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite evidence: {path}")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"evidence path must stay inside repository: {path}") from exc


def setup_preflight(args, output_dir: Path):
    bridge = BotBridge(BotConfig(
        host=args.host,
        port=args.port,
        username=args.username,
        version=PROTOCOL["minecraft_version"],
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
    ))
    if not bridge.connect():
        raise RuntimeError("could not connect to the M4 bot bridge for preflight")
    try:
        status = bridge.benchmark_protocol(PROTOCOL["profile"])
        reset = bridge.reset_benchmark(args.task_id)
    finally:
        bridge.disconnect()
    preflight = build_m4_preflight(
        status,
        reset,
        args.episode_id,
        args.level_name,
        fresh_episode=args.fresh_level,
        task_id=args.task_id,
    )
    write_json(output_dir / "protocol_status.json", status)
    write_json(output_dir / "reset.json", reset)
    write_json(output_dir / "preflight.json", preflight)
    if not preflight.get("passed"):
        raise RuntimeError(f"M4 preflight failed: {preflight.get('validation', {}).get('issues', [])}")
    return preflight


def run_episode(args, output_dir: Path, preflight: dict):
    api_key = os.environ.get("SINGULARITY_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("M4 runtime requires SINGULARITY_LLM_API_KEY or OPENAI_API_KEY")
    llm = PROTOCOL["llm"]
    config = Config(
        bot=BotConfig(
            host=args.host,
            port=args.port,
            username=args.username,
            version=PROTOCOL["minecraft_version"],
            bridge_host=args.bridge_host,
            bridge_port=args.bridge_port,
        ),
        llm=LLMConfig(
            provider=llm["provider"],
            model=llm["model"],
            api_key=api_key,
            base_url=llm["base_url"],
            max_tokens=int(llm["max_tokens"]),
            temperature=float(llm["temperature"]),
        ),
        log_dir=repo_relative(output_dir),
        planner_protocol=PROTOCOL["profile"],
        require_llm_root_plan=True,
        skill_execution_mode="off",
        enable_skill_candidate_extraction=False,
        enable_policy_skills=False,
        enable_skill_frontier_routing=False,
        enable_memory_policy=False,
        enable_memory_persistence=False,
        enable_planning_memory_context=False,
        enable_task_memory_context=False,
        enable_task_continuity_context=False,
        enable_bounded_planning_context=False,
        enable_skill_memory_context=False,
        enable_knowledge_correction_context=False,
        enable_task_precondition_context=False,
        enable_weighted_memory_retrieval=False,
        enable_coaching_policy=False,
        enable_vision_analysis=False,
        enable_visual_action_grounding=False,
        enable_screenshot_capture=False,
        enable_goal_critic=False,
        enable_self_evolution_policy=False,
        enable_world_model_curriculum_feedback=False,
        enable_action_candidate_selection=False,
        enable_blocked_plan_rule_fallback=False,
        enable_plan_cache=False,
        episode_abort_mode="off",
        frontier_budget_mode="off",
        enable_autocurriculum=True,
        enable_goal_verification=True,
        enable_action_verification=True,
        enforce_action_verification=True,
        max_action_timeout=int(float(PROTOCOL["deadline_policy"]["action_timeout_s"]) * 1000),
    )
    runtime_controls = runtime_controls_from_config(config)
    if runtime_controls != PROTOCOL["baseline_runtime_controls"]:
        raise RuntimeError(f"M4 baseline runtime controls drifted: {runtime_controls}")
    agent = Agent(config)
    if not agent.connect():
        raise RuntimeError("agent could not connect to the M4 bot bridge")
    terminal_observation = {}
    try:
        autonomous = agent.run_autonomous(
            max_goals=args.max_goals,
            max_cycles_per_goal=args.max_cycles,
            max_duration_s=args.max_duration,
            task_id=args.task_id,
        )
        try:
            terminal_observation = agent._observe()
        except Exception as exc:
            terminal_observation = {"observation_error": str(exc)}
        events = list(agent.session_logger.events)
        session_id = str(agent.session_logger.session_id)
        bot_connected = bool(getattr(agent.bot, "_connected", False))
    finally:
        agent.disconnect()

    ended_monotonic = time.monotonic()
    evidence_paths = {
        "preflight": repo_relative(output_dir / "preflight.json"),
        "protocol_status": repo_relative(output_dir / "protocol_status.json"),
        "reset": repo_relative(output_dir / "reset.json"),
        "manifest": repo_relative(output_dir / "manifest.json"),
        "session": repo_relative(output_dir / "session.json"),
        "result": repo_relative(output_dir / "result.json"),
        "eligibility": repo_relative(output_dir / "eligibility.json"),
        "preparation": repo_relative(output_dir / "preparation.json"),
    }
    manifest = build_m4_runtime_manifest(
        preflight,
        session_id,
        autonomous["episode_started_monotonic"],
        autonomous["episode_deadline_monotonic"],
        ended_monotonic,
        evidence_paths=evidence_paths,
        runtime_controls=runtime_controls,
        runtime_limits={
            "max_duration_s": float(args.max_duration),
            "max_goals": int(args.max_goals),
            "max_cycles_per_goal": int(args.max_cycles),
        },
    )
    terminal_state = {
        "health": terminal_observation.get("health", 0),
        "food": terminal_observation.get("hunger"),
        "time_of_day": terminal_observation.get("time_of_day"),
        "position": terminal_observation.get("position", {}),
        "inventory": terminal_observation.get("inventory", {}),
        "nearby_blocks": terminal_observation.get("nearby_blocks", []),
        "nearby_entities": terminal_observation.get("nearby_entities", []),
        "player_lifecycle": terminal_observation.get("player_lifecycle", {}),
        "bot_connected": bot_connected,
    }
    expected_termination = (
        "terminal_survival_verified" if args.task_id == "BM-011" else "terminal_task_verified"
    )
    result = {
        "type": "m4_episode_result",
        "schema_version": 1,
        "task_id": args.task_id,
        "profile": PROTOCOL["profile"],
        "completed": autonomous.get("termination_reason") == expected_termination,
        "termination_reason": str(autonomous.get("termination_reason") or "preparation_probe_complete"),
        "elapsed_s": autonomous.get("elapsed_s"),
        "deadline_eligible": bool(autonomous.get("deadline_eligible")),
        "external_step_script": False,
        "terminal_state": terminal_state,
        "autonomous_result": autonomous,
    }
    result = attach_m4_evidence_hashes(result, preflight, manifest, events)
    eligibility = evaluate_m4_episode(events, result, preflight, manifest, args.task_id)
    preparation = build_m4_episode_progress_report(events, result, preflight, manifest, eligibility)

    write_json(output_dir / "manifest.json", manifest)
    write_json(output_dir / "session.json", events)
    write_json(output_dir / "result.json", result)
    write_json(output_dir / "eligibility.json", eligibility)
    write_json(output_dir / "preparation.json", preparation)
    return {
        "episode_id": args.episode_id,
        "session_id": session_id,
        "level_name": args.level_name,
        "preflight_passed": preflight.get("passed") is True,
        "progress_gate_passed": bool(
            preparation.get("g2_passed") is True
            or preparation.get("progress_gate_passed") is True
        ),
        "task_id": args.task_id,
        "task_eligible": eligibility.get("eligible") is True,
        "first_unrecovered_transition": preparation.get("first_unrecovered_transition", {}),
        "evidence_dir": repo_relative(output_dir),
    }


def main():
    args = parse_args()
    task = next(task for task in PROTOCOL["tasks"] if task["id"] == args.task_id)
    expected = {
        "max_duration": float(task["max_duration_s"]),
        "max_goals": int(PROTOCOL["limits"]["max_autonomous_goals"]),
        "max_cycles": int(PROTOCOL["limits"]["max_cycles_per_goal"]),
    }
    actual = {
        "max_duration": float(args.max_duration),
        "max_goals": int(args.max_goals),
        "max_cycles": int(args.max_cycles),
    }
    if actual != expected:
        raise ValueError(f"{args.task_id} requires exact fixed runtime limits: {expected}")
    output_dir = (REPO_ROOT / args.output_dir).resolve()
    repo_relative(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    preflight = setup_preflight(args, output_dir)
    summary = run_episode(args, output_dir, preflight)
    print(json.dumps(summary, sort_keys=True, ensure_ascii=True))


if __name__ == "__main__":
    main()
