import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from singularity.action.verifier import ActionVerifier
from singularity.core.agent import Agent


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "m4_bm014_furnace_place_local_snapshot_repair_audit.json"
)
REPAIR_COMMIT = "0d97e4314c454fa8408b6ad56d8aff263f07d28e"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_blob(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{Path(path).as_posix()}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _git_json(commit: str, path: str) -> dict:
    return json.loads(_git_blob(commit, path).decode("utf-8"))


def _audit() -> dict:
    return _json(AUDIT_PATH)


def _m4_phase(capability: dict) -> dict:
    return next(phase for phase in capability["phases"] if phase["id"] == "M4")


def _bm014(capability: dict) -> dict:
    return next(
        benchmark
        for benchmark in _m4_phase(capability)["benchmarks"]
        if benchmark["task_id"] == "BM-014"
    )


def _probe51_machine_state() -> dict:
    blocks = []
    for x in range(117, 120):
        for y in range(122, 126):
            for z in range(-51, -48):
                blocks.append(
                    {
                        "name": "stone",
                        "type": 1,
                        "position": {"x": x, "y": y, "z": z},
                        "collision": "block",
                        "solid": True,
                        "passable": False,
                    }
                )

    replacements = {
        (118, 122, -49): {
            "name": "crafting_table",
            "type": 151,
            "collision": "block",
            "solid": True,
            "passable": False,
        },
        (118, 123, -49): {
            "name": "air",
            "type": 0,
            "collision": "empty",
            "solid": False,
            "passable": True,
        },
    }
    for block in blocks:
        position = block["position"]
        replacement = replacements.get(
            (position["x"], position["y"], position["z"])
        )
        if replacement:
            block.update(replacement)
    return {
        "success": True,
        "type": "m4_shelter_machine_snapshot",
        "schema_version": 1,
        "source": "mineflayer_world_state",
        "player_position": {"x": 118.5, "y": 123, "z": -49.5},
        "player_cell": {"x": 118, "y": 123, "z": -50},
        "blocks": blocks,
        "nearby_hostiles": [],
        "observed_at_ms": 1785126143000,
    }


def _agent() -> Agent:
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol="m4-fixed-v1")
    agent._m4_task_id = "BM-014"
    agent.session_logger = SimpleNamespace(events=[])
    return agent


def test_furnace_place_repair_audit_binds_probe51_consumed_auth_and_sources():
    audit = _audit()
    assert audit["type"] == "m4_bm014_furnace_place_local_snapshot_repair_audit"
    assert audit["profile"] == "m4-fixed-v1"
    assert audit["task_id"] == "BM-014"
    assert audit["task_contract_id"] == "m4-bm014-iron-pickaxe-contract-v1"
    assert audit["task_contract_sha256"] == _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_bm014_protocol.json"
    )

    bindings = audit["bindings"]
    report_path = ROOT / bindings["probe_51_report_path"]
    authorization_path = ROOT / bindings["probe_51_authorization_path"]
    assert bindings["probe_51_report_sha256"] == _sha256(report_path)
    assert bindings["probe_51_consumed_authorization_sha256"] == _sha256(
        authorization_path
    )
    capability_blob = _git_blob(
        REPAIR_COMMIT,
        bindings["capability_evidence_path"],
    )
    assert bindings["capability_evidence_sha256"] == _sha256_bytes(capability_blob)
    for key, relative_path in audit["source_paths"].items():
        assert audit["source_sha256"][key] == _sha256_bytes(
            _git_blob(REPAIR_COMMIT, relative_path)
        )

    report = _json(report_path)
    authorization = _json(authorization_path)
    assert authorization["consumed"] is True
    assert authorization["consumed_at"] == "autonomous_start"
    assert authorization["consumed_by_episode"] == (
        bindings["probe_51_consumed_episode_id"]
    )
    assert authorization["consumed_session_id"] == (
        bindings["probe_51_consumed_session_id"]
    )
    assert authorization["consumed_event_line"] == (
        bindings["probe_51_consumed_event_line"]
    )
    assert report["authorization"]["consumed_sha256"] == (
        bindings["probe_51_consumed_authorization_sha256"]
    )
    assert report["episode_id"] == bindings["probe_51_consumed_episode_id"]
    assert report["session_id"] == bindings["probe_51_consumed_session_id"]


def test_furnace_place_repair_audit_records_complete_bounded_fail_closed_design():
    audit = _audit()
    repair = audit["offline_repair"]
    complete = repair["complete_snapshot"]
    candidates = repair["candidate_derivation"]
    execution = repair["execution_path_gates"]
    node = repair["node_mutation_time_gates"]

    assert repair["policy_id"] == (
        "m4-bm013-bm014-furnace-place-local-snapshot-v1"
    )
    assert complete["required_machine_snapshot_check"] == "machine_snapshot"
    assert complete["required_machine_snapshot_passed"] is True
    assert complete["required_machine_check_evidence"] == {
        "expected_snapshot_position_count": 36,
        "observed_snapshot_position_count": 36,
        "duplicate_positions": [],
    }
    assert complete["code_requires_exact_raw_block_count"] is True
    assert (
        complete["x_cell_count"]
        * complete["y_cell_count"]
        * complete["z_cell_count"]
        == complete["required_cell_count"]
        == 36
    )
    assert complete["duplicate_positions_allowed"] is False
    assert complete["single_snapshot_binding"] is True
    assert complete["player_position_and_cell_required"] is True
    assert complete["snapshot_and_current_player_same_cell_required"] is True
    assert complete["positive_observed_at_ms_required"] is True
    assert complete["maximum_snapshot_age_ms"] == 5000
    assert candidates["maximum_candidate_count"] == 27
    assert candidates["reference_and_target_from_same_snapshot"] is True
    assert candidates["reference_required_solid"] is True
    assert candidates["target_required_replaceable"] is True
    assert candidates["target_required_solid"] is False
    assert candidates["target_required_passable"] is True
    assert candidates["exact_integral_reference_target_pair_required"] is True
    assert (
        candidates["target_outside_snapshot_and_current_player_collision_union"]
        is True
    )
    assert candidates["capped_nearby_blocks_fallback"] is False
    assert execution["action_verifier_exact_snapshot_pair_hard_required"] is True
    assert execution["action_verifier_task_scope"] == ["BM-013", "BM-014"]
    assert execution["bm012_generic_furnace_place_behavior_unchanged"] is True
    assert execution["missing_forged_stale_or_unbound_snapshot_rejected"] is True
    assert execution["target_not_observed_occupied_acceptance_possible"] is False
    assert execution["missing_candidate_returns_bounded_block"] is True
    assert execution["bounded_block_action_count"] == 0
    assert execution["full_think_fallback_suppressed"] is True
    assert execution["suppressed_execution_paths"] == [
        "learned_skill",
        "bm012_machine_step",
        "llm_plan",
        "rule_plan",
        "visual_action_grounding",
    ]
    assert audit["offline_validation"]["focused_python_pass_count"] == 130
    assert audit["offline_validation"]["selected_python_pass_count"] == 214
    assert audit["offline_validation"]["selected_python_suite_file_count"] == 14
    assert audit["offline_validation"]["selected_node_internal_case_pass_count"] == 19
    covered = audit["offline_validation"]["covered_boundaries"]
    assert (
        "the ActionVerifier hard-requires the exact same-snapshot pair and records target:air"
        in covered
    )
    assert (
        "snapshot-time and current player collision cells are unioned before selection and verification"
        in covered
    )
    assert (
        "no valid candidate returns a zero-action bounded block before learned, BM-012, LLM, rule, or visual fallback execution"
        in covered
    )

    assert node["changed_by_repair"] is False
    assert node["server_sha256"] == _sha256(ROOT / node["server_path"])
    assert node["authoritative_target_block_at_before_mutation"] is True
    assert node["occupied_target_rejected_before_equip_or_mutation"] is True
    assert node["player_collision_rejected_before_mutation"] is True
    assert node["post_place_target_block_observation_required"] is True
    node_source = (ROOT / node["server_path"]).read_text(encoding="utf-8")
    assert "const before = shelterBlockState(activeBot, targetPosition);" in node_source
    assert "if (before.solid)" in node_source
    assert "if (targetIntersectsPlayer)" in node_source
    assert "await activeBot.placeBlock(referenceBlock, new Vec3(0, 1, 0));" in node_source
    assert "const after = shelterBlockState(activeBot, targetPosition);" in node_source


def test_furnace_place_repair_audit_replays_probe51_exact_reference_and_target():
    audit = _audit()
    expected = audit["offline_repair"]["exact_probe_51_replay"]
    agent = _agent()
    machine_state = _probe51_machine_state()
    assert len(machine_state["blocks"]) == 36
    report = {
        "checks": [
            {
                "name": "machine_snapshot",
                "passed": True,
                "evidence": {
                    "expected_snapshot_position_count": 36,
                    "observed_snapshot_position_count": 36,
                    "duplicate_positions": [],
                },
            }
        ],
    }

    snapshot = agent._m4_bm013_bm014_local_place_candidate_snapshot(
        machine_state,
        report,
    )
    assert snapshot["machine_snapshot_passed"] is True
    assert snapshot["snapshot_position_count"] == 36
    assert snapshot["candidate_limit"] == 27
    assert snapshot["candidate_count"] <= 27
    placement = agent._m4_bm013_bm014_furnace_place_reference(
        {
            "position": machine_state["player_position"],
            "nearby_blocks": [
                {
                    "name": "crafting_table",
                    "position": {"x": 118, "y": 122, "z": -49},
                },
                {
                    "name": "stone",
                    "position": {"x": 119, "y": 124, "z": -49},
                },
            ],
            "m4_local_place_candidates": snapshot,
        }
    )
    assert placement["reference_position"] == expected["selected_reference_position"]
    assert placement["target_position"] == expected["selected_target_position"]
    assert placement["reference_block"]["name"] == "crafting_table"
    assert placement["target_block"]["name"] == "air"

    action = {
        "type": "place",
        "parameters": {
            "item": "furnace",
            **placement["reference_position"],
        },
    }
    decision = ActionVerifier().verify(
        action,
        {
            "position": machine_state["player_position"],
            "inventory": {"furnace": 1},
            "nearby_blocks": [],
            "m4_local_place_candidates": snapshot,
        },
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert decision.status == "accept"
    assert expected["action_verifier_target_evidence"] in decision.evidence


def test_furnace_place_repair_audit_is_offline_zero_of_three_and_probe52_locked():
    audit = _audit()
    report = _json(ROOT / audit["bindings"]["probe_51_report_path"])
    authorization = _json(
        ROOT / audit["bindings"]["probe_51_authorization_path"]
    )
    capability = _git_json(
        REPAIR_COMMIT,
        audit["bindings"]["capability_evidence_path"],
    )
    bm014 = _bm014(capability)
    m4 = _m4_phase(capability)
    decision = audit["decision"]

    assert audit["classification"] == "offline_repair"
    assert audit["counts_toward_bm014_success"] is False
    assert audit["counts_toward_capability"] is False
    assert report["offline_repair"]["counts_toward_bm014_success"] is False
    assert report["offline_repair"]["counts_toward_capability"] is False
    assert bm014["status"] == "failing"
    assert bm014["successes"] == decision["bm014_eligible_success_count"] == 0
    assert bm014["repeats_required"] == (
        decision["required_bm014_eligible_success_count"]
    ) == 3
    assert m4["status"] == "failing"
    assert decision["bm014_repeat_verified"] is False
    assert decision["probe_52_authorized"] is False
    assert decision["probe_52_locked"] is True
    assert authorization["probe_52_authorized"] is False
    assert report["decision"]["probe_52_authorized"] is False
