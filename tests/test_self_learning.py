"""Offline-only contract tests for the self-learning mechanism under evaluation."""

import hashlib
import json
import os
import tempfile

from singularity.core.config import Config
from singularity.core.agent import Agent
from singularity.action.verifier import ActionVerifier
from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor
from singularity.core.skill_learning import (
    EVALUATION_AUTHORIZATION_TYPE,
    evaluation_authorization_issues,
    executable_promotion_gate_issues,
)
from singularity.core.skill_library import SkillLibrary
from singularity.core.skill_runtime import (
    DSL_VERSION,
    build_bounded_skill_plan,
    evaluate_skill_postconditions,
    evaluate_skill_preconditions,
    validate_bounded_action_template,
)
from singularity.evaluation.capability_evidence import _build_m3_live_evidence
from singularity.evaluation.m1_protocol import PROTOCOL_SHA256 as M1_PROTOCOL_SHA256
from singularity.evaluation.skill_learning_experiment import (
    LIVE_RUN_TYPE,
    build_skill_research_config,
    build_continual_learning_report,
    build_heldout_transfer_report,
    build_paired_ablation_report,
    build_runtime_default_gate,
    write_json,
)


def _gather_template():
    return {
        "dsl_version": DSL_VERSION,
        "max_actions": 6,
        "parameters": {
            "quantity": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
        },
        "phases": [{
            "id": "acquire_target",
            "op": "acquire_block_drop",
            "source_blocks": ["oak_log"],
            "target_item": "oak_log",
            "target_count": {"parameter": "quantity", "default": 3},
            "selector": "nearest_observed",
            "search_radius": 32,
            "interaction_range": 4.5,
            "navigation_tolerance": 1.75,
        }],
    }


def _live_source_events(session_id: str, environment_id: str):
    events = [
        {
            "session": session_id,
            "type": "benchmark_runtime_profile",
            "data": {
                "isolated": True,
                "protocol_sha256": M1_PROTOCOL_SHA256,
                "verifier_id": "goal-action-verifier-v1",
            },
        },
        {
            "session": session_id,
            "type": "benchmark_reset",
            "data": {
                "success": True,
                "level_name": environment_id,
                "episode_id": environment_id,
                "seed": "12345",
                "protocol_sha256": M1_PROTOCOL_SHA256,
                "server_jar_sha256": "test-server-hash",
            },
        },
        {"session": session_id, "type": "goal_start", "data": {"goal": "Gather 3 oak logs"}},
        {
            "session": session_id,
            "type": "observation",
            "data": {
                "position": {"x": 0, "y": 64, "z": 0},
                "inventory": {},
                "trees_found": [{"name": "oak_log", "position": {"x": 2, "y": 64, "z": 0}}],
            },
        },
        {
            "session": session_id,
            "type": "action",
            "data": {
                "action": {"type": "move_to", "parameters": {"x": 2, "z": 0}},
                "result": {"success": True, "reached": True},
                "pre_observation": {"position": {"x": 0, "y": 64, "z": 0}, "inventory": {}},
                "post_observation": {"position": {"x": 1.5, "y": 64, "z": 0}, "inventory": {}},
            },
        },
    ]
    for index in range(3):
        events.append({
            "session": session_id,
            "type": "action",
            "data": {
                "action": {
                    "type": "dig",
                    "parameters": {"block": "oak_log", "x": 2, "y": 64 + index, "z": 0},
                },
                "result": {"success": True, "block_removed": True},
                "pre_observation": {
                    "position": {"x": 1.5, "y": 64, "z": 0},
                    "inventory": {"oak_log": index} if index else {},
                },
                "post_observation": {
                    "position": {"x": 1.5, "y": 64, "z": 0},
                    "inventory": {"oak_log": index + 1},
                },
            },
        })
    events.extend([
        {
            "session": session_id,
            "type": "goal_verification",
            "data": {
                "goal": "Gather 3 oak logs",
                "achieved": True,
                "status": "achieved",
                "target_inventory": {"oak_log": 3},
                "inventory_delta": {"oak_log": 3},
                "evidence": ["inventory delta gained 3 oak_log"],
                "context": {"accepted": True, "acceptance_reason": "deterministic_evidence_satisfied"},
            },
        },
        {
            "session": session_id,
            "type": "goal_end",
            "data": {
                "goal": "Gather 3 oak logs",
                "result": {"completed": True, "termination_reason": "goal_verified"},
            },
        },
    ])
    return events


def test_candidate_extraction_dedup_and_provenance():
    tmpdir = tempfile.mkdtemp()
    library = SkillLibrary(os.path.join(tmpdir, "skills"), persist=True)
    extractor = SkillExtractor(library, auto_promote=False)
    queue = SkillCandidateQueue(os.path.join(tmpdir, "skill_candidates.jsonl"))

    for index in range(3):
        events = _live_source_events(f"session-{index}", f"environment-{index}")
        candidate = extractor.extract_skill_candidates_from_events(events, f"session-{index}.jsonl")[0]
        queued = queue.enqueue(candidate)
    queue.enqueue(extractor.extract_skill_candidates_from_events(
        _live_source_events("session-0", "environment-0"),
        "session-0-duplicate.jsonl",
    )[0])

    assert len(queue.all()) == 1
    queued = queue.all()[0]
    assert queued.skill_id == "learned:gather_wood"
    assert queued.source_session_ids == ["session-0", "session-1", "session-2"]
    assert queued.source_environment_ids == ["environment-0", "environment-1", "environment-2"]
    assert queued.success_count == 3
    assert queued.provenance["sources"][0]["source_trace_sha256"]
    report = extractor.validate_candidate_for_promotion(queued)
    assert report.decision == "promote_advisory", report.to_dict()
    queued.signals["promotion_report"] = report.to_dict()
    skill = extractor.approve_candidate(queued)
    assert skill is not None
    assert skill.status == "advisory"
    assert skill.source_session_ids == queued.source_session_ids
    queue.save()

    legacy_duplicate = extractor.extract_skill_candidates_from_events(
        _live_source_events("session-3", "environment-3"),
        "session-3.jsonl",
    )[0]
    with open(queue.path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(legacy_duplicate.__dict__, default=str) + "\n")
    reloaded = SkillCandidateQueue(queue.path)
    assert len(reloaded.all()) == 1
    canonical = reloaded.all()[0]
    assert canonical.id == queued.id
    assert canonical.status == "advisory"
    assert canonical.review_status == "approved"
    assert canonical.source_session_ids == ["session-0", "session-1", "session-2", "session-3"]
    assert legacy_duplicate.id in canonical.signals["merged_candidate_ids"]

    post_approval = extractor.extract_skill_candidates_from_events(
        _live_source_events("session-4", "environment-4"),
        "session-4.jsonl",
    )[0]
    merged = reloaded.enqueue(post_approval)
    assert merged.id == queued.id
    assert len(reloaded.all()) == 1
    assert merged.source_session_ids[-1] == "session-4"

    merged.status = "quarantined"
    reloaded.save()
    post_quarantine = extractor.extract_skill_candidates_from_events(
        _live_source_events("session-5", "environment-5"),
        "session-5.jsonl",
    )[0]
    quarantined = reloaded.enqueue(post_quarantine)
    assert quarantined.id == queued.id
    assert quarantined.status == "quarantined"
    assert len(reloaded.all()) == 1
    print("PASS: candidate identity remains unique across approval, reload, later episodes, and quarantine")


def test_typed_schema_preconditions_postconditions_and_fallback():
    valid = validate_bounded_action_template(_gather_template())
    assert valid.valid
    unsafe = validate_bounded_action_template({
        **_gather_template(),
        "shell": "rm -rf .",
    })
    assert not unsafe.valid
    assert any(issue.startswith("forbidden_executable_field") for issue in unsafe.issues)

    library = SkillLibrary(tempfile.mkdtemp(), persist=False)
    skill = library.create_skill(
        "learned_gather_wood",
        "Gather observed oak logs",
        json.dumps(_gather_template()),
        persist=False,
        skill_id="learned:gather_wood",
        status="advisory",
        task_family="gathering",
        required_inventory=[{"item": "wooden_axe", "count": 1}],
        postconditions={"inventory": {"oak_log": 3}},
        bounded_action_template=_gather_template(),
        transfer_scope={"task_family": "gathering"},
    )
    assert evaluate_skill_preconditions(skill, {"inventory": {}}) == ["inventory:wooden_axe>=1"]
    assert evaluate_skill_preconditions(skill, {"inventory": {"wooden_axe": 1}}) == []
    met, missing = evaluate_skill_postconditions(skill, {"inventory": {"oak_log": 2}})
    assert not met and missing == ["inventory:oak_log>=3"]
    met, missing = evaluate_skill_postconditions(skill, {"inventory": {"oak_log": 3}})
    assert met and not missing
    fallback = build_bounded_skill_plan(
        skill,
        "Gather 3 oak logs",
        {"inventory": {"wooden_axe": 1}, "position": {"x": 0, "y": 64, "z": 0}},
    )
    assert fallback["status"] == "fallback"
    assert fallback["fallback_reason"] == "required_observation_missing"
    heldout = build_bounded_skill_plan(
        skill,
        "Gather 2 oak logs",
        {
            "inventory": {"wooden_axe": 1},
            "position": {"x": 0, "y": 64, "z": 0},
            "trees_found": [{
                "name": "oak_log",
                "position": {"x": 2, "y": 64, "z": 0},
            }],
        },
    )
    assert heldout["bound_parameters"] == {"quantity": 2}
    assert heldout["effective_postconditions"] == {"inventory": {"oak_log": 2}}
    print("PASS: typed schema blocks executable code and enforces pre/postconditions plus safe fallback")


def _write_source_log(path: str, label: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"source": label}) + "\n")
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _synthetic_live_run(
    tmpdir: str,
    skill_id: str,
    arm: str,
    session_id: str,
    pair_id: str = "",
    steps: int = 4,
    heldout: bool = False,
):
    source_log = os.path.join(tmpdir, f"{session_id}.jsonl")
    source_hash = _write_source_log(source_log, session_id)
    metrics = {
        "task_completion": 1,
        "environment_steps": steps,
        "successful_actions": 3,
        "failed_actions": 0,
        "navigation_failures": 0,
        "verifier_rejects": 0,
        "replans": 0,
        "planner_calls": steps,
        "token_usage": 0,
        "wall_clock_latency_s": float(steps),
        "no_progress_loops": 0,
        "skill_selected_count": 1 if arm in {"candidate", "runtime"} else 0,
        "skill_executed_count": 3 if arm in {"candidate", "runtime"} else 0,
        "skill_completion_count": 1 if arm in {"candidate", "runtime"} else 0,
        "skill_outcome_count": 1 if arm in {"candidate", "runtime"} else 0,
        "skill_fallback_count": 1 if arm == "fallback" else 0,
        "skill_shadow_plan_count": 1 if arm == "shadow" else 0,
        "skill_advisory_hint_count": 1 if arm == "advisory" else 0,
        "attribution_confidence": 1.0 if arm in {"candidate", "runtime"} else 0.0,
        "candidate_steps_verified": True,
        "candidate_steps_reobserved": True,
    }
    profile = {
        "profile": "controlled_skill_learning_v1",
        "evidence_kind": "live_minecraft_skill_research",
        "counts_toward_m1_acceptance": False,
        "protocol_sha256": M1_PROTOCOL_SHA256,
        "world_seed": "12345",
        "task_id": "BM-001",
        "agent_id": "singularity-agent-v1",
        "planner_id": "rule-based-v1",
        "action_backend_id": "mineflayer-bridge-v1",
        "verifier_id": "goal-action-verifier-v1",
        "force_rule_planner": True,
        "action_verifier_enforced": True,
        "action_controller_enforced": True,
        "goal_verifier_enforced": True,
        "memory_persistence": False,
        "policy_skills": False,
        "vision": False,
        "candidate_extraction": False,
        "arm": arm,
        "research_fixture_profile": "protocol_default",
    }
    return {
        "type": LIVE_RUN_TYPE,
        "schema_version": 1,
        "run_id": f"experiment:{arm}:{session_id}",
        "experiment_id": "experiment",
        "pair_id": pair_id,
        "replicate_id": pair_id,
        "arm": arm,
        "heldout": heldout,
        "skill_id": skill_id,
        "task_id": "BM-001",
        "goal": "Gather 3 oak logs" if not heldout else "Gather 2 oak logs",
        "success_criteria": {"oak_log": 3} if not heldout else {"oak_log": 2},
        "status": "pass",
        "checks": {"all_required_live_checks": True},
        "failed_checks": [],
        "session_id": session_id,
        "source_log": source_log,
        "source_log_sha256": source_hash,
        "source_log_finalized_before_hash": True,
        "environment_id": f"environment-{session_id}",
        "world_seed": "12345",
        "protocol_sha256": M1_PROTOCOL_SHA256,
        "control_fingerprint": "heldout-control" if heldout else f"pair-control-{pair_id}",
        "runtime_profile": profile,
        "setup_evidence": {"success": True, "protocol_sha256": M1_PROTOCOL_SHA256},
        "research_setup_evidence": {
            "profile": "protocol_default",
            "success": True,
            "verified": True,
            "arbitrary_commands_allowed": False,
        },
        "metrics": metrics,
    }


def _paired_report(tmpdir: str, skill_id: str):
    paths = []
    for index in range(3):
        pair_id = f"pair-{index}"
        for arm, steps in (("baseline", 4), ("candidate", 2)):
            payload = _synthetic_live_run(
                tmpdir,
                skill_id,
                arm,
                f"{arm}-{index}",
                pair_id=pair_id,
                steps=steps,
            )
            path = os.path.join(tmpdir, f"{arm}-{index}.json")
            write_json(path, payload)
            paths.append(path)
    for arm in ("shadow", "advisory", "fallback"):
        payload = _synthetic_live_run(tmpdir, skill_id, arm, f"{arm}-session", steps=4)
        path = os.path.join(tmpdir, f"{arm}.json")
        write_json(path, payload)
        paths.append(path)
    return build_paired_ablation_report(
        paths,
        skill_id=skill_id,
        skill_version="1.0.0",
        task_family="gathering",
        rollback_target="1.0.0",
        transfer_scope={"task_family": "gathering", "goals": ["Gather 3 oak logs"]},
    )


def test_research_runtime_preserves_only_explicit_runtime_gate():
    config = Config(skill_runtime_default_gate_paths=["approved-runtime-gate.json"])

    runtime = build_skill_research_config(
        config,
        arm="runtime",
        skill_id="learned:gather_wood",
        experiment_id="runtime-01",
    )
    candidate = build_skill_research_config(
        config,
        arm="candidate",
        skill_id="learned:gather_wood",
        experiment_id="candidate-01",
    )

    assert runtime.skill_runtime_default_gate_paths == ["approved-runtime-gate.json"]
    assert candidate.skill_runtime_default_gate_paths == []
    print("PASS: controlled research preserves explicit runtime gates only for runtime arms")


def test_controlled_fault_profiles_are_allowlisted_and_verifier_visible():
    class RecordingLogger:
        def __init__(self):
            self.events = []

        def log(self, event_type, data, level="INFO"):
            self.events.append({"type": event_type, "data": data, "level": level})

    profiles = {
        "reject_skill_craft_missing_item_v1": "craft",
        "reject_skill_place_missing_item_v1": "place",
        "reject_skill_equip_missing_item_v1": "equip",
    }
    for profile, expected_type in profiles.items():
        agent = object.__new__(Agent)
        agent.config = Config(skill_fault_profile=profile)
        agent._applied_skill_fault_profiles = set()
        agent.session_logger = RecordingLogger()
        action = {
            "type": "craft",
            "parameters": {"item": "wooden_pickaxe", "count": 1},
            "skill_context": {
                "skill_id": "learned:craft_wooden_pickaxe",
                "experiment_id": profile,
                "goal_fingerprint": "goal",
            },
        }
        agent._apply_controlled_skill_fault(action)
        assert action["type"] == expected_type
        assert ActionVerifier().verify(action, {"inventory": {}}, goal="Craft a wooden pickaxe").status == "reject"
        agent._apply_controlled_skill_fault(action)
        assert len(agent.session_logger.events) == 1
        assert agent.session_logger.events[0]["data"]["counts_toward_promotion"] is False

    normal_agent = object.__new__(Agent)
    normal_agent.config = Config(skill_fault_profile="reject_skill_craft_missing_item_v1")
    normal_agent._applied_skill_fault_profiles = set()
    normal_agent.session_logger = RecordingLogger()
    normal_action = {"type": "craft", "parameters": {"item": "crafting_table", "count": 1}}
    normal_agent._apply_controlled_skill_fault(normal_action)
    assert normal_action["parameters"]["item"] == "crafting_table"
    assert not normal_agent.session_logger.events
    print("PASS: controlled fault profiles are one-shot, skill-scoped, verifier-visible, and promotion-ineligible")


def test_runtime_gate_paired_promotion_and_version_rollback():
    tmpdir = tempfile.mkdtemp()
    skill_id = "learned:gather_wood"
    report = _paired_report(tmpdir, skill_id)
    gate = report["executable_promotion_gate"]
    assert report["decision"] == "promote_executable", report
    assert not executable_promotion_gate_issues(gate, skill_id, "1.0.0")
    assert report["stable_efficiency_gain"]["environment_steps"]["stable_positive"]

    library = SkillLibrary(os.path.join(tmpdir, "skills"), persist=True)
    skill = library.create_skill(
        "learned_gather_wood",
        "Gather observed oak logs",
        json.dumps(_gather_template()),
        skill_id=skill_id,
        status="advisory",
        task_family="gathering",
        bounded_action_template=_gather_template(),
        postconditions={"inventory": {"oak_log": 3}},
        transfer_scope={"task_family": "gathering"},
    )
    world = {
        "position": {"x": 0, "y": 64, "z": 0},
        "inventory": {},
        "trees_found": [{"name": "oak_log", "position": {"x": 2, "y": 64, "z": 0}}],
    }
    assert library.select_runtime_skill("Gather 3 oak logs", world, "runtime", skill_id) is None
    assert library.select_runtime_skill("Gather 3 oak logs", world, "evaluation", skill_id) is None
    assert library.select_runtime_skill("Craft a crafting table", world, "shadow", skill_id) is None
    authorization = {
        "type": EVALUATION_AUTHORIZATION_TYPE,
        "schema_version": 1,
        "allowed": True,
        "skill_id": skill_id,
        "experiment_id": "trial-1",
        "single_target_skill": True,
        "action_verifier_enforced": True,
        "action_controller_enforced": True,
        "goal_verifier_enforced": True,
        "reobserve_each_cycle": True,
        "fallback_to_agentic_planning": True,
        "world_protocol_sha256": M1_PROTOCOL_SHA256,
    }
    assert not evaluation_authorization_issues(authorization, skill_id, "trial-1")
    assert library.select_runtime_skill(
        "Gather 3 oak logs",
        world,
        "advisory",
        skill_id,
        experiment_id="trial-1",
        evaluation_authorization=authorization,
    ) is skill
    assert library.select_runtime_skill(
        "Gather 3 oak logs",
        world,
        "evaluation",
        skill_id,
        experiment_id="trial-1",
        evaluation_authorization=authorization,
    ) is skill

    transition = library.transition_skill_status(
        skill_id,
        "executable",
        "paired live evidence passed",
        evidence=gate,
    )
    assert transition["changed"], transition
    executable = library.get_skill_by_id(skill_id)
    assert executable.version == "1.0.1"
    assert executable.rollback_target == "1.0.0"
    report["executable_promotion_gate"] = json.loads(json.dumps(executable.gate["executable_promotion"]))
    runtime_gate = build_runtime_default_gate(report, executable.name)

    tampered_library = SkillLibrary(os.path.join(tmpdir, "skills"), persist=True)
    tampered_gate = json.loads(json.dumps(runtime_gate))
    tampered_gate["candidates"][0]["promotion_gate_fingerprint"] = "0" * 64
    tampered_gate["executable_promotion_gate_fingerprint"] = "0" * 64
    tampered_library.record_skill_runtime_default_gate(tampered_gate)
    assert tampered_library.select_runtime_skill(
        "Gather 3 oak logs",
        world,
        "runtime",
        skill_id,
    ) is None

    library.record_skill_runtime_default_gate(runtime_gate)
    assert library.select_runtime_skill("Gather 3 oak logs", world, "runtime", skill_id) is executable

    rollback = library.rollback_skill_version(skill_id, "1.0.0", "regression detected")
    assert rollback["changed"], rollback
    restored = library.get_skill_by_id(skill_id)
    assert restored.version == "1.0.2"
    assert restored.status == "advisory"
    assert restored.rollback_target == "1.0.0"
    assert [item.version for item in library.skill_versions(skill_id)] == ["1.0.0", "1.0.1", "1.0.2"]
    print("PASS: advisory trials require authorization; paired live gate promotes a new executable version and rollback preserves history")


def test_failure_attribution_demotes_and_quarantines_without_backend_penalty():
    tmpdir = tempfile.mkdtemp()
    skill_id = "learned:gather_wood"
    report = _paired_report(tmpdir, skill_id)
    library = SkillLibrary(os.path.join(tmpdir, "skills"), persist=True)
    library.create_skill(
        "learned_gather_wood",
        "Gather observed oak logs",
        json.dumps(_gather_template()),
        skill_id=skill_id,
        status="advisory",
        task_family="gathering",
        bounded_action_template=_gather_template(),
        postconditions={"inventory": {"oak_log": 3}},
        transfer_scope={"task_family": "gathering"},
    )
    assert library.transition_skill_status(skill_id, "executable", "paired evidence", report["executable_promotion_gate"])["changed"]
    wrong_route = library.record_learned_skill_outcome(
        skill_id,
        False,
        {
            "failure_type": "postcondition_failure",
            "first_failed_transition": "wrong-family",
            "experiment_id": "wrong-route",
        },
    )
    assert wrong_route["status"] == "executable"
    correction = library.reclassify_learned_skill_failure(
        skill_id,
        "wrong-route",
        "routing_error",
        "task-family router caused the mismatch",
    )
    assert correction["changed"]
    assert library.get_skill_by_id(skill_id).failure_count == 0
    backend = library.record_learned_skill_outcome(
        skill_id,
        False,
        {"failure_type": "backend_execution_error", "first_failed_transition": "move:0"},
    )
    skill = library.get_skill_by_id(skill_id)
    assert backend["status"] == "executable"
    assert skill.failure_count == 0
    assert skill.observed_failure_count == 2
    assert skill.failure_type_counts["routing_error"] == 1

    first = library.record_learned_skill_outcome(
        skill_id,
        False,
        {"failure_type": "skill_error", "first_failed_transition": "dig:0"},
    )
    assert first["status"] == "executable"
    second = library.record_learned_skill_outcome(
        skill_id,
        False,
        {"failure_type": "skill_error", "first_failed_transition": "dig:1"},
    )
    assert second["status"] == "advisory"
    third = library.record_learned_skill_outcome(
        skill_id,
        False,
        {"failure_type": "postcondition_failure", "first_failed_transition": "postcondition"},
    )
    assert third["status"] == "quarantined"
    assert skill.failure_type_counts["backend_execution_error"] == 1
    assert skill.failure_type_counts["skill_error"] == 2
    print("PASS: failure attribution separates backend faults and automatically demotes then quarantines attributable failures")


def test_heldout_transfer_and_m3_adapter():
    tmpdir = tempfile.mkdtemp()
    skill_id = "learned:gather_wood"
    baseline = _synthetic_live_run(tmpdir, skill_id, "baseline", "heldout-baseline", steps=4, heldout=True)
    candidate = _synthetic_live_run(tmpdir, skill_id, "runtime", "heldout-runtime", steps=2, heldout=True)
    baseline_path = os.path.join(tmpdir, "heldout-baseline.json")
    candidate_path = os.path.join(tmpdir, "heldout-runtime.json")
    write_json(baseline_path, baseline)
    write_json(candidate_path, candidate)
    transfer, transfer_gate = build_heldout_transfer_report(
        baseline_path,
        candidate_path,
        skill_id,
        training_task_set=["Gather 3 oak logs"],
        validation_task_set=["Gather 3 oak logs / independent worlds"],
        heldout_task_set=["Gather 2 oak logs"],
        unsupported_task_family=["crafting"],
        training_session_ids=["candidate-0", "candidate-1", "candidate-2"],
    )
    assert transfer["positive_transfer"], transfer
    assert transfer["training_heldout_overlap_count"] == 0
    assert transfer_gate["readiness"] == "approved"

    library = SkillLibrary(os.path.join(tmpdir, "transfer-skills"), persist=True)
    library.create_skill(
        "learned_gather_wood",
        "Gather observed oak logs",
        json.dumps(_gather_template()),
        skill_id=skill_id,
        status="advisory",
        task_family="gathering",
        bounded_action_template=_gather_template(),
        postconditions={"inventory": {"oak_log": 3}},
        transfer_scope={"task_family": "gathering"},
    )
    paired = _paired_report(tmpdir, skill_id)
    assert library.transition_skill_status(
        skill_id,
        "executable",
        "paired evidence",
        paired["executable_promotion_gate"],
    )["changed"]
    applied = library.apply_heldout_transfer_evidence(skill_id, transfer, transfer_gate)
    assert applied["changed"], applied
    assert library.get_skill_by_id(skill_id).transfer_scope["heldout_validated"] is True
    assert "crafting" in library.get_skill_by_id(skill_id).transfer_scope["unsupported_task_families"]

    runtime_paths = []
    for index, runtime_skill in enumerate(("learned:gather_wood", "learned:craft_crafting_table", "learned:craft_wooden_pickaxe")):
        runtime = _synthetic_live_run(tmpdir, runtime_skill, "runtime", f"runtime-{index}", steps=2)
        path = os.path.join(tmpdir, f"runtime-{index}.json")
        write_json(path, runtime)
        runtime_paths.append(path)
    continual = build_continual_learning_report(runtime_paths)
    gate_path = os.path.join(tmpdir, "transfer-gate.json")
    continual_path = os.path.join(tmpdir, "continual.json")
    write_json(gate_path, transfer_gate)
    write_json(continual_path, continual)
    summary, errors = _build_m3_live_evidence(
        [(continual_path, continual), (gate_path, transfer_gate)],
        min_repeats=3,
    )
    assert not errors
    assert summary["status"] == "repeat_verified", summary
    assert summary["verified_successes"] == 3
    print("PASS: held-out sessions do not overlap training and skill retrieval/outcome writes satisfy the M3 adapter")


def main():
    test_candidate_extraction_dedup_and_provenance()
    test_typed_schema_preconditions_postconditions_and_fallback()
    test_research_runtime_preserves_only_explicit_runtime_gate()
    test_controlled_fault_profiles_are_allowlisted_and_verifier_visible()
    test_runtime_gate_paired_promotion_and_version_rollback()
    test_failure_attribution_demotes_and_quarantines_without_backend_penalty()
    test_heldout_transfer_and_m3_adapter()
    print("\nSELF-LEARNING TESTS PASSED")


if __name__ == "__main__":
    main()
