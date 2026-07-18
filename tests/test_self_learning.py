"""Offline-only contract tests for the self-learning mechanism under evaluation."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

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
    _apply_research_fixture,
    _verify_research_fixture,
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

    pickaxe_template = {
        "dsl_version": DSL_VERSION,
        "max_actions": 1,
        "phases": [{
            "id": "craft_target",
            "op": "craft_item",
            "item": "wooden_pickaxe",
            "count": 1,
            "target_item": "wooden_pickaxe",
            "target_count": 1,
        }],
    }
    pickaxe = library.create_skill(
        "learned_craft_wooden_pickaxe",
        "Craft one wooden pickaxe at an observed crafting table",
        json.dumps(pickaxe_template),
        persist=False,
        skill_id="learned:craft_wooden_pickaxe",
        version="1.0.2-candidate",
        status="candidate",
        task_family="crafting",
        preconditions={
            "inventory": {"oak_planks": 3, "stick": 2},
            "nearby_block_present": ["crafting_table"],
            "nearby_block_max_distance": {"crafting_table": 4.5},
        },
        required_observations=["inventory", "nearby_block:crafting_table"],
        required_inventory=[{"item": "oak_planks", "count": 3}, {"item": "stick", "count": 2}],
        postconditions={"inventory": {"wooden_pickaxe": 1}},
        bounded_action_template=pickaxe_template,
        transfer_scope={"task_family": "crafting"},
    )
    materials = {"inventory": {"oak_planks": 3, "stick": 2}, "position": {"x": 0, "y": 64, "z": 0}}
    missing_table = build_bounded_skill_plan(pickaxe, "Craft a wooden pickaxe", materials)
    assert missing_table["status"] == "fallback"
    assert missing_table["fallback_reason"] == "preconditions_not_met"
    assert missing_table["issues"] == ["nearby_block:crafting_table<=4.5"]
    table_too_far = {
        **materials,
        "nearby_blocks": [{"name": "crafting_table", "position": {"x": 5, "y": 64, "z": 0}, "distance": 5}],
    }
    assert build_bounded_skill_plan(pickaxe, "Craft a wooden pickaxe", table_too_far)["status"] == "fallback"
    table_ready = {
        **materials,
        "nearby_blocks": [{"name": "crafting_table", "position": {"x": 1, "y": 64, "z": 0}, "distance": 1}],
    }
    bounded = build_bounded_skill_plan(pickaxe, "Craft a wooden pickaxe", table_ready)
    assert bounded["status"] == "in_progress"
    assert bounded["actions"] == [{"type": "craft", "parameters": {"item": "wooden_pickaxe", "count": 1}}]
    print("PASS: typed schema blocks executable code and enforces pre/postconditions plus safe fallback")


def test_acquire_skill_uses_observed_distance_and_replans_after_each_dig():
    skill = {
        "skill_id": "learned:acquire_cobblestone",
        "name": "learned_acquire_cobblestone",
        "version": "1.0.0",
        "status": "advisory",
        "task_family": "mining",
        "postconditions": {"inventory": {"cobblestone": 3}},
        "bounded_action_template": {
            "dsl_version": DSL_VERSION,
            "max_actions": 6,
            "parameters": {
                "quantity": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
            },
            "phases": [{
                "id": "acquire_target",
                "op": "acquire_block_drop",
                "source_blocks": ["stone"],
                "target_item": "cobblestone",
                "target_count": {"parameter": "quantity", "default": 3},
                "selector": "nearest_observed",
                "search_radius": 32,
                "interaction_range": 4.5,
                "navigation_tolerance": 1.75,
            }],
        },
    }
    observation = {
        "position": {"x": 95.57907285827427, "y": 132, "z": -31.494351547541445},
        "inventory": {"wooden_pickaxe": 1},
        "nearby_blocks": [
            {"name": "stone", "position": {"x": 96, "y": 132, "z": -32}, "distance": 1},
            {"name": "stone", "position": {"x": 95, "y": 131, "z": -32}, "distance": 1},
            {"name": "stone", "position": {"x": 94, "y": 131, "z": -32}, "distance": 1.4142135623730951},
        ],
    }

    first = build_bounded_skill_plan(skill, "Gather 3 cobblestone", observation)
    assert first["actions"] == [{
        "type": "dig",
        "parameters": {"block": "stone", "x": 95, "y": 131, "z": -32},
    }]

    next_observation = {
        **observation,
        "inventory": {"wooden_pickaxe": 1, "cobblestone": 1},
        "nearby_blocks": [{
            "name": "stone",
            "position": {"x": 94, "y": 131, "z": -32},
            "distance": 1,
        }],
    }
    second = build_bounded_skill_plan(skill, "Gather 3 cobblestone", next_observation)
    assert second["actions"] == [{
        "type": "dig",
        "parameters": {"block": "stone", "x": 94, "y": 131, "z": -32},
    }]
    print("PASS: acquire skills honor observed-distance ties and replan one dig per observation")


def test_skill_plank_preconditions_use_pinned_ingredient_family():
    library = SkillLibrary(tempfile.mkdtemp(), persist=False)
    template = {
        "dsl_version": DSL_VERSION,
        "max_actions": 1,
        "phases": [{
            "id": "craft_target",
            "op": "craft_item",
            "item": "crafting_table",
            "count": 1,
            "target_item": "crafting_table",
            "target_count": 1,
        }],
    }
    skill = library.create_skill(
        "learned_craft_crafting_table",
        "Craft one crafting table from any accepted planks",
        json.dumps(template),
        persist=False,
        skill_id="learned:craft_crafting_table",
        status="advisory",
        task_family="crafting",
        preconditions={"inventory": {"oak_planks": 4}},
        required_inventory=[{"item": "oak_planks", "count": 4}],
        required_items=[{"item": "oak_planks", "count": 4}],
        postconditions={"inventory": {"crafting_table": 1}},
        bounded_action_template=template,
        transfer_scope={"task_family": "crafting"},
    )

    for inventory in (
        {"dark_oak_planks": 4},
        {"spruce_planks": 2, "birch_planks": 2},
    ):
        world = {"inventory": inventory}
        assert evaluate_skill_preconditions(skill, world) == []
        assert library._missing_preconditions(skill, world) == []
        assert library._missing_required_items(skill, inventory) == []
        profile = library._skill_contract_profile(skill, "Craft crafting table from planks", world)
        assert profile["missing_preconditions"] == []
        assert profile["missing_required_items"] == []

    for inventory in (
        {"dark_oak_planks": 3},
        {"oak_log": 4},
    ):
        assert evaluate_skill_preconditions(skill, {"inventory": inventory}) == [
            "inventory:oak_planks>=4"
        ]
    print("PASS: skill readiness applies the pinned plank family without weakening quantity checks")


def test_prerelease_skill_version_promotes_without_rewriting_quarantine_history():
    library = SkillLibrary(tempfile.mkdtemp(), persist=False)
    template = {
        "dsl_version": DSL_VERSION,
        "max_actions": 1,
        "phases": [{
            "id": "craft_target",
            "op": "craft_item",
            "item": "wooden_pickaxe",
            "count": 1,
            "target_item": "wooden_pickaxe",
            "target_count": 1,
        }],
    }
    skill_id = "learned:craft_wooden_pickaxe"
    library.create_skill(
        "learned_craft_wooden_pickaxe",
        "Historical quarantined wooden pickaxe skill",
        json.dumps(template),
        persist=False,
        skill_id=skill_id,
        version="1.0.1",
        status="quarantined",
        bounded_action_template=template,
    )
    candidate = library.create_skill(
        "learned_craft_wooden_pickaxe",
        "Independently revalidated wooden pickaxe candidate",
        json.dumps(template),
        persist=False,
        skill_id=skill_id,
        version="1.0.2-candidate",
        status="candidate",
        parent_version="1.0.1",
        rollback_target="1.0.1",
        bounded_action_template=template,
    )
    assert library._version_key("1.0.1") < library._version_key(candidate.version)
    assert library._version_key(candidate.version) < library._version_key("1.0.2")
    assert library._next_patch_version(candidate.version) == "1.0.2"
    assert library.get_skill_by_id(skill_id) is candidate
    historical = {item.version: item for item in library.skill_versions(skill_id)}
    assert historical["1.0.1"].status == "quarantined"
    assert historical["1.0.2-candidate"].status == "candidate"
    print("PASS: prerelease ordering supports stable 1.0.2 promotion and preserves quarantined 1.0.1")


def _write_source_log(path: str, label: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        events = [
            {"session": label, "type": "skill_learning_runtime_profile", "data": {
                "arm": "runtime",
                "evidence_kind": "live_minecraft_skill_research",
                "protocol_sha256": M1_PROTOCOL_SHA256,
            }},
            {"session": label, "type": "benchmark_reset", "data": {
                "success": True,
                "protocol_sha256": M1_PROTOCOL_SHA256,
            }},
            {"session": label, "type": "skill_selected", "data": {"skill_id": "learned:test"}},
            {"session": label, "type": "goal_verification", "data": {
                "achieved": True,
                "status": "achieved",
            }},
            {"session": label, "type": "goal_end", "data": {
                "result": {"completed": True, "termination_reason": "goal_verified"},
            }},
            {"session": label, "type": "skill_execution_outcome", "data": {
                "success": True,
                "attribution_confidence": 1.0,
            }},
        ]
        for event in events:
            handle.write(json.dumps(event) + "\n")
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


def test_wooden_pickaxe_heldout_fixture_is_allowlisted_and_position_verified():
    class Bot:
        def __init__(self):
            self.commands = []

        def chat(self, command):
            self.commands.append(command)
            return {"success": True}

    class FixtureAgent:
        def __init__(self):
            self.bot = Bot()

    agent = FixtureAgent()
    setup = {
        "after_state": {
            "spawn_position": {"x": 10, "y": 64, "z": 20},
            "fixture": {
                "position": {"x": 11, "y": 64, "z": 20},
                "block": "crafting_table",
            },
        },
    }
    research = _apply_research_fixture(agent, setup, "wooden_pickaxe_table_shift_v1")
    assert research["success"]
    assert agent.bot.commands == [
        "/setblock 11 64 20 minecraft:air replace",
        "/setblock 8 64 22 minecraft:crafting_table replace",
    ]
    observation = {
        "nearby_blocks": [{
            "name": "crafting_table",
            "position": {"x": 8, "y": 64, "z": 22},
        }],
    }
    verified = _verify_research_fixture(research, observation)
    assert verified["verified"]
    contaminated = _verify_research_fixture(research, {
        "nearby_blocks": observation["nearby_blocks"] + [{
            "name": "crafting_table",
            "position": {"x": 11, "y": 64, "z": 20},
        }],
    })
    assert not contaminated["verified"]
    assert contaminated["forbidden_blocks_present"]
    print("PASS: wooden-pickaxe held-out fixture uses only allowlisted commands and verifies the position shift")


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
        assert action["skill_context"]["controlled_failure_only"] is True
        assert action["skill_context"]["counts_toward_skill_lifecycle"] is False
        assert ActionVerifier().verify(action, {"inventory": {}}, goal="Craft a wooden pickaxe").status == "reject"
        agent._apply_controlled_skill_fault(action)
        assert len(agent.session_logger.events) == 1
        assert agent.session_logger.events[0]["data"]["counts_toward_promotion"] is False
        agent._active_skill_execution = {"skill_id": "learned:craft_wooden_pickaxe"}
        agent._skill_fallback_goals = set()
        agent.skill_library = type("Library", (), {"record_use": lambda *args, **kwargs: None})()
        agent._record_skill_usage(
            action,
            False,
            {"action_verification": {"status": "reject"}, "error": "controlled rejection"},
        )
        assert agent._active_skill_execution["failure_type"] == "controlled_fault"
        assert agent._active_skill_execution["counts_toward_skill_lifecycle"] is False
        outcome_event = next(
            event for event in agent.session_logger.events if event["type"] == "skill_action_result"
        )
        assert outcome_event["data"]["attributed"] is False

    normal_agent = object.__new__(Agent)
    normal_agent.config = Config(skill_fault_profile="reject_skill_craft_missing_item_v1")
    normal_agent._applied_skill_fault_profiles = set()
    normal_agent.session_logger = RecordingLogger()
    normal_action = {"type": "craft", "parameters": {"item": "crafting_table", "count": 1}}
    normal_agent._apply_controlled_skill_fault(normal_action)
    assert normal_action["parameters"]["item"] == "crafting_table"
    assert not normal_agent.session_logger.events
    print("PASS: controlled fault profiles are one-shot, skill-scoped, verifier-visible, and promotion-ineligible")


def test_skill_local_success_does_not_depend_on_broader_goal_success():
    class RecordingLogger:
        def __init__(self):
            self.events = []

        def log(self, event_type, data, level="INFO"):
            self.events.append({"type": event_type, "data": data, "level": level})

    tmpdir = tempfile.mkdtemp()
    library = SkillLibrary(os.path.join(tmpdir, "skills"), persist=False)
    template = {
        "dsl_version": "bounded_action_template_v1",
        "max_actions": 1,
        "phases": [{
            "id": "craft_target",
            "op": "craft_item",
            "item": "wooden_pickaxe",
            "count": 1,
            "target_item": "wooden_pickaxe",
            "target_count": 1,
        }],
    }
    skill = library.create_skill(
        "learned_craft_wooden_pickaxe",
        "Craft one wooden pickaxe",
        json.dumps(template),
        skill_id="learned:craft_wooden_pickaxe",
        status="advisory",
        task_family="crafting",
        bounded_action_template=template,
        postconditions={"inventory": {"wooden_pickaxe": 1}},
        transfer_scope={"task_family": "crafting"},
    )
    agent = object.__new__(Agent)
    agent.config = Config(skill_experiment_id="partial-goal-candidate")
    agent.skill_library = library
    agent.skill_learning_ledger = None
    agent.session_logger = RecordingLogger()
    agent._active_skill_execution = {
        "skill_id": skill.skill_id,
        "mode": "runtime",
        "executed_count": 1,
        "failed_action_count": 0,
        "effective_postconditions": {"inventory": {"wooden_pickaxe": 1}},
    }
    agent._finalize_active_skill_outcome(
        "Craft wooden pickaxe and get cobblestone",
        False,
        {"inventory": {"wooden_pickaxe": 1}},
        {"termination_reason": "empty_plan"},
    )
    restored = library.get_skill_by_id(skill.skill_id)
    assert restored.success_count == 1
    assert restored.failure_count == 0
    outcome = next(item for item in agent.session_logger.events if item["type"] == "skill_execution_outcome")
    assert outcome["data"]["success"] is True
    assert outcome["data"]["goal_success"] is False
    print("PASS: learned-skill attribution uses its local verified postconditions, not unrelated goal suffixes")


def test_r7_routed_subtask_family_survives_root_goal_finalization():
    class RecordingLogger:
        def __init__(self):
            self.events = []

        def log(self, event_type, data, level="INFO"):
            self.events.append({"type": event_type, "data": data, "level": level})

    tmpdir = tempfile.mkdtemp()
    library = SkillLibrary(os.path.join(tmpdir, "skills"), persist=False)
    template = {
        "dsl_version": DSL_VERSION,
        "max_actions": 6,
        "parameters": {
            "quantity": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
        },
        "phases": [{
            "id": "acquire_target",
            "op": "acquire_block_drop",
            "source_blocks": ["stone"],
            "target_item": "cobblestone",
            "target_count": {"parameter": "quantity", "default": 3},
            "selector": "nearest_observed",
            "search_radius": 32,
            "interaction_range": 4.5,
            "navigation_tolerance": 1.75,
        }],
    }
    skill = library.create_skill(
        "learned_acquire_cobblestone",
        "Acquire three cobblestone from observed stone",
        json.dumps(template),
        persist=False,
        skill_id="learned:acquire_cobblestone",
        status="advisory",
        task_family="mining",
        postconditions={"inventory": {"cobblestone": 3}},
        bounded_action_template=template,
        transfer_scope={"task_family": "mining"},
    )
    authorization = {
        "type": EVALUATION_AUTHORIZATION_TYPE,
        "schema_version": 1,
        "allowed": True,
        "skill_id": skill.skill_id,
        "experiment_id": "sp001_skill_candidate_r7_replay",
        "single_target_skill": True,
        "action_verifier_enforced": True,
        "action_controller_enforced": True,
        "goal_verifier_enforced": True,
        "reobserve_each_cycle": True,
        "fallback_to_agentic_planning": True,
        "world_protocol_sha256": M1_PROTOCOL_SHA256,
    }
    agent = object.__new__(Agent)
    agent.config = Config(
        skill_execution_mode="evaluation",
        target_skill_id=skill.skill_id,
        skill_experiment_id="sp001_skill_candidate_r7_replay",
        skill_evaluation_authorization=authorization,
        skill_regressions_path=os.path.join(tmpdir, "regressions.json"),
    )
    agent.skill_library = library
    agent.skill_learning_ledger = None
    agent.session_logger = RecordingLogger()
    agent._active_skill_execution = {}
    agent._skill_fallback_goals = set()
    routed_goal = "Dig stone for cobblestone"
    plan = agent._learned_skill_plan(routed_goal, {
        "position": {"x": 0.0, "y": 64.0, "z": 0.0},
        "inventory": {"wooden_pickaxe": 1},
        "nearby_blocks": [{
            "name": "stone",
            "position": {"x": 1, "y": 64, "z": 0},
            "distance": 1.0,
        }],
    })

    assert plan is not None and len(plan["actions"]) == 1
    route_fingerprint = agent._goal_fingerprint(routed_goal)
    assert agent._active_skill_execution["route_goal"] == routed_goal
    assert agent._active_skill_execution["route_goal_fingerprint"] == route_fingerprint
    assert agent._active_skill_execution["route_task_family"] == "mining"
    assert plan["actions"][0]["skill_context"]["route_task_family"] == "mining"
    agent._active_skill_execution["executed_count"] = 3
    agent._finalize_active_skill_outcome(
        "Gather 3 cobblestone with the wooden pickaxe",
        True,
        {"inventory": {"wooden_pickaxe": 1, "cobblestone": 3}},
        {"termination_reason": "goal_verified"},
    )

    restored = library.get_skill_by_id(skill.skill_id)
    assert restored.success_count == 1
    assert restored.failure_count == 0
    outcome = next(item for item in agent.session_logger.events if item["type"] == "skill_execution_outcome")
    assert outcome["data"]["success"] is True
    assert outcome["data"]["root_goal_task_family"] == "gathering"
    assert outcome["data"]["route_task_family"] == "mining"
    assert outcome["data"]["route_provenance_valid"] is True
    assert outcome["data"]["route_scope_valid"] is True
    assert outcome["data"]["lifecycle_outcome"]["context"]["goal_task_family"] == "mining"
    print("PASS: r7 replay preserves the legally routed mining subtask through root-goal finalization")


def test_skill_route_provenance_rejects_wrong_family_and_tampering():
    class RecordingLogger:
        def __init__(self):
            self.events = []

        def log(self, event_type, data, level="INFO"):
            self.events.append({"type": event_type, "data": data, "level": level})

    for route_goal, declared_family, declared_fingerprint, provenance_valid in (
        ("Gather three oak logs", "gathering", "", True),
        ("Dig stone for cobblestone", "gathering", "tampered", False),
    ):
        tmpdir = tempfile.mkdtemp()
        library = SkillLibrary(os.path.join(tmpdir, "skills"), persist=False)
        template = {
            "dsl_version": DSL_VERSION,
            "max_actions": 1,
            "phases": [{
                "id": "acquire_target",
                "op": "acquire_block_drop",
                "source_blocks": ["stone"],
                "target_item": "cobblestone",
                "target_count": 3,
                "selector": "nearest_observed",
            }],
        }
        skill = library.create_skill(
            "learned_acquire_cobblestone",
            "Acquire three cobblestone from observed stone",
            json.dumps(template),
            persist=False,
            skill_id="learned:acquire_cobblestone",
            status="advisory",
            task_family="mining",
            postconditions={"inventory": {"cobblestone": 3}},
            bounded_action_template=template,
            transfer_scope={"task_family": "mining"},
        )
        agent = object.__new__(Agent)
        agent.config = Config(
            skill_experiment_id="route-scope-negative",
            skill_regressions_path=os.path.join(tmpdir, "regressions.json"),
        )
        agent.skill_library = library
        agent.skill_learning_ledger = None
        agent.session_logger = RecordingLogger()
        agent._active_skill_execution = {
            "skill_id": skill.skill_id,
            "mode": "evaluation",
            "executed_count": 1,
            "failed_action_count": 0,
            "effective_postconditions": {"inventory": {"cobblestone": 3}},
            "route_goal": route_goal,
            "route_goal_fingerprint": declared_fingerprint or agent._goal_fingerprint(route_goal),
            "route_task_family": declared_family,
        }
        agent._finalize_active_skill_outcome(
            "Gather 3 cobblestone with the wooden pickaxe",
            True,
            {"inventory": {"cobblestone": 3}},
            {"termination_reason": "goal_verified"},
        )

        outcome = next(item for item in agent.session_logger.events if item["type"] == "skill_execution_outcome")
        assert outcome["data"]["success"] is False
        assert outcome["data"]["failure_type"] == "routing_error"
        assert outcome["data"]["route_scope_valid"] is False
        assert outcome["data"]["route_provenance_valid"] is provenance_valid
        restored = library.get_skill_by_id(skill.skill_id)
        assert restored.success_count == 0
        assert restored.failure_count == 0
        assert restored.observed_failure_count == 1
        assert restored.failure_type_counts == {"routing_error": 1}
    print("PASS: wrong-family and tampered learned-skill routes remain fail-closed")


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

    controlled = library.record_learned_skill_outcome(
        skill_id,
        False,
        {
            "failure_type": "controlled_fault",
            "first_failed_transition": "fault:0",
            "controlled_failure_only": True,
            "counts_toward_skill_lifecycle": False,
        },
    )
    assert controlled["status"] == "executable"
    assert skill.failure_count == 0
    assert skill.failure_type_counts["controlled_fault"] == 1

    first = library.record_learned_skill_outcome(
        skill_id,
        False,
        {
            "failure_type": "skill_error",
            "first_failed_transition": "dig:0",
            "experiment_id": "skill-failure-1",
        },
    )
    assert first["status"] == "executable"
    second = library.record_learned_skill_outcome(
        skill_id,
        False,
        {
            "failure_type": "skill_error",
            "first_failed_transition": "dig:1",
            "experiment_id": "skill-failure-2",
        },
    )
    assert second["status"] == "advisory"
    third = library.record_learned_skill_outcome(
        skill_id,
        False,
        {
            "failure_type": "postcondition_failure",
            "first_failed_transition": "postcondition",
            "experiment_id": "skill-failure-3",
        },
    )
    assert third["status"] == "quarantined"
    assert skill.failure_type_counts["backend_execution_error"] == 1
    assert skill.failure_type_counts["skill_error"] == 2
    for experiment_id, corrected_type in (
        ("skill-failure-1", "backend_execution_error"),
        ("skill-failure-2", "backend_execution_error"),
        ("skill-failure-3", "framework_contract_binding_error"),
    ):
        corrected = library.reclassify_learned_skill_failure(
            skill_id,
            experiment_id,
            corrected_type,
            "verified framework attribution error",
        )
        assert corrected["changed"]
    assert skill.failure_count == 0
    restored = library.restore_quarantine_after_attribution_correction(
        skill_id,
        "all attributable failures were corrected to framework-owned causes",
        {"tests": ["backend-retry", "local-postcondition-attribution"]},
    )
    assert restored["changed"]
    assert skill.status == "executable"
    assert skill.version == restored["version"]
    assert skill.lifecycle_history[-1]["event"] == "quarantine_restored_after_attribution_correction"
    print("PASS: failure attribution excludes controlled/backend faults and demotes only attributable failures")


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
    for case in continual["cases"]:
        case["source_log"] = os.path.basename(case["source_log"])
    gate_path = os.path.join(tmpdir, "transfer-gate.json")
    continual_path = os.path.join(tmpdir, "continual.json")
    write_json(gate_path, transfer_gate)
    write_json(continual_path, continual)
    summary, errors = _build_m3_live_evidence(
        [(continual_path, continual), (gate_path, transfer_gate)],
        min_repeats=3,
        source_root=Path(tmpdir),
    )
    assert not errors
    assert summary["status"] == "repeat_verified", summary
    assert summary["verified_successes"] == 3
    print("PASS: held-out sessions do not overlap training and skill retrieval/outcome writes satisfy the M3 adapter")


def test_heldout_fixture_validation_distinguishes_minimum_step_equivalence_from_positive_transfer():
    tmpdir = tempfile.mkdtemp()
    skill_id = "learned:craft_wooden_pickaxe"
    baseline = _synthetic_live_run(
        tmpdir,
        skill_id,
        "baseline",
        "fixture-baseline",
        steps=1,
        heldout=True,
    )
    candidate = _synthetic_live_run(
        tmpdir,
        skill_id,
        "candidate",
        "fixture-candidate",
        steps=1,
        heldout=True,
    )
    for run in (baseline, candidate):
        run["runtime_profile"]["research_fixture_profile"] = "wooden_pickaxe_table_shift_v1"
        run["research_setup_evidence"].update({
            "profile": "wooden_pickaxe_table_shift_v1",
            "expected_blocks": [{
                "name": "crafting_table",
                "position": {"x": 8, "y": 64, "z": 22},
            }],
        })
        run["control_fingerprint"] = "shifted-table-control"
    baseline_path = os.path.join(tmpdir, "fixture-baseline.json")
    candidate_path = os.path.join(tmpdir, "fixture-candidate.json")
    write_json(baseline_path, baseline)
    write_json(candidate_path, candidate)

    report, gate = build_heldout_transfer_report(
        baseline_path,
        candidate_path,
        skill_id,
        training_task_set=["default table"],
        validation_task_set=["default table pairs"],
        heldout_task_set=["shifted placed table"],
        unsupported_task_family=["combat"],
        training_session_ids=["training-1", "training-2", "training-3"],
    )

    assert report["environment_step_gain"] == 0
    assert report["positive_transfer"] is False
    assert gate["readiness"] == "review"
    assert report["heldout_fixture_validation"]["validated"] is True
    assert report["heldout_fixture_validation"]["minimum_step_equivalence"] is True
    assert gate["heldout_fixture_validation"]["readiness"] == "approved"
    print("PASS: irreducible one-step held-out equivalence is validated without being mislabeled positive transfer")


def main():
    test_candidate_extraction_dedup_and_provenance()
    test_typed_schema_preconditions_postconditions_and_fallback()
    test_acquire_skill_uses_observed_distance_and_replans_after_each_dig()
    test_skill_plank_preconditions_use_pinned_ingredient_family()
    test_prerelease_skill_version_promotes_without_rewriting_quarantine_history()
    test_research_runtime_preserves_only_explicit_runtime_gate()
    test_wooden_pickaxe_heldout_fixture_is_allowlisted_and_position_verified()
    test_controlled_fault_profiles_are_allowlisted_and_verifier_visible()
    test_skill_local_success_does_not_depend_on_broader_goal_success()
    test_r7_routed_subtask_family_survives_root_goal_finalization()
    test_skill_route_provenance_rejects_wrong_family_and_tampering()
    test_runtime_gate_paired_promotion_and_version_rollback()
    test_failure_attribution_demotes_and_quarantines_without_backend_penalty()
    test_heldout_transfer_and_m3_adapter()
    test_heldout_fixture_validation_distinguishes_minimum_step_equivalence_from_positive_transfer()
    print("\nSELF-LEARNING TESTS PASSED")


if __name__ == "__main__":
    main()
