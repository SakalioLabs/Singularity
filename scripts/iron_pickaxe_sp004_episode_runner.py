"""Run one immutable SP-004 continuation episode from a stone pickaxe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from singularity.core.config import BotConfig, Config, LLMConfig
from singularity.evaluation.iron_pickaxe_sp004_runtime import (
    SP004_GOAL,
    SP004_RUNTIME_POLICY_ID,
    IronPickaxeSP004RuntimeAgent,
    build_sp004_runtime_config,
    progress_snapshot,
    verify_sp004_runtime_episode,
)


DEFAULT_BASE_URL = "http://192.168.3.27:8317/v1"
DEFAULT_MODEL = "grok-4.5"
SP004_RUN_ROOT = REPOSITORY_ROOT / "workspace/evals/sp004_runs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SP-004 stone-to-iron runtime")
    parser.add_argument("run", choices=("run",))
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--username", default="Singularity")
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=30000)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SINGULARITY_LLM_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("SINGULARITY_LLM_MODEL", DEFAULT_MODEL),
    )
    parser.add_argument("--max-cycles", type=int, default=80)
    parser.add_argument("--max-actions", type=int, default=80)
    parser.add_argument("--max-duration-s", type=float, default=900.0)
    return parser.parse_args()


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    resolved = value.resolve() if value.is_absolute() else (REPOSITORY_ROOT / value).resolve()
    try:
        resolved.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise RuntimeError(f"path must stay inside repository: {path}") from exc
    return resolved


def repo_relative(path: str | Path) -> str:
    return repo_path(path).relative_to(REPOSITORY_ROOT).as_posix()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(repo_path(path).read_bytes()).hexdigest()


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, payload) -> Path:
    target = repo_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError(f"refusing to overwrite SP-004 evidence: {target}")
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n",
        encoding="utf-8",
    )
    return target


def configured_api_key() -> str:
    return str(
        os.environ.get("SINGULARITY_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def normalize_base_url(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("SP-004 requires a non-empty OpenAI-compatible base URL")
    return base if base.endswith("/v1") else f"{base}/v1"


def audit_initial_state(observation) -> dict:
    value = observation if isinstance(observation, dict) else {}
    inventory = value.get("inventory")
    inventory = inventory if isinstance(inventory, dict) else {}

    def count(item):
        raw = inventory.get(item, 0)
        return int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0

    checks = {
        "stone_pickaxe_exact": count("stone_pickaxe") == 1,
        "iron_pickaxe_absent": count("iron_pickaxe") == 0,
        "episode_resources_absent": all(
            count(item) == 0
            for item in ("cobblestone", "coal", "raw_iron", "iron_ingot", "furnace")
        ),
        "player_position_observed": all(
            isinstance((value.get("position") or {}).get(axis), (int, float))
            for axis in ("x", "y", "z")
        ),
        "machine_block_observation_present": isinstance(value.get("nearby_blocks"), list),
    }
    return {
        "type": "iron_pickaxe_sp004_initial_state_audit",
        "schema_version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "issues": sorted(name for name, passed in checks.items() if not passed),
        "inventory": dict(inventory),
        "held_item": str(value.get("held_item") or ""),
        "position": dict(value.get("position") or {}),
    }


def build_episode(*, episode_id, initial, terminal, events, result, progress) -> dict:
    action_rows = []
    observations = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        data = event.get("data")
        data = data if isinstance(data, dict) else {}
        if event.get("type") == "action":
            action_rows.append(
                {
                    "event_id": event.get("id"),
                    "action": data.get("action"),
                    "result": data.get("result"),
                }
            )
        elif event.get("type") == "observation":
            observations.append(data)
    return {
        "type": "iron_pickaxe_sp004_runtime_episode",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "episode_id": str(episode_id),
        "goal": SP004_GOAL,
        "runtime_policy_id": SP004_RUNTIME_POLICY_ID,
        "initial_observation": initial,
        "observations": observations,
        "actions": action_rows,
        "terminal_observation": terminal,
        "progress": progress_snapshot(progress),
        "goal_result": result if isinstance(result, dict) else {},
        "single_episode": True,
        "automatic_retry_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def build_config(args: argparse.Namespace, api_key: str, output_dir: Path) -> Config:
    base = Config(
        bot=BotConfig(
            host=args.host,
            port=int(args.port),
            username=args.username,
            version="1.20.4",
            auth="offline",
            bridge_host=args.bridge_host,
            bridge_port=int(args.bridge_port),
        ),
        llm=LLMConfig(
            provider="openai",
            model=str(args.model),
            api_key=api_key,
            base_url=normalize_base_url(args.base_url),
            max_tokens=4096,
            temperature=0.0,
        ),
        log_dir=repo_relative(output_dir),
        enable_vision_analysis=False,
        enable_visual_action_grounding=False,
        enable_screenshot_capture=False,
        enable_goal_critic=False,
        enable_action_candidate_selection=False,
        enable_blocked_plan_rule_fallback=False,
    )
    return build_sp004_runtime_config(base_config=base)


def run_episode(args: argparse.Namespace) -> int:
    if not args.run_once:
        raise RuntimeError("SP-004 requires explicit --run-once authorization")
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError("SP-004 requires SINGULARITY_LLM_API_KEY or OPENAI_API_KEY")
    if not args.episode_id.replace("_", "").replace("-", "").isalnum():
        raise RuntimeError("episode-id must contain only letters, digits, '_' or '-'")

    output_dir = repo_path(args.output_dir)
    expected = (SP004_RUN_ROOT / args.episode_id).resolve()
    if output_dir != expected:
        raise RuntimeError("SP-004 evidence must use workspace/evals/sp004_runs/<episode-id>")
    if output_dir.exists():
        raise RuntimeError(f"refusing reused SP-004 evidence directory: {output_dir}")
    output_dir.mkdir(parents=True)

    config = build_config(args, api_key, output_dir)
    agent = IronPickaxeSP004RuntimeAgent(config)
    connected = False
    try:
        connected = agent.connect()
        if not connected:
            raise RuntimeError("SP-004 Agent could not connect")
        health = agent.bot.health()
        initial = agent._observe()
        initial_audit = audit_initial_state(initial)
        smelt_policy = health.get("smelt_policy")
        smelt_policy = smelt_policy if isinstance(smelt_policy, dict) else {}
        preflight = {
            "type": "iron_pickaxe_sp004_live_preflight",
            "schema_version": 1,
            "generated_at_utc": utc_now(),
            "episode_id": args.episode_id,
            "runtime_policy_id": SP004_RUNTIME_POLICY_ID,
            "initial_state_audit": initial_audit,
            "bridge_health": health,
            "llm": {
                "provider": "openai",
                "base_url": config.llm.base_url,
                "model": config.llm.model,
                "temperature": config.llm.temperature,
                "api_key_present": bool(api_key),
                "api_key_recorded": False,
            },
            "smelt_policy": smelt_policy,
            "single_episode": True,
            "automatic_retry_allowed": False,
            "passed": bool(
                initial_audit["passed"]
                and health.get("bot_ready") is True
                and smelt_policy.get("max_attempts") == 1
                and smelt_policy.get("automatic_retry") is False
                and "iron_ingot" in smelt_policy.get("supported_outputs", [])
            ),
        }
        write_json(output_dir / "preflight.json", preflight)
        if not preflight["passed"]:
            raise RuntimeError(
                f"SP-004 preflight failed: {initial_audit['issues']}"
            )

        started = time.monotonic()
        result = agent.run_goal(
            SP004_GOAL,
            max_cycles=int(args.max_cycles),
            max_duration_s=float(args.max_duration_s),
            episode_deadline_monotonic=started + float(args.max_duration_s),
            per_action_timeout_s=120.0,
            max_actions=int(args.max_actions),
            deadline_policy_id="sp004-single-episode-deadline-v1",
        )
        time.sleep(0.25)
        terminal = agent._observe()
        events = list(agent.session_logger.events)
        session_id = str(agent.session_logger.session_id)
        progress = progress_snapshot(agent.sp004_progress)
    finally:
        if connected:
            agent.disconnect()

    session_path = write_json(output_dir / "session.json", events)
    episode = build_episode(
        episode_id=args.episode_id,
        initial=initial,
        terminal=terminal,
        events=events,
        result=result,
        progress=progress,
    )
    episode["session_id"] = session_id
    episode["session_sha256"] = file_sha256(session_path)
    episode_path = write_json(output_dir / "episode.json", episode)
    verification = verify_sp004_runtime_episode(episode)
    verification_path = write_json(output_dir / "verification.json", verification)
    evidence_files = [
        output_dir / "preflight.json",
        session_path,
        episode_path,
        verification_path,
    ]
    manifest = {
        "type": "iron_pickaxe_sp004_live_manifest",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "episode_id": args.episode_id,
        "session_id": session_id,
        "runtime_policy_id": SP004_RUNTIME_POLICY_ID,
        "passed": verification.get("passed") is True,
        "single_episode": True,
        "automatic_retry_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
        "files": [
            {"path": repo_relative(path), "sha256": file_sha256(path)}
            for path in evidence_files
        ],
    }
    manifest_path = write_json(output_dir / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "episode_id": args.episode_id,
                "session_id": session_id,
                "passed": manifest["passed"],
                "criteria_issues": verification.get("criteria_issues", []),
                "manifest": repo_relative(manifest_path),
            },
            indent=2,
        )
    )
    return 0 if manifest["passed"] else 1


def main() -> int:
    args = parse_args()
    return run_episode(args)


if __name__ == "__main__":
    raise SystemExit(main())
