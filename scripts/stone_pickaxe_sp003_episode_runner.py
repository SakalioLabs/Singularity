"""Authorize or run one fresh-world SP-003 empty-hand episode."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from singularity.bot.bridge import BotBridge
from singularity.core.config import BotConfig
from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL, PROTOCOL_SHA256
from singularity.evaluation.stone_pickaxe_sp002_runtime import (
    build_runtime_config,
    file_sha256,
    read_json,
    task_graph_snapshot,
    utc_now,
)
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    SP003_AUTHORIZATION_PATH,
    SP003_GOAL,
    SP003_POLICY_PATH,
    SP003_RUNTIME_POLICY_ID,
    audit_sp003_initial_state,
    audit_sp003_reset,
    build_sp003_authorization,
    build_sp003_episode,
    build_sp003_run_audit,
    build_sp003_runtime_config,
    sp003_runtime_controls,
    verify_sp003_authorization,
    verify_sp003_policy_identity,
    verify_sp003_runtime_episode,
)
from singularity.evaluation.stone_pickaxe_sp003_phase116_runtime import (
    StonePickaxeSP003Phase116RuntimeAgent,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SP-003 empty-hand runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    authorize = subparsers.add_parser("write-authorization")
    authorize.add_argument("--arm", required=True, choices=("baseline", "candidate"))
    authorize.add_argument("--replicate-id", required=True, choices=("baseline", "r1", "r2", "r3"))
    authorize.add_argument("--episode-id", required=True)
    authorize.add_argument("--git-head", required=True)
    authorize.add_argument("--prerequisite-manifest", default="")
    authorize.add_argument(
        "--output",
        default=SP003_AUTHORIZATION_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
    )

    audit = subparsers.add_parser("audit-authorization")
    audit.add_argument("--arm", required=True, choices=("baseline", "candidate"))
    audit.add_argument("--replicate-id", required=True, choices=("baseline", "r1", "r2", "r3"))
    audit.add_argument("--episode-id", required=True)
    audit.add_argument("--git-head", required=True)
    audit.add_argument("--git-parent", required=True)
    audit.add_argument(
        "--authorization",
        default=SP003_AUTHORIZATION_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
    )

    run = subparsers.add_parser("run")
    run.add_argument("--arm", required=True, choices=("baseline", "candidate"))
    run.add_argument("--replicate-id", required=True, choices=("baseline", "r1", "r2", "r3"))
    run.add_argument("--episode-id", required=True)
    run.add_argument("--level-name", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--authorization", required=True)
    run.add_argument("--git-head", required=True)
    run.add_argument("--git-parent", required=True)
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=25565)
    run.add_argument("--username", default="Singularity")
    run.add_argument("--bridge-host", default="127.0.0.1")
    run.add_argument("--bridge-port", type=int, default=30000)
    run.add_argument("--fresh-level", action="store_true")
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


def write_json(path: str | Path, payload) -> Path:
    target = repo_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError(f"refusing to overwrite evidence: {target}")
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


def run_write_authorization(args: argparse.Namespace) -> int:
    policy_report = verify_sp003_policy_identity()
    if not policy_report["passed"]:
        raise RuntimeError(f"SP-003 policy identity failed: {policy_report['issues']}")
    prerequisite_path = ""
    prerequisite_sha256 = ""
    if args.prerequisite_manifest:
        path = repo_path(args.prerequisite_manifest)
        prerequisite_path = repo_relative(path)
        prerequisite_sha256 = file_sha256(path)
    artifact = build_sp003_authorization(
        arm=args.arm,
        replicate_id=args.replicate_id,
        episode_id=args.episode_id,
        authorization_predecessor=args.git_head,
        prerequisite_manifest_path=prerequisite_path,
        prerequisite_manifest_sha256=prerequisite_sha256,
    )
    target = repo_path(args.output)
    if target.exists():
        target.unlink()
    write_json(target, artifact)
    print(json.dumps({
        "authorization": repo_relative(target),
        "authorization_sha256": file_sha256(target),
        "authorization_id": artifact["authorization_id"],
        "episode_id": artifact["episode_id"],
        "arm": artifact["arm"],
        "replicate_id": artifact["replicate_id"],
        "single_episode": True,
        "automatic_retry_allowed": False,
    }, indent=2))
    return 0


def run_audit_authorization(args: argparse.Namespace) -> int:
    path = repo_path(args.authorization)
    report = verify_sp003_authorization(
        read_json(path),
        expected_arm=args.arm,
        expected_replicate_id=args.replicate_id,
        expected_episode_id=args.episode_id,
        current_head=args.git_head,
        parent_head=args.git_parent,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


def _setup_reset(args: argparse.Namespace, output_dir: Path) -> dict:
    bridge = BotBridge(BotConfig(
        host=args.host,
        port=args.port,
        username=args.username,
        version=PROTOCOL["environment"]["minecraft_version"],
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
    ))
    if not bridge.connect():
        raise RuntimeError("could not connect to the SP-003 bridge for reset")
    try:
        status = bridge.benchmark_protocol("m4-fixed-v1")
        reset = bridge.reset_benchmark("BM-012")
    finally:
        bridge.disconnect()
    audit = audit_sp003_reset(
        status,
        reset,
        episode_id=args.episode_id,
        level_name=args.level_name,
    )
    write_json(output_dir / "protocol_status.json", status)
    write_json(output_dir / "reset.json", reset)
    write_json(output_dir / "reset_audit.json", audit)
    if not audit["passed"]:
        raise RuntimeError(f"SP-003 reset audit failed: {audit['issues']}")
    return audit


def run_episode(args: argparse.Namespace) -> int:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError("SP-003 requires SINGULARITY_LLM_API_KEY or OPENAI_API_KEY")
    if not args.fresh_level:
        raise RuntimeError("SP-003 requires an explicitly fresh unique level")
    expected_level_name = f"{args.episode_id}_world"
    if args.level_name != expected_level_name:
        raise RuntimeError(
            f"SP-003 level must be derived from episode_id: {expected_level_name}"
        )
    policy_report = verify_sp003_policy_identity()
    if not policy_report["passed"]:
        raise RuntimeError(f"SP-003 policy identity failed: {policy_report['issues']}")
    policy = read_json(SP003_POLICY_PATH)
    if (policy.get("current_state") or {}).get("offline_harness_ready") is not True:
        raise RuntimeError("SP-003 offline harness has not been marked ready")

    output_dir = repo_path(args.output_dir)
    expected_output_dir = repo_path(
        Path("workspace/evals/sp003_runs") / args.episode_id
    )
    if output_dir != expected_output_dir:
        raise RuntimeError(
            "SP-003 evidence must use workspace/evals/sp003_runs/<episode_id>"
        )
    if output_dir.exists():
        raise RuntimeError(f"refusing reused SP-003 evidence directory: {output_dir}")
    output_dir.mkdir(parents=True)
    authorization_source_path = repo_path(args.authorization)
    authorization = read_json(authorization_source_path)
    authorization_report = verify_sp003_authorization(
        authorization,
        expected_arm=args.arm,
        expected_replicate_id=args.replicate_id,
        expected_episode_id=args.episode_id,
        current_head=args.git_head,
        parent_head=args.git_parent,
    )
    if not authorization_report["passed"]:
        raise RuntimeError(f"SP-003 authorization failed: {authorization_report['issues']}")
    authorization_path = write_json(output_dir / "authorization.json", authorization)

    consumption = {
        "type": "stone_pickaxe_sp003_authorization_consumption",
        "schema_version": 1,
        "consumed_at_utc": utc_now(),
        "authorization_id": authorization["authorization_id"],
        "authorization_source_path": repo_relative(authorization_source_path),
        "authorization_source_sha256": file_sha256(authorization_source_path),
        "authorization_path": repo_relative(authorization_path),
        "authorization_sha256": file_sha256(authorization_path),
        "authorization_commit": args.git_head,
        "episode_id": args.episode_id,
        "arm": args.arm,
        "replicate_id": args.replicate_id,
        "consumed_by": "fresh_sp003_process_start",
        "single_episode": True,
        "automatic_retry_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }
    consumption_path = write_json(output_dir / "authorization_consumption.json", consumption)
    reset_audit = _setup_reset(args, output_dir)

    base_config = build_runtime_config(
        api_key=api_key,
        log_dir=repo_relative(output_dir),
        host=args.host,
        port=args.port,
        username=args.username,
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
    )
    config = build_sp003_runtime_config(base_config=base_config, arm=args.arm)
    skill_store_path = REPOSITORY_ROOT / policy["skill_store"]["path"]
    skill_store_sha256_before = file_sha256(skill_store_path)
    agent = StonePickaxeSP003Phase116RuntimeAgent(config, arm=args.arm)
    connected = False
    raw_session_path = Path(agent.session_logger._log_path).resolve()
    try:
        connected = agent.connect()
        if not connected:
            raise RuntimeError("SP-003 Agent could not connect")
        bridge_health = agent.bot.health()
        initial = agent._observe()
        initial_monotonic = time.monotonic()
        initial_audit = audit_sp003_initial_state(initial)
        craft_policy = (
            bridge_health.get("craft_policy")
            if isinstance(bridge_health.get("craft_policy"), dict)
            else {}
        )
        gate_report = dict(getattr(agent, "skill_runtime_default_gate_report", {}) or {})
        runtime_gate_profile = agent.skill_library.skill_runtime_default_profile()
        approved_skill_names = set(runtime_gate_profile.get("approved_skills", []))
        candidate_gate_ready = bool(
            args.arm == "baseline"
            or (
                gate_report.get("gate_approved") is True
                and gate_report.get("gate_readiness") == "approved"
                and gate_report.get("loaded_count") == 2
                and gate_report.get("approved_skill_count") == 2
                and approved_skill_names == {
                    "learned_acquire_cobblestone",
                    "learned_craft_stone_pickaxe",
                }
            )
        )
        preflight = {
            "type": "stone_pickaxe_sp003_live_preflight",
            "schema_version": 1,
            "generated_at_utc": utc_now(),
            "episode_id": args.episode_id,
            "level_name": args.level_name,
            "arm": args.arm,
            "replicate_id": args.replicate_id,
            "runtime_policy_id": SP003_RUNTIME_POLICY_ID,
            "runtime_policy_sha256": file_sha256(SP003_POLICY_PATH),
            "protocol_id": PROTOCOL["id"],
            "protocol_sha256": PROTOCOL_SHA256,
            "policy_identity": policy_report,
            "authorization_preflight": authorization_report,
            "reset_audit": reset_audit,
            "initial_state_audit": initial_audit,
            "bridge_health": bridge_health,
            "craft_backend_policy": craft_policy,
            "skill_runtime_default_gate_report": gate_report,
            "skill_runtime_default_gate_profile": runtime_gate_profile,
            "runtime_controls": sp003_runtime_controls(config, arm=args.arm),
            "fresh_level": True,
            "active_episode_reset": False,
            "external_step_script": False,
            "bm012_terminal_started": False,
            "passed": bool(
                policy_report["passed"]
                and authorization_report["passed"]
                and reset_audit["passed"]
                and initial_audit["passed"]
                and craft_policy.get("max_attempts") == 1
                and craft_policy.get("automatic_retry") is False
                and candidate_gate_ready
            ),
        }
        write_json(output_dir / "preflight.json", preflight)
        if not preflight["passed"]:
            issues = []
            issues.extend(initial_audit.get("issues", []))
            if craft_policy.get("max_attempts") != 1:
                issues.append("craft_backend_max_attempts")
            if not candidate_gate_ready:
                issues.append("candidate_runtime_gates")
            raise RuntimeError(f"SP-003 machine preflight failed: {sorted(set(issues))}")

        contract = policy["episode_contract"]
        deadline = initial_monotonic + float(contract["episode_timeout_s"])
        result = agent.run_goal(
            SP003_GOAL,
            max_cycles=int(contract["maximum_cycles"]),
            max_duration_s=float(contract["episode_timeout_s"]),
            episode_deadline_monotonic=deadline,
            per_action_timeout_s=float(PROTOCOL["deadline_policy"]["per_action_timeout_s"]),
            max_actions=int(contract["maximum_actions"]),
            deadline_policy_id=PROTOCOL["deadline_policy"]["id"],
        )
        time.sleep(float(contract["stable_reobservation_delay_s"]) + 0.05)
        stable = agent._observe()
        stable_monotonic = time.monotonic()
        events = list(agent.session_logger.events)
        session_id = str(agent.session_logger.session_id)
        graph = task_graph_snapshot(agent)
    finally:
        if connected:
            agent.disconnect()

    skill_store_sha256_after = file_sha256(skill_store_path)
    session_path = write_json(output_dir / "session.json", events)
    summary_path = output_dir / f"session_{session_id}_summary.json"
    episode = build_sp003_episode(
        arm=args.arm,
        replicate_id=args.replicate_id,
        episode_id=args.episode_id,
        session_id=session_id,
        session_sha256=file_sha256(session_path),
        level_name=args.level_name,
        events=events,
        initial_observation=initial,
        stable_observation=stable,
        initial_monotonic=initial_monotonic,
        stable_monotonic=stable_monotonic,
        goal_result=result,
        reset_audit=reset_audit,
        authorization_path=repo_relative(authorization_path),
        authorization_sha256=file_sha256(authorization_path),
        authorization_preflight=authorization_report,
        task_graph=graph,
        skill_store_sha256_before=skill_store_sha256_before,
        skill_store_sha256_after=skill_store_sha256_after,
    )
    episode_path = write_json(output_dir / "episode.json", episode)
    verification = verify_sp003_runtime_episode(episode)
    verification_path = write_json(output_dir / "verification.json", verification)
    audit = build_sp003_run_audit(episode, verification)
    audit_path = write_json(output_dir / "audit.json", audit)
    evidence_files = [
        authorization_path,
        consumption_path,
        output_dir / "protocol_status.json",
        output_dir / "reset.json",
        output_dir / "reset_audit.json",
        output_dir / "preflight.json",
        session_path,
        episode_path,
        verification_path,
        audit_path,
    ]
    for retained_session_artifact in (raw_session_path, summary_path):
        if retained_session_artifact.is_file():
            evidence_files.append(retained_session_artifact)
    manifest = {
        "type": "stone_pickaxe_sp003_live_manifest",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "runtime_policy_id": SP003_RUNTIME_POLICY_ID,
        "runtime_policy_sha256": file_sha256(SP003_POLICY_PATH),
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-003",
        "arm": args.arm,
        "replicate_id": args.replicate_id,
        "sequence_position": authorization["sequence_position"],
        "episode_id": args.episode_id,
        "session_id": session_id,
        "level_name": args.level_name,
        "authorization_id": authorization["authorization_id"],
        "passed": verification.get("passed") is True,
        "evidence_eligible": verification.get("evidence_eligible") is True,
        "single_episode": True,
        "automatic_retry_allowed": False,
        "bm012_terminal_started": False,
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
        "arm": args.arm,
        "replicate_id": args.replicate_id,
        "passed": verification.get("passed") is True,
        "evidence_eligible": verification.get("evidence_eligible") is True,
        "criteria_issues": verification.get("criteria_issues", []),
        "manifest": repo_relative(manifest_path),
        "audit": repo_relative(audit_path),
        "automatic_retry_allowed": False,
    }, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "write-authorization":
        return run_write_authorization(args)
    if args.command == "audit-authorization":
        return run_audit_authorization(args)
    if args.command == "run":
        return run_episode(args)
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
