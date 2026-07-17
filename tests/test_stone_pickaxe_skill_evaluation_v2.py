import copy
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from singularity.evaluation.stone_pickaxe_protocol import REPOSITORY_ROOT
from singularity.evaluation.stone_pickaxe_runtime import file_sha256, read_json, repo_relative, write_json
from singularity.evaluation.stone_pickaxe_skill_evaluation import policy_identity_report as v1_policy_identity_report
from singularity.evaluation.stone_pickaxe_skill_evaluation_v2 import (
    POLICY,
    POLICY_PATH,
    POLICY_SHA256,
    build_evaluation_authorization,
    build_paired_evaluation_report,
    build_skill_evaluation_run,
    canonical_record_sha256,
    discover_evaluation_run_paths,
    pair_binding,
    policy_identity_report,
    validate_evaluation_authorization,
    verify_run_record,
)


V1_FROZEN_FILES = {
    "workspace/evals/stone_pickaxe_paired_evaluation_policy.json": "61aebb8606c85b3df0872ccd1900d7e05fb962fba32fce50d00a741d5216a4db",
    "src/singularity/evaluation/stone_pickaxe_skill_evaluation.py": "019215b9038e4746379dea20ae5ea16f29b775196f4be172f7f9f266c013143e",
    "scripts/stone_pickaxe_skill_evaluation.py": "bc9e2be805f74f7ba5a8e0c2d7437d9e9f17b2369e0d181fd812ddc28f1527d7",
    "scripts/stone-pickaxe-runtime.ps1": "77a5c78202f00b236b8640de4a15db4c59526a08a8ca5e44244f2100a90f15e3",
    "workspace/evals/acquire_cobblestone_paired_evaluation.json": "18229bc62dbb4a88aeb3f705a9988ca916305dc27c2c96cfbbcf3cf765f336f0",
}
BASELINE_EPISODE = REPOSITORY_ROOT / POLICY["pair_bindings"][0]["episode_path"]
BASELINE_SESSION = REPOSITORY_ROOT / POLICY["pair_bindings"][0]["session_path"]
BASELINE_VERIFICATION = REPOSITORY_ROOT / POLICY["pair_bindings"][0]["verification_path"]
SKILL = POLICY["target_skill"]


def test_v2_policy_is_isolated_and_v1_identity_remains_valid():
    report = policy_identity_report()
    assert report["passed"], report["issues"]
    assert file_sha256(POLICY_PATH) == POLICY_SHA256
    assert POLICY["arms"]["candidate"]["replicate_ids"] == ["r4", "r5", "r6"]
    assert POLICY["recovery_window"]["excluded_replicate_ids"] == ["r1", "r2", "r3"]
    for relative, expected in V1_FROZEN_FILES.items():
        assert file_sha256(REPOSITORY_ROOT / relative) == expected
    v1_report = v1_policy_identity_report()
    assert v1_report["passed"], v1_report["issues"]


def test_v2_authorizes_only_fresh_candidate_replicates():
    authorization = _authorization("r4", "v2-auth-r4")
    audit = validate_evaluation_authorization(
        authorization,
        expected_arm="candidate",
        expected_replicate_id="r4",
        expected_episode_id="v2-auth-r4",
        expected_git_head="a" * 40,
    )
    assert audit["passed"], audit["issues"]
    assert authorization["pair_id"] == "sp001-acquire-recovery-r4"
    assert authorization["evaluation_window_id"] == "sp001-acquire-runtime-fix-recovery-v2"
    with _raises(ValueError):
        _authorization("r1", "v2-reject-r1")
    with _raises(ValueError):
        build_evaluation_authorization(
            arm="shadow",
            replicate_id="shadow-1",
            episode_id="v2-reject-shadow",
            git_head="a" * 40,
            existing_run_paths=[],
        )


def test_v2_duplicate_candidate_authorization_fails_closed(tmp_path):
    consumed = tmp_path / "authorization.json"
    consumed.write_text(
        json.dumps({"arm": "candidate", "replicate_id": "r4", "authorization_id": "used-r4"}),
        encoding="utf-8",
    )
    with _raises(ValueError, match="already consumed"):
        build_evaluation_authorization(
            arm="candidate",
            replicate_id="r4",
            episode_id="v2-duplicate-r4",
            git_head="a" * 40,
            existing_run_paths=[consumed],
        )


def test_initial_v2_report_inherits_support_and_excludes_failed_r1():
    report = build_paired_evaluation_report(discover_evaluation_run_paths())
    assert report["valid_pair_count"] == 0
    assert report["shadow_verified"] is True
    assert report["advisory_verified"] is True
    assert report["fallback_verified"] is True
    assert report["errors"] == []
    assert report["decision"] == "retain_advisory"
    assert [(item["replicate_id"], item["status"]) for item in report["excluded_prior_runs"]] == [("r1", "fail")]
    assert len(report["inherited_support_runs"]) == 3


def test_v2_policy_rejects_inherited_support_hash_tampering():
    tampered = copy.deepcopy(POLICY)
    tampered["inherited_support_bindings"][0]["sha256"] = "0" * 64
    report = policy_identity_report(tampered)
    assert not report["passed"]
    assert "inherited_shadow_file" in report["issues"]


def test_v2_report_requires_three_new_candidates_before_review():
    with _repository_tempdir() as directory:
        two = [_materialize_candidate(directory, replicate, index) for index, replicate in enumerate(("r4", "r5"), 1)]
        report = build_paired_evaluation_report(two)
        assert report["valid_pair_count"] == 2
        assert report["decision"] == "retain_advisory"
        third = _materialize_candidate(directory, "r6", 3)
        report = build_paired_evaluation_report(two + [third])
        assert report["valid_pair_count"] == 3
        assert report["decision"] == "review_executable_new_version"
        assert report["executable_promotion_gate"]["promoted_skill_version"] == "1.1.0"
        assert report["normal_runtime_permission"] is False


def test_v2_report_rejects_duplicate_and_missing_window_identity():
    with _repository_tempdir() as directory:
        first = _materialize_candidate(directory, "r4", 1)
        duplicate = _materialize_candidate(directory, "r4", 2)
        report = build_paired_evaluation_report([first, duplicate])
        assert "duplicate_arm_replicate:candidate:r4" in report["errors"]
        assert report["decision"] == "retain_advisory"

        run = read_json(first)
        run.pop("evaluation_window_id")
        run["record_payload_sha256"] = _payload_hash(run)
        write_json(first, run)
        report = build_paired_evaluation_report([first])
        assert any("run_evaluation_window" in issue for issue in report["errors"])
        assert report["valid_pair_count"] == 0


def test_v2_context_does_not_leak_into_v1_after_report_build():
    build_paired_evaluation_report([])
    report = v1_policy_identity_report()
    assert report["passed"], report["issues"]
    assert report["policy_id"] == "stone-pickaxe-sp001-paired-evaluation-v1"


def test_v2_launcher_is_candidate_only_and_uses_isolated_cli():
    launcher = (REPOSITORY_ROOT / "scripts/stone-pickaxe-skill-window-v2.ps1").read_text(encoding="utf-8")
    assert '"candidate" = @("r4", "r5", "r6")' in launcher
    assert "stone_pickaxe_skill_evaluation_v2.py write-authorization" in launcher
    assert "stone_pickaxe_skill_evaluation_v2.py run-arm" in launcher
    assert "stone_pickaxe_skill_evaluation_v2.py refresh-report" in launcher
    assert '"shadow" = @("shadow-1")' not in launcher
    assert '"candidate" = @("r1", "r2", "r3")' not in launcher


def test_v2_generated_reports_are_byte_preserved_without_changing_v1_attributes():
    attributes = (REPOSITORY_ROOT / "workspace/evals/.gitattributes").read_text(encoding="utf-8").splitlines()
    assert attributes == [
        "acquire_cobblestone_baseline_index_v2.json binary",
        "acquire_cobblestone_paired_evaluation_v2.json binary",
    ]
    assert file_sha256(REPOSITORY_ROOT / ".gitattributes") == "5e4c42a64e29cb3cb88021d96397283f84241a1b2b336e2461a82879b462f343"


def _authorization(replicate: str, episode: str) -> dict:
    return build_evaluation_authorization(
        arm="candidate",
        replicate_id=replicate,
        episode_id=episode,
        git_head="a" * 40,
        existing_run_paths=[],
    )


def _materialize_candidate(root: Path, replicate: str, ordinal: int) -> Path:
    run_root = root / f"candidate-{replicate}-{ordinal}"
    run_root.mkdir(parents=True)
    episode_id = f"offline-v2-candidate-{replicate}-{ordinal}"
    session_id = f"offline-v2-session-{replicate}-{ordinal}"
    authorization = _authorization(replicate, episode_id)
    events = copy.deepcopy(read_json(BASELINE_SESSION))
    episode = copy.deepcopy(read_json(BASELINE_EPISODE))
    verification = copy.deepcopy(read_json(BASELINE_VERIFICATION))

    for event in events:
        if not isinstance(event, dict) or event.get("type") != "action":
            continue
        data = event.get("data", {})
        action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
        if action.get("type") != "dig":
            continue
        action["skill_context"] = {
            "skill_id": SKILL["skill_id"],
            "skill_name": SKILL["name"],
            "version": SKILL["version"],
            "status": SKILL["required_status"],
            "mode": "evaluation",
            "phase_id": "acquire_target",
            "template_action_index": 0,
            "experiment_id": episode_id,
            "goal": POLICY["fixed_controls"]["goal"],
            "goal_fingerprint": "offline-v2-goal",
        }
    events.extend([
        {
            "type": "skill_selected",
            "data": {"skill": {"skill_id": SKILL["skill_id"], "version": SKILL["version"], "status": SKILL["required_status"]}},
        },
        {
            "type": "skill_execution_outcome",
            "data": {"skill_id": SKILL["skill_id"], "version": SKILL["version"], "success": True, "attribution_confidence": 1.0},
        },
    ])
    episode["selected_skills"] = [{
        "skill_id": SKILL["skill_id"],
        "version": SKILL["version"],
        "status": SKILL["required_status"],
    }]
    authorization_path = write_json(run_root / "authorization.json", authorization)
    session_path = write_json(run_root / "session.json", events)
    episode["episode_id"] = episode_id
    episode["session_id"] = session_id
    episode["level_name"] = episode_id
    episode["session_sha256"] = file_sha256(session_path)
    episode["eligibility"] = {
        **dict(episode.get("eligibility", {})),
        "passed": True,
        "skill_evaluation_authorization": True,
        "skill_arm_selection": True,
    }
    episode["evaluation"] = {
        "policy_id": POLICY["id"],
        "policy_sha256": POLICY_SHA256,
        "authorization_id": authorization["authorization_id"],
        "authorization_fingerprint": canonical_record_sha256(authorization),
        "arm": "candidate",
        "replicate_id": replicate,
        "pair_id": pair_binding(replicate)["pair_id"],
        "skill_id": SKILL["skill_id"],
        "skill_version": SKILL["version"],
        "evaluation_window_id": POLICY["recovery_window"]["id"],
        "normal_runtime_permission": False,
    }
    episode_path = write_json(run_root / "episode.json", episode)
    verification_path = write_json(run_root / "verification.json", verification)
    source_paths = [authorization_path, session_path, episode_path, verification_path]
    source_evidence = [{"path": repo_relative(path), "sha256": file_sha256(path)} for path in source_paths]
    run = build_skill_evaluation_run(
        episode=episode,
        verification=verification,
        events=events,
        authorization=authorization,
        source_evidence=source_evidence,
        preflight_passed=True,
    )
    run_path = write_json(run_root / "evaluation_run.json", run)
    audit = verify_run_record(run)
    assert audit["passed"], audit["issues"]
    return run_path


def _payload_hash(run: dict) -> str:
    payload = dict(run)
    payload.pop("record_payload_sha256", None)
    return canonical_record_sha256(payload)


class _repository_tempdir:
    def __enter__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="stone-skill-eval-v2-test-", dir=REPOSITORY_ROOT / "workspace")
        return Path(self._temporary.name)

    def __exit__(self, exc_type, exc, traceback):
        self._temporary.cleanup()


@contextmanager
def _raises(error_type, match=""):
    try:
        yield
    except error_type as exc:
        if match:
            assert match in str(exc)
    else:
        raise AssertionError(f"expected {error_type.__name__}")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        if "tmp_path" in test.__code__.co_varnames:
            with tempfile.TemporaryDirectory() as directory:
                test(Path(directory))
        else:
            test()
    print(f"PASS: {len(tests)} stone-pickaxe recovery-window cases")
