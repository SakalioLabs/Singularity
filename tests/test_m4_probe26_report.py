import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe26_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe26_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_probe26_report_binds_grok_progress_and_json_envelope_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 26
    assert report["task_id"] == "BM-012"
    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["authorization"]["consumed"] is True
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
    actions = [event for event in events if event.get("type") == "action"]
    invalid_calls = [call for call in calls if not call["data"]["schema_valid"]]

    assert len(calls) == 33
    assert len(invalid_calls) == 4
    assert len(actions) == 29
    assert all(call["data"]["real_llm_call"] is True for call in calls)
    assert all(call["data"]["response_byte_count"] > 0 for call in invalid_calls)
    assert all(
        call["data"]["transport_evidence"]["attempt_count"] == 1
        and call["data"]["transport_evidence"]["retry_count"] == 0
        for call in calls
    )

    assert report["episode_result"]["schema_valid_planner_call_count"] == 29
    assert report["episode_result"]["schema_invalid_planner_call_count"] == 4
    assert report["episode_result"]["successful_action_count"] == 27
    assert report["behavioral_progression"]["empty_hand_to_logs"] is True
    assert report["behavioral_progression"]["logs_to_planks"] is True
    assert report["behavioral_progression"]["planks_to_crafting_table"] is False
    maximum_inventory = report["episode_result"]["maximum_inventory"]
    assert maximum_inventory["oak_log"] == 6
    assert maximum_inventory["oak_planks"] == 24
    assert maximum_inventory["wooden_pickaxe"] == 0
    assert maximum_inventory["stone_pickaxe"] == 0
    assert report["planner_failure"]["provider_authentication_error_count"] == 0
    assert report["offline_repair"]["exact_full_response_code_fence_only"] is True
    assert report["decision"]["value"] == "behavioral_ineligible"
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False
