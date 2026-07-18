import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from singularity.core.skill_learning import evidence_fingerprint
from singularity.core.skill_library import SkillLibrary
from singularity.evaluation.stone_pickaxe_protocol import REPOSITORY_ROOT
from singularity.evaluation.stone_pickaxe_skill_evaluation_v5 import (
    POLICY,
    canonical_record_sha256,
    policy_identity_report,
)


SCRIPT = REPOSITORY_ROOT / "scripts" / "stone_pickaxe_skill_lifecycle.py"
PAIRED_REPORT = (
    REPOSITORY_ROOT
    / "workspace/evals/sp001_skill_evaluation_v5/acquire_cobblestone_paired_evaluation_v5.json"
)


def test_exact_v5_gate_promotes_a_new_executable_version_and_is_idempotent():
    with _promotion_workspace() as paths:
        source_before = _source_record(paths["custom"])
        source_hash = canonical_record_sha256(source_before)
        first = _run_promotion(paths)
        assert first.returncode == 0, first.stderr
        first_result = json.loads(first.stdout)
        assert first_result["changed"] is True
        assert first_result["source_version"] == "1.0.0"
        assert first_result["promoted_version"] == "1.1.0"

        records = _jsonl(paths["custom"])
        source = next(item for item in records if item["version"] == "1.0.0")
        promoted = next(item for item in records if item["version"] == "1.1.0")
        assert len([item for item in records if item["skill_id"] == POLICY["target_skill"]["skill_id"]]) == 2
        assert canonical_record_sha256(source) == source_hash
        assert source["status"] == "advisory"
        assert "executable_promotion" not in source.get("gate", {})
        assert promoted["status"] == "executable"
        assert promoted["parent_version"] == "1.0.0"
        assert promoted["rollback_target"] == "1.0.0"

        report = _read_json(PAIRED_REPORT)
        expected_gate = report["executable_promotion_gate"]
        assert evidence_fingerprint(promoted["gate"]["executable_promotion"]) == evidence_fingerprint(expected_gate)
        promotion = _read_json(paths["output"])
        runtime_gate = _read_json(paths["runtime_gate"])
        assert promotion["stage"] == "executable"
        assert promotion["normal_runtime_permission"] is True
        assert promotion["counts_toward_capability"] is False
        assert promotion["counts_toward_m4"] is False
        assert runtime_gate["readiness"] == "approved"
        assert runtime_gate["normal_runtime_permission"] is True
        assert runtime_gate["executable_promotion_gate_fingerprint"] == evidence_fingerprint(expected_gate)

        library = SkillLibrary(str(paths["storage"]), persist=True)
        assert library.select_runtime_skill(
            "Acquire 3 cobblestone",
            _observation(),
            "runtime",
            POLICY["target_skill"]["skill_id"],
        ) is None
        assert library.record_skill_runtime_default_gate(runtime_gate) == 1
        selected = library.select_runtime_skill(
            "Acquire 3 cobblestone",
            _observation(),
            "runtime",
            POLICY["target_skill"]["skill_id"],
        )
        assert selected is not None
        assert selected.version == "1.1.0"

        retained_hashes = {
            name: _sha256(path)
            for name, path in paths.items()
            if name in {"custom", "ledger", "output", "runtime_gate"}
        }
        second = _run_promotion(paths)
        assert second.returncode == 0, second.stderr
        second_result = json.loads(second.stdout)
        assert second_result["changed"] is False
        assert second_result["reason"] == "exact_promotion_already_applied"
        assert retained_hashes == {
            name: _sha256(path)
            for name, path in paths.items()
            if name in retained_hashes
        }


def test_tampered_v5_report_fails_before_any_promotion_write():
    with _promotion_workspace() as paths:
        before = _sha256(paths["custom"])
        tampered = _read_json(PAIRED_REPORT)
        tampered["valid_pair_count"] = 2
        paths["tampered_report"].write_text(
            json.dumps(tampered, indent=2) + "\n",
            encoding="utf-8",
        )
        result = _run_promotion(paths, paired_report=paths["tampered_report"])
        assert result.returncode != 0
        assert "does not match a fresh reconstruction" in result.stderr
        assert _sha256(paths["custom"]) == before
        assert not paths["output"].exists()
        assert not paths["runtime_gate"].exists()
        assert not paths["ledger"].exists()


def test_v5_policy_identity_survives_append_only_skill_promotion():
    report = policy_identity_report()
    assert report["passed"], report["issues"]
    assert report["skill_record_canonical_sha256"] == POLICY["target_skill"][
        "record_canonical_sha256"
    ]


def test_promotion_artifacts_have_a_local_byte_preservation_boundary():
    attributes = (
        REPOSITORY_ROOT / "workspace/evals/sp001_skill_promotion/.gitattributes"
    ).read_text(encoding="utf-8").splitlines()
    assert attributes == [
        "acquire_cobblestone_executable_promotion.json binary",
        "acquire_cobblestone_runtime_default_gate.json binary",
    ]


class _promotion_workspace:
    def __enter__(self):
        workspace = REPOSITORY_ROOT / "workspace"
        self._temporary = tempfile.TemporaryDirectory(dir=workspace)
        root = Path(self._temporary.name)
        storage = root / "skills"
        storage.mkdir()
        custom = storage / "custom_skills.jsonl"
        source = _real_source_record()
        custom.write_text(json.dumps(source) + "\n", encoding="utf-8")
        self.paths = {
            "root": root,
            "storage": storage,
            "custom": custom,
            "ledger": root / "learning.json",
            "output": root / "promotion.json",
            "runtime_gate": root / "runtime_gate.json",
            "tampered_report": root / "tampered_report.json",
        }
        return self.paths

    def __exit__(self, exc_type, exc, traceback):
        self._temporary.cleanup()


def _run_promotion(paths: dict, paired_report: Path = PAIRED_REPORT):
    relative = lambda path: path.relative_to(REPOSITORY_ROOT).as_posix()
    environment = {**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT / "src")}
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "promote-executable",
            "--storage-path",
            relative(paths["storage"]),
            "--learning-ledger",
            relative(paths["ledger"]),
            "--paired-report",
            relative(paired_report),
            "--output",
            relative(paths["output"]),
            "--runtime-gate-output",
            relative(paths["runtime_gate"]),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def _real_source_record() -> dict:
    records = _jsonl(REPOSITORY_ROOT / "workspace/skills/custom_skills.jsonl")
    matches = [
        item for item in records
        if item.get("skill_id") == POLICY["target_skill"]["skill_id"]
        and item.get("version") == POLICY["target_skill"]["version"]
    ]
    assert len(matches) == 1
    return matches[0]


def _source_record(path: Path) -> dict:
    matches = [item for item in _jsonl(path) if item.get("version") == "1.0.0"]
    assert len(matches) == 1
    return matches[0]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observation() -> dict:
    return {
        "observation_id": "sp001-promotion-test",
        "inventory": {"wooden_pickaxe": 1},
        "safe": True,
        "movable": True,
        "position": {"x": 0, "y": 64, "z": 0},
        "observed_blocks": [
            {
                "source_id": "stone-1",
                "name": "stone",
                "observed": True,
                "reachable": True,
                "position": {"x": 1, "y": 64, "z": 0},
            }
        ],
    }


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"PASS: {len(tests)} stone-pickaxe skill promotion cases")
