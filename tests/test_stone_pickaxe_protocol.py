import copy
import json
import tempfile
from pathlib import Path

from singularity.core.skill_library import SkillLibrary
from singularity.core.task_system import TaskStatus
from singularity.evaluation.stone_pickaxe_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    REPOSITORY_ROOT,
    StonePickaxeCompositeHarness,
    file_sha256,
    plan_sp001_action,
    prospective_skill_contract,
    protocol_integrity_report,
    validate_acquire_template,
    validate_craft_template,
    validate_prospective_skill_contract,
    verify_sp001_episode,
    verify_sp002_episode,
)


def _source(source_id: str, x: float, name: str = "stone", reachable: bool = True) -> dict:
    return {
        "source_id": source_id,
        "name": name,
        "observed": True,
        "reachable": reachable,
        "position": {"x": x, "y": 64, "z": 0},
    }


def _sp001_observation(inventory: dict | None = None, sources: list[dict] | None = None) -> dict:
    return {
        "observation_id": "sp001-observation",
        "monotonic_s": 1.0,
        "inventory": {"wooden_pickaxe": 1} if inventory is None else inventory,
        "safe": True,
        "movable": True,
        "position": {"x": 0, "y": 64, "z": 0},
        "observed_blocks": sources if sources is not None else [
            _source("stone-1", 1),
            _source("stone-2", 2),
            _source("stone-3", 3),
        ],
    }


def _base_episode(task_id: str) -> dict:
    return {
        "type": "stone_pickaxe_microbenchmark_episode",
        "schema_version": 1,
        "task_id": task_id,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "session_id": f"offline-{task_id.lower()}-session",
        "episode_id": f"offline-{task_id.lower()}-episode",
        "session_sha256": "a" * 64,
        "evidence_kind": "offline_fixture",
        "eligibility": {
            "passed": True,
            "protocol_match": True,
            "reset_clean": True,
            "no_forbidden_intervention": True,
            "no_post_deadline_action": True,
        },
        "reset_contamination": False,
        "post_deadline_action_count": 0,
        "forbidden_interventions": [],
        "selected_skills": [],
        "episode_deadline_monotonic": 100.0,
    }


def _valid_sp001_episode() -> dict:
    episode = _base_episode("SP-001")
    episode["initial_observation"] = _sp001_observation()
    episode["action_count"] = 3
    episode["action_failure_count"] = 0
    episode["false_success_dig_count"] = 0
    episode["world_mutating_non_target_actions"] = []
    transitions = []
    for index in range(3):
        source_id = f"stone-{index + 1}"
        pre_count = index
        post_count = index + 1
        transitions.append({
            "source_id": source_id,
            "source_block": "stone",
            "tool": "wooden_pickaxe",
            "action_verified": True,
            "action_started_monotonic": 10.0 + index * 2,
            "action_finished_monotonic": 11.0 + index * 2,
            "action": {
                "type": "dig",
                "parameters": {"block": "stone", "source_id": source_id},
            },
            "pre_observation": {
                "observation_id": f"sp001-pre-{index + 1}",
                "monotonic_s": 10.0 + index * 2,
                "inventory": {"wooden_pickaxe": 1, "cobblestone": pre_count},
                "position": {"x": 0, "y": 64, "z": 0},
                "observed_blocks": [
                    _source(f"stone-{candidate + 1}", candidate + 1)
                    for candidate in range(index, 3)
                ],
                "source": {"id": source_id, "name": "stone", "present": True},
            },
            "post_observation": {
                "observation_id": f"sp001-post-{index + 1}",
                "monotonic_s": 11.0 + index * 2,
                "inventory": {"wooden_pickaxe": 1, "cobblestone": post_count},
                "source": {"id": source_id, "name": "stone", "present": False},
            },
            "pickup": {
                "observed": True,
                "source_id": source_id,
                "item": "cobblestone",
                "count": 1,
            },
        })
    episode["transitions"] = transitions
    episode["terminal_observation"] = {
        "observation_id": "sp001-terminal",
        "monotonic_s": 16.0,
        "inventory": {"wooden_pickaxe": 1, "cobblestone": 3},
    }
    return episode


def _table() -> dict:
    return {
        "block_id": "fixture-table-1",
        "name": "crafting_table",
        "observed": True,
        "interactive": True,
        "distance": 2.0,
    }


def _sp002_observation(observation_id: str, monotonic_s: float, inventory: dict) -> dict:
    return {
        "observation_id": observation_id,
        "monotonic_s": monotonic_s,
        "inventory": inventory,
        "nearby_blocks": [_table()],
    }


def _valid_sp002_episode() -> dict:
    episode = _base_episode("SP-002")
    initial = _sp002_observation("sp002-initial", 1.0, {"cobblestone": 3, "stick": 2})
    pre = _sp002_observation("sp002-pre", 10.0, {"cobblestone": 3, "stick": 2})
    post = _sp002_observation("sp002-post", 11.0, {"cobblestone": 0, "stick": 0, "stone_pickaxe": 1})
    stable = _sp002_observation("sp002-stable", 11.5, {"cobblestone": 0, "stick": 0, "stone_pickaxe": 1})
    episode["initial_observation"] = initial
    episode["transitions"] = [{
        "action_verified": True,
        "action_started_monotonic": 10.0,
        "action_finished_monotonic": 11.0,
        "action": {
            "type": "craft",
            "parameters": {"item": "stone_pickaxe", "count": 1},
        },
        "pre_observation": pre,
        "post_observation": post,
        "stable_observation": stable,
        "crafting_table_interaction": {
            "observed": True,
            "interactive": True,
            "block_id": "fixture-table-1",
            "observation_id": "sp002-pre",
            "distance": 2.0,
        },
    }]
    return episode


def _load_ledger() -> dict:
    path = REPOSITORY_ROOT / "workspace" / "evals" / "stone_pickaxe_failure_ledger.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_01_exact_wooden_pickaxe_precondition():
    assert protocol_integrity_report()["passed"], protocol_integrity_report()
    contract = prospective_skill_contract("SP-001")
    assert validate_prospective_skill_contract("SP-001", contract)["passed"]
    plan = plan_sp001_action(_sp001_observation())
    assert plan["status"] == "in_progress"
    assert plan["actions"][0]["parameters"]["block"] == "stone"


def test_02_missing_wooden_pickaxe_is_blocked():
    plan = plan_sp001_action(_sp001_observation(inventory={}))
    assert plan["status"] == "fallback"
    assert plan["issues"] == ["inventory:wooden_pickaxe>=1"]
    stone_tool_only = plan_sp001_action(_sp001_observation(inventory={"stone_pickaxe": 1}))
    assert stone_tool_only["status"] == "fallback"


def test_03_only_allowlisted_source_blocks_are_selected():
    observation = _sp001_observation(sources=[
        _source("dirt-1", 0.5, name="dirt"),
        _source("ore-1", 0.75, name="iron_ore"),
        _source("stone-1", 2.0),
    ])
    plan = plan_sp001_action(observation)
    assert plan["selected_source"]["source_id"] == "stone-1"
    assert plan["actions"][0]["parameters"]["block"] == "stone"


def test_04_nearest_observed_selection_is_deterministic():
    sources = [_source("stone-far", 3), _source("stone-near", 1), _source("stone-mid", 2)]
    first = plan_sp001_action(_sp001_observation(sources=sources))
    second = plan_sp001_action(_sp001_observation(sources=list(reversed(sources))))
    assert first["selected_source"]["source_id"] == "stone-near"
    assert second["selected_source"]["source_id"] == "stone-near"


def test_05_already_satisfied_returns_complete_with_zero_actions():
    observation = _sp001_observation(inventory={"cobblestone": 3}, sources=[])
    observation["safe"] = False
    observation["movable"] = False
    plan = plan_sp001_action(observation)
    assert plan["status"] == "complete"
    assert plan["actions"] == []


def test_06_quantity_parameter_bounds_are_enforced():
    observation = _sp001_observation()
    assert plan_sp001_action(observation, quantity=1)["status"] == "in_progress"
    assert plan_sp001_action(observation, quantity=8)["status"] == "in_progress"
    for invalid in (0, 9, True, 3.0, "3"):
        report = plan_sp001_action(observation, quantity=invalid)
        assert report["fallback_reason"] == "parameter_outside_transfer_scope:quantity"


def test_07_acquire_template_contains_no_fixed_coordinates():
    template = prospective_skill_contract("SP-001")["bounded_action_template"]
    assert validate_acquire_template(template)["passed"]
    serialized = json.dumps(template, sort_keys=True)
    for forbidden in ('"x"', '"y"', '"z"', "source_id", "session_id", "coordinates"):
        assert forbidden not in serialized
    tampered = copy.deepcopy(template)
    tampered["phases"][0]["x"] = 12
    assert not validate_acquire_template(tampered)["passed"]


def test_08_duplicate_source_block_is_not_dug_twice():
    observation = _sp001_observation()
    plan = plan_sp001_action(observation, used_source_ids={"stone-1"})
    assert plan["selected_source"]["source_id"] == "stone-2"
    exhausted = plan_sp001_action(observation, used_source_ids={"stone-1", "stone-2", "stone-3"})
    assert exhausted["status"] == "fallback"
    assert exhausted["actions"] == []


def test_09_pickup_is_required_for_sp001_postcondition():
    valid = verify_sp001_episode(_valid_sp001_episode())
    assert valid["criteria_passed"]
    assert not valid["evidence_eligible"]
    assert not valid["counts_toward_skill_gate"]
    missing = _valid_sp001_episode()
    missing["transitions"][0]["pickup"]["observed"] = False
    report = verify_sp001_episode(missing)
    assert not report["criteria_passed"]
    assert "transition_1:pickup_provenance" in report["criteria_issues"]


def test_10_wrong_drop_does_not_pass_sp001():
    evidence = _valid_sp001_episode()
    evidence["transitions"][1]["pickup"]["item"] = "stone"
    report = verify_sp001_episode(evidence)
    assert not report["criteria_passed"]
    assert "transition_2:pickup_provenance" in report["criteria_issues"]


def test_11_exact_stone_pickaxe_craft_preconditions_pass():
    contract = prospective_skill_contract("SP-002")
    assert validate_prospective_skill_contract("SP-002", contract)["passed"]
    report = verify_sp002_episode(_valid_sp002_episode())
    assert report["criteria_passed"]
    assert report["metrics"]["material_delta"] == {"cobblestone": -3, "stick": -2}
    assert report["metrics"]["inventory_delta"] == {"stone_pickaxe": 1}
    assert not report["counts_toward_capability"]


def test_12_two_cobblestone_is_rejected():
    evidence = _valid_sp002_episode()
    evidence["initial_observation"]["inventory"]["cobblestone"] = 2
    evidence["transitions"][0]["pre_observation"]["inventory"]["cobblestone"] = 2
    report = verify_sp002_episode(evidence)
    assert not report["criteria_passed"]
    assert "initial_cobblestone_exact" in report["criteria_issues"]
    assert "pre_materials_cobblestone" in report["criteria_issues"]


def test_13_one_stick_is_rejected():
    evidence = _valid_sp002_episode()
    evidence["initial_observation"]["inventory"]["stick"] = 1
    evidence["transitions"][0]["pre_observation"]["inventory"]["stick"] = 1
    report = verify_sp002_episode(evidence)
    assert not report["criteria_passed"]
    assert "initial_stick_exact" in report["criteria_issues"]
    assert "pre_materials_stick" in report["criteria_issues"]


def test_14_missing_crafting_table_is_rejected():
    evidence = _valid_sp002_episode()
    evidence["initial_observation"]["nearby_blocks"] = []
    evidence["transitions"][0]["pre_observation"]["nearby_blocks"] = []
    evidence["transitions"][0]["crafting_table_interaction"] = {}
    report = verify_sp002_episode(evidence)
    assert not report["criteria_passed"]
    assert "initial_crafting_table" in report["criteria_issues"]
    assert "pre_crafting_table" in report["criteria_issues"]


def test_15_wooden_pickaxe_does_not_satisfy_stone_pickaxe_terminal_state():
    evidence = _valid_sp002_episode()
    post = evidence["transitions"][0]["post_observation"]["inventory"]
    stable = evidence["transitions"][0]["stable_observation"]["inventory"]
    post.pop("stone_pickaxe")
    stable.pop("stone_pickaxe")
    post["wooden_pickaxe"] = 1
    stable["wooden_pickaxe"] = 1
    report = verify_sp002_episode(evidence)
    assert not report["criteria_passed"]
    assert "stone_pickaxe_delta" in report["criteria_issues"]


def test_16_transient_inventory_ghost_is_not_success():
    evidence = _valid_sp002_episode()
    evidence["transitions"][0]["stable_observation"]["inventory"]["stone_pickaxe"] = 0
    report = verify_sp002_episode(evidence)
    assert not report["criteria_passed"]
    assert "stable_stone_pickaxe" in report["criteria_issues"]


def test_17_stable_reobservation_is_required():
    evidence = _valid_sp002_episode()
    evidence["transitions"][0].pop("stable_observation")
    report = verify_sp002_episode(evidence)
    assert not report["criteria_passed"]
    assert "stable_observation_id" in report["criteria_issues"]
    assert "stable_reobservation_delay" in report["criteria_issues"]


def test_18_craft_template_max_actions_is_one():
    template = prospective_skill_contract("SP-002")["bounded_action_template"]
    assert template["max_actions"] == 1
    assert validate_craft_template(template)["passed"]
    tampered = copy.deepcopy(template)
    tampered["max_actions"] = 2
    report = validate_craft_template(tampered)
    assert not report["passed"]
    assert "max_actions_must_equal_1" in report["issues"]


def test_19_recipe_field_cannot_replace_exact_item():
    template = copy.deepcopy(prospective_skill_contract("SP-002")["bounded_action_template"])
    phase = template["phases"][0]
    phase["recipe"] = phase.pop("item")
    assert not validate_craft_template(template)["passed"]
    evidence = _valid_sp002_episode()
    parameters = evidence["transitions"][0]["action"]["parameters"]
    parameters["recipe"] = parameters.pop("item")
    report = verify_sp002_episode(evidence)
    assert not report["criteria_passed"]
    assert "craft_item_exact" in report["criteria_issues"]
    assert "recipe_alias_forbidden" in report["criteria_issues"]


def test_20_family_substitutes_do_not_satisfy_exact_material_contract():
    contract = copy.deepcopy(prospective_skill_contract("SP-002"))
    contract["preconditions"]["inventory"] = {"cobbled_deepslate": 3, "stick": 2}
    report = validate_prospective_skill_contract("SP-002", contract)
    assert not report["passed"]
    assert "exact_preconditions_required" in report["issues"]


def test_21_acquire_completion_releases_craft_dependency():
    harness = StonePickaxeCompositeHarness()
    initial = {
        "inventory": {"wooden_pickaxe": 1, "stick": 2},
        "nearby_blocks": [{"name": "crafting_table"}],
    }
    assert [task.id for task in harness.frontier(initial)] == [harness.task("SP-001").id]
    acquired = {
        "inventory": {"wooden_pickaxe": 1, "stick": 2, "cobblestone": 3},
        "nearby_blocks": [{"name": "crafting_table"}],
    }
    assert harness.complete_from_machine_state("SP-001", acquired)
    assert harness.task("SP-002") in harness.frontier(acquired)


def test_22_completed_acquire_task_is_not_recreated():
    harness = StonePickaxeCompositeHarness()
    state = {"inventory": {"cobblestone": 3}}
    assert harness.complete_from_machine_state("SP-001", state)
    count = len(harness.task_system.tasks)
    task = harness.ensure_task("SP-001")
    assert task.status == TaskStatus.COMPLETED
    assert harness.ensure_task("SP-001") is task
    assert len(harness.task_system.tasks) == count


def test_23_completed_craft_task_is_not_rescheduled():
    harness = StonePickaxeCompositeHarness()
    acquired = {
        "inventory": {"cobblestone": 3, "stick": 2},
        "nearby_blocks": [{"name": "crafting_table"}],
    }
    assert harness.complete_from_machine_state("SP-001", acquired)
    complete = {
        "inventory": {"stone_pickaxe": 1},
        "nearby_blocks": [{"name": "crafting_table"}],
    }
    assert harness.complete_from_machine_state("SP-002", complete)
    assert harness.task("SP-002").status == TaskStatus.COMPLETED
    assert harness.frontier(complete) == []


def test_24_one_active_recovery_child_per_fingerprint():
    harness = StonePickaxeCompositeHarness()
    fingerprint = "f" * 64
    first = harness.ensure_recovery_child("SP-001", fingerprint)
    second = harness.ensure_recovery_child("SP-001", fingerprint)
    assert first is second
    active = [
        task for task in harness.task_system.tasks.values()
        if task.metadata.get("stone_pickaxe_recovery", {}).get("fingerprint") == fingerprint
        and task.status in {TaskStatus.ACCEPTED, TaskStatus.ACTIVE}
    ]
    assert active == [first]
    assert first.failure_criteria == {"max_failures": 3}


def test_25_task_frontier_contains_no_stale_recovery_sibling():
    harness = StonePickaxeCompositeHarness()
    fingerprint = "e" * 64
    keep = harness.ensure_recovery_child("SP-001", fingerprint)
    target = harness.task("SP-001")
    stale = harness.task_system.create_task(
        "Duplicate recovery fixture",
        task_type="recovery",
        parent_id=target.id,
        status=TaskStatus.ACCEPTED,
        metadata={
            "stone_pickaxe_recovery": {
                "fingerprint": fingerprint,
                "target_task_id": target.id,
            }
        },
    )
    assert harness.ensure_recovery_child("SP-001", fingerprint) is keep
    assert stale.status == TaskStatus.CANCELLED
    frontier_ids = {task.id for task in harness.frontier({"inventory": {}})}
    assert keep.id in frontier_ids
    assert stale.id not in frontier_ids


def test_26_fallback_excludes_quarantined_skill():
    library = SkillLibrary(tempfile.mkdtemp(), persist=False)
    contract = prospective_skill_contract("SP-001")
    skill = library.create_skill(
        "learned_acquire_cobblestone",
        "Quarantined acquire-cobblestone fixture",
        json.dumps(contract["bounded_action_template"]),
        persist=False,
        skill_id="learned:acquire_cobblestone",
        version="1.0.0",
        status="quarantined",
        task_family="mining",
        preconditions=contract["preconditions"],
        postconditions=contract["postconditions"],
        required_observations=contract["required_observations"],
        bounded_action_template=contract["bounded_action_template"],
        transfer_scope={"supported_task_families": ["mining"]},
    )
    selected = library.select_runtime_skill(
        "Mine 3 cobblestone",
        _sp001_observation(),
        execution_mode="shadow",
        target_skill_id=skill.skill_id,
    )
    assert selected is None


def test_27_skill_attribution_remains_separate():
    harness = StonePickaxeCompositeHarness()
    acquire = harness.record_skill_attribution(
        "SP-001",
        "learned:acquire_cobblestone",
        {"inventory": {"cobblestone": 3}},
    )
    craft = harness.record_skill_attribution(
        "SP-002",
        "learned:craft_stone_pickaxe",
        {"inventory": {"stone_pickaxe": 1}},
    )
    wrong = harness.record_skill_attribution(
        "SP-001",
        "learned:craft_stone_pickaxe",
        {"inventory": {"stone_pickaxe": 1}},
    )
    assert acquire["accepted"] and craft["accepted"]
    assert not wrong["accepted"]
    assert {record["task_id"] for record in harness.attributions} == {"SP-001", "SP-002"}
    assert all(record["root_goal_attributed"] is False for record in harness.attributions)


def test_28_m1_m2_m3_regressions_remain_required_and_statuses_unchanged():
    capability_path = REPOSITORY_ROOT / "workspace" / "evals" / "capability_evidence_current.json"
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    statuses = {phase["id"]: phase["status"] for phase in capability["phases"]}
    assert {phase: statuses[phase] for phase in ("M1", "M2", "M3")} == {
        "M1": "repeat_verified",
        "M2": "repeat_verified",
        "M3": "repeat_verified",
    }
    gate = PROTOCOL["regression_gate"]
    assert gate["required_capability_statuses"] == {
        "M1": "repeat_verified",
        "M2": "repeat_verified",
        "M3": "repeat_verified",
    }
    assert gate["capability_threshold_changes_allowed"] is False
    assert gate["goal_verifier_relaxation_allowed"] is False


def test_29_existing_wooden_pickaxe_skill_history_hash_is_unchanged():
    baseline = _load_ledger()["immutable_baseline"]
    path = REPOSITORY_ROOT / baseline["custom_skills"]["path"]
    assert baseline["custom_skills"]["sha256"] == file_sha256(path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    versions = {
        record["version"]: record["status"]
        for record in records
        if record.get("skill_id") == "learned:craft_wooden_pickaxe"
    }
    assert versions == {
        "1.0.0": "advisory",
        "1.0.1": "quarantined",
        "1.0.2-candidate": "advisory",
        "1.0.2": "executable",
    }


def test_30_probe_21_22_23_evidence_hashes_are_unchanged():
    baseline = _load_ledger()["immutable_baseline"]
    files = baseline["probe_evidence"]
    assert files
    assert {record["probe"] for record in files} == {21, 22, 23}
    for record in files:
        path = REPOSITORY_ROOT / Path(record["path"])
        assert path.is_file(), record["path"]
        assert file_sha256(path) == record["sha256"], record["path"]


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"PASS: {len(tests)} stone-pickaxe protocol cases")
