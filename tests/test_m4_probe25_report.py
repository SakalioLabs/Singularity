import hashlib
import json
import tarfile
from pathlib import Path
from pathlib import PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe25_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe25_authorization.json"
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


def test_m4_probe25_report_binds_stale_credential_failure_and_evidence():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 25
    assert report["task_id"] == "BM-012"
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
    assert len(calls) == 24
    assert not actions
    assert all(call["data"]["real_llm_call"] is False for call in calls)
    assert all(call["data"]["schema_valid"] is False for call in calls)
    assert all(call["data"]["response_byte_count"] == 0 for call in calls)
    assert all(
        call["data"]["provider_metadata"]["error_type"] == "AuthenticationError"
        for call in calls
    )
    assert all(
        call["data"]["transport_evidence"]["attempt_count"] == 1
        and call["data"]["transport_evidence"]["retry_count"] == 0
        for call in calls
    )

    assert report["planner_failure"]["http_status"] == 401
    assert report["planner_failure"]["provider_health_before_episode"] is True
    assert report["planner_failure"]["selected_runtime_credential_health"] is False
    assert report["runtime_repair"]["runs_before_minecraft_start"] is True
    assert report["decision"]["value"] == "infrastructure_ineligible"
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False
    assert report["eligibility"]["pass_count"] == 62
    assert report["eligibility"]["check_count"] == 74
