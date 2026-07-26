import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe42_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe42_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(report: dict) -> list[dict]:
    events = []
    for line_number, line in enumerate(
        (ROOT / report["evidence_paths"]["raw_session_jsonl"]).read_text(
            encoding="utf-8"
        ).splitlines(),
        1,
    ):
        if not line.strip():
            continue
        event = json.loads(line)
        event["_line"] = line_number
        events.append(event)
    return events


def test_m4_probe42_report_binds_grok_latency_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 42
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["frozen_controls"]["provider_modalities"] == ["text", "image"]
    assert report["frozen_controls"]["runtime_modalities"] == ["text"]
    assert report["episode_result"]["completed"] is False
    assert report["episode_result"]["termination_reason"] == "episode_deadline"
    assert report["episode_result"]["planner_call_count"] == 23
    assert report["episode_result"]["real_planner_call_count"] == 21
    assert report["episode_result"]["schema_valid_real_planner_call_count"] == 21
    assert report["episode_result"]["schema_invalid_nonreal_call_count"] == 2
    assert report["episode_result"]["planner_timeout_call_count"] == 2
    assert report["episode_result"]["action_count"] == 19
    assert report["episode_result"]["successful_action_count"] == 19
    assert report["episode_result"]["terminal_inventory"]["wooden_pickaxe"] == 1
    assert report["episode_result"]["terminal_inventory"]["cobblestone"] == 1
    assert "stone_pickaxe" not in report["episode_result"]["terminal_inventory"]
    assert report["behavioral_progression"]["wooden_pickaxe_to_positive_cobblestone"]
    assert not report["behavioral_progression"]["wooden_pickaxe_to_three_cobblestone"]
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["bm012_success_count_after"] == 1


def test_probe42_jsonl_exposes_no_detour_but_planner_latency_tail():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 521
    actions = [event for event in events if event.get("type") == "action"]
    assert len(actions) == 19
    assert all(action["data"]["result"]["success"] is True for action in actions)

    goals = [
        event["data"]["goal"]
        for event in events
        if event.get("type") == "auto_goal"
    ]
    assert "Collect coal or charcoal for torches" not in goals
    assert goals[:4] == [
        "Gather 6 oak logs for tools and shelter",
        "Craft and place a crafting table for iron-tool progression",
        "Craft a wooden pickaxe for stone acquisition",
        "Gather 3 cobblestone with the wooden pickaxe",
    ]

    assert events[185]["_line"] == 186
    assert events[185]["data"]["action"] == {
        "type": "craft",
        "parameters": {"item": "oak_planks", "count": 4},
    }
    assert events[231]["_line"] == 232
    assert events[231]["data"]["action"]["type"] == "place"
    assert events[391]["_line"] == 392
    assert events[391]["data"]["action"] == {
        "type": "craft",
        "parameters": {"item": "wooden_pickaxe", "count": 1},
    }
    assert events[420]["_line"] == 421
    assert events[420]["data"]["action"] == {
        "type": "equip",
        "parameters": {"item": "wooden_pickaxe"},
    }
    assert events[476]["_line"] == 477
    assert events[476]["data"]["action"] == {
        "type": "dig",
        "parameters": {"x": 114, "y": 133, "z": -29, "block": "stone"},
    }

    timeout_lines = [
        event["_line"]
        for event in events
        if event.get("type") == "llm_planner_call"
        and event["data"].get("real_llm_call") is False
        and event["data"].get("schema_valid") is False
    ]
    assert timeout_lines == [483, 513]
    assert events[487]["_line"] == 488
    assert events[487]["type"] == "m4_planner_transport_recovery"
    assert events[487]["data"]["error_type"] == "APITimeoutError"
    assert events[500]["_line"] == 501
    assert events[500]["type"] == "runtime_interrupt"
    assert events[500]["data"]["reason"] == "dusk_shelter_required"
    assert events[514]["_line"] == 515
    assert events[514]["type"] == "episode_deadline_exceeded"


def test_probe42_offline_repair_binds_machine_step_policy():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_bm012_planner_latency_toolchain_budget_gap"
    assert blocker["secondary_failure_layer"] == (
        "m4_bm012_single_action_planner_timeout_tail"
    )
    assert blocker["wooden_pickaxe_craft_action_line"] == 392
    assert blocker["cobblestone_dig_action_count"] == 1
    assert blocker["terminal_cobblestone"] == 1
    assert blocker["terminal_stone_pickaxe"] == 0

    repair = report["offline_repair"]
    assert repair["policy_id"] == "m4-bm012-toolchain-machine-step-plan-v1"
    assert repair["one_action_per_observation"] is True
    assert repair["completion_requires_machine_verifier"] is True
    assert repair["llm_bypassed_only_for_structured_machine_state"] is True
    assert repair["protocol_changed"] is False
    assert repair["task_contract_changed"] is False
    assert repair["validated_offline"] is True
    assert repair["probe_43_authorized"] is False
