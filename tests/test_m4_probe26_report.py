import hashlib
import json
import tarfile
from pathlib import Path
from pathlib import PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe26_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe26_authorization.json"
ARCHIVE_ROOT = ROOT / "workspace" / "evals" / "m4_raw_archives"
EVIDENCE_PREFIX = "logs/benchmarks/m4/"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archived_evidence(report: dict) -> dict[str, bytes]:
    episode_id = report["episode_id"]
    assert episode_id not in {"", ".", ".."}
    assert PurePosixPath(episode_id).name == episode_id
    assert "\\" not in episode_id
    assert set(report["evidence_paths"]) == set(report["evidence_sha256"])

    member_to_evidence_name = {}
    for evidence_name, evidence_path in report["evidence_paths"].items():
        assert evidence_path.startswith(EVIDENCE_PREFIX)
        assert "\\" not in evidence_path
        member_name = evidence_path.removeprefix(EVIDENCE_PREFIX)
        assert member_name
        assert member_name == PurePosixPath(member_name).as_posix()
        assert all(part not in {"", ".", ".."} for part in member_name.split("/"))
        assert PurePosixPath(member_name).parts[0] == episode_id
        assert member_name not in member_to_evidence_name
        member_to_evidence_name[member_name] = evidence_name

    archive_path = ARCHIVE_ROOT / f"{episode_id}.tar.gz"
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        member_names = [member.name for member in members]
        assert len(member_names) == len(set(member_names))
        assert set(member_names) == set(member_to_evidence_name)
        assert all(member.isfile() for member in members)
        assert all("\\" not in member.name for member in members)
        assert all(
            member.name == PurePosixPath(member.name).as_posix()
            and all(part not in {"", ".", ".."} for part in member.name.split("/"))
            for member in members
        )

        evidence = {}
        for member in members:
            extracted = archive.extractfile(member)
            assert extracted is not None
            evidence[member_to_evidence_name[member.name]] = extracted.read()
    return evidence


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

    evidence = _archived_evidence(report)
    for name, expected_sha256 in report["evidence_sha256"].items():
        assert hashlib.sha256(evidence[name]).hexdigest() == expected_sha256

    events = [
        json.loads(line)
        for line in evidence["raw_session_jsonl"].decode("utf-8").splitlines()
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
