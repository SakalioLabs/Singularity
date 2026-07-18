#!/usr/bin/env python3
"""Evidence-producing runner for controlled stone-pickaxe microbenchmarks."""

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
from singularity.evaluation.stone_pickaxe_sp002_runtime import (
    SP002_FIXTURE_GOAL,
    SP002_GOAL,
    SP002_RUNTIME_POLICY_ID,
    StonePickaxeRuntimeAgent as StonePickaxeSP002RuntimeAgent,
    audit_sp002_bridge_protocol_status,
    audit_sp002_fixture,
    build_sp002_authorization,
    build_sp002_episode,
    build_sp002_fixture_artifact,
    build_sp002_run_audit,
    verify_sp002_authorization,
    verify_sp002_fixture_manifest,
    verify_sp002_runtime_episode,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SP002_POLICY_PATH = REPOSITORY_ROOT / "workspace/evals/stone_pickaxe_sp002_harness_policy.json"


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

    prepare_sp002 = subparsers.add_parser("prepare-sp002-fixture")
    _add_connection_args(prepare_sp002)
    prepare_sp002.add_argument("--episode-id", required=True)
    prepare_sp002.add_argument("--level-name", required=True)
    prepare_sp002.add_argument("--output-dir", required=True)
    prepare_sp002.add_argument("--source-fixture", required=True)
    prepare_sp002.add_argument("--authorization", required=True)
    prepare_sp002.add_argument("--git-head", required=True)
    prepare_sp002.add_argument("--git-parent", required=True)
    prepare_sp002.add_argument("--max-duration", type=float, default=180.0)
    prepare_sp002.add_argument("--max-cycles", type=int, default=12)
    prepare_sp002.add_argument("--max-actions", type=int, default=8)

    seal_sp002 = subparsers.add_parser("seal-sp002-fixture")
    seal_sp002.add_argument("--snapshot-root", required=True)
    seal_sp002.add_argument("--preparation", required=True)
    seal_sp002.add_argument("--output", required=True)

    audit_sp002 = subparsers.add_parser("audit-sp002-fixture")
    audit_sp002.add_argument("--fixture", required=True)
    audit_sp002.add_argument("--snapshot-root", required=True)
    audit_sp002.add_argument("--output", default="")

    authorize_sp002 = subparsers.add_parser("write-sp002-authorization")
    authorize_sp002.add_argument(
        "--scope",
        required=True,
        choices=("fixture_preparation", "live_episode"),
    )
    authorize_sp002.add_argument("--episode-id", required=True)
    authorize_sp002.add_argument("--git-head", required=True)
    authorize_sp002.add_argument("--fixture", required=True)
    authorize_sp002.add_argument("--output", required=True)

    audit_authorization_sp002 = subparsers.add_parser("audit-sp002-authorization")
    audit_authorization_sp002.add_argument(
        "--scope",
        required=True,
        choices=("fixture_preparation", "live_episode"),
    )
    audit_authorization_sp002.add_argument("--episode-id", required=True)
    audit_authorization_sp002.add_argument("--git-head", required=True)
    audit_authorization_sp002.add_argument("--git-parent", required=True)
    audit_authorization_sp002.add_argument("--fixture", required=True)
    audit_authorization_sp002.add_argument("--authorization", required=True)
    audit_authorization_sp002.add_argument("--output", default="")

    hypothesis_sp002 = subparsers.add_parser("write-sp002-hypothesis")
    hypothesis_sp002.add_argument("--fixture", required=True)
    hypothesis_sp002.add_argument("--snapshot-root", required=True)
    hypothesis_sp002.add_argument("--authorization", required=True)
    hypothesis_sp002.add_argument("--episode-id", required=True)
    hypothesis_sp002.add_argument("--git-head", required=True)
    hypothesis_sp002.add_argument("--git-parent", required=True)
    hypothesis_sp002.add_argument("--output", required=True)

    run_sp002 = subparsers.add_parser("run-sp002")
    _add_connection_args(run_sp002)
    run_sp002.add_argument("--episode-id", required=True)
    run_sp002.add_argument("--level-name", required=True)
    run_sp002.add_argument("--output-dir", required=True)
    run_sp002.add_argument("--fixture", required=True)
    run_sp002.add_argument("--authorization", required=True)
    run_sp002.add_argument("--hypothesis", required=True)
    run_sp002.add_argument("--restoration", required=True)
    run_sp002.add_argument("--git-head", required=True)
    run_sp002.add_argument("--git-parent", required=True)
    run_sp002.add_argument("--server-jar-sha256", required=True)
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


def _sp002_authorization_preflight(
    *,
    authorization_path: Path,
    fixture_path: Path,
    expected_scope: str,
    expected_episode_id: str,
    current_head: str,
    parent_head: str,
) -> tuple[dict, dict, dict]:
    if not SP002_POLICY_PATH.is_file():
        raise RuntimeError("SP-002 supplemental harness policy is missing")
    authorization = read_json(authorization_path)
    fixture = read_json(fixture_path)
    report = verify_sp002_authorization(
        authorization,
        expected_scope=expected_scope,
        current_head=current_head,
        parent_head=parent_head,
        fixture_manifest=fixture,
        fixture_path=repo_relative(fixture_path),
        fixture_sha256=file_sha256(fixture_path),
        harness_policy_path=repo_relative(SP002_POLICY_PATH),
        harness_policy_sha256=file_sha256(SP002_POLICY_PATH),
    )
    if authorization.get("episode_id") != expected_episode_id:
        report = dict(report)
        report["passed"] = False
        report["checks"] = {**dict(report.get("checks", {})), "episode_binding": False}
        report["issues"] = sorted(set(list(report.get("issues", [])) + ["episode_binding"]))
    return authorization, fixture, report


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


def run_prepare_sp002_fixture(args: argparse.Namespace) -> int:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError("SP-002 fixture preparation requires an LLM credential")
    output_dir = (REPOSITORY_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    source_fixture_path = (REPOSITORY_ROOT / args.source_fixture).resolve()
    authorization_path = (REPOSITORY_ROOT / args.authorization).resolve()
    authorization, source_fixture, authorization_report = _sp002_authorization_preflight(
        authorization_path=authorization_path,
        fixture_path=source_fixture_path,
        expected_scope="fixture_preparation",
        expected_episode_id=args.episode_id,
        current_head=args.git_head,
        parent_head=args.git_parent,
    )
    write_json(output_dir / "authorization_preflight.json", authorization_report)
    if not authorization_report["passed"]:
        raise RuntimeError(
            f"SP-002 fixture authorization failed: {authorization_report['issues']}"
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
    agent = StonePickaxeSP002RuntimeAgent(config, "prepare_sp002_fixture")
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
            raise RuntimeError("SP-002 fixture Agent could not connect")
        protocol_status = agent.bot.benchmark_protocol("m4-fixed-v1")
        protocol_status_audit = audit_sp002_bridge_protocol_status(
            protocol_status,
            episode_id=args.episode_id,
            level_name=args.level_name,
        )
        if not protocol_status_audit["passed"]:
            raise RuntimeError(
                "SP-002 fixture bridge protocol failed before actions: "
                + ", ".join(protocol_status_audit["issues"])
            )
        initial = agent._observe()
        initial_monotonic = time.monotonic()
        deadline = initial_monotonic + float(args.max_duration)
        result = agent.run_goal(
            SP002_FIXTURE_GOAL,
            max_cycles=int(args.max_cycles),
            max_duration_s=float(args.max_duration),
            episode_deadline_monotonic=deadline,
            per_action_timeout_s=float(PROTOCOL["deadline_policy"]["per_action_timeout_s"]),
            max_actions=int(args.max_actions),
            deadline_policy_id=PROTOCOL["deadline_policy"]["id"],
        )
        terminal = agent._observe()
        terminal_monotonic = time.monotonic()
        audit = audit_sp002_fixture(terminal)
        events = list(agent.session_logger.events)
        planner_request_audit = planner_request_controls_audit(events)
        audit = dict(audit)
        audit["checks"] = {
            **dict(audit.get("checks", {})),
            "planner_request_controls": planner_request_audit["passed"],
            "bridge_protocol_status": protocol_status_audit["passed"],
        }
        audit["passed"] = bool(
            audit.get("passed")
            and planner_request_audit["passed"]
            and protocol_status_audit["passed"]
        )
        if not planner_request_audit["passed"]:
            audit["issues"] = sorted(
                set(list(audit.get("issues", [])) + ["planner_request_controls"])
            )
        if not protocol_status_audit["passed"]:
            audit["issues"] = sorted(
                set(list(audit.get("issues", [])) + ["bridge_protocol_status"])
            )
        if audit["passed"]:
            save_result = agent.bot.chat("/save-all flush")
            admin_commands.append({
                "command": "save-all flush",
                "purpose": "persist SP-002 survival-prepared world before snapshot sealing",
                "success": save_result.get("success") is True,
            })
            if save_result.get("success") is not True:
                audit["passed"] = False
                audit["issues"] = sorted(
                    set(list(audit.get("issues", [])) + ["save_all_flush_failed"])
                )
        session_id = str(agent.session_logger.session_id)
        graph = task_graph_snapshot(agent)
        health = agent.bot.health()
    finally:
        if connected:
            agent.disconnect()

    session_path = write_json(output_dir / "session.json", events)
    preparation_path = output_dir / "preparation.json"
    forbidden = _forbidden_interventions(events)
    source_snapshot = source_fixture.get("snapshot", {})
    preparation = {
        "type": "stone_pickaxe_sp002_fixture_preparation",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "policy_id": "stone-pickaxe-sp002-survival-fixture-preparation-v1",
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "episode_id": args.episode_id,
        "session_id": session_id,
        "session_sha256": file_sha256(session_path),
        "level_name": args.level_name,
        "goal": SP002_FIXTURE_GOAL,
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
        "protocol_status_audit": protocol_status_audit,
        "bridge_health": health,
        "game_mode": str(terminal.get("game_mode") or ""),
        "source_fixture": {
            "path": repo_relative(source_fixture_path),
            "sha256": file_sha256(source_fixture_path),
            "fixture_id": source_fixture.get("fixture_id", ""),
            "tree_sha256": source_snapshot.get("tree_sha256", ""),
            "snapshot_identity_verified": source_fixture.get("snapshot_identity_verified") is True,
        },
        "authorization": authorization,
        "authorization_preflight": authorization_report,
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
        "automatic_retry_allowed": False,
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


def run_seal_sp002_fixture(args: argparse.Namespace) -> int:
    snapshot_root = (REPOSITORY_ROOT / args.snapshot_root).resolve()
    preparation_path = (REPOSITORY_ROOT / args.preparation).resolve()
    output_path = (REPOSITORY_ROOT / args.output).resolve()
    report = snapshot_tree_report(snapshot_root)
    artifact = build_sp002_fixture_artifact(
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


def run_audit_sp002_fixture(args: argparse.Namespace) -> int:
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    snapshot_root = (REPOSITORY_ROOT / args.snapshot_root).resolve()
    report = verify_sp002_fixture_manifest(read_json(fixture_path), snapshot_root)
    if args.output:
        write_json((REPOSITORY_ROOT / args.output).resolve(), report)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


def run_write_sp002_authorization(args: argparse.Namespace) -> int:
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    output_path = (REPOSITORY_ROOT / args.output).resolve()
    fixture = read_json(fixture_path)
    expected_fixture_id = (
        "sp001-acquire-cobblestone-v1"
        if args.scope == "fixture_preparation"
        else "sp002-craft-stone-pickaxe-v1"
    )
    if fixture.get("fixture_id") != expected_fixture_id:
        raise RuntimeError(
            f"authorization fixture must be {expected_fixture_id}, got {fixture.get('fixture_id')}"
        )
    if fixture.get("snapshot_identity_verified") is not True:
        raise RuntimeError("authorization requires a verified immutable fixture")
    if output_path.exists():
        existing = read_json(output_path)
        if existing.get("status") == "active":
            raise RuntimeError("an active SP-002 authorization already exists")
    artifact = build_sp002_authorization(
        scope=args.scope,
        episode_id=args.episode_id,
        authorization_predecessor=args.git_head,
        fixture_path=repo_relative(fixture_path),
        fixture_sha256=file_sha256(fixture_path),
        fixture_id=fixture["fixture_id"],
        fixture_tree_sha256=fixture["snapshot"]["tree_sha256"],
        harness_policy_path=repo_relative(SP002_POLICY_PATH),
        harness_policy_sha256=file_sha256(SP002_POLICY_PATH),
    )
    write_json(output_path, artifact)
    print(json.dumps({
        "authorization": repo_relative(output_path),
        "authorization_id": artifact["authorization_id"],
        "scope": artifact["scope"],
        "episode_id": artifact["episode_id"],
        "automatic_retry_allowed": False,
    }, indent=2))
    return 0


def run_audit_sp002_authorization(args: argparse.Namespace) -> int:
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    authorization_path = (REPOSITORY_ROOT / args.authorization).resolve()
    _, _, report = _sp002_authorization_preflight(
        authorization_path=authorization_path,
        fixture_path=fixture_path,
        expected_scope=args.scope,
        expected_episode_id=args.episode_id,
        current_head=args.git_head,
        parent_head=args.git_parent,
    )
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


def run_write_sp002_hypothesis(args: argparse.Namespace) -> int:
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    snapshot_root = (REPOSITORY_ROOT / args.snapshot_root).resolve()
    authorization_path = (REPOSITORY_ROOT / args.authorization).resolve()
    fixture = read_json(fixture_path)
    fixture_preflight = verify_sp002_fixture_manifest(fixture, snapshot_root)
    if not fixture_preflight["passed"]:
        raise RuntimeError(f"SP-002 fixture preflight failed: {fixture_preflight['issues']}")
    authorization, _, authorization_report = _sp002_authorization_preflight(
        authorization_path=authorization_path,
        fixture_path=fixture_path,
        expected_scope="live_episode",
        expected_episode_id=args.episode_id,
        current_head=args.git_head,
        parent_head=args.git_parent,
    )
    if not authorization_report["passed"]:
        raise RuntimeError(
            f"SP-002 authorization preflight failed: {authorization_report['issues']}"
        )
    output_path = (REPOSITORY_ROOT / args.output).resolve()
    hypothesis = {
        "type": "stone_pickaxe_live_hypothesis",
        "schema_version": 1,
        "created_at_utc": utc_now(),
        "created_before_live_process_start": True,
        "episode_id": args.episode_id,
        "task_id": "SP-002",
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "git_head_before_episode": args.git_head,
        "authorization_id": authorization["authorization_id"],
        "authorization_path": repo_relative(authorization_path),
        "fixture_path": repo_relative(fixture_path),
        "fixture_tree_sha256": fixture["snapshot"]["tree_sha256"],
        "hypothesis": (
            "From the verified immutable SP-002 snapshot, the skills-off LLM Planner "
            "will emit one exact craft stone_pickaxe action. The single-attempt bridge "
            "will consume exactly three cobblestone and two sticks at the observed "
            "crafting table, and a distinct delayed observation will retain one stone_pickaxe."
        ),
        "falsifiers": [
            "initial inventory is not exact cobblestone=3 and stick=2",
            "stone_pickaxe is present before the action",
            "no interactive crafting table is observed within 4.5 blocks",
            "Planner emits anything other than one exact craft action",
            "backend reports more than one craft attempt or any retry",
            "material consumption is not exactly cobblestone=3 and stick=2",
            "stone_pickaxe is absent or transient at stable reobservation",
            "any learned or quarantined skill is selected",
        ],
        "authorization": {
            "single_episode": True,
            "automatic_retry_allowed": False,
            "consumed_by_process_start": True,
        },
        "counts_toward_capability": False,
        "counts_toward_m4": False,
        "sp003_allowed": False,
    }
    write_json(output_path, hypothesis)
    print(json.dumps({
        "hypothesis": repo_relative(output_path),
        "episode_id": args.episode_id,
        "authorization_id": authorization["authorization_id"],
    }, indent=2))
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


def run_sp002(args: argparse.Namespace) -> int:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError("SP-002 requires an LLM credential")
    output_dir = (REPOSITORY_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = (REPOSITORY_ROOT / args.fixture).resolve()
    authorization_path = (REPOSITORY_ROOT / args.authorization).resolve()
    hypothesis_path = (REPOSITORY_ROOT / args.hypothesis).resolve()
    restoration_path = (REPOSITORY_ROOT / args.restoration).resolve()
    hypothesis = read_json(hypothesis_path)
    restoration = read_json(restoration_path)
    authorization, fixture, authorization_report = _sp002_authorization_preflight(
        authorization_path=authorization_path,
        fixture_path=fixture_path,
        expected_scope="live_episode",
        expected_episode_id=args.episode_id,
        current_head=args.git_head,
        parent_head=args.git_parent,
    )
    static_checks = {
        "authorization": authorization_report["passed"],
        "protocol_hash": fixture.get("protocol_sha256") == PROTOCOL_SHA256,
        "fixture_scope": fixture.get("fixture_id") == "sp002-craft-stone-pickaxe-v1",
        "fixture_identity": fixture.get("snapshot_identity_verified") is True,
        "hypothesis_episode": hypothesis.get("episode_id") == args.episode_id,
        "hypothesis_task": hypothesis.get("task_id") == "SP-002",
        "hypothesis_precedes_live": hypothesis.get("created_before_live_process_start") is True,
        "hypothesis_protocol": hypothesis.get("protocol_sha256") == PROTOCOL_SHA256,
        "hypothesis_authorization": (
            hypothesis.get("authorization_id") == authorization.get("authorization_id")
        ),
        "restoration_passed": restoration.get("passed") is True,
        "restoration_level": restoration.get("level_name") == args.level_name,
        "server_jar": args.server_jar_sha256.lower() == PROTOCOL["environment"]["server_jar_sha256"],
    }
    if not all(static_checks.values()):
        raise RuntimeError(
            "SP-002 static preflight failed: "
            + ", ".join(key for key, passed in static_checks.items() if not passed)
        )

    consumption = {
        "type": "stone_pickaxe_sp002_authorization_consumption",
        "schema_version": 1,
        "consumed_at_utc": utc_now(),
        "authorization_id": authorization["authorization_id"],
        "authorization_path": repo_relative(authorization_path),
        "authorization_sha256": file_sha256(authorization_path),
        "authorization_commit": args.git_head,
        "episode_id": args.episode_id,
        "scope": "live_episode",
        "consumed_by": "controlled_runtime_start",
        "automatic_retry_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }
    consumption_path = write_json(output_dir / "authorization_consumption.json", consumption)

    config = build_runtime_config(
        api_key=api_key,
        log_dir=repo_relative(output_dir),
        host=args.host,
        port=args.port,
        username=args.username,
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
    )
    agent = StonePickaxeSP002RuntimeAgent(config, "sp002")
    connected = False
    try:
        connected = agent.connect()
        if not connected:
            raise RuntimeError("SP-002 Agent could not connect")
        protocol_status = agent.bot.benchmark_protocol("m4-fixed-v1")
        protocol_status_audit = audit_sp002_bridge_protocol_status(
            protocol_status,
            episode_id=args.episode_id,
            level_name=args.level_name,
        )
        bridge_health = agent.bot.health()
        initial = agent._observe()
        initial_monotonic = time.monotonic()
        fixture_audit = audit_sp002_fixture(initial)
        craft_policy = (
            bridge_health.get("craft_policy")
            if isinstance(bridge_health.get("craft_policy"), dict)
            else {}
        )
        preflight = {
            "type": "stone_pickaxe_live_preflight",
            "schema_version": 1,
            "generated_at_utc": utc_now(),
            "episode_id": args.episode_id,
            "task_id": "SP-002",
            "runtime_policy_id": SP002_RUNTIME_POLICY_ID,
            "protocol_id": PROTOCOL["id"],
            "protocol_sha256": PROTOCOL_SHA256,
            "static_checks": static_checks,
            "authorization_preflight": authorization_report,
            "fixture_machine_audit": fixture_audit,
            "protocol_status": protocol_status,
            "protocol_status_audit": protocol_status_audit,
            "bridge_health": bridge_health,
            "runtime_controls": runtime_controls(config),
            "craft_backend_policy": craft_policy,
            "active_episode_reset": False,
            "external_step_script": False,
            "passed": bool(
                all(static_checks.values())
                and protocol_status_audit["passed"]
                and fixture_audit["passed"]
                and craft_policy.get("max_attempts") == 1
                and craft_policy.get("automatic_retry") is False
            ),
        }
        write_json(output_dir / "preflight.json", preflight)
        if not preflight["passed"]:
            raise RuntimeError(
                "SP-002 machine preflight failed: "
                + ", ".join(protocol_status_audit.get("issues", []))
                + ("; " if protocol_status_audit.get("issues") else "")
                + ", ".join(fixture_audit.get("issues", []))
                + ("; craft_backend_policy" if craft_policy.get("max_attempts") != 1 else "")
            )
        task = PROTOCOL["tasks"][1]
        deadline = initial_monotonic + float(task["episode_timeout_s"])
        result = agent.run_goal(
            SP002_GOAL,
            max_cycles=int(task["maximum_cycles"]),
            max_duration_s=float(task["episode_timeout_s"]),
            episode_deadline_monotonic=deadline,
            per_action_timeout_s=float(PROTOCOL["deadline_policy"]["per_action_timeout_s"]),
            max_actions=int(task["maximum_actions"]),
            deadline_policy_id=PROTOCOL["deadline_policy"]["id"],
        )
        delay = float(PROTOCOL["evidence_policy"]["stable_reobservation_delay_s"])
        time.sleep(delay + 0.05)
        stable = agent._observe()
        stable_monotonic = time.monotonic()
        events = list(agent.session_logger.events)
        session_id = str(agent.session_logger.session_id)
        graph = task_graph_snapshot(agent)
    finally:
        if connected:
            agent.disconnect()

    session_path = write_json(output_dir / "session.json", events)
    episode = build_sp002_episode(
        episode_id=args.episode_id,
        session_id=session_id,
        session_sha256=file_sha256(session_path),
        events=events,
        initial_observation=initial,
        stable_observation=stable,
        initial_monotonic=initial_monotonic,
        stable_monotonic=stable_monotonic,
        goal_result=result,
        fixture_manifest=fixture,
        hypothesis_path=repo_relative(hypothesis_path),
        authorization_path=repo_relative(authorization_path),
        level_name=args.level_name,
    )
    episode_path = write_json(output_dir / "episode.json", episode)
    verification = verify_sp002_runtime_episode(episode)
    verification_path = write_json(output_dir / "verification.json", verification)
    audit = build_sp002_run_audit(episode, verification, events, graph)
    audit_path = write_json(output_dir / "audit.json", audit)
    evidence_files = [
        authorization_path,
        consumption_path,
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
        "runtime_policy_id": SP002_RUNTIME_POLICY_ID,
        "episode_id": args.episode_id,
        "session_id": session_id,
        "task_id": "SP-002",
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "authorization_id": authorization["authorization_id"],
        "fixture_tree_sha256": fixture["snapshot"]["tree_sha256"],
        "server_jar_sha256": args.server_jar_sha256.lower(),
        "evidence_eligible": verification.get("evidence_eligible") is True,
        "passed": verification.get("passed") is True,
        "automatic_retry_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
        "sp003_allowed": False,
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
        "automatic_retry_allowed": False,
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
    if args.command == "prepare-sp002-fixture":
        return run_prepare_sp002_fixture(args)
    if args.command == "seal-fixture":
        return run_seal_fixture(args)
    if args.command == "seal-sp002-fixture":
        return run_seal_sp002_fixture(args)
    if args.command == "audit-fixture":
        return run_audit_fixture(args)
    if args.command == "audit-sp002-fixture":
        return run_audit_sp002_fixture(args)
    if args.command == "audit-restoration":
        return run_audit_restoration(args)
    if args.command == "write-sp002-authorization":
        return run_write_sp002_authorization(args)
    if args.command == "audit-sp002-authorization":
        return run_audit_sp002_authorization(args)
    if args.command == "write-hypothesis":
        return run_write_hypothesis(args)
    if args.command == "write-sp002-hypothesis":
        return run_write_sp002_hypothesis(args)
    if args.command == "run-sp001":
        return run_sp001(args)
    if args.command == "run-sp002":
        return run_sp002(args)
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc), "automatic_retry_allowed": False}, indent=2), file=sys.stderr)
        raise
