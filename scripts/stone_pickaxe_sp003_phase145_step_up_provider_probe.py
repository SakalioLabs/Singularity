"""Run one bounded SP-003 step-up Planner probe without Minecraft."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from singularity.core.config import LLMConfig
from singularity.core.planner import Planner
from singularity.core.task_system import TaskSystem
from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL
from singularity.evaluation.stone_pickaxe_sp003_phase122_runtime import (
    StonePickaxeSP003Phase122RuntimeAgent,
)
from singularity.evaluation.stone_pickaxe_sp003_runtime import SP003_GOAL
from singularity.llm.provider import LLMProvider
from stone_pickaxe_sp003_provider_throughput_probe import (
    canonical_sha256,
    configured_api_key,
    current_head,
    file_sha256,
    repo_path,
    repo_relative,
    request_payload_metadata,
    utc_now,
    write_evidence,
)


PHASE = 145
POLICY_ID = "sp003-step-up-provider-probe-v1"
PROBE_EPISODE_ID = "sp003-step-up-provider-probe-phase145"
PURPOSE = "verify_phase_144_step_up_planner_contract_before_live_authorization"
SOURCE_EPISODE_ID = "sp003_baseline_20260720_173513_afba21cd"
SOURCE_CALL_ID = "llm-47b868e32e5d4372"
SOURCE_CALL_INDEX = 13
SOURCE_ROOT_PLAN_ID = "root-962181a6dc644323"
SOURCE_PARENT_CALL_ID = "llm-5748d8f926c14955"
STEP_UP_SOURCE_ID = "sp003_clearance_shaft_step_up_egress:120:141:-37"
EXPECTED_SOURCE_SHA256 = (
    "3ee5f34cc307bedca43f49ed13dda004145ca893882d5a7e4f0fa568edb7fcde"
)
EXPECTED_OBSERVATION_LINE_NUMBER = 270
EXPECTED_OBSERVATION_CANONICAL_SHA256 = (
    "ebedf2b2fa0ffbb14021349a681e60aecab1f412f026a6fe1cc41babc7cfe7de"
)
EXPECTED_SOURCE_CALL_LINE_NUMBER = 273
EXPECTED_SOURCE_CALL_CANONICAL_SHA256 = (
    "20745da7cd00f09ee13605167e17cc17e5e478d784c38291c1304aef35636947"
)
EXPECTED_SOURCE_PLAN_LINE_NUMBER = 274
EXPECTED_SOURCE_PLAN_CANONICAL_SHA256 = (
    "5ed7a486c3b1d80bcf7605e7a4c035cd983f89ef4911498c9b79e1bd8ca5528d"
)
EXPECTED_SOURCE_REQUEST_SHA256 = (
    "d6ef16b6b02aa0fd6a044d90449acd62b85de0cc36c63cba19126c35bdd82495"
)
EXPECTED_SOURCE_RESPONSE_SHA256 = (
    "2de820729335b6824dbe5fa2f26873f6eaba61199350fdb17e422c44310f4e96"
)
DEFAULT_SOURCE = Path(
    "workspace/evals/sp003_runs/"
    f"{SOURCE_EPISODE_ID}/session_dc3e3ade-e4f.jsonl"
)
DEFAULT_OUTPUT = Path(
    "workspace/evals/stone_pickaxe_sp003_phase145_step_up_provider_probe.json"
)
REQUEST_TIMEOUT_S = 12.0
MAX_ACCEPTABLE_DURATION_MS = 7_500
MIN_REPRESENTATIVE_PROMPT_TOKENS = 2_500
MIN_REPRESENTATIVE_REQUEST_BYTES = 10_000
EXPECTED_REQUEST_SHA256 = (
    "8b66dcafe3eb4b5b89f88998b3b7949ebec1cf5758169c24fc03edb4b18c0d1f"
)
EXPECTED_REQUEST_PAYLOAD_BYTE_COUNT = 12_924
EXPECTED_SYSTEM_MESSAGE_BYTE_COUNT = 9_099
EXPECTED_USER_MESSAGE_BYTE_COUNT = 3_380
EXPECTED_SOURCE_ACTION = {
    "type": "place",
    "parameters": {
        "item": "crafting_table",
        "x": 120.5,
        "y": 141,
        "z": -36.5,
    },
}
EXPECTED_RAW_ACTION = {
    "type": "move_to",
    "parameters": {"x": 120.5, "y": 141, "z": -36.5},
}
EXPECTED_NORMALIZED_ACTION = {
    "type": "move_to",
    "parameters": {
        "x": 120.5,
        "y": 141,
        "z": -36.5,
        "tolerance": 1.0,
        "preserve_inventory": True,
    },
}
EXPECTED_SOURCE_STATE = {
    "runtime_mode": "sp003",
    "arm": "baseline",
    "stage": "place_crafting_table",
    "inventory": {
        "crafting_table": 1,
        "dark_oak_planks": 6,
        "dirt": 2,
        "stick": 4,
    },
    "progress": {
        "crafting_table_craft_count": 1,
        "crafting_table_place_count": 0,
        "crafting_table_position": {},
        "delayed_log_pickup_reconciliation_count": 1,
        "iron_mining_action_count": 0,
        "log_item": "dark_oak_log",
        "log_source_removal_count": 3,
        "pending_log_pickup_count": 0,
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "stone_pickaxe_craft_count": 0,
        "stone_source_removal_count": 0,
        "successful_mutation_count": 7,
        "surface_clearance_removal_count": 2,
        "wooden_pickaxe_craft_count": 0,
        "wooden_pickaxe_equip_count": 0,
    },
    "target_count": 1,
    "target": {
        "source_id": STEP_UP_SOURCE_ID,
        "name": "sp003_clearance_shaft_step_up_egress",
        "position": {"x": 120.5, "y": 141, "z": -36.5},
        "stand_position": {"x": 120.5, "y": 141, "z": -36.5},
        "navigation_only": True,
        "stone_clearance_shaft_step_up_egress": True,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one no-Minecraft SP-003 step-up Planner probe"
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE.as_posix())
    parser.add_argument("--output", default=DEFAULT_OUTPUT.as_posix())
    return parser.parse_args()


def retained_step_up_source(source: Path) -> tuple[dict, dict, dict]:
    if file_sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Phase 143 JSONL identity mismatch")

    latest_observation: dict = {}
    observation_record: dict = {}
    call_record: dict = {}
    plan_record: dict = {}
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        event = json.loads(line)
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "observation":
            latest_observation = {"line_number": line_number, "event": event}
        if event.get("type") == "llm_planner_call" and data.get(
            "call_id"
        ) == SOURCE_CALL_ID:
            observation_record = latest_observation
            call_record = {"line_number": line_number, "event": event}
        if event.get("type") == "plan" and data.get(
            "planner_call_id"
        ) == SOURCE_CALL_ID:
            plan_record = {"line_number": line_number, "event": event}
            break

    if not observation_record or not call_record or not plan_record:
        raise RuntimeError("exact Phase 143 step-up source chain not found")
    checks = source_identity_checks(observation_record, call_record, plan_record)
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError("Phase 143 source chain mismatch: " + ",".join(failed))
    return observation_record, call_record, plan_record


def source_identity_checks(
    observation_record: dict,
    call_record: dict,
    plan_record: dict,
) -> dict:
    observation = observation_record.get("event", {})
    world_state = observation.get("data", {})
    targets = world_state.get("sp003_targets")
    target = targets[0] if isinstance(targets, list) and targets else {}
    call_event = call_record.get("event", {})
    call = call_event.get("data", {})
    plan_event = plan_record.get("event", {})
    plan = plan_event.get("data", {})
    transport = call.get("transport_evidence", {})
    return {
        "observation_line": observation_record.get("line_number")
        == EXPECTED_OBSERVATION_LINE_NUMBER,
        "observation_hash": canonical_sha256(observation)
        == EXPECTED_OBSERVATION_CANONICAL_SHA256,
        "step_up_target": (
            target.get("source_id") == STEP_UP_SOURCE_ID
            and target.get("navigation_only") is True
            and target.get("stone_clearance_shaft_step_up_egress") is True
            and target.get("stand_position")
            == {"x": 120.5, "y": 141, "z": -36.5}
        ),
        "call_line": call_record.get("line_number")
        == EXPECTED_SOURCE_CALL_LINE_NUMBER,
        "call_hash": canonical_sha256(call_event)
        == EXPECTED_SOURCE_CALL_CANONICAL_SHA256,
        "call_chain": (
            call.get("call_id") == SOURCE_CALL_ID
            and call.get("call_index") == SOURCE_CALL_INDEX
            and call.get("plan_kind") == "continuation"
            and call.get("root_plan_id") == SOURCE_ROOT_PLAN_ID
            and call.get("parent_call_id") == SOURCE_PARENT_CALL_ID
        ),
        "source_provider_result": (
            call.get("real_llm_call") is True
            and call.get("schema_valid") is True
            and call.get("provider_metadata", {}).get("request_sha256")
            == EXPECTED_SOURCE_REQUEST_SHA256
            and call.get("response_sha256") == EXPECTED_SOURCE_RESPONSE_SHA256
            and transport.get("attempt_count") == 1
            and transport.get("retry_count") == 0
        ),
        "plan_line": plan_record.get("line_number")
        == EXPECTED_SOURCE_PLAN_LINE_NUMBER,
        "plan_hash": canonical_sha256(plan_event)
        == EXPECTED_SOURCE_PLAN_CANONICAL_SHA256,
        "wrong_source_action": (
            plan.get("plan_kind") == "continuation"
            and plan.get("status") == "planning"
            and plan.get("planner_call_id") == SOURCE_CALL_ID
            and plan.get("actions") == [EXPECTED_SOURCE_ACTION]
        ),
    }


def compact_source_state(planner: Planner, world_state: dict) -> dict:
    compact = planner._compact_stone_pickaxe_state(world_state)
    targets = compact.get("sp003_targets")
    target = targets[0] if isinstance(targets, list) and targets else {}
    return {
        "runtime_mode": compact.get("runtime_mode"),
        "arm": compact.get("sp003_arm"),
        "stage": compact.get("sp003_stage"),
        "inventory": compact.get("inventory"),
        "progress": compact.get("sp003_progress"),
        "target_count": len(targets) if isinstance(targets, list) else 0,
        "target": {
            "source_id": target.get("source_id"),
            "name": target.get("name"),
            "position": target.get("position"),
            "stand_position": target.get("stand_position"),
            "navigation_only": target.get("navigation_only"),
            "stone_clearance_shaft_step_up_egress": target.get(
                "stone_clearance_shaft_step_up_egress"
            ),
        },
    }


def exact_probe_messages(planner: Planner, world_state: dict) -> list[dict]:
    planner._expected_plan_kind = "continuation"
    return [
        {"role": "system", "content": planner._planner_system_prompt()},
        {
            "role": "user",
            "content": planner._build_planning_prompt(
                SP003_GOAL, world_state, memory_context=""
            ),
        },
    ]


def retained_transport_evidence(transport: dict) -> dict:
    attempts = transport.get("attempts")
    safe_attempts = []
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            safe_attempts.append(
                {
                    "attempt_index": attempt.get("attempt_index"),
                    "success": attempt.get("success"),
                    "timeout_s": attempt.get("timeout_s"),
                    "sdk_max_retries": attempt.get("sdk_max_retries"),
                    "error_type": attempt.get("error_type", ""),
                    "error_chain": attempt.get("error_chain", []),
                }
            )
    return {
        "policy_id": transport.get("policy_id", ""),
        "attempt_count": int(transport.get("attempt_count") or 0),
        "retry_count": int(transport.get("retry_count") or 0),
        "attempts": safe_attempts,
    }


def effective_guard_action_evidence(action: dict, world_state: dict) -> dict:
    progress = world_state.get("sp003_progress")
    if not isinstance(progress, dict):
        return {
            "allowed": False,
            "issues": ["sp003_progress_missing"],
            "policy_id": "",
            "raw_action": action,
            "normalized_action": {},
            "selected_source": {},
            "raw_action_exact_expected": False,
            "normalized_action_exact_expected": False,
        }
    agent = StonePickaxeSP003Phase122RuntimeAgent.__new__(
        StonePickaxeSP003Phase122RuntimeAgent
    )
    agent.sp003_arm = "baseline"
    agent.sp003_progress = copy.deepcopy(progress)
    agent._sp003_phase120_egress_attempted_fingerprints = set()
    guarded = agent._effective_sp003_action_guard(action, world_state)
    normalized = guarded.get("action")
    normalized = normalized if isinstance(normalized, dict) else {}
    selected_source = guarded.get("selected_source")
    selected_source = selected_source if isinstance(selected_source, dict) else {}
    issues = guarded.get("issues")
    issues = issues if isinstance(issues, list) else ["invalid_guard_issues"]
    return {
        "allowed": guarded.get("allowed") is True,
        "issues": issues,
        "policy_id": guarded.get("policy_id", ""),
        "raw_action": action,
        "normalized_action": normalized,
        "selected_source": selected_source,
        "raw_action_exact_expected": action == EXPECTED_RAW_ACTION,
        "normalized_action_exact_expected": normalized
        == EXPECTED_NORMALIZED_ACTION,
    }


def run_probe(source: Path) -> dict:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError(
            "probe requires SINGULARITY_LLM_API_KEY or OPENAI_API_KEY"
        )

    observation_record, call_record, plan_record = retained_step_up_source(source)
    observation_event = observation_record["event"]
    world_state = observation_event["data"]
    source_call = call_record["event"]["data"]
    source_plan = plan_record["event"]["data"]
    source_checks = source_identity_checks(
        observation_record, call_record, plan_record
    )
    planner_config = PROTOCOL["planner"]
    provider = LLMProvider(
        LLMConfig(
            provider=planner_config["provider"],
            model=planner_config["model"],
            api_key=api_key,
            base_url=planner_config["base_url"],
            max_tokens=int(planner_config["max_tokens"]),
            temperature=float(planner_config["temperature"]),
        )
    )
    planner = Planner(provider, TaskSystem(), protocol=PROTOCOL["id"])
    planner.start_episode(SP003_GOAL, PROBE_EPISODE_ID)
    planner._call_index = SOURCE_CALL_INDEX
    planner._active_root_plan_id = SOURCE_ROOT_PLAN_ID
    planner._last_call_id = SOURCE_CALL_ID

    request_shape = request_payload_metadata(exact_probe_messages(planner, world_state))
    captured_request: dict = {}
    provider_chat_call_count = 0
    original_chat = provider.chat

    def capture_chat(
        messages: list[dict],
        response_format: dict | None = None,
        timeout_s: float | None = None,
        extra_body: dict | None = None,
    ) -> str:
        nonlocal provider_chat_call_count
        provider_chat_call_count += 1
        if provider_chat_call_count > 1:
            raise RuntimeError("Phase 145 provider call limit exhausted")
        captured_request.update(request_payload_metadata(messages))
        captured_request["request_message_count"] = len(messages)
        return original_chat(
            messages,
            response_format=response_format,
            timeout_s=timeout_s,
            extra_body=extra_body,
        )

    provider.chat = capture_chat
    actual_source_state = compact_source_state(planner, world_state)

    started_at_utc = utc_now()
    started = time.monotonic()
    planner.set_deadline(started + REQUEST_TIMEOUT_S, action_guard_s=0.0)
    probe_exception = ""
    try:
        plan = planner.plan_from_goal(SP003_GOAL, world_state, memory_context="")
    except Exception as exc:
        probe_exception = type(exc).__name__
        plan = {
            "plan_kind": "continuation",
            "status": "error",
            "actions": [],
            "subtasks": [],
            "schema_validation": {
                "type": "planner_schema_validation",
                "passed": False,
                "issues": [f"probe_exception:{type(exc).__name__}"],
            },
        }
    wall_duration_ms = int((time.monotonic() - started) * 1000)
    ended_at_utc = utc_now()

    planner_evidence = dict(planner.last_call_evidence or {})
    provider_metadata = dict(
        planner_evidence.get("provider_metadata")
        or getattr(provider, "last_call_metadata", {})
        or {}
    )
    transport = dict(planner_evidence.get("transport_evidence") or {})
    actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
    subtasks = (
        plan.get("subtasks") if isinstance(plan.get("subtasks"), list) else []
    )
    duration_ms = provider_metadata.get("duration_ms")
    request_count = int(transport.get("attempt_count") or 0)
    retry_count = int(transport.get("retry_count") or 0)
    fixed_controls_match = all(
        (
            provider_metadata.get("provider") == planner_config["provider"],
            provider_metadata.get("base_url") == planner_config["base_url"],
            provider_metadata.get("model") == planner_config["model"],
            provider_metadata.get("temperature") == planner_config["temperature"],
            provider_metadata.get("max_tokens") == planner_config["max_tokens"],
            provider_metadata.get("response_format") == {"type": "json_object"},
            provider_metadata.get("extra_body")
            == {"thinking": {"type": planner_config["thinking"]}},
            provider_metadata.get("max_retries") == 0,
        )
    )
    guarded_action = effective_guard_action_evidence(
        actions[0] if len(actions) == 1 else {}, world_state
    )
    criteria = {
        "source_artifact_is_exact": file_sha256(source)
        == EXPECTED_SOURCE_SHA256,
        "source_chain_is_exact": all(source_checks.values()),
        "source_state_matches": actual_source_state == EXPECTED_SOURCE_STATE,
        "source_wrong_action_is_exact": source_plan.get("actions")
        == [EXPECTED_SOURCE_ACTION],
        "precomputed_request_shape_matches": (
            request_shape.get("request_sha256") == EXPECTED_REQUEST_SHA256
            and request_shape.get("request_payload_byte_count")
            == EXPECTED_REQUEST_PAYLOAD_BYTE_COUNT
            and request_shape.get("system_message_byte_count")
            == EXPECTED_SYSTEM_MESSAGE_BYTE_COUNT
            and request_shape.get("user_message_byte_count")
            == EXPECTED_USER_MESSAGE_BYTE_COUNT
            and captured_request == {**request_shape, "request_message_count": 2}
        ),
        "request_payload_matches_provider_sha256": (
            bool(captured_request.get("request_sha256"))
            and provider_metadata.get("request_sha256")
            == captured_request.get("request_sha256")
        ),
        "representative_request_size": int(
            captured_request.get("request_payload_byte_count") or 0
        )
        >= MIN_REPRESENTATIVE_REQUEST_BYTES,
        "representative_prompt_tokens": (
            isinstance(provider_metadata.get("prompt_tokens"), int)
            and provider_metadata["prompt_tokens"]
            >= MIN_REPRESENTATIVE_PROMPT_TOKENS
        ),
        "fixed_provider_controls": fixed_controls_match,
        "single_provider_chat_call": provider_chat_call_count == 1,
        "single_transport_request": request_count == 1,
        "zero_retries": retry_count == 0,
        "within_latency_gate": (
            isinstance(duration_ms, int)
            and duration_ms <= MAX_ACCEPTABLE_DURATION_MS
        ),
        "real_llm_call": planner_evidence.get("real_llm_call") is True,
        "schema_valid": planner_evidence.get("schema_valid") is True,
        "continuation_plan": (
            plan.get("plan_kind") == "continuation"
            and plan.get("status") == "planning"
        ),
        "single_provider_action": len(actions) == 1,
        "raw_action_exact_expected": guarded_action[
            "raw_action_exact_expected"
        ],
        "effective_guard_normalized_expected_action": (
            guarded_action["allowed"]
            and not guarded_action["issues"]
            and guarded_action["normalized_action_exact_expected"]
        ),
        "no_probe_exception": not probe_exception,
    }
    passed = all(criteria.values())

    return {
        "type": "stone_pickaxe_sp003_step_up_provider_probe",
        "schema_version": 1,
        "phase": PHASE,
        "policy_id": POLICY_ID,
        "task_id": "SP-003",
        "purpose": PURPOSE,
        "predecessor_commit": current_head(),
        "started_at_utc": started_at_utc,
        "ended_at_utc": ended_at_utc,
        "passed": passed,
        "decision": (
            "permit_one_parent_bound_baseline_authorization"
            if passed
            else "hold_live_authorization_step_up_provider_probe_failed"
        ),
        "thresholds": {
            "request_timeout_s": REQUEST_TIMEOUT_S,
            "max_acceptable_duration_ms": MAX_ACCEPTABLE_DURATION_MS,
            "min_representative_prompt_tokens": MIN_REPRESENTATIVE_PROMPT_TOKENS,
            "min_representative_request_bytes": MIN_REPRESENTATIVE_REQUEST_BYTES,
            "max_provider_chat_call_count": 1,
            "max_transport_request_count": 1,
            "max_retry_count": 0,
        },
        "criteria": criteria,
        "source": {
            "episode_id": SOURCE_EPISODE_ID,
            "path": repo_relative(source),
            "sha256": file_sha256(source),
            "immutable": True,
            "rewritten": False,
            "observation_line_number": observation_record["line_number"],
            "observation_canonical_sha256": canonical_sha256(observation_event),
            "call_line_number": call_record["line_number"],
            "call_canonical_sha256": canonical_sha256(call_record["event"]),
            "call_id": source_call.get("call_id"),
            "call_index": source_call.get("call_index"),
            "plan_kind": source_call.get("plan_kind"),
            "parent_call_id": source_call.get("parent_call_id"),
            "root_plan_id": source_call.get("root_plan_id"),
            "request_sha256": source_call.get("provider_metadata", {}).get(
                "request_sha256", ""
            ),
            "response_sha256": source_call.get("response_sha256", ""),
            "plan_line_number": plan_record["line_number"],
            "plan_canonical_sha256": canonical_sha256(plan_record["event"]),
            "wrong_action": copy.deepcopy(source_plan["actions"][0]),
            "state": actual_source_state,
            "checks": source_checks,
        },
        "expected_plan_kind": "continuation",
        "expected_raw_action": EXPECTED_RAW_ACTION,
        "expected_normalized_action": EXPECTED_NORMALIZED_ACTION,
        "request": {
            **captured_request,
            "precomputed_request_sha256": request_shape.get("request_sha256", ""),
            "provider_request_sha256": provider_metadata.get(
                "request_sha256", ""
            ),
        },
        "provider_chat_call_count": provider_chat_call_count,
        "request_count": request_count,
        "retry_count": retry_count,
        "transport_evidence": retained_transport_evidence(transport),
        "provider": provider_metadata.get("provider", planner_config["provider"]),
        "base_url": provider_metadata.get("base_url", planner_config["base_url"]),
        "model": provider_metadata.get("model", planner_config["model"]),
        "temperature": provider_metadata.get(
            "temperature", planner_config["temperature"]
        ),
        "max_tokens": provider_metadata.get(
            "max_tokens", planner_config["max_tokens"]
        ),
        "response_format": provider_metadata.get("response_format", {}),
        "extra_body": provider_metadata.get("extra_body", {}),
        "timeout_s": provider_metadata.get("timeout_s"),
        "sdk_max_retries": provider_metadata.get("max_retries"),
        "response_sha256": provider_metadata.get("response_sha256", ""),
        "response_byte_count": planner_evidence.get("response_byte_count", 0),
        "response_id": provider_metadata.get("response_id", ""),
        "finish_reason": provider_metadata.get("finish_reason", ""),
        "reasoning_content_byte_count": provider_metadata.get(
            "reasoning_content_byte_count", 0
        ),
        "duration_ms": duration_ms,
        "wall_duration_ms": wall_duration_ms,
        "prompt_tokens": provider_metadata.get("prompt_tokens"),
        "completion_tokens": provider_metadata.get("completion_tokens"),
        "total_tokens": provider_metadata.get("total_tokens"),
        "real_llm_call": planner_evidence.get("real_llm_call") is True,
        "schema_valid": planner_evidence.get("schema_valid") is True,
        "schema_validation": planner_evidence.get(
            "schema_validation", plan.get("schema_validation", {})
        ),
        "returned_plan": {
            "plan_kind": plan.get("plan_kind", ""),
            "status": plan.get("status", ""),
            "subtask_count": len(subtasks),
            "actions": actions,
        },
        "effective_guard_action_evidence": guarded_action,
        "probe_exception_type": probe_exception,
        "credential_value_retained": False,
        "minecraft_process_started": False,
        "authorization_created": False,
        "automatic_retry_attempted": False,
        "live_authorization": False,
        "counts_toward_baseline_success": False,
        "counts_toward_skill_gate": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def main() -> int:
    args = parse_args()
    source = repo_path(args.source)
    output = repo_path(args.output)
    if not source.is_file():
        raise RuntimeError(f"source evidence not found: {source}")
    evidence = run_probe(source)
    write_evidence(output, evidence)
    print(
        json.dumps(
            {
                "output": repo_relative(output),
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
