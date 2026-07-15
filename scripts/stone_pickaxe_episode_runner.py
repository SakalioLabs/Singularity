#!/usr/bin/env python3
"""Evidence-producing runner for survival fixture preparation and one SP-001 run."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL, PROTOCOL_SHA256
from singularity.evaluation.stone_pickaxe_runtime import (
    FIXTURE_GOAL,
    RUNTIME_POLICY_ID,
    SP001_GOAL,
    StonePickaxeRuntimeAgent,
    audit_sp001_fixture,
    build_fixture_artifact,
    build_runtime_config,
    build_sp001_episode,
    build_sp001_run_audit,
    file_sha256,
    planner_request_controls_audit,
    read_json,
    repo_relative,
    runtime_controls,
    snapshot_tree_report,
    task_graph_snapshot,
    utc_now,
    verify_fixture_manifest,
    verify_sp001_runtime_episode,
    write_json,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-fixture")
    _add_connection_args(prepare)
    prepare.add_argument("--episode-id", required=True)
    prepare.add_argument("--level-name", required=True)
    prepare.add_argument("--output-dir", required=True)
    prepare.add_argument("--max-duration", type=float, default=300.0)
    prepare.add_argument("--max-cycles", type=int, default=40)
    prepare.add_argument("--max-actions", type=int, default=40)

    seal = subparsers.add_parser("seal-fixture")
    seal.add_argument("--snapshot-root", required=True)
    seal.add_argument("--preparation", required=True)
    seal.add_argument("--output", required=True)

    audit = subparsers.add_parser("audit-fixture")
    audit.add_argument("--fixture", required=True)
    audit.add_argument("--snapshot-root", required=True)
    audit.add_argument("--output", default="")

    restoration = subparsers.add_parser("audit-restoration")
    restoration.add_argument("--fixture", required=True)
    restoration.add_argument("--server-root", required=True)
    restoration.add_argument("--level-name", required=True)
    restoration.add_argument("--output", required=True)

    hypothesis = subparsers.add_parser("write-hypothesis")
    hypothesis.add_argument("--fixture", required=True)
    hypothesis.add_argument("--snapshot-root", required=True)
    hypothesis.add_argument("--episode-id", required=True)
    hypothesis.add_argument("--git-head", required=True)
    hypothesis.add_argument("--output", required=True)

    run = subparsers.add_parser("run-sp001")
    _add_connection_args(run)
    run.add_argument("--episode-id", required=True)
    run.add_argument("--level-name", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--fixture", required=True)
    run.add_argument("--hypothesis", required=True)
    run.add_argument("--restoration", required=True)
    run.add_argument("--server-jar-sha256", required=True)
    return parser.parse_args()


def _add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--username", default="Singularity")
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=30000)


def configured_api_key() -> str:
    return str(
        os.environ.get("SINGULARITY_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def run_prepare_fixture(args: argparse.Namespace) -> int:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError("fixture preparation requires an LLM credential")
    output_dir = (REPOSITORY_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    config = build_runtime_config(
        api_key=api_key,
        log_dir=repo_relative(output_dir),
        host=args.host,
        port=args.port,
        username=args.username,
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
    )
    agent = StonePickaxeRuntimeAgent(config, "prepare_fixture")
    connected = False
    initial = {}
    terminal = {}
    result = {}
    audit = {}
    planner_request_audit = {}
    admin_commands = []
    events = []
    initial_monotonic = time.monotonic()
    terminal_monotonic = initial_monotonic
    try:
        connected = agent.connect()
        if not connected:
            raise RuntimeError("fixture preparation Agent could not connect")
        protocol_status = agent.bot.benchmark_protocol("m4-fixed-v1")
        initial = agent._observe()
        initial_monotonic = time.monotonic()
        deadline = initial_monotonic + float(args.max_duration)
        result = agent.run_goal(
            FIXTURE_GOAL,
            max_cycles=int(args.max_cycles),
            max_duration_s=float(args.max_duration),
            episode_deadline_monotonic=deadline,
            per_action_timeout_s=float(PROTOCOL["deadline_policy"]["per_action_timeout_s"]),
            max_actions=int(args.max_actions),
            deadline_policy_id="stone-pickaxe-fixture-preparation-deadline-v1",
        )
        terminal = agent._observe()
        terminal_monotonic = time.monotonic()
        audit = audit_sp001_fixture(terminal)
        events = list(agent.session_logger.events)
        planner_request_audit = planner_request_controls_audit(events)
        audit = dict(audit)
        audit["checks"] = {
            **dict(audit.get("checks", {})),
            "planner_request_controls": planner_request_audit["passed"],
        }
        audit["passed"] = bool(audit.get("passed") and planner_request_audit["passed"])
        if not planner_request_audit["passed"]:
            audit["issues"] = sorted(set(
                list(audit.get("issues", [])) + ["planner_request_controls"]
            ))
        if audit["passed"]:
            save_result = agent.bot.chat("/save-all flush")
            admin_commands.append({
                "command": "save-all flush",
                "purpose": "persist survival-prepared world before offline snapshot sealing",
                "success": save_result.get("success") is True,
            })
            if save_result.get("success") is not True:
                audit = dict(audit)
                audit["passed"] = False
                audit["issues"] = sorted(set(audit.get("issues", []) + ["save_all_flush_failed"]))
        session_id = str(agent.session_logger.session_id)
        graph = task_graph_snapshot(agent)
        health = agent.bot.health()
    finally:
        if connected:
            agent.disconnect()

    session_path = write_json(output_dir / "session.json", events)
    preparation_path = output_dir / "preparation.json"
    forbidden = _forbidden_interventions(events)
    preparation = {
        "type": "stone_pickaxe_fixture_preparation",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "policy_id": "stone-pickaxe-survival-fixture-preparation-v1",
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "episode_id": args.episode_id,
        "session_id": session_id,
        "session_sha256": file_sha256(session_path),
        "level_name": args.level_name,
        "goal": FIXTURE_GOAL,
        "goal_result": result,
        "initial_observation": initial,
        "terminal_observation": terminal,
        "initial_monotonic": initial_monotonic,
        "terminal_monotonic": terminal_monotonic,
        "fixture_audit": audit,
        "planner_request_controls": planner_request_audit,
        "task_graph": graph,
        "runtime_controls": runtime_controls(config),
        "protocol_status": protocol_status,
        "bridge_health": health,
        "game_mode": str(terminal.get("game_mode") or ""),
        "external_step_script": False,
        "target_result_injection": False,
        "active_benchmark_reset": False,
        "forbidden_interventions": forbidden,
        "administrative_commands": admin_commands,
        "evidence_path": repo_relative(preparation_path),
        "session_path": repo_relative(session_path),
        "counts_toward_skill_gate": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }
    write_json(preparation_path, preparation)
    print(json.dumps({
        "preparation": repo_relative(preparation_path),
        "fixture_audit_passed": audit.get("passed") is True,
        "issues": audit.get("issues", []),
    }, indent=2))
    return 0 if audit.get("passed") is True and not forbidden else 2


def run_seal_fixture(args: argparse.Namespace) -> int:
    snapshot_root = (REPOSITORY_ROOT / args.snapshot_root).resolve()
    preparation_path = (REPOSITORY_ROOT / args.preparation).resolve()
    output_path = (REPOSITORY_ROOT / args.output).resolve()
    report = snapshot_tree_report(snapshot_root)
    artifact = build_fixture_artifact(
        read_json(preparation_path),
        report,
        snapshot_path=repo_relative(snapshot_root),
    )
    write_json(output_path, artifact)
    write_json(snapshot_root / "snapshot_identity.json", artifact)
    print(json.dumps({
        "fixture": repo_relative(output_path),
        "snapshot_identity_verified": artifact["snapshot_identity_verified"],
        "tree_sha256": artifact["snapshot"]["tree_sha256"],
        "issues": artifact["issues"],
    }, indent=2))
    return 0 if artifact["snapshot_identity_verified"] else 2


def run_audit_fixture(args: argparse.Namespace) -> int:
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    snapshot_root = (REPOSITORY_ROOT / args.snapshot_root).resolve()
    report = verify_fixture_manifest(read_json(fixture_path), snapshot_root)
    if args.output:
        write_json((REPOSITORY_ROOT / args.output).resolve(), report)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


def run_audit_restoration(args: argparse.Namespace) -> int:
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    server_root = (REPOSITORY_ROOT / args.server_root).resolve()
    fixture = read_json(fixture_path)
    names = {
        "world": args.level_name,
        "world_nether": f"{args.level_name}_nether",
        "world_the_end": f"{args.level_name}_the_end",
    }
    tree = snapshot_tree_report(server_root, names)
    snapshot = fixture.get("snapshot", {}) if isinstance(fixture, dict) else {}
    checks = {
        "fixture_protocol": fixture.get("protocol_sha256") == PROTOCOL_SHA256,
        "fixture_identity": fixture.get("snapshot_identity_verified") is True,
        "restored_tree": tree.get("passed") is True,
        "tree_sha256": tree.get("tree_sha256") == snapshot.get("tree_sha256"),
        "file_count": tree.get("file_count") == snapshot.get("file_count"),
        "total_bytes": tree.get("total_bytes") == snapshot.get("total_bytes"),
    }
    report = {
        "type": "stone_pickaxe_restoration_preflight",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "episode_id": Path(args.output).parent.name,
        "level_name": args.level_name,
        "protocol_sha256": PROTOCOL_SHA256,
        "fixture_path": repo_relative(fixture_path),
        "passed": all(checks.values()),
        "checks": checks,
        "issues": sorted(key for key, passed in checks.items() if not passed),
        "tree": tree,
        "active_episode_reset": False,
        "target_result_injection": False,
    }
    write_json((REPOSITORY_ROOT / args.output).resolve(), report)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


def run_write_hypothesis(args: argparse.Namespace) -> int:
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    snapshot_root = (REPOSITORY_ROOT / args.snapshot_root).resolve()
    fixture = read_json(fixture_path)
    preflight = verify_fixture_manifest(fixture, snapshot_root)
    if not preflight["passed"]:
        raise RuntimeError(f"fixture preflight failed: {preflight['issues']}")
    output_path = (REPOSITORY_ROOT / args.output).resolve()
    hypothesis = {
        "type": "stone_pickaxe_live_hypothesis",
        "schema_version": 1,
        "created_at_utc": utc_now(),
        "created_before_live_process_start": True,
        "episode_id": args.episode_id,
        "task_id": "SP-001",
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "git_head_before_episode": args.git_head,
        "fixture_path": repo_relative(fixture_path),
        "fixture_tree_sha256": fixture["snapshot"]["tree_sha256"],
        "hypothesis": (
            "From the verified immutable survival snapshot, the skills-off LLM Planner "
            "will choose distinct nearest observed stone digs, the guarded Mineflayer "
            "backend will equip the one wooden pickaxe and prove each pickup, and terminal "
            "inventory will gain at least three cobblestone within eight total actions and "
            "the single 180-second deadline."
        ),
        "falsifiers": [
            "initial fixture machine audit fails",
            "Planner selects a non-nearest or non-stone mutation",
            "any action fails or crosses an action/episode deadline",
            "fewer than three distinct stone removals have pickup provenance",
            "terminal cobblestone delta is below three",
            "any learned or quarantined skill is selected",
        ],
        "authorization": {
            "single_episode": True,
            "automatic_retry_allowed": False,
            "consumed_by_episode_start": True,
        },
    }
    write_json(output_path, hypothesis)
    print(json.dumps({"hypothesis": repo_relative(output_path), "episode_id": args.episode_id}, indent=2))
    return 0


def run_sp001(args: argparse.Namespace) -> int:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError("SP-001 requires an LLM credential")
    output_dir = (REPOSITORY_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    hypothesis_path = (REPOSITORY_ROOT / args.hypothesis).resolve()
    restoration_path = (REPOSITORY_ROOT / args.restoration).resolve()
    fixture = read_json(fixture_path)
    hypothesis = read_json(hypothesis_path)
    restoration = read_json(restoration_path)
    static_checks = {
        "protocol_hash": fixture.get("protocol_sha256") == PROTOCOL_SHA256,
        "fixture_identity": fixture.get("snapshot_identity_verified") is True,
        "hypothesis_episode": hypothesis.get("episode_id") == args.episode_id,
        "hypothesis_precedes_live": hypothesis.get("created_before_live_process_start") is True,
        "hypothesis_protocol": hypothesis.get("protocol_sha256") == PROTOCOL_SHA256,
        "restoration_passed": restoration.get("passed") is True,
        "restoration_level": restoration.get("level_name") == args.level_name,
        "server_jar": args.server_jar_sha256.lower() == PROTOCOL["environment"]["server_jar_sha256"],
    }
    if not all(static_checks.values()):
        raise RuntimeError(
            "SP-001 static preflight failed: "
            + ", ".join(key for key, passed in static_checks.items() if not passed)
        )

    config = build_runtime_config(
        api_key=api_key,
        log_dir=repo_relative(output_dir),
        host=args.host,
        port=args.port,
        username=args.username,
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
    )
    agent = StonePickaxeRuntimeAgent(config, "sp001")
    connected = False
    try:
        connected = agent.connect()
        if not connected:
            raise RuntimeError("SP-001 Agent could not connect")
        protocol_status = agent.bot.benchmark_protocol("m4-fixed-v1")
        bridge_health = agent.bot.health()
        initial = agent._observe()
        initial_monotonic = time.monotonic()
        fixture_audit = audit_sp001_fixture(initial)
        preflight = {
            "type": "stone_pickaxe_live_preflight",
            "schema_version": 1,
            "generated_at_utc": utc_now(),
            "episode_id": args.episode_id,
            "task_id": "SP-001",
            "protocol_id": PROTOCOL["id"],
            "protocol_sha256": PROTOCOL_SHA256,
            "static_checks": static_checks,
            "fixture_machine_audit": fixture_audit,
            "protocol_status": protocol_status,
            "bridge_health": bridge_health,
            "runtime_controls": runtime_controls(config),
            "active_episode_reset": False,
            "external_step_script": False,
            "passed": all(static_checks.values()) and fixture_audit["passed"],
        }
        write_json(output_dir / "preflight.json", preflight)
        if not preflight["passed"]:
            raise RuntimeError(f"SP-001 machine preflight failed: {fixture_audit['issues']}")
        deadline = initial_monotonic + float(PROTOCOL["tasks"][0]["episode_timeout_s"])
        result = agent.run_goal(
            SP001_GOAL,
            max_cycles=int(PROTOCOL["tasks"][0]["maximum_cycles"]),
            max_duration_s=float(PROTOCOL["tasks"][0]["episode_timeout_s"]),
            episode_deadline_monotonic=deadline,
            per_action_timeout_s=float(PROTOCOL["deadline_policy"]["per_action_timeout_s"]),
            max_actions=int(PROTOCOL["tasks"][0]["maximum_actions"]),
            deadline_policy_id=PROTOCOL["deadline_policy"]["id"],
        )
        terminal = agent._observe()
        terminal_monotonic = time.monotonic()
        events = list(agent.session_logger.events)
        session_id = str(agent.session_logger.session_id)
        graph = task_graph_snapshot(agent)
    finally:
        if connected:
            agent.disconnect()

    session_path = write_json(output_dir / "session.json", events)
    session_sha256 = file_sha256(session_path)
    episode = build_sp001_episode(
        episode_id=args.episode_id,
        session_id=session_id,
        session_sha256=session_sha256,
        events=events,
        initial_observation=initial,
        terminal_observation=terminal,
        initial_monotonic=initial_monotonic,
        terminal_monotonic=terminal_monotonic,
        goal_result=result,
        fixture_manifest=fixture,
        hypothesis_path=repo_relative(hypothesis_path),
        level_name=args.level_name,
    )
    episode_path = write_json(output_dir / "episode.json", episode)
    verification = verify_sp001_runtime_episode(episode)
    verification_path = write_json(output_dir / "verification.json", verification)
    audit = build_sp001_run_audit(episode, verification, events, graph)
    audit_path = write_json(output_dir / "audit.json", audit)
    evidence_files = [
        hypothesis_path,
        restoration_path,
        output_dir / "preflight.json",
        session_path,
        episode_path,
        verification_path,
        audit_path,
    ]
    manifest = {
        "type": "stone_pickaxe_live_manifest",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "runtime_policy_id": RUNTIME_POLICY_ID,
        "episode_id": args.episode_id,
        "session_id": session_id,
        "task_id": "SP-001",
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "fixture_tree_sha256": fixture["snapshot"]["tree_sha256"],
        "server_jar_sha256": args.server_jar_sha256.lower(),
        "evidence_eligible": verification.get("evidence_eligible") is True,
        "passed": verification.get("passed") is True,
        "automatic_retry_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
        "files": [
            {"path": repo_relative(path), "sha256": file_sha256(path)}
            for path in evidence_files
        ],
    }
    manifest_path = write_json(output_dir / "manifest.json", manifest)
    print(json.dumps({
        "episode_id": args.episode_id,
        "session_id": session_id,
        "passed": verification.get("passed") is True,
        "evidence_eligible": verification.get("evidence_eligible") is True,
        "criteria_issues": verification.get("criteria_issues", []),
        "eligibility_issues": verification.get("eligibility_issues", []),
        "audit": repo_relative(audit_path),
        "manifest": repo_relative(manifest_path),
    }, indent=2))
    return 0


def _forbidden_interventions(events: list[dict]) -> list[dict]:
    forbidden = []
    tokens = {"give", "teleport", "tp", "gamemode", "setblock"}
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("type") != "action":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        action = data.get("action") if isinstance(data.get("action"), dict) else {}
        params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        if action.get("type") != "chat":
            continue
        command = str(params.get("message") or "").strip().lower().lstrip("/")
        token = command.split(" ", 1)[0]
        if token in tokens:
            forbidden.append({"event_index": index, "command": token})
    return forbidden


def main() -> int:
    args = parse_args()
    if args.command == "prepare-fixture":
        return run_prepare_fixture(args)
    if args.command == "seal-fixture":
        return run_seal_fixture(args)
    if args.command == "audit-fixture":
        return run_audit_fixture(args)
    if args.command == "audit-restoration":
        return run_audit_restoration(args)
    if args.command == "write-hypothesis":
        return run_write_hypothesis(args)
    if args.command == "run-sp001":
        return run_sp001(args)
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc), "automatic_retry_allowed": False}, indent=2), file=sys.stderr)
        raise
