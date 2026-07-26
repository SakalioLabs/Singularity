import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe28_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe28_authorization.json"
REPAIR_AUDIT_PATH = (
    ROOT / "workspace" / "evals" / "m4_probe28_iron_window_repair_audit.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_probe28_report_binds_complete_stone_pickaxe_loop_without_iron_credit():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 28
    assert report["task_id"] == "BM-012"
    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["maximum_retry_count"] == 0
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    session_path = ROOT / report["evidence_paths"]["raw_session_jsonl"]
    events = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]
    verifications = [
        event for event in events if event.get("type") == "goal_verification"
    ]

    assert len(calls) == 33
    assert len(real_calls) == 31
    assert all(call["data"]["schema_valid"] is True for call in real_calls)
    assert all(
        call["data"]["transport_evidence"]["attempt_count"] == 1
        and call["data"]["transport_evidence"]["retry_count"] == 0
        for call in real_calls
    )
    assert len(actions) == 37
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 36
    assert len(verifications) == 9
    assert all(event["data"]["status"] == "achieved" for event in verifications)

    maximum_inventory = report["episode_result"]["maximum_inventory"]
    terminal_inventory = report["episode_result"]["terminal_inventory"]
    assert maximum_inventory["cobblestone"] == 12
    assert maximum_inventory["stone_pickaxe"] == 1
    assert terminal_inventory["stone_pickaxe"] == 1
    assert maximum_inventory["raw_iron"] == 0
    assert maximum_inventory["iron_ore"] == 0
    assert report["behavioral_progression"]["full_stone_pickaxe_loop_completed"] is True
    assert report["behavioral_progression"]["stone_pickaxe_to_iron"] is False
    assert report["goal_summary"]["goal_verification_unknown_count"] == 0
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False


def test_m4_probe28_iron_window_repair_is_bounded_and_source_bound():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    audit = json.loads(REPAIR_AUDIT_PATH.read_text(encoding="utf-8"))
    runtime_source = (
        ROOT / "src" / "singularity" / "core" / "runtime.py"
    ).read_text(encoding="utf-8")
    agent_source = (
        ROOT / "src" / "singularity" / "core" / "agent.py"
    ).read_text(encoding="utf-8")

    assert audit["source_probe_number"] == report["probe_number"] == 28
    assert audit["source_episode_id"] == report["episode_id"]
    assert audit["source_probe_report_sha256"] == _sha256(REPORT_PATH)
    assert audit["policy_id"] == "m4-bm012-bounded-dusk-iron-continuation-v1"
    assert audit["repair"]["preserve_exact_bm012_cobblestone_goal"] is True
    assert audit["repair"]["generic_twelve_cobblestone_override_rejected"] is True
    assert audit["repair"]["dusk_iron_continuation_enabled"] is True
    assert audit["repair"]["night_iron_continuation_enabled"] is False
    assert all(audit["fail_closed_boundaries"].values())
    assert audit["verification"]["probe_29_authorized"] is False
    assert audit["verification"]["counts_toward_bm012_success"] is False
    assert audit["verification"]["counts_toward_capability"] is False
    assert audit["policy_id"] in runtime_source
    assert "gather 3 cobblestone with the wooden pickaxe" in agent_source
    assert "collect 8 raw iron from iron ore with the stone pickaxe" in agent_source
