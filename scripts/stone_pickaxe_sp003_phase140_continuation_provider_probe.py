"""Run one bounded SP-003 continuation-provider probe without Minecraft."""

from __future__ import annotations

import argparse
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
    retained_observation_before_call,
    utc_now,
    write_evidence,
)


PHASE = 140
POLICY_ID = "sp003-continuation-provider-recovery-gate-v1"
PROBE_EPISODE_ID = "sp003-provider-continuation-probe-phase140"
PURPOSE = "recover_from_phase_139_continuation_provider_tls_eof"
SOURCE_CALL_ID = "llm-124e7e9947b04a13"
SOURCE_ROOT_PLAN_ID = "root-a9494909f5f74130"
SOURCE_PARENT_CALL_ID = "llm-34675e6feebf47e7"
EXPECTED_SOURCE_SHA256 = (
    "caeea8567f124b8fae638037059b049edf5a8ad115fde50ebd97f7c1eba230bf"
)
EXPECTED_OBSERVATION_LINE_NUMBER = 77
EXPECTED_OBSERVATION_CANONICAL_SHA256 = (
    "9d6f6bff05e668586f41f6d10a84d64dc3f087b8a9cd31a45a88b2d48b060caa"
)
EXPECTED_PREDECESSOR_REQUEST_SHA256 = (
    "375766bb9f4aac6e0608bf4430daf6faf943b2987924f5c6bcec682000a570d2"
)
DEFAULT_SOURCE = Path(
    "workspace/evals/sp003_runs/"
    "sp003_baseline_20260720_150508_7a645e08/"
    "session_0420e30c-1b8.jsonl"
)
DEFAULT_OUTPUT = Path(
    "workspace/evals/stone_pickaxe_sp003_phase140_continuation_provider_probe.json"
)
REQUEST_TIMEOUT_S = 12.0
MAX_ACCEPTABLE_DURATION_MS = 7500
MIN_REPRESENTATIVE_PROMPT_TOKENS = 2500
MIN_REPRESENTATIVE_REQUEST_BYTES = 10_000
EXPECTED_REQUEST_SHA256 = (
    "a93b634c940d0ffdacbdb260b7409220250634439379ca79a6b71cf81e98532c"
)
EXPECTED_REQUEST_PAYLOAD_BYTE_COUNT = 11_686
EXPECTED_SYSTEM_MESSAGE_BYTE_COUNT = 8_482
EXPECTED_USER_MESSAGE_BYTE_COUNT = 2_779
EXPECTED_ACTION = {
    "type": "dig",
    "parameters": {
        "block": "dark_oak_log",
        "x": 118,
        "y": 141,
        "z": -38,
        "source_id": "dark_oak_log:118:141:-38",
    },
}
EXPECTED_SOURCE_STATE = {
    "runtime_mode": "sp003",
    "arm": "baseline",
    "stage": "acquire_wood",
    "inventory": {"dark_oak_log": 2},
    "log_source_removal_count": 2,
    "pending_log_pickup_count": 0,
    "delayed_log_pickup_reconciliation_count": 1,
    "target_count": 1,
    "target_source_id": "dark_oak_log:118:141:-38",
    "target_name": "dark_oak_log",
    "target_position": {"x": 118.0, "y": 141.0, "z": -38.0},
    "target_navigation_only": False,
    "target_canopy_egress": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one no-Minecraft SP-003 continuation-provider probe"
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE.as_posix())
    parser.add_argument("--output", default=DEFAULT_OUTPUT.as_posix())
    return parser.parse_args()


def compact_source_state(planner: Planner, world_state: dict) -> dict:
    compact = planner._compact_stone_pickaxe_state(world_state)
    targets = compact.get("sp003_targets")
    target = targets[0] if isinstance(targets, list) and targets else {}
    progress = compact.get("sp003_progress")
    progress = progress if isinstance(progress, dict) else {}
    return {
        "runtime_mode": compact.get("runtime_mode"),
        "arm": compact.get("sp003_arm"),
        "stage": compact.get("sp003_stage"),
        "inventory": compact.get("inventory"),
        "log_source_removal_count": progress.get("log_source_removal_count"),
        "pending_log_pickup_count": progress.get("pending_log_pickup_count"),
        "delayed_log_pickup_reconciliation_count": progress.get(
            "delayed_log_pickup_reconciliation_count"
        ),
        "target_count": len(targets) if isinstance(targets, list) else 0,
        "target_source_id": target.get("source_id"),
        "target_name": target.get("name"),
        "target_position": target.get("position"),
        "target_navigation_only": target.get("navigation_only"),
        "target_canopy_egress": target.get("canopy_egress"),
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


def run_probe(source: Path) -> dict:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError(
            "probe requires SINGULARITY_LLM_API_KEY or OPENAI_API_KEY"
        )

    observation_record, predecessor_call = retained_observation_before_call(
        source, SOURCE_CALL_ID
    )
    observation_event = observation_record["event"]
    world_state = observation_event["data"]
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
    planner._call_index = int(predecessor_call["data"]["call_index"])
    planner._active_root_plan_id = SOURCE_ROOT_PLAN_ID
    planner._last_call_id = SOURCE_PARENT_CALL_ID

    request_shape = request_payload_metadata(exact_probe_messages(planner, world_state))
    captured_request: dict = {}
    original_chat = provider.chat

    def capture_chat(
        messages: list[dict],
        response_format: dict | None = None,
        timeout_s: float | None = None,
        extra_body: dict | None = None,
    ) -> str:
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
    predecessor_transport = dict(
        predecessor_call["data"].get("transport_evidence") or {}
    )
    predecessor_attempts = predecessor_transport.get("attempts")
    predecessor_attempt = (
        predecessor_attempts[0]
        if isinstance(predecessor_attempts, list) and predecessor_attempts
        else {}
    )
    source_sha256 = file_sha256(source)
    observation_canonical_sha256 = canonical_sha256(observation_event)
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
    criteria = {
        "source_artifact_is_exact": (
            source_sha256 == EXPECTED_SOURCE_SHA256
            and observation_record["line_number"]
            == EXPECTED_OBSERVATION_LINE_NUMBER
            and observation_canonical_sha256
            == EXPECTED_OBSERVATION_CANONICAL_SHA256
        ),
        "source_state_matches": actual_source_state == EXPECTED_SOURCE_STATE,
        "source_predecessor_is_exact_tls_eof": (
            predecessor_call["data"].get("call_index") == 3
            and predecessor_call["data"].get("plan_kind") == "continuation"
            and predecessor_call["data"].get("parent_call_id")
            == SOURCE_PARENT_CALL_ID
            and predecessor_call["data"].get("root_plan_id")
            == SOURCE_ROOT_PLAN_ID
            and predecessor_call["data"]
            .get("provider_metadata", {})
            .get("request_sha256")
            == EXPECTED_PREDECESSOR_REQUEST_SHA256
            and predecessor_transport.get("attempt_count") == 1
            and predecessor_transport.get("retry_count") == 0
            and predecessor_attempt.get("error_chain")
            == ["APIConnectionError", "ConnectError", "ConnectError", "SSLEOFError"]
        ),
        "precomputed_request_shape_matches": (
            request_shape.get("request_sha256") == EXPECTED_REQUEST_SHA256
            and request_shape.get("request_payload_byte_count")
            == EXPECTED_REQUEST_PAYLOAD_BYTE_COUNT
            and request_shape.get("system_message_byte_count")
            == EXPECTED_SYSTEM_MESSAGE_BYTE_COUNT
            and request_shape.get("user_message_byte_count")
            == EXPECTED_USER_MESSAGE_BYTE_COUNT
            and captured_request == {
                **request_shape,
                "request_message_count": 2,
            }
        ),
        "request_payload_matches_provider_sha256": (
            bool(captured_request.get("request_sha256"))
            and provider_metadata.get("request_sha256")
            == captured_request.get("request_sha256")
        ),
        "representative_request_size": (
            int(captured_request.get("request_payload_byte_count") or 0)
            >= MIN_REPRESENTATIVE_REQUEST_BYTES
        ),
        "representative_prompt_tokens": (
            isinstance(provider_metadata.get("prompt_tokens"), int)
            and provider_metadata["prompt_tokens"]
            >= MIN_REPRESENTATIVE_PROMPT_TOKENS
        ),
        "fixed_provider_controls": fixed_controls_match,
        "single_request": request_count == 1,
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
        "exact_expected_action": actions == [EXPECTED_ACTION],
        "no_probe_exception": not probe_exception,
    }
    passed = all(criteria.values())

    return {
        "type": "stone_pickaxe_sp003_continuation_provider_probe",
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
            "permit_one_new_authorization"
            if passed
            else "hold_new_authorization_provider_continuation_ineligible"
        ),
        "thresholds": {
            "request_timeout_s": REQUEST_TIMEOUT_S,
            "max_acceptable_duration_ms": MAX_ACCEPTABLE_DURATION_MS,
            "min_representative_prompt_tokens": MIN_REPRESENTATIVE_PROMPT_TOKENS,
            "min_representative_request_bytes": MIN_REPRESENTATIVE_REQUEST_BYTES,
            "max_request_count": 1,
            "max_retry_count": 0,
        },
        "criteria": criteria,
        "source": {
            "path": repo_relative(source),
            "sha256": source_sha256,
            "observation_line_number": observation_record["line_number"],
            "observation_canonical_sha256": observation_canonical_sha256,
            "predecessor_call_id": SOURCE_CALL_ID,
            "predecessor_call_index": predecessor_call["data"].get("call_index"),
            "predecessor_plan_kind": predecessor_call["data"].get("plan_kind"),
            "predecessor_parent_call_id": predecessor_call["data"].get(
                "parent_call_id"
            ),
            "predecessor_root_plan_id": predecessor_call["data"].get(
                "root_plan_id"
            ),
            "predecessor_request_sha256": predecessor_call["data"]
            .get("provider_metadata", {})
            .get("request_sha256", ""),
            "predecessor_error_chain": predecessor_attempt.get("error_chain", []),
            "state": actual_source_state,
        },
        "expected_plan_kind": "continuation",
        "expected_action": EXPECTED_ACTION,
        "request": {
            **captured_request,
            "precomputed_request_sha256": request_shape.get("request_sha256", ""),
            "provider_request_sha256": provider_metadata.get("request_sha256", ""),
        },
        "request_count": request_count,
        "retry_count": retry_count,
        "transport_evidence": retained_transport_evidence(transport),
        "provider": provider_metadata.get("provider", planner_config["provider"]),
        "base_url": provider_metadata.get("base_url", planner_config["base_url"]),
        "model": provider_metadata.get("model", planner_config["model"]),
        "temperature": provider_metadata.get(
            "temperature", planner_config["temperature"]
        ),
        "max_tokens": provider_metadata.get("max_tokens", planner_config["max_tokens"]),
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
        "probe_exception_type": probe_exception,
        "credential_value_retained": False,
        "minecraft_process_started": False,
        "authorization_created": False,
        "automatic_retry_attempted": False,
        "counts_toward_baseline_success": False,
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
