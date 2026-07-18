import hashlib
import json
import tempfile
from pathlib import Path

from singularity.core.planner import Planner
from singularity.core.task_system import TaskSystem
from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL, PROTOCOL_SHA256
from singularity.evaluation.stone_pickaxe_sp002_runtime import (
    SP002_GOAL,
    SP002_RUNTIME_POLICY_ID,
    audit_sp002_bridge_protocol_status,
    audit_sp002_fixture,
    build_runtime_config,
    build_sp002_authorization,
    build_sp002_episode,
    build_sp002_fixture_artifact,
    guard_runtime_action,
    snapshot_tree_report,
    verify_sp002_authorization,
    verify_sp002_fixture_manifest,
    verify_sp002_runtime_episode,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "workspace/evals/stone_pickaxe_sp002_harness_policy.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_observation(*, cobblestone=3, stick=2, stone_pickaxe=0, table=True):
    inventory = {
        "wooden_pickaxe": 1,
        "cobblestone": cobblestone,
        "stick": stick,
    }
    if stone_pickaxe:
        inventory["stone_pickaxe"] = stone_pickaxe
    blocks = []
    if table:
        blocks.append({
            "name": "crafting_table",
            "position": {"x": 1, "y": 64, "z": 0},
            "distance": 1.0,
        })
    return {
        "position": {"x": 0.0, "y": 64.0, "z": 0.0},
        "health": 20,
        "hunger": 20,
        "game_mode": "survival",
        "dimension": "overworld",
        "ground_block": "grass_block",
        "inventory": inventory,
        "equipment": [None],
        "nearby_entities": [],
        "nearby_blocks": blocks,
    }


def _planner_event():
    timeout = 89.5
    return {
        "type": "llm_planner_call",
        "data": {
            "protocol": PROTOCOL["id"],
            "call_id": "offline-sp002-call-1",
            "call_index": 0,
            "real_llm_call": True,
            "schema_valid": True,
            "response_sha256": "e" * 64,
            "response_byte_count": 128,
            "deadline_policy": {
                "policy_id": PROTOCOL["deadline_policy"]["id"],
                "remaining_before_call_s": 90.0,
                "request_timeout_s": timeout,
                "max_retries": 0,
            },
            "transport_evidence": {
                "policy_id": "single-attempt",
                "attempt_count": 1,
                "retry_count": 0,
                "attempts": [{
                    "attempt_index": 0,
                    "success": True,
                    "timeout_s": timeout,
                    "sdk_max_retries": 0,
                    "finish_reason": "stop",
                }],
            },
            "provider_metadata": {
                "provider": PROTOCOL["planner"]["provider"],
                "base_url": PROTOCOL["planner"]["base_url"],
                "model": PROTOCOL["planner"]["model"],
                "temperature": PROTOCOL["planner"]["temperature"],
                "max_tokens": PROTOCOL["planner"]["max_tokens"],
                "response_format": {"type": "json_object"},
                "extra_body": {"thinking": {"type": "disabled"}},
                "request_sha256": "d" * 64,
                "timeout_s": timeout,
                "max_retries": 0,
                "finish_reason": "stop",
                "reasoning_content_byte_count": 0,
            },
            "error": "",
        },
    }


def _craft_event(*, attempts=1, retry_count=0, post_pickaxe=1):
    before = _raw_observation()
    after = _raw_observation(cobblestone=0, stick=0, stone_pickaxe=post_pickaxe)
    return {
        "type": "action",
        "elapsed_s": 1.0,
        "data": {
            "action": {
                "type": "craft",
                "parameters": {"item": "stone_pickaxe", "count": 1},
            },
            "result": {
                "success": True,
                "item": "stone_pickaxe",
                "requested_output_count": 1,
                "inventory_before": {"cobblestone": 3, "stick": 2},
                "inventory_after": {"stone_pickaxe": post_pickaxe},
                "inventory_delta": {"stone_pickaxe": post_pickaxe},
                "craft_attempts": attempts,
                "craft_retry_count": retry_count,
                "stable_ms": 800,
                "crafting_table_found": True,
                "crafting_table_position": {"x": 1, "y": 64, "z": 0},
                "action_verification": {"status": "accept"},
                "action_started_monotonic": 10.5,
                "action_finished_monotonic": 11.0,
                "accepted_within_episode_deadline": True,
            },
            "pre_observation": before,
            "post_observation": after,
        },
    }


def _fixture_manifest():
    return {
        "type": "stone_pickaxe_fixture_manifest",
        "schema_version": 1,
        "fixture_id": "sp002-craft-stone-pickaxe-v1",
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "snapshot_identity_verified": True,
        "snapshot": {"tree_sha256": "b" * 64, "file_count": 3, "total_bytes": 30},
    }


def _episode(
    *,
    attempts=1,
    retry_count=0,
    stable_pickaxe=1,
    post_pickaxe=1,
    include_craft=True,
):
    events = [_planner_event()]
    if include_craft:
        events.append(_craft_event(
            attempts=attempts,
            retry_count=retry_count,
            post_pickaxe=post_pickaxe,
        ))
    stable = _raw_observation(
        cobblestone=0,
        stick=0,
        stone_pickaxe=stable_pickaxe,
    )
    return build_sp002_episode(
        episode_id="sp002-offline",
        session_id="sp002-session",
        session_sha256="a" * 64,
        events=events,
        initial_observation=_raw_observation(),
        stable_observation=stable,
        initial_monotonic=10.0,
        stable_monotonic=11.3,
        goal_result={
            "episode_started_monotonic": 10.0,
            "episode_deadline_monotonic": 100.0,
            "deadline_policy_id": PROTOCOL["deadline_policy"]["id"],
        },
        fixture_manifest=_fixture_manifest(),
        hypothesis_path="workspace/evals/sp002_runs/sp002-offline/hypothesis.json",
        authorization_path="workspace/evals/sp002_runs/sp002-offline/authorization.json",
        level_name="sp002-offline",
    )


def test_01_policy_binds_promoted_acquire_skill_and_frozen_protocol():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert policy["id"] == SP002_RUNTIME_POLICY_ID
    prerequisite = policy["prerequisite_acquire_skill"]
    assert policy["protocol"]["sha256"] == _sha256(
        ROOT / policy["protocol"]["path"]
    )
    assert prerequisite["version"] == "1.1.0"
    assert prerequisite["status"] == "executable"
    implementation = policy["implementation_contract"]
    assert implementation["authorization_predecessor_is_implementation_commit"]
    assert implementation["bridge_protocol_configured_required"]
    assert implementation["legacy_sp001_runtime_identity_must_remain_unchanged"]
    for key in (
        "isolated_runtime_module",
        "isolated_launcher",
        "episode_runner",
        "bridge_backend",
    ):
        assert (ROOT / implementation[key]).is_file()
    for key in ("promotion_artifact", "runtime_default_gate"):
        binding = prerequisite[key]
        assert binding["sha256"] == _sha256(ROOT / binding["path"])
    records = [
        json.loads(line)
        for line in (ROOT / "workspace/skills/custom_skills.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    acquire = [record for record in records if record.get("name") == "learned_acquire_cobblestone"]
    assert {(record["version"], record["status"]) for record in acquire} >= {
        ("1.0.0", "advisory"),
        ("1.1.0", "executable"),
    }


def test_02_sp002_fixture_audit_requires_exact_inputs_and_table():
    assert audit_sp002_fixture(_raw_observation())["passed"]
    assert "cobblestone_exact" in audit_sp002_fixture(
        _raw_observation(cobblestone=2)
    )["issues"]
    assert "interactive_crafting_table_observed" in audit_sp002_fixture(
        _raw_observation(table=False)
    )["issues"]
    assert "stone_pickaxe_absent" in audit_sp002_fixture(
        _raw_observation(stone_pickaxe=1)
    )["issues"]


def test_03_sp002_guard_accepts_only_one_exact_craft():
    exact = {
        "type": "craft",
        "parameters": {"item": "stone_pickaxe", "count": 1},
    }
    assert guard_runtime_action("sp002", exact, _raw_observation())["allowed"]
    wrong_item = {
        "type": "craft",
        "parameters": {"item": "wooden_pickaxe", "count": 1},
    }
    assert not guard_runtime_action("sp002", wrong_item, _raw_observation())["allowed"]
    alias = {
        "type": "craft",
        "parameters": {"item": "stone_pickaxe", "count": 1, "recipe": "alias"},
    }
    assert "sp002_exact_craft_parameters_required" in guard_runtime_action(
        "sp002", alias, _raw_observation()
    )["issues"]
    assert not guard_runtime_action(
        "sp002", exact, _raw_observation(table=False)
    )["allowed"]
    assert not guard_runtime_action(
        "sp002", {"type": "wait", "parameters": {"ms": 250}}, _raw_observation()
    )["allowed"]


def test_04_sp002_preparation_guard_stops_at_three_and_forbids_target_craft():
    dig = {
        "type": "dig",
        "parameters": {"block": "stone", "x": 1, "y": 64, "z": 0},
    }
    observation = _raw_observation(cobblestone=3)
    observation["nearby_blocks"].append({
        "name": "stone",
        "position": {"x": 1, "y": 64, "z": 0},
        "distance": 1.0,
    })
    assert "prepare_sp002_fixture_cobblestone_limit_reached" in guard_runtime_action(
        "prepare_sp002_fixture", dig, observation
    )["issues"]
    target_craft = {
        "type": "craft",
        "parameters": {"item": "stone_pickaxe", "count": 1},
    }
    assert not guard_runtime_action(
        "prepare_sp002_fixture", target_craft, observation
    )["allowed"]


def test_05_sp002_fixture_manifest_round_trip_is_hash_bound():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for index, component in enumerate(("world", "world_nether", "world_the_end"), 1):
            component_root = root / component
            component_root.mkdir()
            (component_root / "level.dat").write_bytes(f"component-{index}".encode())
        tree = snapshot_tree_report(root)
        audit = audit_sp002_fixture(_raw_observation())
        preparation = {
            "protocol_sha256": PROTOCOL_SHA256,
            "fixture_audit": audit,
            "planner_request_controls": {"passed": True},
            "protocol_status_audit": {"passed": True},
            "source_fixture": {
                "fixture_id": "sp001-acquire-cobblestone-v1",
                "snapshot_identity_verified": True,
                "tree_sha256": "c" * 64,
            },
            "game_mode": "survival",
            "external_step_script": False,
            "forbidden_interventions": [],
            "target_result_injection": False,
            "active_benchmark_reset": False,
        }
        manifest = build_sp002_fixture_artifact(
            preparation,
            tree,
            snapshot_path="logs/stone_pickaxe/fixtures/sp002-test",
        )
        assert manifest["snapshot_identity_verified"]
        assert verify_sp002_fixture_manifest(manifest, root)["passed"]
        (root / "world" / "level.dat").write_bytes(b"tampered")
        assert not verify_sp002_fixture_manifest(manifest, root)["passed"]


def test_06_one_time_authorization_is_parent_fixture_and_policy_bound():
    fixture = _fixture_manifest()
    predecessor = "1" * 40
    policy_hash = _sha256(POLICY_PATH)
    authorization = build_sp002_authorization(
        scope="live_episode",
        episode_id="sp002-live-1",
        authorization_predecessor=predecessor,
        fixture_path="workspace/evals/stone_pickaxe_sp002_fixture.json",
        fixture_sha256="2" * 64,
        fixture_id=fixture["fixture_id"],
        fixture_tree_sha256=fixture["snapshot"]["tree_sha256"],
        harness_policy_path="workspace/evals/stone_pickaxe_sp002_harness_policy.json",
        harness_policy_sha256=policy_hash,
    )
    report = verify_sp002_authorization(
        authorization,
        expected_scope="live_episode",
        current_head="3" * 40,
        parent_head=predecessor,
        fixture_manifest=fixture,
        fixture_path="workspace/evals/stone_pickaxe_sp002_fixture.json",
        fixture_sha256="2" * 64,
        harness_policy_path="workspace/evals/stone_pickaxe_sp002_harness_policy.json",
        harness_policy_sha256=policy_hash,
    )
    assert report["passed"]
    tampered = dict(authorization)
    tampered["automatic_retry_allowed"] = True
    assert not verify_sp002_authorization(
        tampered,
        expected_scope="live_episode",
        current_head="3" * 40,
        parent_head=predecessor,
        fixture_manifest=fixture,
        fixture_path="workspace/evals/stone_pickaxe_sp002_fixture.json",
        fixture_sha256="2" * 64,
        harness_policy_path="workspace/evals/stone_pickaxe_sp002_harness_policy.json",
        harness_policy_sha256=policy_hash,
    )["passed"]
    try:
        build_sp002_authorization(
            scope="live_episode",
            episode_id="../../escaped",
            authorization_predecessor=predecessor,
            fixture_path="workspace/evals/stone_pickaxe_sp002_fixture.json",
            fixture_sha256="2" * 64,
            fixture_id=fixture["fixture_id"],
            fixture_tree_sha256=fixture["snapshot"]["tree_sha256"],
            harness_policy_path=(
                "workspace/evals/stone_pickaxe_sp002_harness_policy.json"
            ),
            harness_policy_sha256=policy_hash,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe episode_id must be rejected")


def test_07_synthetic_sp002_episode_passes_full_machine_verifier():
    episode = _episode()
    report = verify_sp002_runtime_episode(episode)
    assert report["passed"]
    assert report["evidence_eligible"]
    assert episode["runtime_policy_id"] == SP002_RUNTIME_POLICY_ID
    assert report["metrics"]["material_delta"] == {"cobblestone": -3, "stick": -2}
    assert report["metrics"]["inventory_delta"] == {"stone_pickaxe": 1}
    transition = episode["transitions"][0]
    assert transition["crafting_table_interaction"]["observed"] is True
    assert transition["backend_result"]["single_attempt"] is True


def test_08_transient_stable_observation_fails_closed():
    report = verify_sp002_runtime_episode(_episode(stable_pickaxe=0))
    assert not report["passed"]
    assert "stable_stone_pickaxe" in report["criteria_issues"]


def test_09_backend_retry_is_runtime_ineligible_even_if_inventory_succeeds():
    report = verify_sp002_runtime_episode(_episode(attempts=2, retry_count=1))
    assert not report["passed"]
    assert "backend_single_craft_attempt" in report["eligibility_issues"]
    no_craft = verify_sp002_runtime_episode(_episode(include_craft=False))
    assert not no_craft["passed"]
    assert "backend_single_craft_attempt" in no_craft["eligibility_issues"]


def test_10_missing_material_consumption_fails_machine_criteria():
    episode = _episode()
    episode["transitions"][0]["post_observation"]["inventory"]["stick"] = 1
    report = verify_sp002_runtime_episode(episode)
    assert not report["passed"]
    assert "stick_consumption_exact" in report["criteria_issues"]


def test_11_planner_prompt_and_runtime_config_are_sp002_fail_closed():
    planner = object.__new__(Planner)
    planner._expected_plan_kind = "root"
    prompt = Planner._stone_pickaxe_system_prompt(planner)
    assert "sp002: on a root planning call, copy the exact two-node" in prompt
    assert "Emit exactly one action" in prompt
    plan = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "root",
        "goal": SP002_GOAL,
        "status": "planning",
        "reasoning": "Craft once from the exact observed fixture.",
        "subtasks": [
            {
                "id": "verify_inputs",
                "title": "Verify exact materials and table",
                "type": "verify",
                "priority": 1,
                "preconditions": {},
                "success_criteria": {"observed": True},
                "depends_on": [],
            },
            {
                "id": "craft_pickaxe",
                "title": "Craft exactly one stone pickaxe",
                "type": "craft",
                "priority": 1,
                "preconditions": {"inventory": {"cobblestone": 3, "stick": 2}},
                "success_criteria": {"inventory": {"stone_pickaxe": 1}},
                "depends_on": ["verify_inputs"],
            },
        ],
        "actions": [{
            "type": "craft",
            "parameters": {"item": "stone_pickaxe", "count": 1},
        }],
    }
    assert Planner._validate_stone_pickaxe_plan_envelope(
        plan, SP002_GOAL, "root"
    )["passed"]
    config = build_runtime_config(
        api_key="offline",
        log_dir="logs/offline-sp002",
        host="127.0.0.1",
        port=25565,
        username="Singularity",
        bridge_host="127.0.0.1",
        bridge_port=30000,
    )
    assert config.skill_execution_mode == "off"
    assert config.enable_skill_candidate_extraction is False
    assert config.enable_memory_persistence is False
    bridge_status = {
        "success": True,
        "configured": True,
        "profile": "m4-fixed-v1",
        "minecraft_version": "1.20.4",
        "observed_minecraft_version": "1.20.4",
        "seed": "12345",
        "episode_id": "sp002-offline",
        "level_name": "sp002-offline_world",
        "server_jar_sha256": PROTOCOL["environment"]["server_jar_sha256"],
        "runtime_controls": {"skill_execution_mode": "off"},
        "errors": [],
    }
    assert audit_sp002_bridge_protocol_status(
        bridge_status,
        episode_id="sp002-offline",
        level_name="sp002-offline_world",
    )["passed"]
    bridge_status["configured"] = False
    assert not audit_sp002_bridge_protocol_status(
        bridge_status,
        episode_id="sp002-offline",
        level_name="sp002-offline_world",
    )["passed"]


def test_12_launcher_and_evidence_boundaries_forbid_retry_and_sp003():
    launcher = (ROOT / "scripts/stone-pickaxe-sp002-runtime.ps1").read_text(
        encoding="utf-8"
    )
    legacy_launcher = (ROOT / "scripts/stone-pickaxe-runtime.ps1").read_text(
        encoding="utf-8"
    )
    attributes = (ROOT / "workspace/evals/sp002_runs/.gitattributes").read_text(
        encoding="utf-8"
    )
    assert '"RunSP002"' in launcher
    assert "--craft-max-attempts" in launcher
    assert '"--craft-max-attempts", "1"' in launcher
    assert '$levelName = "${episodeId}_world"' in launcher
    assert "The current commit must contain only the one-time SP-002 authorization" in launcher
    assert "automatic retry is forbidden" in launcher
    assert "*.json binary" in attributes
    assert '"RunSP002"' not in legacy_launcher
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert policy["automatic_retry_allowed"] is False
    assert policy["current_state"]["live_authorization"] is False
    assert policy["current_state"]["sp003_unlocked"] is False
    assert policy["capability_policy"]["capability_upgrade_allowed"] is False


def test_13_prior_protocol_and_promotion_evidence_remain_byte_identical():
    expected = {
        "workspace/evals/stone_pickaxe_protocol.json": "e0722422b62da73d9c1c1c449ae6a3392913125e85c72adad8fa2c9bd0970006",
        "workspace/evals/sp001_skill_evaluation_v5/acquire_cobblestone_paired_evaluation_v5.json": "e1d064c3b93eb92a3eef9c495fb8411b99632eadd183738c99682e36e6c2586d",
        "workspace/evals/sp001_skill_promotion/acquire_cobblestone_executable_promotion.json": "d03a4e9790d714504719f522b0e4ac1a0c0f80a02a9dbc1168caedbdb3aeec62",
        "workspace/evals/sp001_skill_promotion/acquire_cobblestone_runtime_default_gate.json": "6a91887265adc3a8979a59636d3235da5cd0d13b487869308d029752a63800d7",
    }
    for relative, digest in expected.items():
        assert _sha256(ROOT / relative) == digest


def test_14_fixture_terminal_action_contract_is_prompted_and_fails_closed():
    planner = Planner(object(), TaskSystem(), protocol=PROTOCOL["id"])
    planner._expected_plan_kind = "continuation"
    observation = _raw_observation(table=False)
    observation["stone_pickaxe_runtime_mode"] = "prepare_sp002_fixture"

    system_prompt = planner._stone_pickaxe_system_prompt()
    user_prompt = planner._build_planning_prompt(SP002_GOAL, observation, "")
    assert "Every response containing an action must use status planning" in system_prompt
    assert "completion_ready=false" in user_prompt
    assert "status=complete is forbidden" in user_prompt
    assert "An action's predicted result does not satisfy this gate" in user_prompt

    retained_terminal_shape = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "continuation",
        "goal": SP002_GOAL,
        "status": "complete",
        "reasoning": "Approach the table and finish the fixture.",
        "subtasks": [],
        "actions": [{
            "type": "move_to",
            "parameters": {"x": 95, "y": 132, "z": -32},
        }],
    }
    report = Planner._validate_stone_pickaxe_plan_envelope(
        retained_terminal_shape,
        SP002_GOAL,
        "continuation",
    )
    assert not report["passed"]
    assert report["issues"] == ["terminal_actions_forbidden"]

    ready_observation = _raw_observation(table=True)
    ready_observation["stone_pickaxe_runtime_mode"] = "prepare_sp002_fixture"
    ready_prompt = planner._build_planning_prompt(SP002_GOAL, ready_observation, "")
    assert "completion_ready=true" in ready_prompt
    assert "return status=complete with actions=[]" in ready_prompt


def test_15_fixture_root_graph_contract_is_prompted_and_fails_closed():
    planner = Planner(object(), TaskSystem(), protocol=PROTOCOL["id"])
    planner._expected_plan_kind = "root"
    observation = _raw_observation(table=False)
    observation["stone_pickaxe_runtime_mode"] = "prepare_sp002_fixture"

    system_prompt = planner._stone_pickaxe_system_prompt()
    user_prompt = planner._build_planning_prompt(SP002_GOAL, observation, "")
    assert "copy the exact two-node subtask graph" in system_prompt
    assert "root_graph_required=true" in user_prompt
    assert '"id":"acquire_cobblestone"' in user_prompt
    assert '"id":"observe_crafting_table"' in user_prompt
    assert '"depends_on":["acquire_cobblestone"]' in user_prompt
    assert "Never return subtasks=[] on this root planning call" in user_prompt
    assert "only the one next grounded action" in user_prompt

    retained_root_shape = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "root",
        "goal": SP002_GOAL,
        "status": "planning",
        "reasoning": "Equip the observed wooden pickaxe first.",
        "subtasks": [],
        "actions": [{
            "type": "equip",
            "parameters": {"item": "wooden_pickaxe"},
        }],
    }
    report = Planner._validate_stone_pickaxe_plan_envelope(
        retained_root_shape,
        SP002_GOAL,
        "root",
    )
    assert not report["passed"]
    assert report["issues"] == [
        "root_dependency_edge_missing",
        "root_subtask_count_out_of_bounds",
    ]

    contract_valid_shape = dict(retained_root_shape)
    contract_valid_shape["subtasks"] = [
        {
            "id": "acquire_cobblestone",
            "title": "Acquire exactly three cobblestone",
            "type": "gather",
            "priority": 1,
            "preconditions": {"inventory": {"wooden_pickaxe": 1}},
            "success_criteria": {"inventory": {"cobblestone": 3}},
            "depends_on": [],
        },
        {
            "id": "observe_crafting_table",
            "title": "Observe an interactive crafting table",
            "type": "verify",
            "priority": 1,
            "preconditions": {"inventory": {"cobblestone": 3}},
            "success_criteria": {"nearby_block_present": "crafting_table"},
            "depends_on": ["acquire_cobblestone"],
        },
    ]
    valid_report = Planner._validate_stone_pickaxe_plan_envelope(
        contract_valid_shape,
        SP002_GOAL,
        "root",
    )
    assert valid_report["passed"]

    planner._expected_plan_kind = "continuation"
    continuation_prompt = planner._build_planning_prompt(SP002_GOAL, observation, "")
    assert "root_graph_required=false" in continuation_prompt
    assert "This call must return subtasks=[]" in continuation_prompt


def test_16_live_root_graph_contract_replays_retained_failure():
    planner = Planner(object(), TaskSystem(), protocol=PROTOCOL["id"])
    planner._expected_plan_kind = "root"
    observation = _raw_observation(table=True)
    observation["stone_pickaxe_runtime_mode"] = "sp002"

    system_prompt = planner._stone_pickaxe_system_prompt()
    user_prompt = planner._build_planning_prompt(SP002_GOAL, observation, "")
    assert "sp002: on a root planning call, copy the exact two-node" in system_prompt
    assert "SP-002 live root graph gate: root_graph_required=true" in user_prompt
    assert '"id":"verify_inputs"' in user_prompt
    assert '"id":"craft_stone_pickaxe"' in user_prompt
    assert '"depends_on":["verify_inputs"]' in user_prompt
    assert "Never return subtasks=[] on this root planning call" in user_prompt
    assert "only craft stone_pickaxe count=1" in user_prompt

    retained_root_shape = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "root",
        "goal": SP002_GOAL,
        "status": "planning",
        "reasoning": "Craft exactly one stone pickaxe from the verified fixture.",
        "subtasks": [],
        "actions": [{
            "type": "craft",
            "parameters": {"item": "stone_pickaxe", "count": 1},
        }],
    }
    report = Planner._validate_stone_pickaxe_plan_envelope(
        retained_root_shape,
        SP002_GOAL,
        "root",
    )
    assert not report["passed"]
    assert report["issues"] == [
        "root_dependency_edge_missing",
        "root_subtask_count_out_of_bounds",
    ]

    contract_valid_shape = dict(retained_root_shape)
    contract_valid_shape["subtasks"] = [
        {
            "id": "verify_inputs",
            "title": "Verify exact materials and crafting table",
            "type": "verify",
            "priority": 1,
            "preconditions": {},
            "success_criteria": {
                "inventory": {"cobblestone": 3, "stick": 2},
                "nearby_block_present": "crafting_table",
            },
            "depends_on": [],
        },
        {
            "id": "craft_stone_pickaxe",
            "title": "Craft exactly one stone pickaxe",
            "type": "craft",
            "priority": 1,
            "preconditions": {
                "inventory": {"cobblestone": 3, "stick": 2},
                "nearby_block_present": "crafting_table",
            },
            "success_criteria": {"inventory": {"stone_pickaxe": 1}},
            "depends_on": ["verify_inputs"],
        },
    ]
    valid_report = Planner._validate_stone_pickaxe_plan_envelope(
        contract_valid_shape,
        SP002_GOAL,
        "root",
    )
    assert valid_report["passed"]

    planner._expected_plan_kind = "continuation"
    continuation_prompt = planner._build_planning_prompt(
        SP002_GOAL,
        observation,
        "",
    )
    assert "SP-002 live root graph gate: root_graph_required=false" in continuation_prompt
    assert "This call must return subtasks=[]" in continuation_prompt


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"PASS: {len(tests)} SP-002 runtime harness cases")
