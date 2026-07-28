import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe56_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_probe56_authorization_binds_published_gemini_gate():
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))
    assert authorization["type"] == "m4_live_probe_authorization"
    assert authorization["model"] == "gemini-3.6-flash-high"
    assert authorization["task_id"] == "BM-014"
    assert authorization["probe_number"] == 56
    assert authorization["authorized"] is True
    assert authorization["one_use"] is True
    assert authorization["maximum_episode_count"] == 1
    assert authorization["maximum_retry_count"] == 0
    assert authorization["visible_observer_required"] is True
    assert authorization["observer_read_only_required"] is True
    assert authorization["consumed"] is False
    assert authorization["next_authorization"] is False
    assert authorization["probe_57_authorized"] is False
    assert authorization["protocol_sha256"] == _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_protocol.json"
    )
    assert authorization["task_contract_sha256"] == _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_bm014_protocol.json"
    )
    for path_key, hash_key in (
        ("provider_migration_path", "provider_migration_sha256"),
        ("prior_probe_report_path", "prior_probe_report_sha256"),
        (
            "prior_probe_consumed_authorization_path",
            "prior_probe_consumed_authorization_sha256",
        ),
    ):
        assert authorization[hash_key] == _sha256(ROOT / authorization[path_key])
    assert subprocess.check_output(
        ["git", "rev-parse", authorization["gate_remote_readback"]["ref"]],
        cwd=ROOT,
        text=True,
    ).strip() == authorization["gate_parent_commit"]
    assert subprocess.check_output(
        ["git", "show", "-s", "--format=%T", authorization["gate_parent_commit"]],
        cwd=ROOT,
        text=True,
    ).strip() == authorization["gate_tree"]
