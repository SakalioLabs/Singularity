import copy
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import singularity.evaluation.stone_pickaxe_sp002_skill_evaluation as v1
import singularity.evaluation.stone_pickaxe_sp002_skill_evaluation_v2 as recovery
from singularity.evaluation.stone_pickaxe_protocol import REPOSITORY_ROOT


PREDECESSOR = "a" * 40
AUTHORIZATION_COMMIT = "b" * 40
FAILED_RUN_PATH = (
    REPOSITORY_ROOT
    / "workspace/evals/sp002_skill_evaluation_runs/"
    "sp002_skill_shadow_20260718_235731_deb281fc/evaluation_run.json"
)
FROZEN_V1_FILES = {
    "workspace/evals/sp002_skill_evaluation/stone_pickaxe_sp002_paired_evaluation_policy.json": (
        "f050c96428f9be7c576a19acc9b6ef135fd9530f49c959bb67024d721eb87880"
    ),
    "workspace/evals/sp002_skill_evaluation/craft_stone_pickaxe_paired_evaluation.json": (
        "54a836ec1b2a16d97409b117ba5a0a0d54b037dce576a69d1d6edba8dfa443eb"
    ),
    "workspace/evals/sp002_skill_evaluation_runs/"
    "sp002_skill_shadow_20260718_235731_deb281fc/evaluation_run.json": (
        "a5efc29ffe388a4d81d5cf47adf4ee6cdae778a8fd1b33cb9be3d7dea01cea8f"
    ),
    "workspace/evals/.gitattributes": (
        "e12faffa3b5452c743e7df344478e0d85897899bbca79c25b7667ddb64dcdfab"
    ),
}


def test_recovery_policy_is_valid_and_v1_context_is_unchanged():
    report = recovery.policy_identity_report()
    assert report["passed"], report["issues"]
    assert recovery.file_sha256(recovery.POLICY_PATH) == recovery.POLICY_SHA256
    assert recovery.POLICY["arms"]["candidate"]["replicate_ids"] == ["r4", "r5", "r6"]
    assert recovery.POLICY["recovery_window"]["excluded_replicate_ids"] == [
        "shadow-1",
        "advisory-1",
        "fallback-1",
        "r1",
        "r2",
        "r3",
    ]
    v1_report = v1.policy_identity_report()
    assert v1_report["passed"], v1_report["issues"]
    assert v1_report["policy_id"] == "stone-pickaxe-sp002-paired-evaluation-v1"


def test_recovery_authorization_is_parent_bound_and_rejects_prior_ids():
    authorization = _authorization("shadow", "shadow-2", "shadow-v2-test")
    audit = recovery.validate_evaluation_authorization(
        authorization,
        expected_arm="shadow",
        expected_replicate_id="shadow-2",
        expected_episode_id="shadow-v2-test",
        current_head=AUTHORIZATION_COMMIT,
        parent_head=PREDECESSOR,
    )
    assert audit["passed"], audit["issues"]
    assert authorization["authorization_predecessor"] == PREDECESSOR
    assert authorization["evaluation_window_id"] == "sp002-first-cycle-skill-routing-v2"
    assert authorization["automatic_retry_allowed"] is False

    with pytest.raises(ValueError, match="prior window"):
        _authorization("shadow", "shadow-1", "prior-shadow-test")

    with _repository_tempdir() as root:
        consumed = root / "consumed.json"
        consumed.write_text(
            json.dumps({"arm": "shadow", "replicate_id": "shadow-2"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="already consumed"):
            recovery.build_evaluation_authorization(
                arm="shadow",
                replicate_id="shadow-2",
                episode_id="duplicate-shadow-test",
                authorization_predecessor=PREDECESSOR,
                existing_run_paths=[consumed],
            )


@pytest.mark.parametrize(
    ("arm", "replicate", "mode"),
    (
        ("shadow", "shadow-2", "shadow"),
        ("advisory", "advisory-2", "advisory"),
        ("fallback", "fallback-2", "runtime"),
        ("candidate", "r4", "evaluation"),
    ),
)
def test_recovery_runtime_config_maps_only_controlled_modes(arm, replicate, mode):
    authorization = _authorization(arm, replicate, f"{arm}-config-test")
    config = recovery.build_skill_evaluation_runtime_config(
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
    assert config.target_skill_id == recovery.POLICY["target_skill"]["skill_id"]
    assert config.skill_runtime_default_gate_paths == []
    assert config.enable_skill_candidate_extraction is False


@pytest.mark.parametrize("mode", ("shadow", "advisory", "runtime"))
def test_support_modes_route_skill_before_first_root_planner_call(mode):
    order = []
    agent, logger = _bare_agent(mode)
    agent._learned_skill_plan = lambda goal, observation: order.append("skill")
    agent._think_llm = lambda observation, goal: (
        order.append("llm") or {"status": "active", "subtasks": [], "actions": []}
    )

    plan = agent._think({}, "Craft exactly 1 stone_pickaxe")

    assert order == ["skill", "llm"]
    assert plan["status"] == "active"
    event = next(data for name, data in logger.events if name == "sp002_skill_first_cycle_routing")
    assert event["mode"] == mode
    assert event["root_plan_valid_before_routing"] is False


def test_candidate_first_cycle_preserves_root_subtasks_and_overlays_skill_action():
    order = []
    agent, logger = _bare_agent("evaluation")
    root_subtasks = [
        {"id": "inspect", "title": "Inspect ingredients"},
        {"id": "craft", "title": "Craft the stone pickaxe"},
    ]

    def root_plan(observation, goal):
        order.append("llm")
        agent._m2_root_plan_valid = True
        return {
            "status": "active",
            "subtasks": root_subtasks,
            "actions": [{"type": "look", "yaw": 0}],
        }

    skill_action = {
        "type": "craft",
        "item": "stone_pickaxe",
        "count": 1,
        "skill_context": {"skill_id": "learned:craft_stone_pickaxe"},
    }
    agent._think_llm = root_plan
    agent._learned_skill_plan = lambda goal, observation: (
        order.append("skill") or {"status": "active", "actions": [skill_action]}
    )

    plan = agent._think({}, "Craft exactly 1 stone_pickaxe")

    assert order == ["llm", "skill"]
    assert plan["subtasks"] == root_subtasks
    assert plan["actions"] == [skill_action]
    assert plan["sp002_skill_first_cycle_overlay"]["root_planner_call_preserved"] is True
    event = next(data for name, data in logger.events if name == "sp002_skill_first_cycle_routing")
    assert event["runtime_influence"] is True


def test_candidate_first_cycle_fails_closed_when_root_plan_is_invalid():
    agent, _ = _bare_agent("evaluation")
    calls = []
    agent._think_llm = lambda observation, goal: {
        "status": "error",
        "subtasks": [],
        "actions": [],
    }
    agent._learned_skill_plan = lambda goal, observation: calls.append("skill")

    plan = agent._think({}, "Craft exactly 1 stone_pickaxe")

    assert plan["status"] == "error"
    assert calls == []


def test_report_uses_fresh_support_ids_and_excludes_retained_v1_failure():
    report = recovery.build_paired_evaluation_report(
        recovery.discover_evaluation_run_paths()
    )
    assert [(item["arm"], item["replicate_id"], item["status"]) for item in report["support_runs"]] == [
        ("shadow", "shadow-2", "pass"),
        ("advisory", "advisory-2", "missing"),
        ("fallback", "fallback-2", "missing"),
    ]
    assert [item["replicate_id"] for item in report["excluded_prior_runs"]] == ["shadow-1"]
    assert report["valid_pair_count"] == 0
    assert report["shadow_verified"] is True
    assert report["decision"] == "retain_advisory"


def test_report_requires_all_fresh_support_and_candidate_runs():
    with _repository_tempdir() as root:
        paths = []
        for arm, replicate, metric in (
            ("shadow", "shadow-2", "skill_shadow_plan_count"),
            ("advisory", "advisory-2", "skill_advisory_hint_count"),
            ("fallback", "fallback-2", "skill_fallback_count"),
        ):
            paths.append(_write_run(root, _support_run(arm, replicate, metric)))
        for ordinal, replicate in enumerate(("r4", "r5", "r6"), 1):
            paths.append(_write_run(root, _candidate_run(replicate, ordinal)))

        report = recovery.build_paired_evaluation_report(paths)

    assert report["valid_pair_count"] == 3
    assert report["shadow_verified"] is True
    assert report["advisory_verified"] is True
    assert report["fallback_verified"] is True
    assert report["decision"] == "review_executable_new_version"
    assert report["readiness"] == "approved"
    assert report["executable_promotion_gate"]["validation_issues"] == []


def test_v1_failure_and_parent_attributes_remain_byte_immutable():
    for relative, expected_hash in FROZEN_V1_FILES.items():
        assert recovery.file_sha256(REPOSITORY_ROOT / relative) == expected_hash
    failed = recovery.read_json(FAILED_RUN_PATH)
    assert failed["status"] == "fail"
    assert failed["replicate_id"] == "shadow-1"
    assert failed["record_payload_sha256"] == (
        "25b65b34a4ef2a9c56d73aeb0ab6a401407eac630a5562a15be38e17e8d5b8fe"
    )


def test_generated_initial_report_is_non_promoting_and_uses_v2_ids():
    path = (
        REPOSITORY_ROOT
        / "workspace/evals/sp002_skill_evaluation_v2/"
        "craft_stone_pickaxe_paired_evaluation_v2.json"
    )
    report = recovery.read_json(path)
    assert report["policy_sha256"] == recovery.POLICY_SHA256
    assert report["valid_pair_count"] == 0
    assert report["decision"] == "retain_advisory"
    assert [item["replicate_id"] for item in report["support_runs"]] == [
        "shadow-2",
        "advisory-2",
        "fallback-2",
    ]


def _authorization(arm: str, replicate: str, episode: str) -> dict:
    return recovery.build_evaluation_authorization(
        arm=arm,
        replicate_id=replicate,
        episode_id=episode,
        authorization_predecessor=PREDECESSOR,
        existing_run_paths=[],
    )


def _bare_agent(mode: str):
    class Logger:
        def __init__(self):
            self.events = []

        def log(self, name, data, **kwargs):
            self.events.append((name, data))

    logger = Logger()
    agent = object.__new__(recovery.StonePickaxeSP002SkillEvaluationAgent)
    agent.config = SimpleNamespace(
        skill_execution_mode=mode,
        require_llm_root_plan=True,
    )
    agent.current_goal = "Craft exactly 1 stone_pickaxe"
    agent._episode_deadline_monotonic = None
    agent._m2_root_plan_valid = False
    agent._use_llm = True
    agent.session_logger = logger
    agent._blocked_plan_rule_fallback = lambda plan, goal, observation: plan
    agent._apply_visual_action_grounding = lambda plan, observation, goal: plan
    return agent, logger


def _support_run(arm: str, replicate: str, metric: str) -> dict:
    run = copy.deepcopy(recovery.build_baseline_index()["records"][0])
    run.update({
        "run_id": f"{arm}:offline-{replicate}",
        "arm": arm,
        "replicate_id": replicate,
        "pair_id": "",
        "session_id": f"offline-session-{replicate}",
        "evaluation_window_id": recovery.POLICY["recovery_window"]["id"],
        "checks": {"support_contract": True},
    })
    run["metrics"].update({
        "skill_selected_count": 0,
        "skill_executed_count": 0,
        "skill_completion_count": 0,
        metric: 1,
    })
    return _fingerprint(run)


def _candidate_run(replicate: str, ordinal: int) -> dict:
    baseline = next(
        record
        for record in recovery.build_baseline_index()["records"]
        if record["replicate_id"] == replicate
    )
    run = copy.deepcopy(baseline)
    run.update({
        "run_id": f"candidate:offline-{replicate}",
        "arm": "candidate",
        "session_id": f"offline-candidate-session-{ordinal}",
        "evaluation_window_id": recovery.POLICY["recovery_window"]["id"],
        "checks": {"candidate_contract": True},
    })
    run["metrics"].update({
        "skill_selected_count": 1,
        "skill_executed_count": 1,
        "skill_completion_count": 1,
        "candidate_steps_verified": True,
        "candidate_steps_reobserved": True,
        "exact_skill_context_only": True,
        "attribution_confidence": 1.0,
    })
    return _fingerprint(run)


def _fingerprint(run: dict) -> dict:
    run.pop("record_payload_sha256", None)
    run["record_payload_sha256"] = recovery.canonical_record_sha256(run)
    return run


def _write_run(root: Path, run: dict) -> Path:
    path = root / f"{run['arm']}-{run['replicate_id']}.json"
    path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    return path


@contextmanager
def _repository_tempdir():
    with tempfile.TemporaryDirectory(
        prefix="sp002-v2-test-",
        dir=REPOSITORY_ROOT / "workspace/evals",
    ) as directory:
        yield Path(directory)
