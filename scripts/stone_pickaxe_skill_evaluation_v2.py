#!/usr/bin/env python3
"""Authorize, run, and summarize one isolated SP-001 recovery candidate."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL, PROTOCOL_SHA256
from singularity.evaluation.stone_pickaxe_runtime import (
    RUNTIME_POLICY_ID,
    SP001_GOAL,
    audit_sp001_fixture,
    build_sp001_run_audit,
    file_sha256,
    read_json,
    repo_relative,
    runtime_controls,
    task_graph_snapshot,
    utc_now,
    verify_sp001_runtime_episode,
    write_json,
)
from singularity.evaluation.stone_pickaxe_skill_evaluation_v2 import (
    POLICY,
    POLICY_SHA256,
    StonePickaxeSkillEvaluationAgent,
    build_baseline_index,
    build_evaluation_authorization,
    build_paired_evaluation_report,
    build_skill_evaluation_episode,
    build_skill_evaluation_run,
    build_skill_evaluation_runtime_config,
    discover_evaluation_run_paths,
    policy_identity_report,
    validate_evaluation_authorization,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit-policy")
    audit.add_argument("--output", default="")

    authorize = subparsers.add_parser("write-authorization")
    authorize.add_argument("--arm", required=True, choices=("candidate",))
    authorize.add_argument("--replicate-id", required=True)
    authorize.add_argument("--episode-id", required=True)
    authorize.add_argument("--git-head", required=True)
    authorize.add_argument("--output", required=True)

    run = subparsers.add_parser("run-arm")
    _add_connection_args(run)
    run.add_argument("--arm", required=True, choices=("candidate",))
    run.add_argument("--replicate-id", required=True)
    run.add_argument("--episode-id", required=True)
    run.add_argument("--level-name", required=True)
    run.add_argument("--git-head", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--fixture", required=True)
    run.add_argument("--authorization", required=True)
    run.add_argument("--restoration", required=True)
    run.add_argument("--server-jar-sha256", required=True)

    report = subparsers.add_parser("refresh-report")
    report.add_argument("--runs-root", default="workspace/evals/sp001_skill_evaluation_runs")
    report.add_argument(
        "--baseline-output",
        default="workspace/evals/acquire_cobblestone_baseline_index_v2.json",
    )
    report.add_argument(
        "--report-output",
        default="workspace/evals/acquire_cobblestone_paired_evaluation_v2.json",
    )
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


def run_audit_policy(args: argparse.Namespace) -> int:
    report = policy_identity_report()
    if args.output:
        write_json(_repository_path(args.output), report)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


def run_write_authorization(args: argparse.Namespace) -> int:
    authorization = build_evaluation_authorization(
        arm=args.arm,
        replicate_id=args.replicate_id,
        episode_id=args.episode_id,
        git_head=args.git_head,
    )
    path = write_json(_repository_path(args.output), authorization)
    print(json.dumps({
        "authorization": repo_relative(path),
        "authorization_sha256": file_sha256(path),
        "authorization_id": authorization["authorization_id"],
        "arm": authorization["arm"],
        "replicate_id": authorization["replicate_id"],
        "normal_runtime_permission": False,
        "automatic_retry_allowed": False,
    }, indent=2))
    return 0


def run_arm(args: argparse.Namespace) -> int:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError("SP-001 skill evaluation requires an LLM credential")
    output_dir = _repository_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = _repository_path(args.fixture)
    authorization_path = _repository_path(args.authorization)
    restoration_path = _repository_path(args.restoration)
    fixture = read_json(fixture_path)
    authorization = read_json(authorization_path)
    restoration = read_json(restoration_path)
    authorization_audit = validate_evaluation_authorization(
        authorization,
        expected_arm=args.arm,
        expected_replicate_id=args.replicate_id,
        expected_episode_id=args.episode_id,
        expected_git_head=args.git_head,
    )
    static_checks = {
        "policy_identity": policy_identity_report()["passed"],
        "policy_hash": authorization.get("policy_sha256") == POLICY_SHA256,
        "authorization": authorization_audit["passed"],
        "protocol_hash": fixture.get("protocol_sha256") == PROTOCOL_SHA256,
        "fixture_identity": fixture.get("snapshot_identity_verified") is True,
        "fixture_tree": fixture.get("snapshot", {}).get("tree_sha256") == POLICY["fixture"]["tree_sha256"],
        "restoration_passed": restoration.get("passed") is True,
        "restoration_level": restoration.get("level_name") == args.level_name,
        "server_jar": args.server_jar_sha256.lower() == PROTOCOL["environment"]["server_jar_sha256"],
    }
    if not all(static_checks.values()):
        raise RuntimeError(
            "SP-001 skill evaluation static preflight failed: "
            + ", ".join(key for key, passed in static_checks.items() if not passed)
        )

    config = build_skill_evaluation_runtime_config(
        authorization=authorization,
        api_key=api_key,
        log_dir=repo_relative(output_dir),
        host=args.host,
        port=args.port,
        username=args.username,
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
    )
    agent = StonePickaxeSkillEvaluationAgent(config, authorization)
    connected = False
    initial: dict = {}
    terminal: dict = {}
    result: dict = {}
    events: list[dict] = []
    graph: dict = {}
    initial_monotonic = time.monotonic()
    terminal_monotonic = initial_monotonic
    try:
        connected = agent.connect()
        if not connected:
            raise RuntimeError("SP-001 skill evaluation Agent could not connect")
        protocol_status = agent.bot.benchmark_protocol("m4-fixed-v1")
        bridge_health = agent.bot.health()
        initial = agent._observe()
        initial_monotonic = time.monotonic()
        fixture_audit = audit_sp001_fixture(initial)
        controls = runtime_controls(config)
        preflight = {
            "type": "stone_pickaxe_skill_evaluation_preflight",
            "schema_version": 1,
            "generated_at_utc": utc_now(),
            "episode_id": args.episode_id,
            "task_id": "SP-001",
            "arm": args.arm,
            "replicate_id": args.replicate_id,
            "policy_id": POLICY["id"],
            "policy_sha256": POLICY_SHA256,
            "protocol_id": PROTOCOL["id"],
            "protocol_sha256": PROTOCOL_SHA256,
            "static_checks": static_checks,
            "authorization_audit": authorization_audit,
            "fixture_machine_audit": fixture_audit,
            "protocol_status": protocol_status,
            "bridge_health": bridge_health,
            "runtime_controls": controls,
            "target_skill_id": config.target_skill_id,
            "skill_execution_mode": config.skill_execution_mode,
            "skill_artifact_persistence": False,
            "active_episode_reset": False,
            "external_step_script": False,
            "normal_runtime_permission": False,
            "automatic_retry_allowed": False,
            "counts_toward_capability": False,
            "counts_toward_m4": False,
            "passed": all(static_checks.values())
            and fixture_audit["passed"]
            and controls["action_verification_enforced"] is True
            and controls["goal_verification"] is True,
        }
        preflight_path = write_json(output_dir / "preflight.json", preflight)
        if not preflight["passed"]:
            raise RuntimeError(f"SP-001 skill evaluation machine preflight failed: {fixture_audit['issues']}")
        task = next(item for item in PROTOCOL["tasks"] if item["id"] == "SP-001")
        deadline = initial_monotonic + float(task["episode_timeout_s"])
        result = agent.run_goal(
            SP001_GOAL,
            max_cycles=int(task["maximum_cycles"]),
            max_duration_s=float(task["episode_timeout_s"]),
            episode_deadline_monotonic=deadline,
            per_action_timeout_s=float(PROTOCOL["deadline_policy"]["per_action_timeout_s"]),
            max_actions=int(task["maximum_actions"]),
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
    episode = build_skill_evaluation_episode(
        authorization=authorization,
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
        hypothesis_path=repo_relative(authorization_path),
        level_name=args.level_name,
    )
    episode_path = write_json(output_dir / "episode.json", episode)
    verification = verify_sp001_runtime_episode(episode)
    verification_path = write_json(output_dir / "verification.json", verification)
    audit = build_sp001_run_audit(episode, verification, events, graph)
    audit.update({
        "evaluation_arm": args.arm,
        "replicate_id": args.replicate_id,
        "policy_id": POLICY["id"],
        "policy_sha256": POLICY_SHA256,
        "normal_runtime_permission": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    })
    audit_path = write_json(output_dir / "audit.json", audit)
    source_paths = [
        authorization_path,
        restoration_path,
        preflight_path,
        session_path,
        episode_path,
        verification_path,
        audit_path,
    ]
    source_evidence = [
        {"path": repo_relative(path), "sha256": file_sha256(path)}
        for path in source_paths
    ]
    evaluation_run = build_skill_evaluation_run(
        episode=episode,
        verification=verification,
        events=events,
        authorization=authorization,
        source_evidence=source_evidence,
        preflight_passed=preflight["passed"],
    )
    evaluation_run_path = write_json(output_dir / "evaluation_run.json", evaluation_run)
    manifest_files = source_paths + [evaluation_run_path]
    manifest = {
        "type": "stone_pickaxe_skill_evaluation_manifest",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "runtime_policy_id": RUNTIME_POLICY_ID,
        "policy_id": POLICY["id"],
        "policy_sha256": POLICY_SHA256,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "episode_id": args.episode_id,
        "session_id": session_id,
        "task_id": "SP-001",
        "arm": args.arm,
        "replicate_id": args.replicate_id,
        "pair_id": authorization.get("pair_id", ""),
        "fixture_tree_sha256": fixture["snapshot"]["tree_sha256"],
        "server_jar_sha256": args.server_jar_sha256.lower(),
        "machine_verification_passed": verification.get("passed") is True,
        "evaluation_passed": evaluation_run.get("status") == "pass",
        "authorization_consumed": True,
        "normal_runtime_permission": False,
        "automatic_retry_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
        "files": [
            {"path": repo_relative(path), "sha256": file_sha256(path)}
            for path in manifest_files
        ],
    }
    manifest_path = write_json(output_dir / "manifest.json", manifest)
    print(json.dumps({
        "episode_id": args.episode_id,
        "session_id": session_id,
        "arm": args.arm,
        "replicate_id": args.replicate_id,
        "machine_verification_passed": verification.get("passed") is True,
        "evaluation_status": evaluation_run.get("status"),
        "failed_checks": sorted(key for key, passed in evaluation_run.get("checks", {}).items() if not passed),
        "evaluation_run": repo_relative(evaluation_run_path),
        "manifest": repo_relative(manifest_path),
        "automatic_retry_allowed": False,
    }, indent=2))
    return 0


def run_refresh_report(args: argparse.Namespace) -> int:
    run_paths = discover_evaluation_run_paths(_repository_path(args.runs_root))
    baseline = build_baseline_index()
    report = build_paired_evaluation_report(run_paths)
    baseline_path = write_json(_repository_path(args.baseline_output), baseline)
    report_path = write_json(_repository_path(args.report_output), report)
    print(json.dumps({
        "baseline_index": repo_relative(baseline_path),
        "baseline_count": baseline["record_count"],
        "evaluation_run_count": len(run_paths),
        "paired_report": repo_relative(report_path),
        "valid_pair_count": report["valid_pair_count"],
        "decision": report["decision"],
        "readiness": report["readiness"],
        "normal_runtime_permission": False,
    }, indent=2))
    return 0


def _repository_path(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = REPOSITORY_ROOT / target
    resolved = target.resolve()
    try:
        resolved.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise ValueError(f"path escaped repository: {path}") from exc
    return resolved


def main() -> int:
    args = parse_args()
    if args.command == "audit-policy":
        return run_audit_policy(args)
    if args.command == "write-authorization":
        return run_write_authorization(args)
    if args.command == "run-arm":
        return run_arm(args)
    if args.command == "refresh-report":
        return run_refresh_report(args)
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({
            "error": str(exc),
            "automatic_retry_allowed": False,
        }, indent=2), file=sys.stderr)
        raise
