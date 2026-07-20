"""Run one new bounded SP-003 continuation-provider recovery probe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import stone_pickaxe_sp003_phase140_continuation_provider_probe as base


PHASE = 141
POLICY_ID = "sp003-continuation-provider-recovery-gate-v1"
PROBE_EPISODE_ID = "sp003-provider-continuation-recovery-probe-phase141"
PURPOSE = "recover_from_phase_140_continuation_provider_connection_error"
PHASE140_EVIDENCE_COMMIT = "c38e09a9e1c95966e87fcca70bfd13f2cad710f8"
EXPECTED_PHASE140_SHA256 = (
    "966c214f0a8117406137c4b59aceee59c2922949c3dd3e96eeda4413c601ebca"
)
DEFAULT_SOURCE = base.DEFAULT_SOURCE
DEFAULT_PREDECESSOR = Path(
    "workspace/evals/stone_pickaxe_sp003_phase140_continuation_provider_probe.json"
)
DEFAULT_OUTPUT = Path(
    "workspace/evals/"
    "stone_pickaxe_sp003_phase141_continuation_provider_recovery_probe.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one no-Minecraft SP-003 continuation-provider recovery probe"
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE.as_posix())
    parser.add_argument(
        "--predecessor", default=DEFAULT_PREDECESSOR.as_posix()
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT.as_posix())
    return parser.parse_args()


def exact_phase140_predecessor(predecessor: Path) -> tuple[dict, dict]:
    artifact = json.loads(predecessor.read_text(encoding="utf-8"))
    checks = {
        "artifact_sha256": (
            base.file_sha256(predecessor) == EXPECTED_PHASE140_SHA256
        ),
        "phase": artifact.get("phase") == 140,
        "policy": artifact.get("policy_id") == POLICY_ID,
        "tooling_commit": artifact.get("predecessor_commit")
        == "859114b808c39ec7b00f50618924cf53092a5541",
        "failed": artifact.get("passed") is False,
        "decision": artifact.get("decision")
        == "hold_new_authorization_provider_continuation_ineligible",
        "single_request": artifact.get("request_count") == 1,
        "zero_retries": artifact.get("retry_count") == 0,
        "request_sha256": artifact.get("request", {}).get("request_sha256")
        == base.EXPECTED_REQUEST_SHA256,
        "provider_request_sha256": artifact.get("request", {}).get(
            "provider_request_sha256"
        )
        == base.EXPECTED_REQUEST_SHA256,
        "zero_response_bytes": artifact.get("response_byte_count") == 0,
        "connection_error": artifact.get("schema_validation", {}).get("issues")
        == ["Connection error."],
        "not_real_or_schema_valid": (
            artifact.get("real_llm_call") is False
            and artifact.get("schema_valid") is False
        ),
        "no_minecraft_or_authorization": (
            artifact.get("minecraft_process_started") is False
            and artifact.get("authorization_created") is False
        ),
        "no_retry_or_credit": (
            artifact.get("automatic_retry_attempted") is False
            and artifact.get("counts_toward_baseline_success") is False
            and artifact.get("counts_toward_capability") is False
            and artifact.get("counts_toward_m4") is False
        ),
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError(
            "Phase 140 predecessor evidence mismatch: " + ",".join(failed)
        )
    return artifact, checks


def run_probe(source: Path, predecessor: Path) -> dict:
    phase140, predecessor_checks = exact_phase140_predecessor(predecessor)

    base.PHASE = PHASE
    base.POLICY_ID = POLICY_ID
    base.PROBE_EPISODE_ID = PROBE_EPISODE_ID
    base.PURPOSE = PURPOSE
    evidence = base.run_probe(source)
    evidence["purpose"] = PURPOSE
    evidence["recovery_predecessor"] = {
        "path": base.repo_relative(predecessor),
        "sha256": base.file_sha256(predecessor),
        "evidence_commit": PHASE140_EVIDENCE_COMMIT,
        "passed": phase140["passed"],
        "decision": phase140["decision"],
        "request_sha256": phase140["request"]["request_sha256"],
        "request_count": phase140["request_count"],
        "retry_count": phase140["retry_count"],
        "response_byte_count": phase140["response_byte_count"],
        "schema_validation_issues": phase140["schema_validation"]["issues"],
        "checks": predecessor_checks,
    }
    evidence["criteria"] = {
        "phase_140_failure_is_exact": all(predecessor_checks.values()),
        **evidence["criteria"],
    }
    evidence["passed"] = all(evidence["criteria"].values())
    evidence["decision"] = (
        "permit_one_new_authorization"
        if evidence["passed"]
        else "hold_new_authorization_provider_continuation_ineligible"
    )
    return evidence


def main() -> int:
    args = parse_args()
    source = base.repo_path(args.source)
    predecessor = base.repo_path(args.predecessor)
    output = base.repo_path(args.output)
    if not source.is_file():
        raise RuntimeError(f"source evidence not found: {source}")
    if not predecessor.is_file():
        raise RuntimeError(f"predecessor evidence not found: {predecessor}")
    evidence = run_probe(source, predecessor)
    base.write_evidence(output, evidence)
    print(
        json.dumps(
            {
                "output": base.repo_relative(output),
                "passed": evidence["passed"],
                "decision": evidence["decision"],
                "duration_ms": evidence["duration_ms"],
                "wall_duration_ms": evidence["wall_duration_ms"],
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
