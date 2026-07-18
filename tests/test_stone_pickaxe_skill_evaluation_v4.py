import copy
import hashlib
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from singularity.evaluation.stone_pickaxe_protocol import REPOSITORY_ROOT
from singularity.evaluation.stone_pickaxe_runtime import file_sha256, read_json, repo_relative, write_json
from singularity.evaluation.stone_pickaxe_skill_evaluation import policy_identity_report as v1_policy_identity_report
from singularity.evaluation.stone_pickaxe_skill_evaluation_v2 import policy_identity_report as v2_policy_identity_report
from singularity.evaluation.stone_pickaxe_skill_evaluation_v3 import policy_identity_report as v3_policy_identity_report
from singularity.evaluation.stone_pickaxe_skill_evaluation_v4 import (
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
V2_FROZEN_FILES = {
    "workspace/evals/stone_pickaxe_paired_evaluation_policy_v2.json": "18c4f5d812eae758018c3326e362679ea4061c642e4e10eaa40d95e52d7369d6",
    "src/singularity/evaluation/stone_pickaxe_skill_evaluation_v2.py": "907fdc15dd614a526cc1eb9e469d1eaffc9fe792affc7c16699a9082de8f60dc",
    "scripts/stone_pickaxe_skill_evaluation_v2.py": "e4bd0bd5bf8e3f664df0570e25e9a8c314c134aa060fe853ab366c229cb3f446",
    "scripts/stone-pickaxe-skill-window-v2.ps1": "6e8373ce3719cd9e2cfda0321897aa5db1386d4d6374e180da1d9edf54adc9e8",
    "workspace/evals/acquire_cobblestone_paired_evaluation_v2.json": "c3e0631992e2ba1a4193247d748b5822414019cb704e9db784dac3302bcba2f0",
}
V3_FROZEN_FILES = {
    "workspace/evals/sp001_skill_evaluation_v3/stone_pickaxe_paired_evaluation_policy_v3.json": "164e25386748315b1b160fb6ac6c6d052634a290154a42fbc6e8d0ed20a434ef",
    "src/singularity/evaluation/stone_pickaxe_skill_evaluation_v3.py": "0d5d76aeee561ee77605c5c5983cbdaf097c99cc098a002f8cc174e1e9e6e0d2",
    "scripts/stone_pickaxe_skill_evaluation_v3.py": "6c7fb16ca2a37e09955b3e679e7c236567402d9117853fe523d13fbb001d6396",
    "scripts/stone-pickaxe-skill-window-v3.ps1": "d0cc8fb7f68da504d0e0f913231c0994ac05a10630c58542f01771ac8bf13a4a",
    "workspace/evals/sp001_skill_evaluation_v3/acquire_cobblestone_baseline_index_v3.json": "34f3adf64e916f1b549fee05909bb5ff1249365120c3f769581cd73c27987b93",
    "workspace/evals/sp001_skill_evaluation_v3/acquire_cobblestone_paired_evaluation_v3.json": "b5a4300dfaa434d419f80e0fbaf23467370c98d826969d530d3602ebc8ac4627",
}
BASELINE_EPISODE = REPOSITORY_ROOT / POLICY["pair_bindings"][0]["episode_path"]
BASELINE_SESSION = REPOSITORY_ROOT / POLICY["pair_bindings"][0]["session_path"]
BASELINE_VERIFICATION = REPOSITORY_ROOT / POLICY["pair_bindings"][0]["verification_path"]
SKILL = POLICY["target_skill"]


def test_v4_policy_is_isolated_and_prior_identities_remain_valid():
    report = policy_identity_report()
    assert report["passed"], report["issues"]
    assert file_sha256(POLICY_PATH) == POLICY_SHA256
    assert POLICY["arms"]["candidate"]["replicate_ids"] == ["r10", "r11", "r12"]
    assert POLICY["recovery_window"]["excluded_replicate_ids"] == [
        "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9"
    ]
    for relative, expected in {**V1_FROZEN_FILES, **V2_FROZEN_FILES, **V3_FROZEN_FILES}.items():
        assert file_sha256(REPOSITORY_ROOT / relative) == expected
    v1_report = v1_policy_identity_report()
    assert v1_report["passed"], v1_report["issues"]
    v2_report = v2_policy_identity_report()
    assert v2_report["passed"], v2_report["issues"]
    v3_report = v3_policy_identity_report()
    assert v3_report["passed"], v3_report["issues"]


def test_v4_authorizes_only_fresh_candidate_replicates():
    authorization = _authorization("r10", "v4-auth-r10")
    audit = validate_evaluation_authorization(
        authorization,
        expected_arm="candidate",
        expected_replicate_id="r10",
        expected_episode_id="v4-auth-r10",
        expected_git_head="a" * 40,
    )
    assert audit["passed"], audit["issues"]
    assert authorization["pair_id"] == "sp001-acquire-recovery-v4-r10"
    assert authorization["evaluation_window_id"] == "sp001-acquire-route-scope-recovery-v4"
    assert authorization["prior_window_policy_sha256"] == V3_FROZEN_FILES[
        "workspace/evals/sp001_skill_evaluation_v3/stone_pickaxe_paired_evaluation_policy_v3.json"
    ]
    for replicate in ("r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9"):
        with _raises(ValueError):
            _authorization(replicate, f"v4-reject-{replicate}")
    with _raises(ValueError):
        build_evaluation_authorization(
            arm="shadow",
            replicate_id="shadow-1",
            episode_id="v4-reject-shadow",
            git_head="a" * 40,
            existing_run_paths=[],
        )


def test_v4_duplicate_candidate_authorization_fails_closed(tmp_path):
    consumed = tmp_path / "authorization.json"
    consumed.write_text(
        json.dumps({"arm": "candidate", "replicate_id": "r10", "authorization_id": "used-r10"}),
        encoding="utf-8",
    )
    with _raises(ValueError, match="already consumed"):
        build_evaluation_authorization(
            arm="candidate",
            replicate_id="r10",
            episode_id="v4-duplicate-r10",
            git_head="a" * 40,
            existing_run_paths=[consumed],
        )


def test_initial_v4_report_inherits_support_and_excludes_all_failed_candidates():
    prior_paths = [
        path
        for path in discover_evaluation_run_paths()
        if read_json(path).get("policy_id") != POLICY["id"]
    ]
    report = build_paired_evaluation_report(prior_paths)
    assert report["valid_pair_count"] == 0
    assert report["shadow_verified"] is True
    assert report["advisory_verified"] is True
    assert report["fallback_verified"] is True
    assert report["errors"] == []
    assert report["decision"] == "retain_advisory"
    assert [(item["replicate_id"], item["status"]) for item in report["excluded_prior_runs"]] == [
        ("r1", "fail"),
        ("r4", "fail"),
        ("r7", "fail"),
    ]
    assert len(report["inherited_support_runs"]) == 3


def test_current_v4_report_retains_r10_and_r11_as_two_eligible_pairs():
    report = read_json(
        REPOSITORY_ROOT
        / "workspace/evals/sp001_skill_evaluation_v4/acquire_cobblestone_paired_evaluation_v4.json"
    )
    assert report["valid_pair_count"] == 2
    assert report["decision"] == "retain_advisory"
    assert report["normal_runtime_permission"] is False
    run_paths = {
        "r10": "sp001_skill_candidate_20260718_085317_8e8de2cf",
        "r11": "sp001_skill_candidate_20260718_093639_8f6f185f",
    }
    for replicate_id, episode_id in run_paths.items():
        pair = next(item for item in report["pairs"] if item["replicate_id"] == replicate_id)
        assert pair["eligible"] is True
        run = read_json(
            REPOSITORY_ROOT
            / "workspace/evals/sp001_skill_evaluation_runs"
            / episode_id
            / "evaluation_run.json"
        )
        audit = verify_run_record(run)
        assert audit["passed"], audit["issues"]
        assert run["status"] == "pass"
        assert run["metrics"]["skill_completion_count"] == 1


def test_r12_infrastructure_failure_is_schema_valid_consumed_and_ineligible():
    run_root = (
        REPOSITORY_ROOT
        / "workspace/evals/sp001_skill_evaluation_runs"
        / "sp001_skill_candidate_20260718_100900_f4399a21"
    )
    failure = read_json(run_root / "infrastructure_failure.json")
    schema = read_json(
        REPOSITORY_ROOT
        / "workspace/evals/schemas/sp001_skill_evaluation_infrastructure_failure.schema.json"
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(failure)

    authorization = read_json(run_root / "authorization.json")
    restoration = read_json(run_root / "restoration.json")
    assert failure["authorization"]["authorization_id"] == authorization["authorization_id"]
    assert failure["authorization"]["git_head"] == authorization["git_head"]
    assert failure["authorization"]["consumed"] is True
    assert failure["restoration"]["passed"] == restoration["passed"] is True
    assert failure["eligibility"]["eligible_pair"] is False
    assert failure["runtime"]["planner_call_count"] == 0
    assert failure["runtime"]["action_count"] == 0
    assert failure["retry_policy"] == {
        "automatic_retry_allowed": False,
        "r12_reuse_allowed": False,
        "fresh_window_required": True,
    }

    for record in [failure["authorization"], failure["restoration"], *failure["evidence"]]:
        path = REPOSITORY_ROOT / record["path"]
        assert path.is_file(), record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        if "bytes" in record:
            assert path.stat().st_size == record["bytes"]

    for forbidden in ("preflight.json", "session.json", "episode.json", "evaluation_run.json", "manifest.json"):
        assert not (run_root / forbidden).exists()

    report_path = (
        REPOSITORY_ROOT
        / "workspace/evals/sp001_skill_evaluation_v4/acquire_cobblestone_paired_evaluation_v4.json"
    )
    report = read_json(report_path)
    assert file_sha256(report_path) == "cad8a9ed52168b1c06adb669851f730e6cafe14aa0badf2ab337a1f50c158469"
    assert report["valid_pair_count"] == 2
    assert {pair["replicate_id"] for pair in report["pairs"] if pair["eligible"]} == {"r10", "r11"}
    r12_pair = next(pair for pair in report["pairs"] if pair["replicate_id"] == "r12")
    assert r12_pair["candidate_run_id"] == ""
    assert r12_pair["candidate_integrity"] is False
    assert r12_pair["eligible"] is False

    ledger = read_json(REPOSITORY_ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json")
    retained = next(item for item in ledger["failures"] if item.get("replicate_id") == "r12")
    assert ledger["live_authorization"] is False
    assert ledger["authorized_live_episode_count"] == 0
    assert ledger["authorization_consumption"]["paired_evaluation_arms_consumed"] == 9
    assert retained["status"] == "infrastructure_ineligible"
    assert retained["attributable_to_learned_skill"] is False
    assert retained["episode_created"] is False
    assert retained["automatic_retry_allowed"] is False
    assert ledger["paired_evaluation"]["next_arm"] is None
    assert ledger["next_required_gate"]["authorization"] is False


def test_v4_policy_rejects_inherited_support_hash_tampering():
    tampered = copy.deepcopy(POLICY)
    tampered["inherited_support_bindings"][0]["sha256"] = "0" * 64
    report = policy_identity_report(tampered)
    assert not report["passed"]
    assert "inherited_shadow_file" in report["issues"]


def test_v4_policy_rejects_prior_window_and_retained_failure_tampering():
    tampered = copy.deepcopy(POLICY)
    tampered["recovery_window"]["prior_window_report"]["sha256"] = "0" * 64
    report = policy_identity_report(tampered)
    assert not report["passed"]
    assert "prior_window_report_file" in report["issues"]

    tampered = copy.deepcopy(POLICY)
    tampered["recovery_window"]["retained_failed_runs"][2]["sha256"] = "0" * 64
    report = policy_identity_report(tampered)
    assert not report["passed"]
    assert "failed_r7_file" in report["issues"]


def test_v4_report_requires_three_new_candidates_before_review():
    with _repository_tempdir() as directory:
        two = [_materialize_candidate(directory, replicate, index) for index, replicate in enumerate(("r10", "r11"), 1)]
        report = build_paired_evaluation_report(two)
        assert report["valid_pair_count"] == 2
        assert report["decision"] == "retain_advisory"
        third = _materialize_candidate(directory, "r12", 3)
        report = build_paired_evaluation_report(two + [third])
        assert report["valid_pair_count"] == 3
        assert report["decision"] == "review_executable_new_version"
        assert report["executable_promotion_gate"]["promoted_skill_version"] == "1.1.0"
        assert report["normal_runtime_permission"] is False


def test_v4_report_rejects_duplicate_and_missing_window_identity():
    with _repository_tempdir() as directory:
        first = _materialize_candidate(directory, "r10", 1)
        duplicate = _materialize_candidate(directory, "r10", 2)
        report = build_paired_evaluation_report([first, duplicate])
        assert "duplicate_arm_replicate:candidate:r10" in report["errors"]
        assert report["decision"] == "retain_advisory"

        run = read_json(first)
        run.pop("evaluation_window_id")
        run["record_payload_sha256"] = _payload_hash(run)
        write_json(first, run)
        report = build_paired_evaluation_report([first])
        assert any("run_evaluation_window" in issue for issue in report["errors"])
        assert report["valid_pair_count"] == 0


def test_v4_context_does_not_leak_into_prior_policies_after_report_build():
    build_paired_evaluation_report([])
    report = v1_policy_identity_report()
    assert report["passed"], report["issues"]
    assert report["policy_id"] == "stone-pickaxe-sp001-paired-evaluation-v1"
    previous = v2_policy_identity_report()
    assert previous["passed"], previous["issues"]
    previous = v3_policy_identity_report()
    assert previous["passed"], previous["issues"]


def test_v4_launcher_is_candidate_only_and_uses_isolated_cli():
    launcher = (REPOSITORY_ROOT / "scripts/stone-pickaxe-skill-window-v4.ps1").read_text(encoding="utf-8")
    assert '"candidate" = @("r10", "r11", "r12")' in launcher
    assert "stone_pickaxe_skill_evaluation_v4.py write-authorization" in launcher
    assert "stone_pickaxe_skill_evaluation_v4.py run-arm" in launcher
    assert "stone_pickaxe_skill_evaluation_v4.py refresh-report" in launcher
    assert '"shadow" = @("shadow-1")' not in launcher
    assert '"candidate" = @("r1", "r2", "r3")' not in launcher
    assert '"candidate" = @("r4", "r5", "r6")' not in launcher
    assert '"candidate" = @("r7", "r8", "r9")' not in launcher
    assert "workspace\\evals\\sp001_skill_evaluation_v4" in launcher


def test_v4_generated_reports_are_byte_preserved_without_changing_v1_attributes():
    attributes = (
        REPOSITORY_ROOT / "workspace/evals/sp001_skill_evaluation_v4/.gitattributes"
    ).read_text(encoding="utf-8").splitlines()
    assert attributes == [
        "acquire_cobblestone_baseline_index_v4.json binary",
        "acquire_cobblestone_paired_evaluation_v4.json binary",
        "stone_pickaxe_paired_evaluation_policy_v4.json binary",
    ]
    assert file_sha256(REPOSITORY_ROOT / ".gitattributes") == "5e4c42a64e29cb3cb88021d96397283f84241a1b2b336e2461a82879b462f343"
    assert file_sha256(REPOSITORY_ROOT / "workspace/evals/.gitattributes") == (
        "e12faffa3b5452c743e7df344478e0d85897899bbca79c25b7667ddb64dcdfab"
    )


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
    episode_id = f"offline-v4-candidate-{replicate}-{ordinal}"
    session_id = f"offline-v4-session-{replicate}-{ordinal}"
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
            "goal_fingerprint": "offline-v4-goal",
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
        self._temporary = tempfile.TemporaryDirectory(prefix="stone-skill-eval-v4-test-", dir=REPOSITORY_ROOT / "workspace")
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
