from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess

from singularity.evaluation.stone_pickaxe_sp003_phase122_runtime import (
    SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
    StonePickaxeSP003Phase122RuntimeAgent,
)
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    SP003_GOAL,
    SP003_GROUNDED_APPROACH_PRE_DISPATCH_REPLAN_POLICY_ID,
    SP003_PRE_DISPATCH_REPLAN_POLICY_ID,
    verify_sp003_policy_identity,
)


REPO = Path(__file__).resolve().parents[1]
RUN_DIR = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_095823_dad3c456"
)
AUDIT_PATH = (
    REPO
    / "workspace/evals/stone_pickaxe_sp003_grounded_approach_replan_repair.json"
)


class LogStub:
    def __init__(self):
        self.events = []

    def log(self, event_type, data, level="INFO"):
        self.events.append({"type": event_type, "data": data, "level": level})

    def get_summary(self):
        return {"action_count": 0}


def _events():
    return json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))


def _phase131_divergence():
    events = _events()
    call_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "llm_planner_call"
        and event["data"].get("call_index") == 18
    )
    observation = next(
        event["data"]
        for event in reversed(events[:call_index])
        if event.get("type") == "observation"
    )
    plan = next(
        event["data"]
        for event in events[call_index + 1 :]
        if event.get("type") == "plan"
    )
    return copy.deepcopy(observation), copy.deepcopy(plan["actions"][0])


def _bare_agent(observation):
    agent = StonePickaxeSP003Phase122RuntimeAgent.__new__(
        StonePickaxeSP003Phase122RuntimeAgent
    )
    agent.sp003_arm = "baseline"
    agent.sp003_progress = copy.deepcopy(observation["sp003_progress"])
    agent._sp003_phase120_egress_attempted_fingerprints = set()
    agent._sp003_pre_dispatch_replan_fingerprints = set()
    agent._sp003_pre_dispatch_replan_count = 0
    agent._sp003_actionless_replan_fingerprints = set()
    agent._sp003_actionless_replan_count = 0
    agent.session_logger = LogStub()
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent.replan_reasons = []
    agent._request_m2_replan = agent.replan_reasons.append
    return agent


def test_phase132_replays_the_exact_phase131_grounded_approach_rejection():
    observation, action = _phase131_divergence()
    agent = _bare_agent(observation)

    target = observation["sp003_targets"][0]
    assert target["source_id"] == "stone:124:138:-38"
    assert target["navigation_only"] is True
    assert target["stone_pickup_approach"] is True
    assert "source_id" not in action["parameters"]

    guard = agent._effective_sp003_action_guard(action, observation)
    assert guard["policy_id"] == SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID
    assert guard["allowed"] is False
    assert guard["issues"] == [
        "sp003_stone_grounded_approach_required_before_dig"
    ]

    original = copy.deepcopy(action)
    replan = agent._pre_dispatch_replan_for_action(
        action,
        observation,
        SP003_GOAL,
        {"cycle": 19, "mode": "goal"},
    )
    assert replan["requires_replan"] is True
    assert replan["policy_id"] == (
        SP003_GROUNDED_APPROACH_PRE_DISPATCH_REPLAN_POLICY_ID
    )
    assert action == original

    report = agent.session_logger.events[-1]["data"]
    assert report["policy_id"] == (
        SP003_GROUNDED_APPROACH_PRE_DISPATCH_REPLAN_POLICY_ID
    )
    assert report["parent_policy_id"] == SP003_PRE_DISPATCH_REPLAN_POLICY_ID
    assert report["granted"] is True
    assert report["action_suppressed_before_dispatch"] is True
    assert report["action_budget_consumed"] is False
    assert report["backend_invoked"] is False
    assert report["world_mutation"] is False
    assert report["same_call_retry_count"] == 0
    assert report["fresh_observation_required"] is True
    assert report["action_rewrite"] is False


def test_phase132_inherits_existing_bounds_and_keeps_other_safety_rejections():
    observation, action = _phase131_divergence()
    agent = _bare_agent(observation)

    first = agent._pre_dispatch_replan_for_action(
        action, observation, SP003_GOAL, {"cycle": 19, "mode": "goal"}
    )
    duplicate = agent._pre_dispatch_replan_for_action(
        action, observation, SP003_GOAL, {"cycle": 20, "mode": "goal"}
    )
    assert first["requires_replan"] is True
    assert duplicate is None
    reports = [
        event["data"]
        for event in agent.session_logger.events
        if event["type"] == "stone_pickaxe_sp003_pre_dispatch_replan"
    ]
    assert [report["granted"] for report in reports] == [True, False]
    assert reports[-1]["limit_reason"] == "fingerprint_limit_exhausted"

    unsafe = _bare_agent(observation)
    wrong_target = {
        "type": "dig",
        "parameters": {"block": "stone", "x": 999, "y": 1, "z": 999},
    }
    guard = unsafe._effective_sp003_action_guard(wrong_target, observation)
    assert guard["allowed"] is False
    assert guard["issues"] != [
        "sp003_stone_grounded_approach_required_before_dig"
    ]
    assert unsafe._pre_dispatch_replan_for_action(
        wrong_target,
        observation,
        SP003_GOAL,
        {"cycle": 19, "mode": "goal"},
    ) is None
    assert unsafe.session_logger.events == []

    mixed = _bare_agent(observation)
    mixed._effective_sp003_action_guard = lambda *_: {
        "allowed": False,
        "stage": "acquire_stone",
        "issues": [
            "sp003_stone_grounded_approach_required_before_dig",
            "sp003_exact_one_stone_pickaxe_craft_required",
        ],
    }
    assert mixed._pre_dispatch_replan_for_action(
        action,
        observation,
        SP003_GOAL,
        {"cycle": 19, "mode": "goal"},
    ) is None
    assert mixed.session_logger.events == []


def test_phase132_counterfactual_removes_only_the_failed_fourth_stone_action():
    events = _events()
    actions = [event["data"] for event in events if event.get("type") == "action"]
    episode = json.loads((RUN_DIR / "episode.json").read_text(encoding="utf-8"))
    terminal = [
        event["data"] for event in events if event.get("type") == "observation"
    ][-1]

    assert len(actions) == 23
    assert actions[18]["result"]["success"] is False
    counterfactual = actions[:18] + actions[19:]
    assert len(counterfactual) == 22
    assert all(action["result"].get("success") is True for action in counterfactual)
    stone_digs = [
        action
        for action in counterfactual
        if action["action"].get("type") == "dig"
        and action["action"].get("parameters", {}).get("block") == "stone"
    ]
    assert len(stone_digs) == 3
    assert len(
        {
            action["action"]["parameters"]["source_id"]
            for action in stone_digs
        }
    ) == 3
    assert len(episode["raw_action_failures"]) == 1
    assert terminal["inventory"]["stone_pickaxe"] == 1
    assert terminal["sp003_progress"]["stone_source_removal_count"] == 3


def test_phase132_policy_contract_is_machine_bound():
    identity = verify_sp003_policy_identity()
    assert identity["passed"], identity
    assert identity["checks"][
        "grounded_approach_pre_dispatch_replan_contract"
    ] is True

    policy = json.loads(
        (
            REPO / "workspace/evals/stone_pickaxe_sp003_harness_policy.json"
        ).read_text(encoding="utf-8")
    )
    contract = policy["episode_contract"]
    assert contract["grounded_approach_pre_dispatch_replan_policy_id"] == (
        SP003_GROUNDED_APPROACH_PRE_DISPATCH_REPLAN_POLICY_ID
    )
    assert contract["grounded_approach_pre_dispatch_replan_exact_issue"] == (
        "sp003_stone_grounded_approach_required_before_dig"
    )
    assert contract[
        "grounded_approach_pre_dispatch_replan_inherits_existing_bounds"
    ] is True


def test_phase132_audit_binds_implementation_and_retained_failure():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert audit["phase"] == 132
    assert audit["base_commit"] == (
        "00ee52711c085931dfc0962ab006f472cfe753f4"
    )
    assert audit["policy_id"] == (
        SP003_GROUNDED_APPROACH_PRE_DISPATCH_REPLAN_POLICY_ID
    )
    assert audit["status"] == "offline_verified"
    assert audit["retained_phase_131_failure"]["manifest_sha256"] == (
        "2ae4db2da1170ee976ce26fc42b03088ee0cfe13f60c226f4b44137159cdbee2"
    )
    assert audit["counterfactual_tests"]["focused_cases"] == "5/5"
    assert audit["repair_contract"]["action_rewrite_allowed"] is False
    assert audit["repair_contract"]["same_call_retry_allowed"] is False
    assert audit["repair_contract"]["backend_invocation_on_replan"] is False
    assert audit["repair_contract"]["action_budget_consumed_on_replan"] is False
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_skill_gate"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
    evolved_historical_paths = {
        "src/singularity/evaluation/stone_pickaxe_sp003_runtime.py": (
            "c6aa6b2836215e58ee3465e4185e5eb30cf975aebf5896cb18f491789c6b7312"
        ),
        "tests/test_stone_pickaxe_sp003_phase130_replan_dispatch.py": (
            "3c368b04fbeef200e0b85687721691d573285b421bbf51d18031c0ee3a98ae3d"
        ),
        "tests/test_stone_pickaxe_sp003_phase132_grounded_approach_replan.py": (
            "681c5282a89c91fbed4aa5b10771f411f7f4c412a8d9ed0355db6620ceb8a98c"
        ),
        "workspace/evals/stone_pickaxe_sp003_harness_policy.json": (
            "227523095386318a67614b4205e44360e78f77d596d6e166080e8c383bb87dcf"
        ),
    }
    records = [
        *audit["implementation"],
        *audit["protected_identities"],
        *audit["retained_phase_131_identities"],
    ]
    assert {
        record["path"]: record["sha256"]
        for record in records
        if record["path"] in evolved_historical_paths
    } == evolved_historical_paths
    for record in records:
        if record["path"] in evolved_historical_paths:
            retained = subprocess.check_output(
                [
                    "git",
                    "show",
                    f"0393ba45fd3cf1ea1cafb3536d3000eb857868de:{record['path']}",
                ],
                cwd=REPO,
            )
            actual = hashlib.sha256(retained).hexdigest()
        else:
            actual = hashlib.sha256((REPO / record["path"]).read_bytes()).hexdigest()
        assert actual == record["sha256"]
