"""Contract checks for the immutable Probe 22 decision-taxonomy annotation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe22_report.json"
AUDIT_PATH = ROOT / "workspace" / "evals" / "m4_probe22_derived_audit.json"
SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_probe22_derived_audit.schema.json"
)
COMPARISON_PATH = (
    ROOT / "workspace" / "evals" / "m4_probe21_probe22_comparison.json"
)

REPORT_SHA256 = "3db980c2c95efa9c505cd3da92d78883f5628006871210904e18cf8f782251f0"
COMPARISON_SHA256 = "28679e2eafc632bfb26ce2f8c19737cf784a27cc9f16de0f996c44c2ee49a90a"
FUTURE_DECISION = "intervention_not_exercised_new_blocker"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_probe22_derived_audit_schema_and_immutability() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(audit)

    assert _sha256(REPORT_PATH) == REPORT_SHA256
    assert _sha256(COMPARISON_PATH) == COMPARISON_SHA256
    assert audit["source_artifact"]["sha256"] == REPORT_SHA256
    assert audit["source_artifact"]["immutable"] is True
    assert audit["source_artifact"]["rewritten"] is False

    original = audit["original_decision"]
    assert original["value"] == report["decision"]["value"]
    assert original["reason"] == report["decision"]["reason"]
    assert original["infrastructure_preflight_passed"] is True
    assert audit["audit_annotation"]["classification"] == "taxonomy_limitation"
    assert audit["audit_annotation"]["prospective_decision"] == FUTURE_DECISION
    assert audit["taxonomy_patch"]["added_value"] == FUTURE_DECISION

    assert audit["taxonomy_patch"]["counts_as_capability_evidence"] is False
    assert audit["capability_effect"] == {
        "upgrades_capability": False,
        "bm012_eligible_success_delta": 0,
        "bm012_eligible_success_count_after": 0,
        "m4_status_after": "failing",
        "probe_23_authorized": False,
    }


if __name__ == "__main__":
    test_probe22_derived_audit_schema_and_immutability()
    print("PASS: Probe 22 derived audit is schema-valid and evidence-immutable")
