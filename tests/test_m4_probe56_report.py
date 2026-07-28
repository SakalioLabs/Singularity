import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe56_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe56_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_probe56_report_binds_consumption_failure_and_machine_evidence():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))
    issued = subprocess.check_output(
        [
            "git",
            "show",
            f"{report['authorization']['commit']}:workspace/evals/m4_probe56_authorization.json",
        ],
        cwd=ROOT,
    )
    assert hashlib.sha256(issued).hexdigest() == report["authorization"]["issued_sha256"]
    assert authorization["consumed"] is True
    assert authorization["consumed_at"] == "autonomous_start"
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    evidence_dir = ROOT / report["evidence_dir"]
    for name, expected in report["evidence_sha256"].items():
        assert _sha256(evidence_dir / name) == expected
    eligibility = json.loads((evidence_dir / "eligibility.json").read_text(encoding="utf-8"))
    result = json.loads((evidence_dir / "result.json").read_text(encoding="utf-8"))
    assert eligibility["eligible"] is False
    assert eligibility["success"] is False
    assert eligibility["issues"] == report["eligibility"]["issues"]
    assert result["completed"] is False
    assert result["terminal_state"]["inventory"]["raw_iron"] == 3
    assert result["terminal_state"]["inventory"]["coal"] == 1
    assert result["terminal_state"]["inventory"]["furnace"] == 1
    assert report["first_unrecovered_transition"]["classification"] == (
        "furnace_local_snapshot_candidate_gap"
    )
    assert report["first_unrecovered_transition"]["provider_transport_failure"] is False
    assert report["decision"]["probe_57_authorized"] is False
