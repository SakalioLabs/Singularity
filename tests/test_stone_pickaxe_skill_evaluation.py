import copy
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from singularity.core.skill_library import SkillLibrary
from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL_SHA256, REPOSITORY_ROOT
from singularity.evaluation.stone_pickaxe_runtime import file_sha256, read_json, repo_relative, write_json
from singularity.evaluation.stone_pickaxe_skill_evaluation import (
    POLICY,
    POLICY_PATH,
    POLICY_SHA256,
    arm_spec,
    build_baseline_index,
    build_evaluation_authorization,
    build_paired_evaluation_report,
    build_skill_evaluation_run,
    build_skill_evaluation_runtime_config,
    canonical_record_sha256,
    pair_binding,
    policy_identity_report,
    validate_evaluation_authorization,
    verify_run_record,
)


BASELINE_EPISODE = (
    REPOSITORY_ROOT
    / "workspace/evals/sp001_runs/sp001_episode_20260717_232454_5c05abf0/episode.json"
)
BASELINE_SESSION = BASELINE_EPISODE.with_name("session.json")
BASELINE_VERIFICATION = BASELINE_EPISODE.with_name("verification.json")
SKILL = POLICY["target_skill"]


def test_paired_policy_identity_binds_protocol_fixture_skill_and_baselines():
    report = policy_identity_report()
    assert report["passed"], report["issues"]
    assert file_sha256(POLICY_PATH) == POLICY_SHA256
    assert POLICY["base_protocol"]["sha256"] == PROTOCOL_SHA256
    assert report["skill_record_canonical_sha256"] == SKILL["record_canonical_sha256"]
    assert len(set(report["baseline_session_ids"])) == 3


def test_retained_baselines_are_distinct_and_fixed_control_equivalent():
    index = build_baseline_index()
    assert index["all_records_passed"]
    assert index["record_count"] == 3
    assert len({record["session_id"] for record in index["records"]}) == 3
    assert len({record["fixed_controls_fingerprint"] for record in index["records"]}) == 1
    assert len({record["initial_state_fingerprint"] for record in index["records"]}) == 1
    assert all(verify_run_record(record)["passed"] for record in index["records"])


def test_candidate_authorization_is_exact_and_has_no_runtime_authority():
    authorization = _authorization("candidate", "r1", "candidate-auth-1")
    audit = validate_evaluation_authorization(
        authorization,
        expected_arm="candidate",
        expected_replicate_id="r1",
        expected_episode_id="candidate-auth-1",
        expected_git_head="a" * 40,
    )
    assert audit["passed"], audit["issues"]
    assert authorization["baseline_binding"] == pair_binding("r1")
    assert authorization["skill_id"] == "learned:acquire_cobblestone"
    assert authorization["skill_version"] == "1.0.0"
    assert authorization["skill_status"] == "advisory"
    assert authorization["normal_runtime_permission"] is False
    assert authorization["automatic_retry_allowed"] is False


def test_authorization_rejects_wrong_arm_replicate_and_skill_version():
    with _raises(ValueError):
        _authorization("candidate", "shadow-1", "bad-replicate")
    authorization = _authorization("candidate", "r1", "bad-version")
    authorization["skill_version"] = "1.0.1"
    audit = validate_evaluation_authorization(authorization)
    assert not audit["passed"]
    assert "authorization_skill_version" in audit["issues"]


def test_authorization_rejects_consumed_arm_replicate(tmp_path):
    consumed = tmp_path / "authorization.json"
    consumed.write_text(
        json.dumps({
            "arm": "candidate",
            "replicate_id": "r1",
            "authorization_id": "consumed-before-runtime-r1",
        }),
        encoding="utf-8",
    )
    with _raises(ValueError, match="already consumed"):
        build_evaluation_authorization(
            arm="candidate",
            replicate_id="r1",
            episode_id="candidate-rerun",
            git_head="a" * 40,
            existing_run_paths=[consumed],
        )


def test_runtime_config_maps_each_arm_without_enabling_default_runtime():
    expected = {
        "shadow": ("shadow-1", "shadow"),
        "advisory": ("advisory-1", "advisory"),
        "fallback": ("fallback-1", "runtime"),
        "candidate": ("r1", "evaluation"),
    }
    for arm, (replicate, mode) in expected.items():
        authorization = _authorization(arm, replicate, f"config-{arm}")
        config = build_skill_evaluation_runtime_config(
            authorization=authorization,
            api_key="offline-test-key",
            log_dir="workspace/test-logs",
            host="127.0.0.1",
            port=25565,
            username="Singularity",
            bridge_host="127.0.0.1",
            bridge_port=30000,
        )
        assert config.skill_execution_mode == mode
        assert config.target_skill_id == SKILL["skill_id"]
        assert config.skill_runtime_default_gate_paths == []
        assert not config.enable_skill_candidate_extraction


def test_fallback_arm_proves_advisory_is_not_runtime_executable():
    library = SkillLibrary(storage_path=str(REPOSITORY_ROOT / "workspace/skills"), persist=False)
    observation = {
        "position": {"x": 95.5, "y": 132, "z": -31.5},
        "inventory": {"wooden_pickaxe": 1},
        "nearby_blocks": [{
            "name": "stone",
            "position": {"x": 95, "y": 131, "z": -32},
            "distance": 1.0,
        }],
    }
    selected = library.select_runtime_skill(
        "Gather 3 cobblestone with the wooden pickaxe",
        observation,
        execution_mode="runtime",
        target_skill_id=SKILL["skill_id"],
    )
    assert selected is None


def test_candidate_run_recomputes_exact_skill_metrics_and_integrity():
    with _repository_tempdir() as directory:
        run_path = _materialize_run(directory, "candidate", "r1", 1)
        run = read_json(run_path)
        assert run["status"] == "pass"
        assert run["metrics"]["skill_selected_count"] == 1
        assert run["metrics"]["skill_executed_count"] == 3
        assert run["metrics"]["candidate_steps_verified"] is True
        assert run["metrics"]["candidate_steps_reobserved"] is True
        assert verify_run_record(run)["passed"]


def test_shadow_advisory_and_fallback_runs_have_zero_direct_execution():
    with _repository_tempdir() as directory:
        for index, (arm, replicate, metric) in enumerate((
            ("shadow", "shadow-1", "skill_shadow_plan_count"),
            ("advisory", "advisory-1", "skill_advisory_hint_count"),
            ("fallback", "fallback-1", "skill_fallback_count"),
        ), start=1):
            run = read_json(_materialize_run(directory, arm, replicate, index))
            assert run["status"] == "pass"
            assert run["metrics"][metric] == 1
            assert run["metrics"]["skill_selected_count"] == 0
            assert run["metrics"]["skill_executed_count"] == 0


def test_run_record_rejects_metric_and_source_identity_tampering():
    with _repository_tempdir() as directory:
        run = read_json(_materialize_run(directory, "candidate", "r1", 1))
        run["metrics"]["skill_executed_count"] = 99
        run["record_payload_sha256"] = _payload_hash(run)
        audit = verify_run_record(run)
        assert not audit["passed"]
        assert "run_source_metrics" in audit["issues"]


def test_paired_report_remains_advisory_without_live_evaluation_runs():
    report = build_paired_evaluation_report([])
    assert report["pair_count"] == 3
    assert report["valid_pair_count"] == 0
    assert report["decision"] == "retain_advisory"
    assert report["readiness"] == "review"
    assert report["executable_promotion_gate"]["decision"] == "retain_advisory"
    assert report["normal_runtime_permission"] is False


def test_three_pairs_without_support_arms_cannot_promote():
    with _repository_tempdir() as directory:
        paths = [
            _materialize_run(directory, "candidate", replicate, index)
            for index, replicate in enumerate(("r1", "r2", "r3"), start=1)
        ]
        report = build_paired_evaluation_report(paths)
        assert report["valid_pair_count"] == 3
        assert report["shadow_verified"] is False
        assert report["advisory_verified"] is False
        assert report["fallback_verified"] is False
        assert report["decision"] == "retain_advisory"


def test_complete_six_arm_evidence_approves_only_new_version_review():
    with _repository_tempdir() as directory:
        paths = [
            _materialize_run(directory, "shadow", "shadow-1", 10),
            _materialize_run(directory, "advisory", "advisory-1", 11),
            _materialize_run(directory, "fallback", "fallback-1", 12),
            _materialize_run(directory, "candidate", "r1", 1),
            _materialize_run(directory, "candidate", "r2", 2),
            _materialize_run(directory, "candidate", "r3", 3),
        ]
        report = build_paired_evaluation_report(paths)
        gate = report["executable_promotion_gate"]
        assert report["valid_pair_count"] == 3
        assert report["decision"] == "review_executable_new_version"
        assert report["readiness"] == "approved"
        assert gate["decision"] == "promote_executable"
        assert gate["promoted_skill_version"] == "1.1.0"
        assert gate["evaluated_skill_version"] == "1.0.0"
        assert gate["rollback_target"] == "learned:acquire_cobblestone@1.0.0"
        assert gate["validation_issues"] == []
        assert gate["normal_runtime_permission"] is False


def test_duplicate_live_arm_is_fail_closed_in_paired_report():
    with _repository_tempdir() as directory:
        first = _materialize_run(directory, "candidate", "r1", 1)
        second = _materialize_run(directory, "candidate", "r1", 2)
        report = build_paired_evaluation_report([first, second])
        assert report["valid_pair_count"] == 0
        assert "duplicate_arm_replicate:candidate:r1" in report["errors"]
        assert report["decision"] == "retain_advisory"


def test_policy_forbids_base_mutation_in_place_rewrite_and_capability_credit():
    assert POLICY["evidence_policy"]["base_protocol_mutation_allowed"] is False
    assert POLICY["evidence_policy"]["prior_episode_mutation_allowed"] is False
    assert POLICY["evidence_policy"]["skill_record_mutation_during_evaluation_allowed"] is False
    assert POLICY["promotion_gate"]["in_place_version_rewrite_allowed"] is False
    assert POLICY["promotion_gate"]["promoted_version"] != SKILL["version"]
    assert POLICY["evidence_policy"]["counts_toward_capability"] is False
    assert POLICY["evidence_policy"]["counts_toward_m4"] is False


def _authorization(arm, replicate, episode):
    return build_evaluation_authorization(
        arm=arm,
        replicate_id=replicate,
        episode_id=episode,
        git_head="a" * 40,
        existing_run_paths=[],
    )


def _materialize_run(root: Path, arm: str, replicate: str, ordinal: int) -> Path:
    run_root = root / f"{arm}-{replicate}-{ordinal}"
    run_root.mkdir(parents=True)
    episode_id = f"offline-{arm}-{replicate}-{ordinal}"
    session_id = f"offline-session-{arm}-{replicate}-{ordinal}"
    authorization = _authorization(arm, replicate, episode_id)
    events = copy.deepcopy(read_json(BASELINE_SESSION))
    episode = copy.deepcopy(read_json(BASELINE_EPISODE))
    verification = copy.deepcopy(read_json(BASELINE_VERIFICATION))

    if arm == "candidate":
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
                "goal_fingerprint": "offline-goal",
            }
        events.append({
            "type": "skill_selected",
            "data": {
                "skill": {
                    "skill_id": SKILL["skill_id"],
                    "version": SKILL["version"],
                    "status": SKILL["required_status"],
                }
            },
        })
        events.append({
            "type": "skill_execution_outcome",
            "data": {
                "skill_id": SKILL["skill_id"],
                "version": SKILL["version"],
                "success": True,
                "attribution_confidence": 1.0,
            },
        })
        episode["selected_skills"] = [{
            "skill_id": SKILL["skill_id"],
            "version": SKILL["version"],
            "status": SKILL["required_status"],
        }]
    else:
        event_type = {
            "shadow": "skill_shadow_plan",
            "advisory": "skill_advisory_hint",
            "fallback": "skill_fallback",
        }[arm]
        events.append({"type": event_type, "data": {"skill_id": SKILL["skill_id"]}})
        episode["selected_skills"] = []

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
        "arm": arm,
        "replicate_id": replicate,
        "pair_id": authorization.get("pair_id", ""),
        "skill_id": SKILL["skill_id"],
        "skill_version": SKILL["version"],
        "normal_runtime_permission": False,
    }
    episode_path = write_json(run_root / "episode.json", episode)
    verification_path = write_json(run_root / "verification.json", verification)
    source_paths = [authorization_path, session_path, episode_path, verification_path]
    source_evidence = [
        {"path": repo_relative(path), "sha256": file_sha256(path)}
        for path in source_paths
    ]
    run = build_skill_evaluation_run(
        episode=episode,
        verification=verification,
        events=events,
        authorization=authorization,
        source_evidence=source_evidence,
        preflight_passed=True,
    )
    run_path = write_json(run_root / "evaluation_run.json", run)
    assert verify_run_record(run)["passed"], verify_run_record(run)["issues"]
    return run_path


def _payload_hash(run):
    payload = dict(run)
    payload.pop("record_payload_sha256", None)
    return canonical_record_sha256(payload)


class _repository_tempdir:
    def __enter__(self):
        self._temporary = tempfile.TemporaryDirectory(
            prefix="stone-skill-eval-test-",
            dir=REPOSITORY_ROOT / "workspace",
        )
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
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        if "tmp_path" in test.__code__.co_varnames:
            with tempfile.TemporaryDirectory() as directory:
                test(Path(directory))
        else:
            test()
    print(f"PASS: {len(tests)} stone-pickaxe skill-evaluation cases")
