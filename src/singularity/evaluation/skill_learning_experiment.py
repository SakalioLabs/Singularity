"""Controlled live experiments for verifier-gated learned skills.

This module deliberately runs one arm at a time.  Server/world lifecycle is
owned by ``scripts/m1-runtime.ps1`` so every arm receives a fresh level.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Optional

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.skill_learning import (
    EVALUATION_AUTHORIZATION_TYPE,
    EXECUTABLE_PROMOTION_GATE_TYPE,
    SkillLearningLedger,
    evidence_fingerprint,
)
from singularity.evaluation.benchmark_runner import M1_BENCHMARKS, m1_convergence_config
from singularity.evaluation.m1_protocol import PROTOCOL as M1_PROTOCOL
from singularity.evaluation.m1_protocol import PROTOCOL_SHA256 as M1_PROTOCOL_SHA256


LIVE_RUN_TYPE = "skill_learning_live_run"
PAIRED_REPORT_TYPE = "skill_paired_ablation_report"
TRANSFER_REPORT_TYPE = "skill_heldout_transfer_report"
RUNTIME_GATE_TYPE = "skill_runtime_default_gate"
ARMS = {"baseline", "shadow", "advisory", "candidate", "runtime", "fallback", "fault", "extraction"}
RESEARCH_FIXTURE_PROFILES = {"protocol_default", "gather_oak_near_v1", "gather_oak_shifted_v1"}
SKILL_FAULT_PROFILES = {
    "reject_skill_craft_missing_item_v1",
    "reject_skill_place_missing_item_v1",
    "reject_skill_equip_missing_item_v1",
}


def build_skill_research_config(
    config: Config,
    arm: str,
    skill_id: str,
    experiment_id: str,
    fault_profile: str = "",
) -> Config:
    """Pin all non-skill controls to the M1 convergence runtime."""
    arm = str(arm or "").strip().lower()
    if arm not in ARMS:
        raise ValueError(f"unsupported skill-learning arm: {arm}")
    controlled = m1_convergence_config(config)
    mode = {
        "baseline": "off",
        "shadow": "shadow",
        "advisory": "advisory",
        "candidate": "evaluation",
        "fallback": "evaluation",
        "fault": "evaluation",
        "extraction": "off",
        "runtime": "runtime",
    }[arm]
    authorization = {}
    if arm in {"advisory", "candidate", "fallback", "fault"}:
        authorization = {
            "type": EVALUATION_AUTHORIZATION_TYPE,
            "schema_version": 1,
            "allowed": True,
            "skill_id": str(skill_id or ""),
            "experiment_id": str(experiment_id or ""),
            "single_target_skill": True,
            "action_verifier_enforced": True,
            "action_controller_enforced": True,
            "goal_verifier_enforced": True,
            "reobserve_each_cycle": True,
            "fallback_to_agentic_planning": True,
            "world_protocol_sha256": M1_PROTOCOL_SHA256,
            "runtime_scope": "controlled_live_skill_trial_only",
            "normal_runtime_permission": False,
        }
    return replace(
        controlled,
        skill_execution_mode=mode,
        target_skill_id="" if arm in {"baseline", "extraction"} else str(skill_id or ""),
        skill_experiment_id=str(experiment_id or ""),
        skill_evaluation_authorization=authorization,
        skill_fault_profile=str(fault_profile or "") if arm == "fault" else "",
        enable_skill_candidate_extraction=arm == "extraction",
        skill_runtime_default_gate_paths=(
            list(config.skill_runtime_default_gate_paths)
            if arm == "runtime"
            else []
        ),
    )


def skill_research_runtime_profile(
    config: Config,
    arm: str,
    task_id: str,
    research_fixture_profile: str = "protocol_default",
) -> dict:
    return {
        "profile": "controlled_skill_learning_v1",
        "evidence_kind": "live_minecraft_skill_research",
        "counts_toward_m1_acceptance": False,
        "protocol": M1_PROTOCOL["profile"],
        "protocol_sha256": M1_PROTOCOL_SHA256,
        "world_seed": str(M1_PROTOCOL["world_seed"]),
        "task_id": str(task_id),
        "arm": str(arm),
        "research_fixture_profile": str(research_fixture_profile),
        "agent_id": M1_PROTOCOL["agent_id"],
        "planner_id": M1_PROTOCOL["planner_id"],
        "action_backend_id": M1_PROTOCOL["action_backend_id"],
        "verifier_id": M1_PROTOCOL["verifier_id"],
        "force_rule_planner": bool(config.force_rule_planner),
        "skill_execution_mode": str(config.skill_execution_mode),
        "target_skill_id": str(config.target_skill_id),
        "experiment_id": str(config.skill_experiment_id),
        "single_target_skill": bool(config.target_skill_id) or str(arm) == "baseline",
        "action_verifier_enforced": bool(
            config.enable_action_verification and config.enforce_action_verification
        ),
        "action_controller_enforced": True,
        "goal_verifier_enforced": bool(config.enable_goal_verification),
        "memory_persistence": bool(config.enable_memory_persistence),
        "policy_skills": bool(config.enable_policy_skills),
        "vision": bool(config.enable_vision_analysis),
        "candidate_extraction": bool(config.enable_skill_candidate_extraction),
        "skill_fault_profile": str(config.skill_fault_profile or ""),
        "controlled_failure_only": bool(config.skill_fault_profile),
    }


def run_live_skill_arm(
    config: Config,
    task_id: str,
    arm: str,
    skill_id: str,
    experiment_id: str,
    pair_id: str = "",
    replicate_id: str = "",
    goal_override: str = "",
    success_criteria_override: Optional[dict] = None,
    heldout: bool = False,
    research_fixture_profile: str = "protocol_default",
    fault_profile: str = "",
) -> dict:
    """Run one fresh-world arm and return self-contained live evidence."""
    task = _task(task_id)
    normalized_fault = str(fault_profile or "").strip().lower()
    if arm == "fault" and normalized_fault not in SKILL_FAULT_PROFILES:
        raise ValueError(f"unsupported skill fault profile: {normalized_fault}")
    if arm != "fault" and normalized_fault:
        raise ValueError("skill fault profiles are only valid for the fault arm")
    research_config = build_skill_research_config(
        config,
        arm,
        skill_id,
        experiment_id,
        fault_profile=normalized_fault,
    )
    fixture_profile = str(research_fixture_profile or "protocol_default").strip().lower()
    if fixture_profile not in RESEARCH_FIXTURE_PROFILES:
        raise ValueError(f"unsupported research fixture profile: {fixture_profile}")
    if fixture_profile != "protocol_default" and task.id != "BM-001":
        raise ValueError("gather research fixtures are only valid for BM-001")
    profile = skill_research_runtime_profile(research_config, arm, task.id, fixture_profile)
    goal = str(goal_override or task.goal)
    success_criteria = dict(success_criteria_override or task.success_criteria)
    agent = Agent(research_config)
    started = time.time()
    setup = {}
    result = {}
    initial_observation = {}
    final_inventory = {}
    connection_error = ""
    disconnected = False
    try:
        try:
            connected = bool(agent.connect())
        except Exception as exc:
            connected = False
            connection_error = str(exc)
        if not connected:
            return _failed_live_run(
                profile,
                task,
                arm,
                skill_id,
                experiment_id,
                pair_id,
                replicate_id,
                heldout,
                goal,
                success_criteria,
                agent,
                started,
                connection_error or "bridge_connection_failed",
            )
        agent.session_logger.log("skill_learning_runtime_profile", profile)
        agent.session_logger.log("benchmark_runtime_profile", {
            **profile,
            "isolated": arm == "extraction",
            "research_profile": True,
        })
        setup = agent.bot.reset_benchmark(task.id)
        agent.session_logger.log("benchmark_reset", setup)
        if not setup.get("success"):
            error = str(setup.get("error") or "benchmark_reset_failed")
            return _failed_live_run(
                profile,
                task,
                arm,
                skill_id,
                experiment_id,
                pair_id,
                replicate_id,
                heldout,
                goal,
                success_criteria,
                agent,
                started,
                error,
                setup=setup,
            )
        research_setup = _apply_research_fixture(agent, setup, fixture_profile)
        agent.session_logger.log("skill_learning_research_setup", research_setup)
        if not research_setup.get("success"):
            return _failed_live_run(
                profile,
                task,
                arm,
                skill_id,
                experiment_id,
                pair_id,
                replicate_id,
                heldout,
                goal,
                success_criteria,
                agent,
                started,
                str(research_setup.get("error") or "research_fixture_failed"),
                setup=setup,
            )
        initial_observation = agent._observe()
        research_setup = _verify_research_fixture(research_setup, initial_observation)
        agent.session_logger.log("skill_learning_research_setup_verification", research_setup)
        if not research_setup.get("verified"):
            return _failed_live_run(
                profile,
                task,
                arm,
                skill_id,
                experiment_id,
                pair_id,
                replicate_id,
                heldout,
                goal,
                success_criteria,
                agent,
                started,
                "research_fixture_verification_failed",
                setup=setup,
            )
        agent.session_logger.log("skill_learning_initial_observation", initial_observation)
        result = agent.run_goal(
            goal,
            max_cycles=task.timeout_cycles,
            max_duration_s=task.max_duration_s or None,
        )
        final_inventory = _inventory_counts(agent.bot.get_inventory())
        events = list(agent.session_logger.events)
        report = _assess_live_run(
            profile=profile,
            task=task,
            arm=arm,
            skill_id=skill_id,
            experiment_id=experiment_id,
            pair_id=pair_id,
            replicate_id=replicate_id,
            heldout=heldout,
            goal=goal,
            success_criteria=success_criteria,
            setup=setup,
            research_setup=research_setup,
            initial_observation=initial_observation,
            final_inventory=final_inventory,
            result=result,
            events=events,
            duration_s=time.time() - started,
            fault_profile=normalized_fault,
        )
        agent.session_logger.log("skill_learning_live_assessment", {
            "run_id": report["run_id"],
            "status": report["status"],
            "checks": report["checks"],
        })
        agent.disconnect()
        disconnected = True
        report["source_log_sha256"] = _file_sha256(report.get("source_log", ""))
        report["source_log_finalized_before_hash"] = True
        return report
    finally:
        if not disconnected:
            try:
                agent.disconnect()
            except Exception:
                pass


def build_paired_ablation_report(
    run_paths: Iterable[str],
    skill_id: str,
    skill_version: str,
    task_family: str,
    rollback_target: str,
    transfer_scope: dict,
) -> dict:
    runs, errors = _load_typed_runs(run_paths)
    selected = [run for run in runs if run.get("skill_id") == skill_id]
    pairs = []
    grouped: dict[str, dict[str, dict]] = {}
    fallback_runs = []
    shadow_runs = []
    advisory_runs = []
    for run in selected:
        arm = str(run.get("arm") or "")
        if arm == "fallback":
            fallback_runs.append(run)
            continue
        if arm == "shadow":
            shadow_runs.append(run)
            continue
        if arm == "advisory":
            advisory_runs.append(run)
            continue
        if arm not in {"baseline", "candidate"}:
            continue
        pair_id = str(run.get("pair_id") or "")
        if not pair_id:
            errors.append(f"{run.get('run_id')}: pair_id_missing")
            continue
        grouped.setdefault(pair_id, {})[arm] = run

    for pair_id, arms in sorted(grouped.items()):
        baseline = arms.get("baseline")
        candidate = arms.get("candidate")
        if not baseline or not candidate:
            errors.append(f"{pair_id}: baseline_candidate_pair_incomplete")
            continue
        controls_match = _fixed_controls_match(baseline, candidate)
        baseline_integrity = _run_artifact_integrity(baseline)
        candidate_integrity = _run_artifact_integrity(candidate)
        baseline_metrics = baseline.get("metrics", {})
        candidate_metrics = candidate.get("metrics", {})
        pairs.append({
            "pair_id": pair_id,
            "replicate_id": candidate.get("replicate_id") or baseline.get("replicate_id") or "",
            "baseline_run_id": baseline.get("run_id", ""),
            "candidate_run_id": candidate.get("run_id", ""),
            "baseline_session_id": baseline.get("session_id", ""),
            "candidate_session_id": candidate.get("session_id", ""),
            "baseline_source_log": baseline.get("source_log", ""),
            "candidate_source_log": candidate.get("source_log", ""),
            "initial_observation_match": (
                baseline.get("initial_observation_fingerprint")
                == candidate.get("initial_observation_fingerprint")
            ),
            "controlled_setup_match": (
                _controlled_setup_fingerprint(baseline)
                == _controlled_setup_fingerprint(candidate)
            ),
            "fixed_controls_match": controls_match,
            "baseline_live_integrity": baseline_integrity,
            "candidate_live_integrity": candidate_integrity,
            "baseline_passed": baseline.get("status") == "pass",
            "candidate_passed": candidate.get("status") == "pass",
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "deltas": _metric_deltas(baseline_metrics, candidate_metrics),
        })

    baseline_ids = _unique(pair.get("baseline_session_id") for pair in pairs)
    candidate_ids = _unique(pair.get("candidate_session_id") for pair in pairs)
    valid_pairs = [
        pair for pair in pairs
        if pair["fixed_controls_match"]
        and pair["baseline_live_integrity"]
        and pair["candidate_live_integrity"]
    ]
    baseline_completion = _rate(valid_pairs, "baseline_passed")
    candidate_completion = _rate(valid_pairs, "candidate_passed")
    aggregate = _aggregate_pair_metrics(valid_pairs)
    shadow_verified = any(
        run.get("status") == "pass"
        and _run_artifact_integrity(run)
        and int(run.get("metrics", {}).get("skill_shadow_plan_count", 0) or 0) >= 1
        for run in shadow_runs
    )
    fallback_verified = any(
        run.get("status") == "pass"
        and _run_artifact_integrity(run)
        and int(run.get("metrics", {}).get("skill_fallback_count", 0) or 0) >= 1
        and int(run.get("metrics", {}).get("skill_executed_count", 0) or 0) == 0
        for run in fallback_runs
    )
    advisory_verified = any(
        run.get("status") == "pass"
        and _run_artifact_integrity(run)
        and int(run.get("metrics", {}).get("skill_advisory_hint_count", 0) or 0) >= 1
        and int(run.get("metrics", {}).get("skill_executed_count", 0) or 0) == 0
        for run in advisory_runs
    )
    all_candidate_steps_verified = bool(valid_pairs) and all(
        pair["candidate_metrics"].get("candidate_steps_verified") is True
        for pair in valid_pairs
    )
    all_candidate_steps_reobserved = bool(valid_pairs) and all(
        pair["candidate_metrics"].get("candidate_steps_reobserved") is True
        for pair in valid_pairs
    )
    fixed_controls = len(valid_pairs) == len(pairs) and bool(valid_pairs)
    no_completion_regression = candidate_completion >= baseline_completion
    no_action_failure_regression = aggregate["candidate_failed_actions"] <= aggregate["baseline_failed_actions"]
    no_verifier_regression = aggregate["candidate_verifier_rejects"] <= aggregate["baseline_verifier_rejects"]
    no_progress_regression = aggregate["candidate_no_progress_loops"] <= aggregate["baseline_no_progress_loops"]
    minimum_evidence = (
        len(valid_pairs) >= 3
        and len(baseline_ids) >= 3
        and len(candidate_ids) >= 3
        and not set(baseline_ids).intersection(candidate_ids)
    )
    promotable = all((
        minimum_evidence,
        shadow_verified,
        advisory_verified,
        fallback_verified,
        fixed_controls,
        all_candidate_steps_verified,
        all_candidate_steps_reobserved,
        no_completion_regression,
        no_action_failure_regression,
        no_verifier_regression,
        no_progress_regression,
        all(pair["candidate_passed"] for pair in valid_pairs),
    ))
    report_id = f"paired:{skill_id}:{skill_version}"
    report = {
        "type": PAIRED_REPORT_TYPE,
        "schema_version": 1,
        "report_id": report_id,
        "claim": "self-learning mechanism under evaluation",
        "skill_id": skill_id,
        "skill_version": skill_version,
        "task_family": task_family,
        "single_target_skill": True,
        "pair_count": len(pairs),
        "valid_pair_count": len(valid_pairs),
        "baseline_session_ids": baseline_ids,
        "candidate_session_ids": candidate_ids,
        "shadow_session_ids": _unique(run.get("session_id") for run in shadow_runs),
        "advisory_session_ids": _unique(run.get("session_id") for run in advisory_runs),
        "fallback_session_ids": _unique(run.get("session_id") for run in fallback_runs),
        "baseline_completion_rate": baseline_completion,
        "candidate_completion_rate": candidate_completion,
        "shadow_verified": shadow_verified,
        "advisory_verified": advisory_verified,
        "fallback_verified": fallback_verified,
        "fixed_controls_match": fixed_controls,
        "live_minecraft_only": bool(valid_pairs) and all(
            pair.get("baseline_live_integrity") and pair.get("candidate_live_integrity")
            for pair in valid_pairs
        ),
        "candidate_steps_verified": all_candidate_steps_verified,
        "candidate_steps_reobserved": all_candidate_steps_reobserved,
        "no_completion_rate_regression": no_completion_regression,
        "no_action_failure_regression": no_action_failure_regression,
        "no_verifier_reject_regression": no_verifier_regression,
        "no_no_progress_regression": no_progress_regression,
        "aggregate_metrics": aggregate,
        "stable_efficiency_gain": _stable_efficiency_gain(valid_pairs),
        "decision": "promote_executable" if promotable else "retain_advisory",
        "readiness": "approved" if promotable else "review",
        "pairs": pairs,
        "errors": errors,
    }
    report["executable_promotion_gate"] = _promotion_gate(
        report,
        rollback_target=rollback_target,
        transfer_scope=transfer_scope,
    )
    return report


def build_runtime_default_gate(paired_report: dict, skill_name: str) -> dict:
    gate = paired_report.get("executable_promotion_gate", {})
    approved = gate.get("readiness") == "approved" and gate.get("decision") == "promote_executable"
    family = str(paired_report.get("task_family") or "")
    candidate = {
        "skill": skill_name,
        "skill_id": paired_report.get("skill_id", ""),
        "task_family": family,
        "candidate_readiness": "approved" if approved else "review",
        "decision": "allow_task_family_runtime_default" if approved else "keep_runtime_default_review_only",
        "promotion_gate_fingerprint": evidence_fingerprint(gate) if gate else "",
    }
    return {
        "type": RUNTIME_GATE_TYPE,
        "schema_version": 1,
        "required": True,
        "readiness": "approved" if approved else "review",
        "decision": "allow_task_family_runtime_default" if approved else "keep_runtime_default_review_only",
        "reason": "paired live executable evidence approved" if approved else "paired live evidence incomplete",
        "target_task_family": family,
        "approved_candidate_count": 1 if approved else 0,
        "review_candidate_count": 0 if approved else 1,
        "executable_promotion_gate_fingerprint": evidence_fingerprint(gate) if gate else "",
        "source_report_id": paired_report.get("report_id", ""),
        "candidates": [candidate],
    }


def build_heldout_transfer_report(
    baseline_path: str,
    candidate_path: str,
    skill_id: str,
    training_task_set: list[str],
    validation_task_set: list[str],
    heldout_task_set: list[str],
    unsupported_task_family: list[str],
    training_session_ids: Optional[list[str]] = None,
) -> tuple[dict, dict]:
    runs, errors = _load_typed_runs([baseline_path, candidate_path])
    baseline = next((run for run in runs if run.get("arm") == "baseline"), {})
    candidate = next((run for run in runs if run.get("arm") in {"candidate", "runtime"}), {})
    controls_match = bool(baseline and candidate and _fixed_controls_match(baseline, candidate, allow_goal_difference=False))
    distinct = bool(
        baseline.get("session_id")
        and candidate.get("session_id")
        and baseline.get("session_id") != candidate.get("session_id")
    )
    baseline_metrics = baseline.get("metrics", {})
    candidate_metrics = candidate.get("metrics", {})
    baseline_steps = int(baseline_metrics.get("environment_steps", 0) or 0)
    candidate_steps = int(candidate_metrics.get("environment_steps", 0) or 0)
    completion_gain = int(candidate.get("status") == "pass") - int(baseline.get("status") == "pass")
    efficiency_gain = baseline_steps - candidate_steps
    training_ids = _unique(training_session_ids or [])
    heldout_ids = _unique([baseline.get("session_id"), candidate.get("session_id")])
    overlap_count = len(set(training_ids).intersection(heldout_ids))
    positive_transfer = bool(
        controls_match
        and distinct
        and overlap_count == 0
        and _run_artifact_integrity(baseline)
        and _run_artifact_integrity(candidate)
        and candidate.get("status") == "pass"
        and completion_gain >= 0
        and efficiency_gain > 0
        and candidate_metrics.get("candidate_steps_verified") is True
    )
    report = {
        "type": TRANSFER_REPORT_TYPE,
        "schema_version": 1,
        "claim": "self-learning mechanism under evaluation",
        "skill_id": skill_id,
        "heldout": True,
        "training_task_set": list(training_task_set),
        "validation_task_set": list(validation_task_set),
        "heldout_transfer_task_set": list(heldout_task_set),
        "unsupported_task_family": list(unsupported_task_family),
        "training_session_ids": training_ids,
        "heldout_session_ids": heldout_ids,
        "training_heldout_overlap_count": overlap_count,
        "fixed_controls_match": controls_match,
        "baseline_status": baseline.get("status", "missing"),
        "candidate_status": candidate.get("status", "missing"),
        "completion_gain": completion_gain,
        "environment_step_gain": efficiency_gain,
        "positive_transfer": positive_transfer,
        "baseline": baseline,
        "candidate": candidate,
        "errors": errors,
    }
    gate = {
        "type": "task_stream_transfer_gate",
        "schema_version": 1,
        "target": f"skill:{skill_id}",
        "readiness": "approved" if positive_transfer else "review",
        "decision": "allow_candidate_promotion" if positive_transfer else "keep_candidate_review_only",
        "evidence_count": 1 if positive_transfer else 0,
        "regression_count": 0 if completion_gain >= 0 else 1,
        "ready_stream_count": 1 if positive_transfer else 0,
        "task_count": len(heldout_task_set),
        "average_generalization_gain": float(efficiency_gain) if controls_match else None,
        "thresholds": {"require_heldout": True},
        "heldout_source_session_ids": report["heldout_session_ids"],
        "training_heldout_overlap_count": overlap_count,
        "source_report_fingerprint": evidence_fingerprint(report),
    }
    return report, gate


def build_continual_learning_report(runtime_paths: Iterable[str]) -> dict:
    runs, errors = _load_typed_runs(runtime_paths)
    cases = []
    for run in runs:
        metrics = run.get("metrics", {})
        ready = bool(
            run.get("arm") == "runtime"
            and run.get("status") == "pass"
            and _run_artifact_integrity(run)
            and int(metrics.get("skill_selected_count", 0) or 0) >= 1
            and int(metrics.get("skill_completion_count", 0) or 0) >= 1
            and float(metrics.get("attribution_confidence", 0.0) or 0.0) >= 0.9
        )
        cases.append({
            "source_log": run.get("source_log", ""),
            "source_session_id": run.get("session_id", ""),
            "skill_id": run.get("skill_id", ""),
            "ready_for_continual_learning_review": ready,
            "completed_goal_count": 1 if run.get("status") == "pass" else 0,
            "memory_read_count": 0,
            "memory_write_count": 0,
            "skill_retrieval_count": int(metrics.get("skill_selected_count", 0) or 0),
            "skill_outcome_write_count": int(metrics.get("skill_outcome_count", 0) or 0),
            "progress_event_count": int(metrics.get("successful_actions", 0) or 0),
            "unbounded_context_cycle_count": 0,
            "attribution_confidence": float(metrics.get("attribution_confidence", 0.0) or 0.0),
        })
    return {
        "type": "continual_learning_report",
        "schema_version": 2,
        "claim": "self-learning mechanism under evaluation",
        "cases": cases,
        "errors": errors,
    }


def write_json(path: str, payload: dict) -> str:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    return path


def _apply_research_fixture(agent: Agent, setup: dict, fixture_profile: str) -> dict:
    if fixture_profile == "protocol_default":
        return {
            "profile": fixture_profile,
            "success": True,
            "verified": True,
            "expected_blocks": [],
            "command_results": [],
            "arbitrary_commands_allowed": False,
        }
    spawn = setup.get("after_state", {}).get("spawn_position", {})
    try:
        x = round(float(spawn["x"]))
        y = round(float(spawn["y"]))
        z = round(float(spawn["z"]))
    except (KeyError, TypeError, ValueError):
        return {
            "profile": fixture_profile,
            "success": False,
            "verified": False,
            "error": "spawn_position_required_for_research_fixture",
            "arbitrary_commands_allowed": False,
        }
    if fixture_profile == "gather_oak_near_v1":
        target_x, target_z = x + 3, z
    else:
        target_x, target_z = x - 2, z + 2
    expected = [
        {"name": "oak_log", "position": {"x": target_x, "y": y + offset, "z": target_z}}
        for offset in range(3)
    ]
    command = f"/fill {target_x} {y} {target_z} {target_x} {y + 2} {target_z} minecraft:oak_log replace"
    result = agent.bot.chat(command)
    time.sleep(1.2)
    return {
        "profile": fixture_profile,
        "success": bool(result.get("success")),
        "verified": False,
        "expected_blocks": expected,
        "command_results": [{"kind": "allowlisted_oak_fixture", "success": bool(result.get("success"))}],
        "arbitrary_commands_allowed": False,
        "error": str(result.get("error") or ""),
    }


def _verify_research_fixture(research_setup: dict, observation: dict) -> dict:
    expected = research_setup.get("expected_blocks", [])
    if not expected:
        return {**research_setup, "verified": research_setup.get("success") is True}
    observed = set()
    for key in ("nearby_blocks", "trees_found", "visible_blocks", "grounded_resources"):
        values = observation.get(key, []) if isinstance(observation, dict) else []
        if isinstance(values, dict):
            values = list(values.values())
        for item in values if isinstance(values, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("block") or "").lower()
            position = item.get("position", {}) if isinstance(item.get("position"), dict) else {}
            if name and all(axis in position for axis in ("x", "y", "z")):
                observed.add((
                    name,
                    round(float(position["x"])),
                    round(float(position["y"])),
                    round(float(position["z"])),
                ))
    missing = []
    for item in expected:
        position = item["position"]
        key = (item["name"], position["x"], position["y"], position["z"])
        if key not in observed:
            missing.append(item)
    return {
        **research_setup,
        "verified": research_setup.get("success") is True and not missing,
        "observed_expected_block_count": len(expected) - len(missing),
        "missing_expected_blocks": missing,
    }


def _assess_live_run(**kwargs) -> dict:
    profile = kwargs["profile"]
    task = kwargs["task"]
    arm = str(kwargs["arm"])
    events = kwargs["events"]
    result = kwargs["result"]
    setup = kwargs["setup"]
    research_setup = kwargs["research_setup"]
    final_inventory = kwargs["final_inventory"]
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    learning = summary.get("skill_learning_metrics", {}) if isinstance(summary.get("skill_learning_metrics"), dict) else {}
    action_events = [event for event in events if event.get("type") == "action"]
    action_verifications = [event for event in events if event.get("type") == "action_verification"]
    fault_events = [event for event in events if event.get("type") == "skill_learning_fault_injection"]
    skill_outcomes = [event for event in events if event.get("type") == "skill_execution_outcome"]
    extraction_events = [event for event in events if event.get("type") == "skill_candidate_extraction"]
    skill_actions = []
    successful_actions = 0
    failed_actions = 0
    navigation_failures = 0
    replan_count = 0
    for event in action_events:
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
        action_result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
        success = action_result.get("success") is True
        successful_actions += int(success)
        failed_actions += int(not success)
        if action.get("type") in {"move_to", "walk_to"} and (
            not success or action_result.get("reached") is not True
        ):
            navigation_failures += 1
        if action_result.get("requires_replan") is True:
            replan_count += 1
        if isinstance(action.get("skill_context"), dict) and action["skill_context"].get("skill_id"):
            skill_actions.append(data)
    verifier_rejects = 0
    for event in action_verifications:
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        verification = data.get("verification", {}) if isinstance(data.get("verification"), dict) else {}
        verifier_rejects += int(str(verification.get("status") or "").lower() == "reject")
    criteria_verified = all(
        int(final_inventory.get(item, 0) or 0) >= int(count or 0)
        for item, count in kwargs["success_criteria"].items()
    )
    goal_verified = bool(result.get("completed") and result.get("termination_reason") == "goal_verified")
    goal_verifier_event = any(
        event.get("type") == "goal_verification"
        and isinstance(event.get("data"), dict)
        and (event["data"].get("achieved") is True or event["data"].get("status") == "achieved")
        for event in events
    )
    steps_verified = bool(skill_actions) and all(
        isinstance(data.get("result", {}).get("action_verification"), dict)
        and str(data["result"]["action_verification"].get("status") or "").lower() != "reject"
        for data in skill_actions
    )
    steps_reobserved = bool(skill_actions) and all(
        isinstance(data.get("pre_observation"), dict)
        and bool(data.get("pre_observation"))
        and isinstance(data.get("post_observation"), dict)
        and bool(data.get("post_observation"))
        for data in skill_actions
    )
    checks = {
        "live_connection": True,
        "reset_verified": setup.get("success") is True,
        "research_fixture_verified": research_setup.get("verified") is True,
        "protocol_match": setup.get("protocol_sha256") == M1_PROTOCOL_SHA256,
        "fixed_planner": profile.get("force_rule_planner") is True,
        "action_verifier_enforced": profile.get("action_verifier_enforced") is True,
        "action_controller_enforced": profile.get("action_controller_enforced") is True,
        "goal_verifier_enforced": profile.get("goal_verifier_enforced") is True,
        "goal_verifier_achieved": goal_verified and goal_verifier_event,
        "success_criteria_verified": criteria_verified,
        "no_death_or_safety_event": not any(
            event.get("type") in {"death", "safety_violation"} for event in events
        ),
    }
    if arm == "baseline":
        checks.update({
            "target_skill_disabled": profile.get("skill_execution_mode") == "off",
            "no_skill_selected": int(learning.get("skill_selected_count", 0) or 0) == 0,
            "no_skill_executed": int(learning.get("skill_executed_count", 0) or 0) == 0,
        })
    elif arm == "shadow":
        checks.update({
            "shadow_plan_observed": int(learning.get("skill_shadow_plan_count", 0) or 0) >= 1,
            "shadow_no_runtime_selection": int(learning.get("skill_selected_count", 0) or 0) == 0,
            "shadow_no_execution": int(learning.get("skill_executed_count", 0) or 0) == 0,
        })
    elif arm == "advisory":
        checks.update({
            "advisory_hint_observed": int(learning.get("skill_advisory_hint_count", 0) or 0) >= 1,
            "advisory_no_runtime_selection": int(learning.get("skill_selected_count", 0) or 0) == 0,
            "advisory_no_direct_execution": int(learning.get("skill_executed_count", 0) or 0) == 0,
        })
    elif arm == "fallback":
        checks.update({
            "fallback_observed": int(learning.get("skill_fallback_count", 0) or 0) >= 1,
            "inapplicable_skill_not_executed": int(learning.get("skill_executed_count", 0) or 0) == 0,
        })
    elif arm == "fault":
        outcome_data = (
            skill_outcomes[-1].get("data", {})
            if skill_outcomes and isinstance(skill_outcomes[-1].get("data"), dict)
            else {}
        )
        checks.update({
            "controlled_fault_applied": len(fault_events) == 1,
            "single_skill_selected": int(learning.get("skill_selected_count", 0) or 0) == 1,
            "skill_action_failed": int(learning.get("skill_failed_action_count", 0) or 0) >= 1,
            "skill_not_completed": int(learning.get("skill_completion_count", 0) or 0) == 0,
            "verifier_rejection_observed": verifier_rejects >= 1,
            "ordinary_planner_recovered": goal_verified and criteria_verified,
            "fallback_observed": int(learning.get("skill_fallback_count", 0) or 0) >= 1,
            "failure_attributed": (
                outcome_data.get("success") is False
                and outcome_data.get("failure_type") in {
                    "skill_error",
                    "precondition_misclassification",
                    "postcondition_failure",
                }
                and float(outcome_data.get("attribution_confidence", 0.0) or 0.0) >= 0.9
            ),
            "fault_cannot_promote": all(
                event.get("data", {}).get("counts_toward_promotion") is False
                for event in fault_events
                if isinstance(event.get("data"), dict)
            ),
        })
    elif arm == "extraction":
        goal_end_indexes = [index for index, event in enumerate(events) if event.get("type") == "goal_end"]
        extraction_indexes = [index for index, event in enumerate(events) if event.get("type") == "skill_candidate_extraction"]
        extracted_count = sum(
            int(event.get("data", {}).get("candidate_count", 0) or 0)
            for event in extraction_events
            if isinstance(event.get("data"), dict)
        )
        queued_count = sum(
            len(event.get("data", {}).get("queued_candidate_ids", []) or [])
            for event in extraction_events
            if isinstance(event.get("data"), dict)
        )
        deduplicated_count = sum(
            int(event.get("data", {}).get("deduplicated_candidate_count", 0) or 0)
            for event in extraction_events
            if isinstance(event.get("data"), dict)
        )
        queue_candidate_count = max(
            (
                int(event.get("data", {}).get("queue_candidate_count", 0) or 0)
                for event in extraction_events
                if isinstance(event.get("data"), dict)
            ),
            default=0,
        )
        checks.update({
            "candidate_extraction_enabled": profile.get("candidate_extraction") is True,
            "source_episode_isolated": any(
                event.get("type") == "benchmark_runtime_profile"
                and event.get("data", {}).get("isolated") is True
                for event in events
                if isinstance(event.get("data"), dict)
            ),
            "goal_end_precedes_extraction": bool(
                goal_end_indexes and extraction_indexes and min(extraction_indexes) > max(goal_end_indexes)
            ),
            "candidate_extracted": extracted_count >= 1,
            "durable_queue_write_recorded": queued_count >= 1,
            "durable_queue_unique_by_template": bool(extraction_events) and all(
                event.get("data", {}).get("queue_dedupe_key_unique") is True
                for event in extraction_events
                if isinstance(event.get("data"), dict)
            ),
            "episode_result_unaffected": goal_verified and criteria_verified,
            "no_skill_selected": int(learning.get("skill_selected_count", 0) or 0) == 0,
            "no_skill_executed": int(learning.get("skill_executed_count", 0) or 0) == 0,
        })
    else:
        checks.update({
            "single_skill_selected": int(learning.get("skill_selected_count", 0) or 0) == 1,
            "skill_executed": int(learning.get("skill_executed_count", 0) or 0) >= 1,
            "skill_completed": int(learning.get("skill_completion_count", 0) or 0) >= 1,
            "skill_steps_verified": steps_verified,
            "skill_steps_reobserved": steps_reobserved,
            "high_confidence_attribution": float(learning.get("skill_attribution_confidence", 0.0) or 0.0) >= 0.9,
        })
    session_id = str(summary.get("session_id") or "")
    source_log = str(summary.get("log_path") or "")
    report = {
        "type": LIVE_RUN_TYPE,
        "schema_version": 1,
        "run_id": f"{kwargs['experiment_id']}:{arm}:{session_id}",
        "experiment_id": kwargs["experiment_id"],
        "pair_id": kwargs["pair_id"],
        "replicate_id": kwargs["replicate_id"],
        "arm": arm,
        "heldout": bool(kwargs["heldout"]),
        "fault_profile": str(kwargs.get("fault_profile") or ""),
        "controlled_failure_only": arm == "fault",
        "skill_id": kwargs["skill_id"],
        "task_id": task.id,
        "goal": kwargs["goal"],
        "success_criteria": kwargs["success_criteria"],
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "session_id": session_id,
        "source_log": source_log,
        "source_log_sha256": _file_sha256(source_log),
        "environment_id": str(setup.get("level_name") or setup.get("episode_id") or ""),
        "world_seed": str(setup.get("seed") or ""),
        "protocol_sha256": setup.get("protocol_sha256", ""),
        "control_fingerprint": _control_fingerprint(
            task.id,
            kwargs["goal"],
            kwargs["success_criteria"],
            setup,
            research_setup,
            kwargs["initial_observation"],
        ),
        "runtime_profile": profile,
        "setup_evidence": setup,
        "research_setup_evidence": research_setup,
        "initial_observation_fingerprint": evidence_fingerprint(_bounded_observation(kwargs["initial_observation"])),
        "final_inventory": final_inventory,
        "termination_reason": result.get("termination_reason", ""),
        "lifecycle_status": (
            skill_outcomes[-1].get("data", {}).get("lifecycle_outcome", {}).get("status", "")
            if skill_outcomes
            and isinstance(skill_outcomes[-1].get("data"), dict)
            and isinstance(skill_outcomes[-1].get("data", {}).get("lifecycle_outcome"), dict)
            else ""
        ),
        "metrics": {
            "task_completion": int(goal_verified and criteria_verified),
            "environment_steps": int(result.get("cycles", 0) or 0),
            "successful_actions": successful_actions,
            "failed_actions": failed_actions,
            "navigation_failures": navigation_failures,
            "verifier_rejects": verifier_rejects,
            "replans": replan_count,
            "planner_calls": sum(1 for event in events if event.get("type") == "plan"),
            "token_usage": _token_usage(events),
            "wall_clock_latency_s": round(float(kwargs["duration_s"]), 3),
            "inventory_progress": _inventory_progress(setup, final_inventory),
            "death_or_safety_events": sum(
                1 for event in events if event.get("type") in {"death", "safety_violation"}
            ),
            "no_progress_loops": sum(
                1 for event in events if event.get("type") in {"empty_plan", "blocked_plan"}
            ),
            "skill_selected_count": int(learning.get("skill_selected_count", 0) or 0),
            "skill_executed_count": int(learning.get("skill_executed_count", 0) or 0),
            "skill_completion_count": int(learning.get("skill_completion_count", 0) or 0),
            "skill_outcome_count": int(learning.get("skill_outcome_count", 0) or 0),
            "skill_fallback_count": int(learning.get("skill_fallback_count", 0) or 0),
            "skill_shadow_plan_count": int(learning.get("skill_shadow_plan_count", 0) or 0),
            "skill_advisory_hint_count": int(learning.get("skill_advisory_hint_count", 0) or 0),
            "attribution_confidence": float(learning.get("skill_attribution_confidence", 0.0) or 0.0),
            "candidate_steps_verified": steps_verified if skill_actions else arm in {"baseline", "shadow", "advisory", "fallback"},
            "candidate_steps_reobserved": steps_reobserved if skill_actions else arm in {"baseline", "shadow", "advisory", "fallback"},
            "action_verification_event_count": len(action_verifications),
            "skill_candidate_extraction_event_count": len(extraction_events),
            "deduplicated_candidate_count": deduplicated_count if arm == "extraction" else 0,
            "queue_candidate_count": queue_candidate_count if arm == "extraction" else 0,
        },
    }
    return report


def _promotion_gate(report: dict, rollback_target: str, transfer_scope: dict) -> dict:
    approved = report.get("decision") == "promote_executable" and not report.get("errors")
    return {
        "type": EXECUTABLE_PROMOTION_GATE_TYPE,
        "schema_version": 1,
        "skill_id": report.get("skill_id", ""),
        "skill_version": report.get("skill_version", ""),
        "readiness": "approved" if approved else "review",
        "decision": "promote_executable" if approved else "retain_advisory",
        "thresholds": {"min_paired_live_sessions": 3},
        "paired_live_session_count": int(report.get("valid_pair_count", 0) or 0),
        "baseline_session_ids": list(report.get("baseline_session_ids", [])),
        "candidate_session_ids": list(report.get("candidate_session_ids", [])),
        "single_target_skill": report.get("single_target_skill") is True,
        "shadow_plan_verified": report.get("shadow_verified") is True,
        "advisory_hint_verified": report.get("advisory_verified") is True,
        "fixed_controls_match": report.get("fixed_controls_match") is True,
        "live_minecraft_only": report.get("live_minecraft_only") is True,
        "goal_verifier_enforced": True,
        "action_verifier_enforced": True,
        "action_controller_enforced": True,
        "candidate_steps_reobserved": report.get("candidate_steps_reobserved") is True,
        "candidate_steps_verified": report.get("candidate_steps_verified") is True,
        "fallback_verified": report.get("fallback_verified") is True,
        "no_completion_rate_regression": report.get("no_completion_rate_regression") is True,
        "no_action_failure_regression": report.get("no_action_failure_regression") is True,
        "no_verifier_reject_regression": report.get("no_verifier_reject_regression") is True,
        "no_no_progress_regression": report.get("no_no_progress_regression") is True,
        "rollback_path_present": bool(rollback_target),
        "rollback_target": rollback_target,
        "transfer_scope": dict(transfer_scope or {}),
        "synthetic_evidence_count": 0,
        "paired_report_fingerprint": evidence_fingerprint({
            key: value for key, value in report.items() if key != "executable_promotion_gate"
        }),
    }


def _failed_live_run(
    profile: dict,
    task: Any,
    arm: str,
    skill_id: str,
    experiment_id: str,
    pair_id: str,
    replicate_id: str,
    heldout: bool,
    goal: str,
    success_criteria: dict,
    agent: Agent,
    started: float,
    error: str,
    setup: Optional[dict] = None,
) -> dict:
    summary = agent.session_logger.get_summary()
    session_id = str(summary.get("session_id") or "")
    return {
        "type": LIVE_RUN_TYPE,
        "schema_version": 1,
        "run_id": f"{experiment_id}:{arm}:{session_id}",
        "experiment_id": experiment_id,
        "pair_id": pair_id,
        "replicate_id": replicate_id,
        "arm": arm,
        "heldout": heldout,
        "skill_id": skill_id,
        "task_id": task.id,
        "goal": goal,
        "success_criteria": success_criteria,
        "status": "error",
        "error": error,
        "checks": {"live_connection_and_reset": False},
        "failed_checks": ["live_connection_and_reset"],
        "session_id": session_id,
        "source_log": summary.get("log_path", ""),
        "source_log_sha256": _file_sha256(summary.get("log_path", "")),
        "runtime_profile": profile,
        "setup_evidence": setup or {},
        "duration_s": round(time.time() - started, 3),
        "metrics": {},
    }


def _run_artifact_integrity(run: dict) -> bool:
    if not isinstance(run, dict) or run.get("type") != LIVE_RUN_TYPE:
        return False
    profile = run.get("runtime_profile", {}) if isinstance(run.get("runtime_profile"), dict) else {}
    setup = run.get("setup_evidence", {}) if isinstance(run.get("setup_evidence"), dict) else {}
    research_setup = run.get("research_setup_evidence", {}) if isinstance(run.get("research_setup_evidence"), dict) else {}
    checks = run.get("checks", {}) if isinstance(run.get("checks"), dict) else {}
    source_log = str(run.get("source_log") or "")
    expected_hash = str(run.get("source_log_sha256") or "")
    return bool(
        run.get("status") == "pass"
        and run.get("session_id")
        and run.get("environment_id")
        and profile.get("evidence_kind") == "live_minecraft_skill_research"
        and profile.get("counts_toward_m1_acceptance") is False
        and profile.get("action_verifier_enforced") is True
        and profile.get("action_controller_enforced") is True
        and profile.get("goal_verifier_enforced") is True
        and setup.get("success") is True
        and setup.get("protocol_sha256") == M1_PROTOCOL_SHA256
        and research_setup.get("verified") is True
        and checks
        and all(value is True for value in checks.values())
        and source_log
        and os.path.isfile(source_log)
        and expected_hash
        and run.get("source_log_finalized_before_hash") is True
        and _file_sha256(source_log) == expected_hash
    )


def _fixed_controls_match(left: dict, right: dict, allow_goal_difference: bool = False) -> bool:
    left_profile = left.get("runtime_profile", {})
    right_profile = right.get("runtime_profile", {})
    fixed_profile_keys = (
        "protocol_sha256",
        "world_seed",
        "task_id",
        "agent_id",
        "planner_id",
        "action_backend_id",
        "verifier_id",
        "force_rule_planner",
        "action_verifier_enforced",
        "action_controller_enforced",
        "goal_verifier_enforced",
        "memory_persistence",
        "policy_skills",
        "vision",
        "candidate_extraction",
        "research_fixture_profile",
    )
    if any(left_profile.get(key) != right_profile.get(key) for key in fixed_profile_keys):
        return False
    if left.get("world_seed") != right.get("world_seed"):
        return False
    if left.get("protocol_sha256") != right.get("protocol_sha256"):
        return False
    if _controlled_setup_fingerprint(left) != _controlled_setup_fingerprint(right):
        return False
    if left.get("success_criteria") != right.get("success_criteria"):
        return False
    if not allow_goal_difference and left.get("goal") != right.get("goal"):
        return False
    return True


def _metric_deltas(baseline: dict, candidate: dict) -> dict:
    lower_is_better = (
        "environment_steps",
        "failed_actions",
        "navigation_failures",
        "verifier_rejects",
        "replans",
        "planner_calls",
        "token_usage",
        "wall_clock_latency_s",
        "no_progress_loops",
    )
    return {
        key: round(float(baseline.get(key, 0) or 0) - float(candidate.get(key, 0) or 0), 4)
        for key in lower_is_better
    }


def _aggregate_pair_metrics(pairs: list[dict]) -> dict:
    totals = {
        "baseline_failed_actions": 0,
        "candidate_failed_actions": 0,
        "baseline_verifier_rejects": 0,
        "candidate_verifier_rejects": 0,
        "baseline_no_progress_loops": 0,
        "candidate_no_progress_loops": 0,
        "baseline_environment_steps": 0,
        "candidate_environment_steps": 0,
        "baseline_planner_calls": 0,
        "candidate_planner_calls": 0,
    }
    for pair in pairs:
        baseline = pair["baseline_metrics"]
        candidate = pair["candidate_metrics"]
        for suffix, key in (
            ("failed_actions", "failed_actions"),
            ("verifier_rejects", "verifier_rejects"),
            ("no_progress_loops", "no_progress_loops"),
            ("environment_steps", "environment_steps"),
            ("planner_calls", "planner_calls"),
        ):
            totals[f"baseline_{suffix}"] += int(baseline.get(key, 0) or 0)
            totals[f"candidate_{suffix}"] += int(candidate.get(key, 0) or 0)
    totals["environment_step_gain"] = totals["baseline_environment_steps"] - totals["candidate_environment_steps"]
    totals["planner_call_gain"] = totals["baseline_planner_calls"] - totals["candidate_planner_calls"]
    return totals


def _stable_efficiency_gain(pairs: list[dict]) -> dict:
    metrics = ("environment_steps", "planner_calls", "token_usage", "wall_clock_latency_s")
    gains = {}
    for metric in metrics:
        values = [float(pair["deltas"].get(metric, 0.0) or 0.0) for pair in pairs]
        gains[metric] = {
            "positive_pair_count": sum(1 for value in values if value > 0),
            "nonnegative_pair_count": sum(1 for value in values if value >= 0),
            "mean_gain": round(sum(values) / len(values), 4) if values else 0.0,
            "stable_positive": bool(values) and all(value > 0 for value in values),
        }
    return gains


def _task(task_id: str):
    normalized = str(task_id or "").strip().upper()
    task = next((item for item in M1_BENCHMARKS if item.id == normalized), None)
    if task is None:
        raise ValueError(f"unsupported controlled task: {task_id}")
    return task


def _load_typed_runs(paths: Iterable[str]) -> tuple[list[dict], list[str]]:
    runs = []
    errors = []
    seen = set()
    for raw_path in paths or []:
        path = str(raw_path or "")
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict) or payload.get("type") != LIVE_RUN_TYPE:
                raise ValueError("expected skill_learning_live_run")
            runs.append(payload)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return runs, errors


def _control_fingerprint(
    task_id: str,
    goal: str,
    criteria: dict,
    setup: dict,
    research_setup: dict,
    observation: dict,
) -> str:
    payload = {
        "task_id": task_id,
        "goal": goal,
        "criteria": criteria,
        "seed": setup.get("seed"),
        "protocol_sha256": setup.get("protocol_sha256"),
        "initial_inventory": setup.get("expected", {}).get("initial_inventory", {}),
        "initial_blocks": setup.get("expected", {}).get("initial_blocks", []),
        "reset_after_state": _stable_reset_state(setup),
        "research_fixture_profile": research_setup.get("profile", "protocol_default"),
        "research_fixture_blocks": research_setup.get("expected_blocks", []),
        "near_observation": _near_control_observation(observation),
    }
    return evidence_fingerprint(payload)


def _controlled_setup_fingerprint(run: dict) -> str:
    setup = run.get("setup_evidence", {}) if isinstance(run.get("setup_evidence"), dict) else {}
    research = run.get("research_setup_evidence", {}) if isinstance(run.get("research_setup_evidence"), dict) else {}
    profile = run.get("runtime_profile", {}) if isinstance(run.get("runtime_profile"), dict) else {}
    payload = {
        "task_id": run.get("task_id"),
        "goal": run.get("goal"),
        "success_criteria": run.get("success_criteria", {}),
        "world_seed": run.get("world_seed"),
        "protocol_sha256": run.get("protocol_sha256"),
        "reset_expected": setup.get("expected", {}),
        "reset_after_state": _stable_reset_state(setup),
        "research_fixture_profile": profile.get("research_fixture_profile", research.get("profile", "")),
        "research_fixture_blocks": research.get("expected_blocks", []),
        "research_fixture_verified": research.get("verified") is True,
    }
    return evidence_fingerprint(payload)


def _stable_reset_state(setup: dict) -> dict:
    state = setup.get("after_state", {}) if isinstance(setup.get("after_state"), dict) else {}
    return {
        key: state.get(key)
        for key in (
            "position",
            "spawn_position",
            "health",
            "food",
            "inventory",
            "game_mode",
            "difficulty",
            "dimension",
            "weather",
            "fixture",
        )
    }


def _near_control_observation(observation: dict, radius: float = 8.0) -> dict:
    if not isinstance(observation, dict):
        return {}
    result = {
        "position": observation.get("position", {}),
        "inventory": observation.get("inventory", {}),
    }
    for key in ("trees_found", "nearby_blocks", "grounded_resources", "visible_blocks", "resources"):
        values = observation.get(key, [])
        if isinstance(values, dict):
            values = list(values.values())
        normalized = []
        for item in values if isinstance(values, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                distance = float(item.get("distance", 0.0))
            except (TypeError, ValueError):
                distance = 0.0
            if distance > radius:
                continue
            position = item.get("position", {}) if isinstance(item.get("position"), dict) else {}
            normalized.append({
                "name": str(item.get("name") or item.get("block") or item.get("type") or ""),
                "position": {axis: position.get(axis) for axis in ("x", "y", "z")},
            })
        if normalized:
            result[key] = sorted(
                normalized,
                key=lambda item: (
                    item["name"],
                    str(item["position"].get("x")),
                    str(item["position"].get("y")),
                    str(item["position"].get("z")),
                ),
            )
    return result


def _bounded_observation(observation: dict) -> dict:
    if not isinstance(observation, dict):
        return {}
    result = {
        "position": observation.get("position", {}),
        "inventory": observation.get("inventory", {}),
    }
    for key in ("trees_found", "nearby_blocks", "grounded_resources", "visible_blocks", "resources"):
        value = observation.get(key)
        if isinstance(value, list):
            result[key] = value[:64]
        elif isinstance(value, dict):
            result[key] = value
    return result


def _inventory_counts(items: Any) -> dict:
    result = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name:
            result[name] = result.get(name, 0) + int(item.get("count", 1) or 1)
    return result


def _inventory_progress(setup: dict, final_inventory: dict) -> dict:
    initial = setup.get("expected", {}).get("initial_inventory", {})
    return {
        item: int(final_inventory.get(item, 0) or 0) - int(initial.get(item, 0) or 0)
        for item in sorted(set(initial) | set(final_inventory))
        if int(final_inventory.get(item, 0) or 0) != int(initial.get(item, 0) or 0)
    }


def _token_usage(events: list[dict]) -> int:
    total = 0
    for event in events:
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        usage = data.get("usage", {}) if isinstance(data.get("usage"), dict) else {}
        total += int(usage.get("total_tokens", data.get("token_usage", 0)) or 0)
    return total


def _file_sha256(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def _rate(items: list[dict], key: str) -> float:
    return round(sum(1 for item in items if item.get(key) is True) / len(items), 6) if items else 0.0
