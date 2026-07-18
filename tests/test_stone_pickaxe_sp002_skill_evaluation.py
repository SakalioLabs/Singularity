import copy
import json
import tempfile
from pathlib import Path

from singularity.core.skill_library import SkillLibrary
from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL_SHA256, REPOSITORY_ROOT
from singularity.evaluation.stone_pickaxe_sp002_runtime import file_sha256, read_json, write_json
from singularity.evaluation.stone_pickaxe_sp002_skill_evaluation import (
    POLICY,
    POLICY_PATH,
    POLICY_SHA256,
    arm_spec,
    build_baseline_index,
    build_evaluation_authorization,
    build_paired_evaluation_report,
    build_skill_evaluation_episode,
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
    / "workspace/evals/sp002_runs/sp002_live_20260718_193656_a6ce837e/episode.json"
)
BASELINE_SESSION = BASELINE_EPISODE.with_name("session.json")
BASELINE_VERIFICATION = BASELINE_EPISODE.with_name("verification.json")
SKILL = POLICY["target_skill"]
PREDECESSOR = "a" * 40
AUTHORIZATION_COMMIT = "b" * 40


def test_policy_identity_binds_protocol_fixture_skill_and_three_baselines():
    report = policy_identity_report()
    assert report["passed"], report["issues"]
    assert file_sha256(POLICY_PATH) == POLICY_SHA256
    assert POLICY["base_protocol"]["sha256"] == PROTOCOL_SHA256
    assert report["skill_record_canonical_sha256"] == SKILL["record_canonical_sha256"]
    assert report["candidate_record_canonical_sha256"] == SKILL["queue_record_canonical_sha256"]
    assert len(set(report["baseline_session_ids"])) == 3
    assert len(set(report["baseline_episode_ids"])) == 3


def test_retained_baselines_are_distinct_and_control_equivalent():
    index = build_baseline_index()
    assert index["all_records_passed"]
    assert index["record_count"] == 3
    assert len({record["session_id"] for record in index["records"]}) == 3
    assert len({record["fixed_controls_fingerprint"] for record in index["records"]}) == 1
    assert len({record["initial_state_fingerprint"] for record in index["records"]}) == 1
    assert all(verify_run_record(record)["passed"] for record in index["records"])


def test_candidate_authorization_is_parent_bound_and_has_no_runtime_authority():
    authorization = _authorization("candidate", "r1", "candidate-auth-r1")
    audit = validate_evaluation_authorization(
        authorization,
        expected_arm="candidate",
        expected_replicate_id="r1",
        expected_episode_id="candidate-auth-r1",
        current_head=AUTHORIZATION_COMMIT,
        parent_head=PREDECESSOR,
    )
    assert audit["passed"], audit["issues"]
    assert authorization["baseline_binding"] == pair_binding("r1")
    assert authorization["skill_id"] == "learned:craft_stone_pickaxe"
    assert authorization["skill_status"] == "advisory"
    assert authorization["normal_runtime_permission"] is False
    assert authorization["automatic_retry_allowed"] is False


def test_authorization_rejects_wrong_parent_version_and_consumed_replicate():
    authorization = _authorization("candidate", "r1", "wrong-parent")
    audit = validate_evaluation_authorization(
        authorization,
        current_head=AUTHORIZATION_COMMIT,
        parent_head="c" * 40,
    )
    assert not audit["passed"]
    assert "authorization_predecessor" in audit["issues"]

    modified = copy.deepcopy(authorization)
    modified["skill_version"] = "1.0.1"
    audit = validate_evaluation_authorization(modified)
    assert not audit["passed"]
    assert "authorization_skill_version" in audit["issues"]

    with tempfile.TemporaryDirectory(
        prefix="sp002-auth-test-",
        dir=REPOSITORY_ROOT / "workspace/evals",
    ) as directory:
        consumed = Path(directory) / "authorization.json"
        consumed.write_text(
            json.dumps({"arm": "candidate", "replicate_id": "r1"}),
            encoding="utf-8",
        )
        try:
            build_evaluation_authorization(
                arm="candidate",
                replicate_id="r1",
                episode_id="candidate-reuse",
                authorization_predecessor=PREDECESSOR,
                existing_run_paths=[consumed],
            )
        except ValueError as exc:
            assert "already consumed" in str(exc)
        else:
            raise AssertionError("consumed replicate authorization was accepted")


def test_runtime_config_maps_all_arms_without_enabling_default_runtime():
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


def test_fallback_arm_cannot_execute_the_advisory_skill_in_runtime_mode():
    library = SkillLibrary(
        storage_path=str(REPOSITORY_ROOT / "workspace/skills"),
        persist=False,
    )
    observation = {
        "position": {"x": 96.5, "y": 144.0, "z": -31.5},
        "inventory": {"cobblestone": 3, "stick": 2},
        "nearby_blocks": [{
            "name": "crafting_table",
            "position": {"x": 97, "y": 144, "z": -32},
            "distance": 1.0,
        }],
    }
    selected = library.select_runtime_skill(
        POLICY["fixed_controls"]["goal"],
        observation,
        execution_mode="runtime",
        target_skill_id=SKILL["skill_id"],
    )
    assert selected is None


def test_evaluation_episode_accepts_exact_candidate_selection_only(monkeypatch):
    import singularity.evaluation.stone_pickaxe_sp002_skill_evaluation as evaluation

    base = read_json(BASELINE_EPISODE)
    base["selected_skills"] = [{
        "skill_id": SKILL["skill_id"],
        "version": SKILL["version"],
        "status": SKILL["required_status"],
    }]
    monkeypatch.setattr(evaluation, "build_sp002_episode", lambda **_: copy.deepcopy(base))
    authorization = _authorization("candidate", "r1", base["episode_id"])
    episode = build_skill_evaluation_episode(
        authorization=authorization,
        episode_id=base["episode_id"],
    )
    assert episode["eligibility"]["skill_evaluation_authorization"] is True
    assert episode["eligibility"]["skill_arm_selection"] is True
    assert episode["eligibility"]["passed"] is True

    base["selected_skills"][0]["version"] = "1.0.1"
    rejected = build_skill_evaluation_episode(
        authorization=authorization,
        episode_id=base["episode_id"],
    )
    assert rejected["eligibility"]["skill_arm_selection"] is False
    assert rejected["eligibility"]["passed"] is False


def test_candidate_run_recomputes_exact_single_action_attribution():
    run = _candidate_run("r1", "candidate-session-r1")
    assert run["status"] == "pass", [
        name for name, passed in run["checks"].items() if not passed
    ]
    assert run["metrics"]["skill_selected_count"] == 1
    assert run["metrics"]["skill_executed_count"] == 1
    assert run["metrics"]["skill_completion_count"] == 1
    assert run["metrics"]["candidate_steps_verified"] is True
    assert run["metrics"]["candidate_steps_reobserved"] is True
    assert run["metrics"]["exact_skill_context_only"] is True
    assert verify_run_record(run)["passed"]


def test_report_requires_support_arms_and_all_three_candidate_pairs():
    with tempfile.TemporaryDirectory(
        prefix="sp002-eval-test-",
        dir=REPOSITORY_ROOT / "workspace/evals",
    ) as directory:
        root = Path(directory)
        candidates = [
            _candidate_run(f"r{index}", f"candidate-session-r{index}")
            for index in range(1, 4)
        ]
        support = [
            _support_run("shadow", "shadow-1", "skill_shadow_plan_count"),
            _support_run("advisory", "advisory-1", "skill_advisory_hint_count"),
            _support_run("fallback", "fallback-1", "skill_fallback_count"),
        ]
        paths = []
        for index, run in enumerate(support + candidates, 1):
            path = write_json(root / f"run-{index}.json", run)
            paths.append(path)
        report = build_paired_evaluation_report(paths)
        assert report["valid_pair_count"] == 3
        assert report["shadow_verified"] is True
        assert report["advisory_verified"] is True
        assert report["fallback_verified"] is True
        assert report["readiness"] == "approved"
        assert report["decision"] == "review_executable_new_version"
        assert report["executable_promotion_gate"]["validation_issues"] == []

        report = build_paired_evaluation_report(paths[:-1])
        assert report["valid_pair_count"] == 2
        assert report["readiness"] == "review"
        assert report["decision"] == "retain_advisory"


def test_frozen_sp002_baseline_hashes_match_policy_bindings():
    for binding in POLICY["pair_bindings"]:
        for label in ("episode", "verification", "manifest", "session"):
            path = REPOSITORY_ROOT / binding[f"{label}_path"]
            assert file_sha256(path) == binding[f"{label}_sha256"]


def test_sp002_evidence_attributes_are_isolated_from_frozen_sp001_windows():
    assert file_sha256(REPOSITORY_ROOT / "workspace/evals/.gitattributes") == (
        "e12faffa3b5452c743e7df344478e0d85897899bbca79c25b7667ddb64dcdfab"
    )
    for label in ("evidence_attributes", "run_evidence_attributes"):
        binding = POLICY["implementation"][label]
        assert file_sha256(REPOSITORY_ROOT / binding["path"]) == binding["sha256"]


def _authorization(arm: str, replicate: str, episode: str) -> dict:
    return build_evaluation_authorization(
        arm=arm,
        replicate_id=replicate,
        episode_id=episode,
        authorization_predecessor=PREDECESSOR,
        existing_run_paths=[],
    )


def _candidate_run(replicate: str, session_id: str) -> dict:
    binding = pair_binding(replicate)
    episode = read_json(REPOSITORY_ROOT / binding["episode_path"])
    verification = read_json(REPOSITORY_ROOT / binding["verification_path"])
    events = read_json(REPOSITORY_ROOT / binding["session_path"])
    events = copy.deepcopy(events)
    action_events = [event for event in events if event.get("type") == "action"]
    assert len(action_events) == 1
    context = {
        "skill_id": SKILL["skill_id"],
        "skill_name": SKILL["name"],
        "version": SKILL["version"],
        "status": SKILL["required_status"],
        "mode": "evaluation",
    }
    action_events[0]["data"]["action"]["skill_context"] = context
    events.append({
        "type": "skill_selected",
        "data": {"skill": dict(context)},
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
    episode = copy.deepcopy(episode)
    episode["session_id"] = session_id
    episode["selected_skills"] = [{
        "skill_id": SKILL["skill_id"],
        "version": SKILL["version"],
        "status": SKILL["required_status"],
    }]
    episode["eligibility"]["skill_arm_selection"] = True
    episode["eligibility"]["passed"] = True
    authorization = _authorization("candidate", replicate, episode["episode_id"])
    return build_skill_evaluation_run(
        episode=episode,
        verification=verification,
        events=events,
        authorization=authorization,
        source_evidence=[{
            "path": POLICY["base_protocol"]["path"],
            "sha256": POLICY["base_protocol"]["sha256"],
        }],
        preflight_passed=True,
    )


def _support_run(arm: str, replicate: str, metric: str) -> dict:
    run = _candidate_run("r1", f"support-session-{arm}")
    run["arm"] = arm
    run["replicate_id"] = replicate
    run["pair_id"] = ""
    run["run_id"] = f"{arm}:support-session-{arm}"
    run["checks"] = {"support_contract": True}
    run["metrics"]["skill_selected_count"] = 0
    run["metrics"]["skill_executed_count"] = 0
    run["metrics"]["skill_completion_count"] = 0
    run["metrics"][metric] = 1
    payload = dict(run)
    payload.pop("record_payload_sha256", None)
    run["record_payload_sha256"] = canonical_record_sha256(payload)
    return run
