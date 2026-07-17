import hashlib
import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from singularity.action.controller import ActionController
from singularity.core.agent import Agent
from singularity.core.goal_verifier import GoalVerification
from singularity.core.planner import Planner
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL, PROTOCOL_SHA256
from singularity.evaluation.stone_pickaxe_runtime import (
    build_fixture_artifact,
    build_runtime_config,
    build_sp001_episode,
    guard_runtime_action,
    planner_request_controls_audit,
    snapshot_tree_report,
    source_id,
    verify_fixture_manifest,
    verify_sp001_runtime_episode,
)


class _PlannerEvidenceLLM:
    def __init__(
        self,
        response: str,
        *,
        finish_reason: str = "stop",
        reasoning_bytes: int = 0,
    ):
        self.response = response
        self.finish_reason = finish_reason
        self.reasoning_bytes = reasoning_bytes
        self.calls = []
        self.last_call_metadata = {}

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        self.last_call_metadata = {
            "provider": "openai",
            "base_url": PROTOCOL["planner"]["base_url"],
            "model": PROTOCOL["planner"]["model"],
            "temperature": PROTOCOL["planner"]["temperature"],
            "max_tokens": PROTOCOL["planner"]["max_tokens"],
            "response_format": {"type": "json_object"},
            "request_sha256": "a" * 64,
            "timeout_s": kwargs.get("timeout_s"),
            "max_retries": 0 if kwargs.get("timeout_s") is not None else None,
            "finish_reason": self.finish_reason,
            "extra_body": dict(kwargs.get("extra_body", {})),
            "reasoning_content_byte_count": self.reasoning_bytes,
        }
        return self.response


def _raw_observation(cobblestone=0, remaining=(1, 2, 3)):
    return {
        "position": {"x": 0.0, "y": 64.0, "z": 0.0},
        "health": 20,
        "hunger": 20,
        "game_mode": "survival",
        "dimension": "overworld",
        "ground_block": "grass_block",
        "inventory": {"wooden_pickaxe": 1, **({"cobblestone": cobblestone} if cobblestone else {})},
        "nearby_entities": [],
        "nearby_blocks": [
            {
                "name": "stone",
                "position": {"x": x, "y": 64, "z": 0},
                "distance": float(x),
            }
            for x in remaining
        ],
    }


def _snapshot(tmp_path: Path, names=None):
    names = names or {
        "world": "world",
        "world_nether": "world_nether",
        "world_the_end": "world_the_end",
    }
    for index, component in enumerate(("world", "world_nether", "world_the_end"), start=1):
        root = tmp_path / names[component]
        root.mkdir(parents=True)
        (root / "level.dat").write_bytes(f"component-{index}".encode())
    return names


def _fixture_manifest(tree):
    return {
        "type": "stone_pickaxe_fixture_manifest",
        "schema_version": 1,
        "fixture_id": "sp001-acquire-cobblestone-v1",
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "snapshot_identity_verified": True,
        "snapshot": {
            "tree_sha256": tree["tree_sha256"],
            "file_count": tree["file_count"],
            "total_bytes": tree["total_bytes"],
        },
    }


def _planner_event():
    request_timeout = 179.5
    return {
        "type": "llm_planner_call",
        "monotonic_s": 10.0,
        "data": {
            "protocol": PROTOCOL["id"],
            "call_id": "offline-stone-call-1",
            "call_index": 0,
            "real_llm_call": True,
            "schema_valid": True,
            "response_sha256": "e" * 64,
            "response_byte_count": 128,
            "deadline_policy": {
                "policy_id": PROTOCOL["deadline_policy"]["id"],
                "remaining_before_call_s": 180.0,
                "request_timeout_s": request_timeout,
                "max_retries": 0,
            },
            "transport_evidence": {
                "policy_id": "single-attempt",
                "attempt_count": 1,
                "retry_count": 0,
                "attempts": [{
                    "attempt_index": 0,
                    "success": True,
                    "timeout_s": request_timeout,
                    "sdk_max_retries": 0,
                    "finish_reason": "stop",
                }],
            },
            "provider_metadata": {
                "provider": PROTOCOL["planner"]["provider"],
                "base_url": PROTOCOL["planner"]["base_url"],
                "model": PROTOCOL["planner"]["model"],
                "temperature": PROTOCOL["planner"]["temperature"],
                "max_tokens": PROTOCOL["planner"]["max_tokens"],
                "response_format": {"type": "json_object"},
                "extra_body": {"thinking": {"type": "disabled"}},
                "request_sha256": "d" * 64,
                "timeout_s": request_timeout,
                "max_retries": 0,
                "finish_reason": "stop",
                "reasoning_content_byte_count": 0,
            },
            "error": "",
        },
    }


def _stone_plan(goal, *, plan_kind="root", action=None, status="planning"):
    if action is None and status == "planning":
        action = {"type": "wait", "parameters": {"ms": 500}}
    subtasks = []
    if plan_kind == "root" and status == "planning":
        subtasks = [
            {
                "id": "observe_state",
                "title": "Observe the controlled machine state",
                "type": "observe",
                "priority": 1,
                "preconditions": {},
                "success_criteria": {"observed": True},
                "depends_on": [],
            },
            {
                "id": "advance_goal",
                "title": "Advance the exact stone-pickaxe goal",
                "type": "gather",
                "priority": 1,
                "preconditions": {},
                "success_criteria": {"inventory": {"wooden_pickaxe": 1}},
                "depends_on": ["observe_state"],
            },
        ]
    return {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": plan_kind,
        "goal": goal,
        "status": status,
        "reasoning": "Take one bounded machine-grounded action.",
        "subtasks": subtasks,
        "actions": [action] if action is not None else [],
    }


def _sp001_events():
    events = [_planner_event()]
    for index, x in enumerate((1, 2, 3), start=1):
        before = _raw_observation(index - 1, tuple(range(x, 4)))
        after = _raw_observation(index, tuple(range(x + 1, 4)))
        target = {"x": x, "y": 64, "z": 0}
        events.append({
            "type": "action",
            "elapsed_s": float(index),
            "data": {
                "action": {
                    "type": "dig",
                    "parameters": {
                        "block": "stone",
                        "x": x,
                        "y": 64,
                        "z": 0,
                        "source_id": source_id("stone", target),
                    },
                },
                "result": {
                    "success": True,
                    "block": "stone",
                    "target": target,
                    "block_removed": True,
                    "target_block_before": {"name": "stone", "position": target},
                    "target_block_after": {"name": "air", "position": target},
                    "expected_drops": ["cobblestone"],
                    "pickup_observed": True,
                    "pickup_inventory_delta": {"cobblestone": 1},
                    "dig_tool_equip": {
                        "selected_tool": "wooden_pickaxe",
                        "equipped_tool": "wooden_pickaxe",
                        "passed": True,
                    },
                    "dig_postcondition": {"passed": True},
                    "action_verification": {"status": "accept"},
                    "action_started_monotonic": 10.0 + index,
                    "action_finished_monotonic": 10.5 + index,
                },
                "pre_observation": before,
                "post_observation": after,
            },
        })
    return events


def test_snapshot_tree_hash_is_canonical_and_ignores_helper_manifest(tmp_path):
    _snapshot(tmp_path)
    first = snapshot_tree_report(tmp_path)
    (tmp_path / "snapshot_identity.json").write_text("{}", encoding="utf-8")
    second = snapshot_tree_report(tmp_path)
    assert first["passed"]
    assert first["tree_sha256"] == second["tree_sha256"]
    assert first["file_count"] == 3


def test_restored_component_names_produce_same_snapshot_identity(tmp_path):
    canonical = tmp_path / "canonical"
    restored = tmp_path / "restored"
    _snapshot(canonical)
    names = {
        "world": "episode",
        "world_nether": "episode_nether",
        "world_the_end": "episode_the_end",
    }
    _snapshot(restored, names)
    assert snapshot_tree_report(canonical)["tree_sha256"] == snapshot_tree_report(restored, names)["tree_sha256"]


def test_fixture_manifest_verification_detects_world_tampering(tmp_path):
    _snapshot(tmp_path)
    tree = snapshot_tree_report(tmp_path)
    manifest = _fixture_manifest(tree)
    assert verify_fixture_manifest(manifest, tmp_path)["passed"]
    (tmp_path / "world" / "level.dat").write_bytes(b"tampered")
    report = verify_fixture_manifest(manifest, tmp_path)
    assert not report["passed"]
    assert "tree_sha256" in report["issues"]


def test_sp001_guard_accepts_only_nearest_reachable_observed_stone():
    observation = _raw_observation()
    nearest = {
        "type": "dig",
        "parameters": {"block": "stone", "x": 1, "y": 64, "z": 0},
    }
    farther = {
        "type": "dig",
        "parameters": {"block": "stone", "x": 2, "y": 64, "z": 0},
    }
    allowed = guard_runtime_action("sp001", nearest, observation)
    rejected = guard_runtime_action("sp001", farther, observation)
    assert allowed["allowed"]
    assert allowed["action"]["parameters"]["source_id"] == "stone:1:64:0"
    assert not rejected["allowed"]
    assert "sp001_dig_target_must_be_nearest_observed" in rejected["issues"]


def test_sp001_machine_held_item_advances_past_equip_without_repeating_it():
    before = _raw_observation()
    before["equipment"] = [
        {"slot": 0, "name": "dark_oak_log", "count": 3},
        None,
        None,
        None,
        None,
        None,
    ]
    equip = {
        "type": "equip",
        "parameters": {"item": "wooden_pickaxe"},
    }
    assert guard_runtime_action("sp001", equip, before)["allowed"]

    after = dict(before)
    after["equipment"] = [
        {"slot": 0, "name": "wooden_pickaxe", "count": 1},
        None,
        None,
        None,
        None,
        None,
    ]
    compact = Planner._compact_stone_pickaxe_state(after)
    assert compact["held_item"] == "wooden_pickaxe"

    repeated = guard_runtime_action("sp001", equip, after)
    assert not repeated["allowed"]
    assert repeated["issues"] == ["sp001_redundant_wooden_pickaxe_equip"]

    planner = object.__new__(Planner)
    planner._expected_plan_kind = "continuation"
    prompt = Planner._stone_pickaxe_system_prompt(planner)
    assert "Treat held_item as the authoritative current main-hand item" in prompt
    assert "when held_item is wooden_pickaxe, never equip it again" in prompt


def test_retained_sp001_failure_reproduces_machine_state_equip_disconnect():
    root = Path(__file__).resolve().parents[1]
    session_path = (
        root
        / "workspace"
        / "evals"
        / "sp001_runs"
        / "sp001_episode_20260717_223525_23696e33"
        / "session_2c04a7f7-6e5.jsonl"
    )
    events = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
    ]
    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert len(actions) == 8
    assert {entry["action"]["type"] for entry in actions} == {"equip"}

    first = actions[0]
    assert first["pre_observation"]["equipment"][0]["name"] == "dark_oak_log"
    assert first["post_observation"]["equipment"][0]["name"] == "wooden_pickaxe"
    compact = Planner._compact_stone_pickaxe_state(first["post_observation"])
    assert compact["held_item"] == "wooden_pickaxe"
    report = guard_runtime_action("sp001", first["action"], first["post_observation"])
    assert not report["allowed"]
    assert report["issues"] == ["sp001_redundant_wooden_pickaxe_equip"]


def test_retained_sp001_pickup_failure_proves_delayed_recovery():
    root = Path(__file__).resolve().parents[1]
    session_path = (
        root
        / "workspace"
        / "evals"
        / "sp001_runs"
        / "sp001_episode_20260717_230318_23d8bdf3"
        / "session_404cf3b3-c52.jsonl"
    )
    events = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
    ]
    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert [entry["action"]["type"] for entry in actions] == [
        "equip",
        "dig",
        "dig",
        "dig",
        "dig",
    ]

    failed = actions[2]["result"]
    assert failed["success"] is False
    assert failed["block_removed"] is True
    assert failed["pickup_collection"]["entity_id"] == 322
    assert failed["pickup_collection"]["direct_navigation"]["pathfinder_resolved"] is True
    assert failed["pickup_collection"]["direct_navigation"]["completion_grounded"] is False
    assert failed["pickup_collection"]["fallback_candidate"] is None

    recovered = actions[4]["result"]
    assert recovered["pickup_collection"]["entity_id"] == 322
    assert recovered["pickup_collection"]["fallback_attempt_count"] == 1
    assert recovered["pickup_collection"]["completion_grounded_by"] == "inventory_delta"
    assert recovered["pickup_inventory_delta"] == {"cobblestone": 2}
    assert actions[4]["post_observation"]["inventory"]["cobblestone"] == 4


def test_retained_sp001_same_cell_fallback_alias_is_reproduced():
    root = Path(__file__).resolve().parents[1]
    session_path = (
        root
        / "workspace"
        / "evals"
        / "sp001_runs"
        / "sp001_episode_20260718_014459_7a1a9b49"
        / "session_cebd6eaa-904.jsonl"
    )
    events = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
    ]
    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert len(actions) == 8

    failed = actions[2]["result"]
    collection = failed["pickup_collection"]
    assert failed["success"] is False
    assert failed["block_removed"] is True
    assert collection["entity_id"] == 321
    assert collection["direct_navigation"]["pathfinder_resolved"] is True
    assert collection["direct_navigation"]["completion_grounded"] is False
    assert collection["fallback_candidate"]["position"] == {"x": 95, "y": 131, "z": -32}
    assert collection["fallback_candidate"]["expected_pickup_distance"] < 1.5
    assert collection["fallback_candidate"]["current_distance"] < 0.1
    assert collection["fallback_navigation"]["pathfinder_resolved"] is True
    assert collection["fallback_navigation"]["position"] == collection["direct_navigation"][
        "position"
    ]
    assert collection["fallback_navigation"]["final_distance"] > 1.5
    assert collection["fallback_navigation"]["completion_grounded"] is False

    next_failed = actions[3]["result"]
    assert next_failed["pickup_collection"]["entity_id"] == 321
    assert next_failed["pickup_collection"]["initial_distance"] > 1.5


def test_retained_sp001_transport_failure_is_fail_closed():
    root = Path(__file__).resolve().parents[1]
    run = (
        root
        / "workspace"
        / "evals"
        / "sp001_runs"
        / "sp001_episode_20260718_013304_7c162864"
    )
    episode = json.loads((run / "episode.json").read_text(encoding="utf-8"))
    audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))

    assert episode["goal_result"]["termination_reason"] == "empty_plan"
    assert episode["action_count"] == 0
    assert episode["transitions"] == []
    assert episode["initial_observation"]["inventory"] == episode["terminal_observation"][
        "inventory"
    ]
    assert episode["post_deadline_action_count"] == 0
    assert episode["world_mutating_non_target_actions"] == []
    assert episode["forbidden_interventions"] == []

    planner = audit["planner_decision"]["planner_evidence"]
    transport = planner["transport_evidence"]
    attempt = transport["attempts"][0]
    assert planner["real_llm_call"] is False
    assert planner["response_byte_count"] == 0
    assert transport["policy_id"] == "single-attempt"
    assert transport["attempt_count"] == 1
    assert transport["retry_count"] == 0
    assert attempt["success"] is False
    assert attempt["sdk_max_retries"] == 0
    assert attempt["error_chain"][-1] == "SSLEOFError"
    assert audit["task_graph_state"]["task_count"] == 0


def test_retained_sp001_failure_evidence_hashes_match_ledger():
    root = Path(__file__).resolve().parents[1]
    attributes = (root / ".gitattributes").read_text(encoding="utf-8")
    assert "workspace/evals/sp001_runs/** binary" in attributes
    ledger = json.loads(
        (root / "workspace" / "evals" / "stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failures = [
        item
        for item in ledger["failures"]
        if str(item.get("id") or "").startswith("sp001-")
    ]
    assert [item["id"] for item in failures] == [
        "sp001-001-redundant-equip",
        "sp001-002-pickup-candidate-margin",
        "sp001-003-planner-transport-tls-eof",
        "sp001-004-pickup-same-cell-goal-alias",
    ]
    for failure in failures:
        assert len(failure["evidence"]) == 10
        for record in failure["evidence"]:
            path = root / record["path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_eligible_sp001_success_evidence_hashes_match_ledger():
    root = Path(__file__).resolve().parents[1]
    ledger = json.loads(
        (root / "workspace" / "evals" / "stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    successes = ledger["eligible_successes"]
    assert [item["id"] for item in successes] == [
        "sp001-success-001",
        "sp001-success-002",
    ]
    assert len({item["episode_id"] for item in successes}) == len(successes)
    assert len({item["session_id"] for item in successes}) == len(successes)
    assert len({item["session_sha256"] for item in successes}) == len(successes)

    for success in successes:
        assert success["task_id"] == "SP-001"
        assert success["status"] == "eligible_live_success"
        assert success["machine_verification"]["passed"] is True
        assert success["machine_verification"]["evidence_eligible"] is True
        assert success["counts_toward_skill_gate"] is True
        assert success["counts_toward_capability"] is False
        assert success["counts_toward_m4"] is False
        assert len(success["evidence"]) == 10
        for record in success["evidence"]:
            path = root / record["path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

        verification_path = root / next(
            record["path"]
            for record in success["evidence"]
            if record["path"].endswith("/verification.json")
        )
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        assert verification["passed"] is True
        assert verification["evidence_eligible"] is True
        assert verification["counts_toward_skill_gate"] is True


def test_fixture_guard_blocks_target_result_mining_and_duplicate_pickaxe():
    observation = _raw_observation()
    stone = guard_runtime_action(
        "prepare_fixture",
        {"type": "dig", "parameters": {"block": "stone", "x": 1, "y": 64, "z": 0}},
        observation,
    )
    duplicate = guard_runtime_action(
        "prepare_fixture",
        {"type": "craft", "parameters": {"item": "wooden_pickaxe"}},
        observation,
    )
    assert not stone["allowed"]
    assert not duplicate["allowed"]
    assert guard_runtime_action(
        "prepare_fixture",
        {"type": "dig", "parameters": {"block": "oak_log", "x": 1, "y": 64, "z": 0}},
        observation,
    )["allowed"]


def test_fixture_guard_requires_observed_nearby_table_before_wooden_pickaxe_craft():
    action = {
        "type": "craft",
        "parameters": {"item": "wooden_pickaxe", "count": 1},
    }
    inventory_table_only = {
        "position": {"x": 0.0, "y": 64.0, "z": 0.0},
        "inventory": {
            "crafting_table": 1,
            "dark_oak_planks": 6,
            "stick": 4,
        },
        "nearby_blocks": [],
    }
    rejected = guard_runtime_action("prepare_fixture", action, inventory_table_only)
    assert not rejected["allowed"]
    assert rejected["issues"] == [
        "fixture_wooden_pickaxe_requires_observed_crafting_table"
    ]

    at_boundary = dict(inventory_table_only)
    at_boundary["nearby_blocks"] = [
        {
            "name": "crafting_table",
            "position": {"x": 4.5, "y": 64.0, "z": 0.0},
            "distance": 4.5,
        }
    ]
    assert guard_runtime_action("prepare_fixture", action, at_boundary)["allowed"]

    outside_boundary = dict(inventory_table_only)
    outside_boundary["nearby_blocks"] = [
        {
            "name": "crafting_table",
            "position": {"x": 4.501, "y": 64.0, "z": 0.0},
            "distance": 4.501,
        }
    ]
    report = guard_runtime_action("prepare_fixture", action, outside_boundary)
    assert not report["allowed"]
    assert "fixture_wooden_pickaxe_requires_observed_crafting_table" in report["issues"]


def test_runtime_config_keeps_skills_memory_and_external_control_off():
    config = build_runtime_config(
        api_key="test-key",
        log_dir="logs/test",
        host="127.0.0.1",
        port=25565,
        username="Singularity",
        bridge_host="127.0.0.1",
        bridge_port=30000,
    )
    assert config.planner_protocol == PROTOCOL["id"]
    assert config.require_llm_root_plan is True
    assert config.skill_execution_mode == "off"
    assert config.enable_memory_persistence is False
    assert config.enable_action_verification is True
    assert config.enforce_action_verification is True


def test_powershell_runtime_uses_legacy_compatible_relative_path_helper():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "stone-pickaxe-runtime.ps1"
    ).read_text(encoding="utf-8")
    assert "function Get-RepositoryRelativePath" in script
    assert "[System.IO.Path]::GetRelativePath" not in script
    assert script.count("Get-RepositoryRelativePath $snapshotRoot") == 2


def test_stone_protocol_controller_requires_pickup_and_tool_proof():
    calls = []

    class Bot:
        def dig(self, x, y, z, **kwargs):
            calls.append((x, y, z, kwargs))
            return {"success": True}

    controller = ActionController(
        Bot(),
        SimpleNamespace(planner_protocol="stone-pickaxe-skill-fixed-v1"),
    )
    assert controller._dig({"x": 1, "y": 64, "z": 0})["success"]
    assert calls[0][3] == {"timeout_ms": None, "require_pickup": True, "require_tool_equip": True}


def test_run_goal_enforces_one_absolute_deadline_and_total_action_budget():
    class Logger:
        def __init__(self):
            self.events = []
            self.session_id = "bounded-session"

        def log(self, event_type, data, level="INFO"):
            self.events.append({"type": event_type, "data": data, "level": level})

        def log_goal_start(self, goal):
            self.log("goal_start", {"goal": goal})

        def log_goal_end(self, goal, result):
            self.log("goal_end", {"goal": goal, "result": result})

        def log_observation(self, observation):
            self.log("observation", observation)

        def log_plan(self, plan):
            self.log("plan", plan)

        def log_error(self, error, context=None):
            self.log("error", {"error": error, "context": context or {}})

        def get_summary(self):
            return {"action_count": sum(event["type"] == "action" for event in self.events)}

    class Planner:
        def __init__(self):
            self.deadlines = []

        def start_episode(self, goal, session_id):
            pass

        def set_deadline(self, deadline, guard):
            self.deadlines.append((deadline, guard))

    class Controller:
        def __init__(self):
            self.calls = []
            self.deadlines = []
            self._episode_deadline_monotonic = None
            self._action_timeout_limit_s = None

        def set_episode_deadline(self, deadline, timeout):
            self._episode_deadline_monotonic = deadline
            self._action_timeout_limit_s = timeout
            self.deadlines.append((deadline, timeout))

        def execute(self, action, observation):
            self.calls.append(action)
            return {"success": True}

    class Tasks:
        def get_next_task(self, state):
            return None

    class Explorer:
        def record_position(self, position):
            pass

    class BoundedAgent(Agent):
        def __init__(self):
            self.config = SimpleNamespace(
                planner_protocol="",
                health_critical_threshold=4.0,
                enable_action_verification=False,
            )
            self.planner = Planner()
            self.action_controller = Controller()
            self.session_logger = Logger()
            self.task_system = Tasks()
            self.explorer = Explorer()
            self.current_goal = ""
            self.running = False
            self._episode_deadline_monotonic = None
            self._last_plan_cache_signature = ""
            self._skill_episode_start_index = 0
            self._active_skill_execution = {}
            self._skill_fallback_goals = set()
            self._m2_root_plan_valid = False
            self._m2_skill_contribution_complete = False

        def _think(self, observation, override_goal=None):
            return {
                "status": "in_progress",
                "reasoning": "bounded fixture",
                "actions": [
                    {"type": "wait", "parameters": {"ms": 1}},
                    {"type": "wait", "parameters": {"ms": 1}},
                    {"type": "wait", "parameters": {"ms": 1}},
                ],
            }

        def _observe(self):
            return {"position": {"x": 0, "y": 64, "z": 0}, "health": 20}

        def _goal_is_verified(self, goal, observation, context=None, recent_actions=None):
            return False, GoalVerification(goal=goal, achieved=False, status="failed")

        def _accept_planned_tasks(self):
            pass

        def _record_task_continuity(self, *args, **kwargs):
            pass

        def _state_with_causal_context(self, observation, goal):
            return observation

        def _handle_runtime_interrupt(self, observation, goal, context):
            return False, observation

        def _select_action_for_execution(self, action, observation, goal, context):
            return action, None

        def _verify_action_for_execution(self, action, observation, goal, context=None):
            return None, None

        def _record_action_value(self, *args, **kwargs):
            pass

        def _apply_action_feedback(self, action, result, observation, context):
            return observation

        def _log_action_event(self, action, result, **kwargs):
            self.session_logger.log("action", {"action": action, "result": result, **kwargs})

        def _record_skill_usage(self, *args, **kwargs):
            pass

        def _evaluate_episode_abort(self, *args, **kwargs):
            return False

        def _write_memory_episode(self, *args, **kwargs):
            pass

        def _write_memory_context(self, *args, **kwargs):
            pass

        def _finalize_skill_learning_episode(self, *args, **kwargs):
            pass

    agent = BoundedAgent()
    deadline = 10_000_000_000.0
    result = agent.run_goal(
        "bounded goal",
        max_cycles=5,
        max_duration_s=30,
        episode_deadline_monotonic=deadline,
        per_action_timeout_s=5,
        max_actions=2,
        deadline_policy_id="test-deadline-v1",
    )
    assert result["termination_reason"] == "max_actions"
    assert result["action_count"] == 2
    assert len(agent.action_controller.calls) == 2
    bound_deadline = result["episode_deadline_monotonic"]
    assert agent.planner.deadlines[0][0] == bound_deadline
    assert agent.action_controller.deadlines[0] == (bound_deadline, 5.0)
    assert agent.action_controller.deadlines[-1] == (None, None)


def test_synthetic_sp001_episode_passes_full_machine_verifier():
    events = _sp001_events()
    fixture = _fixture_manifest({"tree_sha256": "b" * 64, "file_count": 3, "total_bytes": 30})
    goal_result = {
        "completed": True,
        "termination_reason": "goal_verified",
        "episode_started_monotonic": 10.0,
        "episode_deadline_monotonic": 190.0,
        "episode_ended_monotonic": 14.0,
        "deadline_policy_id": PROTOCOL["deadline_policy"]["id"],
    }
    episode = build_sp001_episode(
        episode_id="sp001-test",
        session_id="session-test",
        session_sha256="a" * 64,
        events=events,
        initial_observation=_raw_observation(),
        terminal_observation=_raw_observation(3, ()),
        initial_monotonic=10.0,
        terminal_monotonic=14.0,
        goal_result=goal_result,
        fixture_manifest=fixture,
        hypothesis_path="workspace/evals/sp001_runs/sp001-test/hypothesis.json",
        level_name="sp001-test",
    )
    verification = verify_sp001_runtime_episode(episode)
    assert episode["planner_request_controls"]["passed"]
    assert verification["passed"]
    assert verification["metrics"]["source_removal_count"] == 3
    assert verification["metrics"]["inventory_delta"]["cobblestone"] == 3


def test_action_failure_prevents_sp001_evidence_eligibility():
    events = _sp001_events()
    events[1]["data"]["result"]["success"] = False
    events[1]["data"]["result"]["error"] = "pickup timeout"
    fixture = _fixture_manifest({"tree_sha256": "b" * 64, "file_count": 3, "total_bytes": 30})
    episode = build_sp001_episode(
        episode_id="sp001-failed",
        session_id="session-failed",
        session_sha256="c" * 64,
        events=events,
        initial_observation=_raw_observation(),
        terminal_observation=_raw_observation(3, ()),
        initial_monotonic=10.0,
        terminal_monotonic=14.0,
        goal_result={
            "episode_started_monotonic": 10.0,
            "episode_deadline_monotonic": 190.0,
            "deadline_policy_id": PROTOCOL["deadline_policy"]["id"],
        },
        fixture_manifest=fixture,
        hypothesis_path="workspace/evals/sp001_runs/sp001-failed/hypothesis.json",
        level_name="sp001-failed",
    )
    verification = verify_sp001_runtime_episode(episode)
    assert not verification["passed"]
    assert "zero_action_failures" in verification["criteria_issues"]


def test_planner_request_drift_prevents_sp001_evidence_eligibility():
    events = _sp001_events()
    events[0]["data"]["provider_metadata"]["extra_body"] = {}
    audit = planner_request_controls_audit(events)
    assert not audit["passed"]
    assert "offline-stone-call-1:extra_body" in audit["issues"]

    fixture = _fixture_manifest({"tree_sha256": "b" * 64, "file_count": 3, "total_bytes": 30})
    episode = build_sp001_episode(
        episode_id="sp001-planner-drift",
        session_id="session-planner-drift",
        session_sha256="f" * 64,
        events=events,
        initial_observation=_raw_observation(),
        terminal_observation=_raw_observation(3, ()),
        initial_monotonic=10.0,
        terminal_monotonic=14.0,
        goal_result={
            "episode_started_monotonic": 10.0,
            "episode_deadline_monotonic": 190.0,
            "deadline_policy_id": PROTOCOL["deadline_policy"]["id"],
        },
        fixture_manifest=fixture,
        hypothesis_path="workspace/evals/sp001_runs/sp001-planner-drift/hypothesis.json",
        level_name="sp001-planner-drift",
    )
    verification = verify_sp001_runtime_episode(episode)
    assert not verification["passed"]
    assert "eligibility:planner_request_controls" in verification["eligibility_issues"]


def test_stone_planner_propagates_fixed_request_controls():
    goal = "Prepare the fixed fixture"
    response = json.dumps(_stone_plan(goal))
    llm = _PlannerEvidenceLLM(response)
    planner = Planner(llm, TaskSystem(), protocol=PROTOCOL["id"])
    planner.start_episode(goal, "offline-stone-request")
    planner.set_deadline(time.monotonic() + 30.0, 0.0)

    plan = planner.plan_from_goal(
        goal,
        {"inventory": {}, "stone_pickaxe_runtime_mode": "prepare_fixture"},
        "",
    )

    assert plan["schema_validation"]["passed"]
    assert plan["plan_kind"] == "root"
    assert len(llm.calls) == 1
    assert llm.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert 0.0 < llm.calls[0]["timeout_s"] <= 30.0
    evidence = plan["planner_evidence"]
    assert evidence["deadline_policy"]["policy_id"] == PROTOCOL["deadline_policy"]["id"]
    assert evidence["deadline_policy"]["max_retries"] == 0
    assert evidence["transport_evidence"]["retry_count"] == 0
    assert evidence["provider_metadata"]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_stone_planner_rejects_empty_length_response_before_execution():
    llm = _PlannerEvidenceLLM("", finish_reason="length", reasoning_bytes=15685)
    planner = Planner(llm, TaskSystem(), protocol=PROTOCOL["id"])
    planner.start_episode("Prepare the fixed fixture", "offline-stone-empty")
    planner.set_deadline(time.monotonic() + 30.0, 0.0)

    plan = planner.plan_from_goal("Prepare the fixed fixture", {"inventory": {}}, "")

    assert len(llm.calls) == 1
    assert plan["status"] == "error"
    assert plan["actions"] == []
    assert not plan["schema_validation"]["passed"]
    assert "planner_response_empty" in plan["schema_validation"]["issues"]
    assert plan["planner_evidence"]["real_llm_call"] is False


def test_stone_planner_suppresses_post_deadline_call():
    response = json.dumps(_stone_plan("Prepare the fixed fixture"))
    llm = _PlannerEvidenceLLM(response)
    planner = Planner(llm, TaskSystem(), protocol=PROTOCOL["id"])
    planner.start_episode("Prepare the fixed fixture", "offline-stone-deadline")
    planner.set_deadline(time.monotonic() - 1.0, 0.0)

    plan = planner.plan_from_goal("Prepare the fixed fixture", {"inventory": {}}, "")

    assert llm.calls == []
    assert plan["status"] == "error"
    assert "stone_total_deadline_exhausted_before_planner_call" in plan["schema_validation"]["issues"]


def test_stone_planner_contract_rejects_unbounded_and_alias_actions():
    goal = "Prepare the fixed fixture"
    valid = _stone_plan(
        goal,
        action={
            "type": "dig",
            "parameters": {"block": "dark_oak_log", "x": 1, "y": 64, "z": 2},
        },
    )
    assert Planner._validate_stone_pickaxe_plan_envelope(valid, goal, "root")["passed"]

    missing_block = json.loads(json.dumps(valid))
    missing_block["actions"][0]["parameters"].pop("block")
    report = Planner._validate_stone_pickaxe_plan_envelope(missing_block, goal, "root")
    assert not report["passed"]
    assert "dig_block_missing" in report["issues"]

    recipe_alias = json.loads(json.dumps(valid))
    recipe_alias["actions"] = [{
        "type": "craft",
        "parameters": {"recipe": "dark_oak_planks", "count": 4},
    }]
    report = Planner._validate_stone_pickaxe_plan_envelope(recipe_alias, goal, "root")
    assert not report["passed"]
    assert "action_parameter_alias_forbidden:recipe" in report["issues"]
    assert "craft_item_missing" in report["issues"]

    multiple = json.loads(json.dumps(valid))
    multiple["actions"].append({"type": "wait", "parameters": {"ms": 500}})
    report = Planner._validate_stone_pickaxe_plan_envelope(multiple, goal, "root")
    assert not report["passed"]
    assert "planning_action_count_must_equal_one" in report["issues"]

    priority_zero = json.loads(json.dumps(valid))
    priority_zero["subtasks"][-1]["priority"] = 0
    report = Planner._validate_stone_pickaxe_plan_envelope(priority_zero, goal, "root")
    assert not report["passed"]
    assert "subtask[1]:priority_invalid" in report["issues"]

    priority_string = json.loads(json.dumps(valid))
    priority_string["subtasks"][-1]["priority"] = "1"
    report = Planner._validate_stone_pickaxe_plan_envelope(priority_string, goal, "root")
    assert not report["passed"]
    assert "subtask[1]:priority_invalid" in report["issues"]

    continuation = json.loads(json.dumps(valid))
    continuation["plan_kind"] = "continuation"
    report = Planner._validate_stone_pickaxe_plan_envelope(
        continuation,
        goal,
        "continuation",
    )
    assert not report["passed"]
    assert "non_root_subtasks_forbidden" in report["issues"]

    extra_field = json.loads(json.dumps(valid))
    extra_field["debug_trace"] = "unbounded planner detail"
    report = Planner._validate_stone_pickaxe_plan_envelope(extra_field, goal, "root")
    assert not report["passed"]
    assert "plan_field_unexpected:debug_trace" in report["issues"]

    unsupported_task_state = json.loads(json.dumps(valid))
    unsupported_task_state["subtasks"][1]["success_criteria"] = {"placed": True}
    report = Planner._validate_stone_pickaxe_plan_envelope(
        unsupported_task_state,
        goal,
        "root",
    )
    assert not report["passed"]
    assert "subtask[1]:success_criteria_key_forbidden:placed" in report["issues"]


def test_stone_planner_prompt_is_mode_bound_compact_and_canonical():
    goal = "Prepare the fixed fixture"
    llm = _PlannerEvidenceLLM(json.dumps(_stone_plan(goal)))
    planner = Planner(llm, TaskSystem(), protocol=PROTOCOL["id"])
    planner.start_episode(goal, "offline-stone-prompt")
    planner.set_deadline(time.monotonic() + 30.0, 0.0)
    world_state = {
        "stone_pickaxe_runtime_mode": "prepare_fixture",
        "position": {"x": 93.5, "y": 143, "z": -31.5},
        "inventory": {},
        "nearby_blocks": [
            {
                "name": "dark_oak_leaves",
                "position": {"x": index, "y": 142, "z": -32},
                "distance": float(index + 1),
            }
            for index in range(60)
        ] + [
            {
                "name": "dark_oak_log",
                "position": {"x": 93, "y": 142, "z": -31},
                "distance": 1.0,
            },
            {
                "name": "stone",
                "position": {"x": 124, "y": 139, "z": -37},
                "distance": 31.5,
            },
        ],
    }

    planner.plan_from_goal(goal, world_state, "")

    system_prompt = llm.calls[0]["messages"][0]["content"]
    user_prompt = llm.calls[0]["messages"][1]["content"]
    assert "exactly one immediate action" in system_prompt
    assert "Never use recipe" in system_prompt
    assert "priority must be a JSON integer from 1 through 5" in system_prompt
    assert 'success_criteria {"nearby_block_present":"crafting_table"}' in system_prompt
    assert "never use placed" in system_prompt
    assert (
        "A crafting_table item in inventory is not a nearby crafting table"
        in system_prompt
    )
    assert "Never retry wooden_pickaxe craft" in system_prompt
    assert '"subtasks":[{"id":"observe_state"' in system_prompt
    assert "Runtime mode: prepare_fixture" in user_prompt
    assert "dark_oak_log" in user_prompt
    assert "stone" in user_prompt
    assert len(user_prompt) < 5000


def test_stone_planner_replan_preserves_root_tasks_and_failure_reason():
    goal = "Prepare the fixed fixture"

    class SequenceLLM(_PlannerEvidenceLLM):
        def __init__(self, responses):
            super().__init__(responses[0])
            self.responses = list(responses)

        def chat(self, messages, **kwargs):
            self.response = self.responses[len(self.calls)]
            return super().chat(messages, **kwargs)

    llm = SequenceLLM([
        json.dumps(_stone_plan(goal)),
        json.dumps(_stone_plan(goal, plan_kind="replan")),
    ])
    tasks = TaskSystem()
    planner = Planner(llm, tasks, protocol=PROTOCOL["id"])
    planner.start_episode(goal, "offline-stone-replan")
    planner.set_deadline(time.monotonic() + 30.0, 0.0)

    root = planner.plan_from_goal(
        goal,
        {"inventory": {}, "stone_pickaxe_runtime_mode": "prepare_fixture"},
        "",
    )
    assert root["plan_kind"] == "root"
    assert len(tasks.tasks) == 2

    planner.request_replan("fixture_dig_block_forbidden:missing")
    replanned = planner.plan_from_goal(
        goal,
        {"inventory": {}, "stone_pickaxe_runtime_mode": "prepare_fixture"},
        "",
    )
    assert replanned["schema_validation"]["passed"]
    assert replanned["plan_kind"] == "replan"
    assert len(tasks.tasks) == 2
    assert '"subtasks":[]' in llm.calls[1]["messages"][0]["content"]
    assert "fixture_dig_block_forbidden:missing" in llm.calls[1]["messages"][1]["content"]


def test_agent_requests_stone_replan_after_action_failure():
    events = []

    class ReplanPlanner:
        def __init__(self):
            self.reason = ""

        def request_replan(self, reason):
            self.reason = reason

    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol=PROTOCOL["id"])
    agent.planner = ReplanPlanner()
    agent.current_goal = "Prepare the fixed fixture"
    agent.session_logger = SimpleNamespace(
        log=lambda event_type, payload: events.append((event_type, payload))
    )

    Agent._request_m2_replan(agent, "fixture_dig_block_forbidden:missing")

    assert agent.planner.reason == "fixture_dig_block_forbidden:missing"
    assert events[0][0] == "stone_pickaxe_replan_requested"


def test_stone_task_reconciliation_completes_ready_inventory_state_only():
    tasks = TaskSystem()
    planks = tasks.create_task(
        "Craft planks",
        status=TaskStatus.COMPLETED,
        success_criteria={"inventory": {"dark_oak_planks": 12}},
    )
    sticks = tasks.create_task(
        "Craft sticks",
        status=TaskStatus.ACCEPTED,
        success_criteria={"inventory": {"stick": 4}},
        depends_on=[planks.id],
    )
    table = tasks.create_task(
        "Craft table",
        status=TaskStatus.ACCEPTED,
        success_criteria={"inventory": {"crafting_table": 1}},
        depends_on=[planks.id],
    )
    events = []
    transitions = []
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol=PROTOCOL["id"])
    agent.task_system = tasks
    agent.session_logger = SimpleNamespace(
        log=lambda event_type, payload: events.append((event_type, payload))
    )
    agent._flush_task_state_transitions = lambda context: transitions.append(context)

    completed = Agent._reconcile_stone_pickaxe_satisfied_tasks(
        agent,
        {"inventory": {"crafting_table": 1}},
        "Prepare fixture",
        5,
        source="post_action_machine_observation",
    )

    assert completed == [table]
    assert table.status == TaskStatus.COMPLETED
    assert sticks.status == TaskStatus.ACCEPTED
    assert transitions[0]["source"] == "stone_pickaxe_task_state_reconciliation"
    assert events[0][0] == "stone_pickaxe_task_state_reconciliation"

    pickaxe = tasks.create_task(
        "Craft wooden pickaxe",
        status=TaskStatus.ACCEPTED,
        preconditions={
            "inventory": {"dark_oak_planks": 3, "stick": 2},
        },
        success_criteria={"inventory": {"wooden_pickaxe": 1}},
        depends_on=[table.id],
    )
    completed = Agent._reconcile_stone_pickaxe_satisfied_tasks(
        agent,
        {"inventory": {"wooden_pickaxe": 1}},
        "Prepare fixture",
        6,
        source="post_action_machine_observation",
    )
    assert completed == [pickaxe]
    assert pickaxe.status == TaskStatus.COMPLETED


def test_fixture_artifact_never_counts_as_skill_or_capability_evidence():
    preparation = {
        "protocol_sha256": PROTOCOL_SHA256,
        "game_mode": "survival",
        "external_step_script": False,
        "forbidden_interventions": [],
        "target_result_injection": False,
        "fixture_audit": {"passed": True},
        "planner_request_controls": {"passed": True},
    }
    tree = {"passed": True, "tree_sha256": "d" * 64, "file_count": 3, "total_bytes": 30, "components": []}
    artifact = build_fixture_artifact(preparation, tree, snapshot_path="logs/stone_pickaxe/fixture")
    assert artifact["snapshot_identity_verified"]
    assert artifact["counts_toward_skill_gate"] is False
    assert artifact["counts_toward_capability"] is False
    assert artifact["counts_toward_m4"] is False
    missing_planner_audit = dict(preparation)
    missing_planner_audit.pop("planner_request_controls")
    rejected = build_fixture_artifact(
        missing_planner_audit,
        tree,
        snapshot_path="logs/stone_pickaxe/fixture",
    )
    assert not rejected["snapshot_identity_verified"]
    assert "preparation_planner_request_controls" in rejected["issues"]


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
    print(f"PASS: {len(tests)} stone-pickaxe runtime cases")
