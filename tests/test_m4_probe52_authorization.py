"""Bind the one-use Probe 52 authorization to the pushed Probe 51 repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe52_authorization.json"
AUTHORIZATION_COMMIT = "8e2c04a203e51b5152345be34d10b858ae7aa83f"
GATE_PARENT_COMMIT = "0d97e4314c454fa8408b6ad56d8aff263f07d28e"
GATE_TREE = "cae2c41d7d1a9cd8e410f550715c9bb4efe39ed9"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _git_revision(revision: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", revision],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def test_probe52_authorization_binds_pushed_gate_and_fixed_contract():
    authorization = _json(AUTHORIZATION_PATH)
    assert authorization["type"] == "m4_live_probe_authorization"
    assert authorization["profile"] == "m4-fixed-v1"
    assert authorization["task_id"] == "BM-014"
    assert authorization["probe_number"] == 52
    assert authorization["task_contract_id"] == (
        "m4-bm014-iron-pickaxe-contract-v1"
    )
    assert authorization["task_contract_sha256"] == hashlib.sha256(
        _git_blob(
            GATE_PARENT_COMMIT,
            "src/singularity/data/m4_bm014_protocol.json",
        )
    ).hexdigest()
    assert authorization["gate_parent_commit"] == GATE_PARENT_COMMIT
    assert authorization["gate_tree"] == GATE_TREE
    assert _git_revision(f"{GATE_PARENT_COMMIT}^{{tree}}") == GATE_TREE
    assert authorization["policy_id"] == (
        "m4-bm013-bm014-furnace-place-local-snapshot-v1"
    )


def test_probe52_authorization_hashes_probe51_repair_and_capability_state():
    authorization = _json(AUTHORIZATION_PATH)
    for path_key, hash_key in (
        ("prior_probe_report_path", "prior_probe_report_sha256"),
        ("prior_probe_report_test_path", "prior_probe_report_test_sha256"),
        (
            "prior_probe_consumed_authorization_path",
            "prior_probe_consumed_authorization_sha256",
        ),
        ("repair_audit_path", "repair_audit_sha256"),
        ("repair_audit_test_path", "repair_audit_test_sha256"),
        ("capability_evidence_path", "capability_evidence_sha256"),
    ):
        relative_path = authorization[path_key]
        expected = authorization[hash_key]
        assert expected == hashlib.sha256(
            _git_blob(GATE_PARENT_COMMIT, relative_path)
        ).hexdigest()

    for key, relative_path in authorization["repair_source_paths"].items():
        expected = authorization["repair_source_sha256"][key]
        assert expected == _sha256(ROOT / relative_path)
        assert expected == hashlib.sha256(
            _git_blob(GATE_PARENT_COMMIT, relative_path)
        ).hexdigest()

    validation = authorization["repair_validation"]
    assert validation["focused_python_pass_count"] == 130
    assert validation["selected_python_pass_count"] == 214
    assert validation["selected_python_suite_file_count"] == 14
    assert validation["selected_node_internal_case_pass_count"] == 19
    assert validation["complete_snapshot_required"] is True
    assert validation["exact_reference_target_pair_required"] is True
    assert validation["snapshot_and_current_player_collision_union_required"] is True
    assert validation["full_think_fallback_suppressed"] is True
    assert validation["bm012_control_unchanged"] is True
    assert authorization["gate_remote_readback"] == {
        "commit_parent_verified": True,
        "tree_verified": True,
        "expected_blob_count": 30,
        "blob_mismatch_count": 0,
    }

    report = _git_json(GATE_PARENT_COMMIT, authorization["prior_probe_report_path"])
    audit = _git_json(GATE_PARENT_COMMIT, authorization["repair_audit_path"])
    capability = _git_json(
        GATE_PARENT_COMMIT,
        authorization["capability_evidence_path"],
    )
    bm014 = next(
        benchmark
        for phase in capability["phases"]
        if phase["id"] == "M4"
        for benchmark in phase["benchmarks"]
        if benchmark["task_id"] == "BM-014"
    )
    assert report["episode_id"] == authorization["prior_probe_episode_id"]
    assert report["session_id"] == authorization["prior_probe_session_id"]
    assert report["level_name"] == authorization["prior_probe_level_name"]
    assert report["decision"]["bm014_attempt_count_after"] == 1
    assert report["decision"]["bm014_failure_count_after"] == 1
    assert report["decision"]["bm014_success_count_after"] == 0
    assert report["decision"]["remaining_success_count"] == 3
    assert report["decision"]["probe_52_authorized"] is False
    assert audit["decision"]["repair_offline_gate_passed"] is True
    assert audit["decision"]["offline_only"] is True
    assert audit["decision"]["bm014_eligible_success_count"] == 0
    assert audit["decision"]["probe_52_locked"] is True
    assert bm014["attempts"] == authorization["prior_bm014_attempt_count"] == 1
    assert bm014["failures"] == authorization["prior_bm014_failure_count"] == 1
    assert bm014["successes"] == authorization["prior_bm014_eligible_success_count"] == 0
    assert bm014["repeats_required"] == (
        authorization["required_bm014_eligible_success_count"]
    ) == 3
    assert bm014["status"] == authorization["bm014_status_before_probe"] == "failing"
    assert next(
        phase for phase in capability["phases"] if phase["id"] == "M4"
    )["status"] == authorization["m4_status_before_probe"] == "failing"


def test_probe52_authorization_was_issued_unconsumed_then_consumed_at_jsonl_line_2():
    authorization = _json(AUTHORIZATION_PATH)
    issued = _git_json(
        AUTHORIZATION_COMMIT,
        AUTHORIZATION_PATH.relative_to(ROOT).as_posix(),
    )
    consumed_fields = {
        "consumed_by_episode",
        "consumed_session_id",
        "consumed_level_name",
        "consumed_at",
        "consumed_at_utc",
        "consumed_monotonic_s",
        "consumed_event_line",
        "consumed_evidence_dir",
        "consumed_report_path",
    }
    assert set(authorization) - set(issued) == consumed_fields
    for key, value in issued.items():
        if key != "consumed":
            assert authorization[key] == value

    assert authorization["authorized"] is True
    assert authorization["one_use"] is True
    assert authorization["maximum_episode_count"] == 1
    assert authorization["maximum_retry_count"] == 0
    assert authorization["client_max_retries"] == 0
    assert authorization["proxy_max_retries"] == 0
    assert authorization["fresh_level_required"] is True
    assert authorization["fixed_runtime_limits_required"] is True
    assert authorization["credential_provider_preflight_required"] is True
    assert authorization["credential_provider_preflight_before_minecraft"] is True
    assert authorization["skill_execution_mode"] == "off"
    assert authorization["prior_bm014_attempt_count"] == 1
    assert authorization["prior_bm014_failure_count"] == 1
    assert authorization["prior_bm014_eligible_success_count"] == 0
    assert authorization["required_bm014_eligible_success_count"] == 3
    assert authorization["remaining_bm014_eligible_success_count_before_probe"] == 3
    assert authorization["bm014_status_before_probe"] == "failing"
    assert authorization["m4_status_before_probe"] == "failing"
    assert authorization["counts_toward_capability_before_independent_verification"] is False
    assert issued["consumed"] is False
    assert authorization["consumed"] is True
    assert authorization["next_authorization"] is False
    assert authorization["probe_53_authorized"] is False
    assert issued["probe_53_authorized"] is False

    evidence_dir = ROOT / authorization["consumed_evidence_dir"]
    jsonl_path = evidence_dir / (
        f"session_{authorization['consumed_session_id']}.jsonl"
    )
    with jsonl_path.open(encoding="utf-8") as handle:
        first_event = json.loads(next(handle))
        consumed_event = json.loads(next(handle))

    assert first_event["type"] == "connect"
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_at"] == consumed_event["type"] == "autonomous_start"
    assert authorization["consumed_session_id"] == consumed_event["session"]
    assert authorization["consumed_monotonic_s"] == consumed_event["monotonic_s"]
    assert authorization["consumed_at_utc"] == (
        datetime.fromtimestamp(consumed_event["ts"], tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    assert authorization["consumed_by_episode"] == evidence_dir.name
    assert consumed_event["data"]["task_id"] == authorization["task_id"]
    assert (
        consumed_event["data"]["task_contract_id"]
        == authorization["task_contract_id"]
    )
    assert (
        consumed_event["data"]["task_contract_sha256"]
        == authorization["task_contract_sha256"]
    )

    manifest = _json(evidence_dir / "manifest.json")
    assert manifest["episode_id"] == authorization["consumed_by_episode"]
    assert manifest["session_id"] == authorization["consumed_session_id"]
    assert manifest["level_name"] == authorization["consumed_level_name"]
    assert authorization["consumed_report_path"] == (
        "workspace/evals/m4_probe52_report.json"
    )
