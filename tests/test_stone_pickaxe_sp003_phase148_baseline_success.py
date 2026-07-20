from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EPISODE_ID = "sp003_baseline_20260720_211838_phase148"
RUN_DIR = ROOT / "workspace/evals/sp003_runs" / EPISODE_ID
SESSION_ID = "b4e8b2a0-9af"
AUTHORIZATION_COMMIT = "3056719f3ffe2628390a319e47ac2cd58cef82e6"
MANIFEST_SHA256 = (
    "55c9026a83e01b546a2f6dc45b1b4a337cd2510b20307b7136e28dce26e70430"
)
EXPECTED_HASHES = {
    "audit.json": "c1c99a22fbfe9adef3d6c0b399977c3d36a5d0d299af60f8e12acbca35c6793d",
    "authorization.json": "17fd37eb0107dad7394b690f07f81b9dc711d52f73dac2f55d8d3725e0e4db61",
    "authorization_consumption.json": "c0fa1044cd0937d5fe40ae64c3095042996754854ede4e7d28e6b4a46c666725",
    "episode.json": "d272a2030d069fef014fe57af4f86ba62042276e2379083b22e393ae02ca32bf",
    "manifest.json": MANIFEST_SHA256,
    "preflight.json": "17e7235dc1a6799aa1f05eed26f6a88dc8c339ebdab50830df91b53a3b30a4bb",
    "protocol_status.json": "013172fafb6c04560e6c314c82764d702275cc05486ad733cf9769515a8da8e9",
    "reset.json": "f4de5471798cd57c42ab13b64e42c8f853790dbd333aeed8fd7809746577781b",
    "reset_audit.json": "a8c8be85aee67d4e2231146b3de369e7e892637307cbe12d4bf4d28e29e3aade",
    "session.json": "c1693af42444587cf163547322db5f7911c99fcbbeaa5d3dbfa0fbdd2eaf7e52",
    f"session_{SESSION_ID}.jsonl": (
        "53358b68b264316297c6afca0642fc4df9a3cbf47ec9239df9001516b54a569d"
    ),
    f"session_{SESSION_ID}_summary.json": (
        "f23ebde0a336d53c1b1993fbd41d7016380b21585f41169582038ecf76c137ae"
    ),
    "verification.json": (
        "cfc5962d25cc1c0daf271553596ec008995fb1a6a0667f49ce75b1af8d06e671"
    ),
}


def _json(name: str) -> dict:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase148_manifest_binds_all_thirteen_immutable_artifacts() -> None:
    manifest = _json("manifest.json")

    assert set(path.name for path in RUN_DIR.iterdir()) == set(EXPECTED_HASHES)
    for name, expected in EXPECTED_HASHES.items():
        assert _sha256(RUN_DIR / name) == expected
    assert manifest["passed"] is True
    assert manifest["evidence_eligible"] is True
    assert manifest["episode_id"] == EPISODE_ID
    assert manifest["session_id"] == SESSION_ID
    assert manifest["arm"] == "baseline"
    assert manifest["replicate_id"] == "baseline"
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert manifest["counts_toward_capability"] is False
    assert manifest["counts_toward_m4"] is False
    assert len(manifest["files"]) == 12
    for item in manifest["files"]:
        path = ROOT / item["path"]
        assert path.parent == RUN_DIR
        assert _sha256(path) == item["sha256"]


def test_phase148_authorization_reset_and_preflight_are_exact() -> None:
    consumption = _json("authorization_consumption.json")
    preflight = _json("preflight.json")

    assert consumption["authorization_commit"] == AUTHORIZATION_COMMIT
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False
    assert consumption["counts_toward_capability"] is False
    assert consumption["counts_toward_m4"] is False
    assert preflight["passed"] is True
    assert preflight["fresh_level"] is True
    assert preflight["bm012_terminal_started"] is False
    assert all(preflight["authorization_preflight"]["checks"].values())
    assert all(preflight["reset_audit"]["checks"].values())
    assert all(preflight["initial_state_audit"]["checks"].values())
    assert preflight["initial_state_audit"]["inventory"] == {}
    assert preflight["runtime_controls"]["skill_execution_mode"] == "off"
    assert preflight["runtime_controls"]["automatic_retry"] is False


def test_phase148_machine_verifier_accepts_the_strict_baseline() -> None:
    verification = _json("verification.json")

    assert verification["passed"] is True
    assert verification["criteria_passed"] is True
    assert verification["evidence_eligible"] is True
    assert verification["criteria_issues"] == []
    assert verification["eligibility_issues"] == []
    assert len(verification["criteria"]) == 51
    assert all(verification["criteria"].values())
    metrics = verification["metrics"]
    assert metrics == {
        "action_count": 23,
        "cycles": 23,
        "elapsed_s": 146.235,
        "log_source_removal_count": 3,
        "surface_clearance_removal_count": 5,
        "stone_source_removal_count": 3,
        "raw_action_failure_count": 0,
        "reconciled_action_failure_count": 0,
        "unreconciled_action_failure_count": 0,
        "delayed_log_pickup_reconciliation_count": 0,
        "action_result_log_pickup_reconciliation_count": 0,
        "observation_log_pickup_reconciliation_count": 0,
        "selected_skill_count": 0,
        "local_attribution_count": 0,
    }
    assert verification["components"]["sp001"]["passed"] is True
    assert verification["components"]["sp002"]["passed"] is True
    assert verification["task_graph"]["passed"] is True
    assert all(verification["task_graph"]["checks"].values())
    assert verification["counts_toward_sp003_lifecycle"] is True
    assert verification["counts_toward_capability"] is False
    assert verification["counts_toward_m4"] is False


def test_phase148_episode_has_exact_actions_graph_and_terminal_inventory() -> None:
    episode = _json("episode.json")

    assert episode["goal_result"]["completed"] is True
    assert episode["goal_result"]["termination_reason"] == "goal_verified"
    assert episode["goal_result"]["deadline_eligible"] is True
    assert episode["action_count"] == 23
    assert episode["action_type_counts"] == {
        "move_to": 5,
        "dig:oak_log": 3,
        "craft:oak_planks": 1,
        "craft:stick": 1,
        "craft:crafting_table": 1,
        "dig:grass_block": 1,
        "dig:dirt": 4,
        "place:crafting_table": 1,
        "craft:wooden_pickaxe": 1,
        "equip:wooden_pickaxe": 1,
        "dig:stone": 3,
        "craft:stone_pickaxe": 1,
    }
    assert episode["raw_action_failures"] == []
    assert episode["unreconciled_action_failures"] == []
    assert episode["unexpected_actions"] == []
    assert episode["forbidden_interventions"] == []
    assert episode["initial_observation"]["inventory"] == {}
    assert episode["stable_observation"]["inventory"] == {
        "stone_pickaxe": 1,
        "oak_planks": 3,
        "dirt": 5,
        "wooden_pickaxe": 1,
    }
    tasks = episode["task_graph"]["tasks"]
    assert len(tasks) == 5
    assert {task["status"] for task in tasks} == {"completed"}


def test_phase148_trace_has_twenty_three_real_zero_retry_calls_and_actions() -> None:
    rows = [
        json.loads(line)
        for line in (RUN_DIR / f"session_{SESSION_ID}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    planner_calls = [row["data"] for row in rows if row["type"] == "llm_planner_call"]
    actions = [row["data"] for row in rows if row["type"] == "action"]

    assert len(planner_calls) == 23
    assert Counter(call["plan_kind"] for call in planner_calls) == {
        "root": 1,
        "continuation": 22,
    }
    assert all(call["real_llm_call"] is True for call in planner_calls)
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(call["error"] == "" for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        for call in planner_calls
    )
    assert len(actions) == 23
    assert all(action["result"]["success"] is True for action in actions)
    summary = _json(f"session_{SESSION_ID}_summary.json")
    assert summary["action_count"] == 23
    assert summary["error_count"] == 0
    assert summary["intervention_metrics"]["skill_selected_count"] == 0
    assert summary["action_verification_metrics"][
        "action_verification_blocked_count"
    ] == 0


def test_phase148_ledger_counts_one_baseline_and_holds_candidate_gate() -> None:
    ledger = json.loads(
        (ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    sp003 = ledger["current_gate"]["SP-003"]
    successes = [
        item for item in ledger["eligible_successes"] if item["task_id"] == "SP-003"
    ]
    gate = ledger["next_required_gate"]

    assert sp003["eligible_live_successes"] == 1
    assert sp003["baseline_successes"] == 1
    assert sp003["eligible_candidate_successes"] == 0
    assert len(successes) == 1
    assert successes[0]["episode_id"] == EPISODE_ID
    assert successes[0]["manifest_sha256"] == MANIFEST_SHA256
    assert gate["id"] == (
        "sp003_phase_148_baseline_evidence_commit_push_then_phase_149_"
        "candidate_r1_parent_bound_one_use_authorization"
    )
    assert gate["authorization"] is False
    assert gate["arm"] == "candidate"
    assert gate["replicate_id"] == "r1"
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert ledger["live_authorization"] is False
