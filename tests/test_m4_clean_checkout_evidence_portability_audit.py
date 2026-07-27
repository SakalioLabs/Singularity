"""Bind the M4 clean-checkout portability repair to exact raw evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "workspace/evals/m4_clean_checkout_evidence_portability_audit.json"
)
RAW_PREFIX = "logs/benchmarks/m4/"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
    ).strip()


def test_portability_audit_binds_parent_tree_and_complete_survey_partition():
    audit = _json(AUDIT_PATH)
    parent = audit["parent_binding"]
    survey = audit["parent_clean_checkout_survey"]

    assert audit["type"] == "m4_clean_checkout_evidence_portability_audit"
    assert audit["profile"] == "m4-fixed-v1"
    assert audit["classification"] == "offline_evidence_portability_remediation"
    assert audit["counts_toward_bm014_success"] is False
    assert audit["counts_toward_capability"] is False

    assert parent == {
        "commit": "8e0c90e2c66dff991995d51026c546fda4c4f888",
        "tree": "8377e7fb851420488e52deaf64f31591d0b0af26",
    }
    assert _git("rev-parse", f"{parent['commit']}^{{tree}}") == parent["tree"]

    assert survey["report_bound_raw_file_count"] == 240
    assert survey["missing_file_count"] == 40
    assert survey["line_ending_only_mismatch_count"] == 64
    assert survey["exact_byte_match_count"] == 136
    assert (
        survey["missing_file_count"]
        + survey["line_ending_only_mismatch_count"]
        + survey["exact_byte_match_count"]
        == survey["report_bound_raw_file_count"]
    )
    assert survey["partition_complete"] is True
    assert survey["missing_probe_numbers"] == [25, 26, 27, 28]
    assert survey["missing_episode_count"] == 4
    assert survey["missing_episode_file_count"] == 40


def test_portability_archives_strictly_match_all_forty_report_hashes():
    audit = _json(AUDIT_PATH)
    remediation = audit["remediation"]
    archives = remediation["archives"]
    verified_file_count = 0

    assert remediation["archive_format"] == "tar.gz"
    assert remediation["archive_count"] == 4
    assert remediation["archived_regular_file_count"] == 40
    assert remediation["files_per_archive"] == 10
    assert remediation["archive_member_path_rule"] == (
        "report evidence path with the logs/benchmarks/m4/ prefix removed"
    )
    assert len(archives) == 4

    for spec in archives:
        report_path = ROOT / spec["report_path"]
        archive_path = ROOT / spec["archive_path"]
        report = _json(report_path)

        assert report["probe_number"] == spec["probe_number"]
        assert report["episode_id"] == spec["episode_id"]
        assert spec["archive_path"] == (
            "workspace/evals/m4_raw_archives/"
            f"{spec['episode_id']}.tar.gz"
        )
        assert _sha256(archive_path) == spec["archive_sha256"]

        evidence_paths = report["evidence_paths"]
        evidence_sha256 = report["evidence_sha256"]
        assert evidence_paths.keys() == evidence_sha256.keys()
        assert len(evidence_paths) == spec["regular_file_member_count"] == 10

        expected_names = {}
        for key, relative_path in evidence_paths.items():
            assert relative_path.startswith(RAW_PREFIX)
            member_name = relative_path.removeprefix(RAW_PREFIX)
            assert PurePosixPath(member_name).parts[0] == spec["episode_id"]
            expected_names[key] = member_name

        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            actual_names = [member.name for member in members]

            assert len(members) == 10
            assert len(set(actual_names)) == 10
            assert set(actual_names) == set(expected_names.values())
            assert all(member.isfile() for member in members)
            assert all(
                not PurePosixPath(member.name).is_absolute()
                and ".." not in PurePosixPath(member.name).parts
                for member in members
            )

            for key, member_name in expected_names.items():
                extracted = archive.extractfile(member_name)
                assert extracted is not None
                member_bytes = extracted.read()
                assert hashlib.sha256(member_bytes).hexdigest() == (
                    evidence_sha256[key]
                )
                verified_file_count += 1

    assert verified_file_count == 40


def test_portability_policy_preserves_controls_and_locks_probe54():
    audit = _json(AUDIT_PATH)
    remediation = audit["remediation"]
    controls = audit["unchanged_controls"]
    decision = audit["decision"]

    attributes_rule = "logs/benchmarks/m4/** binary"
    attribute_lines = (ROOT / ".gitattributes").read_text(
        encoding="utf-8"
    ).splitlines()
    assert remediation["git_attributes_path"] == ".gitattributes"
    assert remediation["git_attributes_rule"] == attributes_rule
    assert attribute_lines.count(attributes_rule) == 1
    assert remediation["expected_portable_report_binding_count"] == 240

    assert controls == {
        "behavior_source_changed": False,
        "protocol_changed": False,
        "task_contract_changed": False,
        "retry_policy_changed": False,
        "live_episode_executed": False,
    }
    assert decision["portability_repair_complete_offline"] is True
    assert decision["counts_toward_bm014_success"] is False
    assert decision["counts_toward_capability"] is False
    assert decision["bm014_status"] == "live_observed"
    assert decision["m4_status"] == "live_observed"
    assert decision["probe_54_authorized"] is False
