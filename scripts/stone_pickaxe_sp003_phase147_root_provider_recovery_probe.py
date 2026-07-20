"""Run one bounded Phase 147 SP-003 root-provider probe without Minecraft."""

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


PHASE = 147
POLICY_ID = "sp003-phase147-root-provider-recovery-gate-v1"
PROBE_EPISODE_ID = "sp003-provider-root-recovery-probe-phase147"
SOURCE_EPISODE_ID = "sp003_baseline_20260720_194725_phase146"
SOURCE_CALL_ID = "llm-3e890a2ab1314645"
EXPECTED_SOURCE_SHA256 = (
    "4e77402fd3ffd7bb9e1706ac2b8aed744fea5ffd0616e5dd8e7cb9fa2f49f8f0"
)
EXPECTED_OBSERVATION_CANONICAL_SHA256 = (
    "2cd05d400bfd504101dda3807555ff58187b589271747adda3a463be47711fe7"
)
DEFAULT_SOURCE = Path(
    "workspace/evals/sp003_runs/"
    "sp003_baseline_20260720_194725_phase146/"
    "session_2e77e5b0-07f.jsonl"
)
DEFAULT_OUTPUT = Path(
    "workspace/evals/stone_pickaxe_sp003_phase147_root_provider_recovery_probe.json"
)
REQUEST_TIMEOUT_S = 12.0
MAX_ACCEPTABLE_DURATION_MS = 7_500
MIN_REPRESENTATIVE_PROMPT_TOKENS = 2_500
MIN_REPRESENTATIVE_REQUEST_BYTES = 10_000
EXPECTED_SUBTASK_COUNT = 5
EXPECTED_ACTION = {
    "type": "move_to",
    "parameters": {"x": 121, "y": 142, "z": -36},
}
EXPECTED_SOURCE_STATE = {
    "runtime_mode": "sp003",
    "arm": "baseline",
    "stage": "acquire_wood",
    "inventory": {},
    "log_source_removal_count": 0,
    "target_count": 1,
    "target_source_id": "grass_block:121:141:-36",
    "target_name": "grass_block",
    "target_stand_position": {"x": 121, "y": 142, "z": -36},
    "target_navigation_only": True,
    "target_canopy_egress": True,
}
EXPECTED_REQUEST_METADATA = {
    "request_sha256": (
        "97f12aa6c1f929b4a6a7645fa8707932d6f3e279a843f20b151302d57bbb9d26"
    ),
    "request_payload_byte_count": 14_144,
    "system_message_byte_count": 9_404,
    "user_message_byte_count": 4_107,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one no-Minecraft Phase 147 SP-003 root-provider probe"
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
        "target_count": len(targets) if isinstance(targets, list) else 0,
        "target_source_id": target.get("source_id"),
        "target_name": target.get("name"),
        "target_stand_position": target.get("stand_position"),
        "target_navigation_only": target.get("navigation_only"),
        "target_canopy_egress": target.get("canopy_egress"),
    }


def exact_probe_messages(planner: Planner, world_state: dict) -> list[dict]:
    planner._expected_plan_kind = "root"
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
                    "success": attempt.get("success") is True,
                    "timeout_s": attempt.get("timeout_s"),
                    "sdk_max_retries": attempt.get("sdk_max_retries"),
                    "error_type": str(attempt.get("error_type") or ""),
                    "error_chain": list(attempt.get("error_chain") or []),
                }
            )
    return {
        "policy_id": str(transport.get("policy_id") or ""),
        "attempt_count": int(transport.get("attempt_count") or 0),
        "retry_count": int(transport.get("retry_count") or 0),
        "attempts": safe_attempts,
    }


def _offline_planner(api_key: str) -> tuple[LLMProvider, Planner]:
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
    return provider, planner


def run_probe(source: Path) -> dict:
    source_sha256 = file_sha256(source)
    if source_sha256 != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Phase 147 source evidence SHA-256 mismatch")

    observation_record, predecessor_call = retained_observation_before_call(
        source, SOURCE_CALL_ID
    )
    observation_event = observation_record["event"]
    observation_sha256 = canonical_sha256(observation_event)
    if observation_sha256 != EXPECTED_OBSERVATION_CANONICAL_SHA256:
        raise RuntimeError("Phase 147 source observation fingerprint mismatch")

    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError(
            "probe requires SINGULARITY_LLM_API_KEY or OPENAI_API_KEY"
        )

    world_state = observation_event["data"]
    provider, planner = _offline_planner(api_key)
    actual_source_state = compact_source_state(planner, world_state)
    request_shape = request_payload_metadata(
        exact_probe_messages(planner, world_state)
    )
    if actual_source_state != EXPECTED_SOURCE_STATE:
        raise RuntimeError("Phase 147 compact source state mismatch")
    if request_shape != EXPECTED_REQUEST_METADATA:
        raise RuntimeError("Phase 147 offline request fingerprint mismatch")

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
            raise RuntimeError("Phase 147 provider call limit exhausted")
        captured_request.update(request_payload_metadata(messages))
        captured_request["request_message_count"] = len(messages)
        return original_chat(
            messages,
            response_format=response_format,
            timeout_s=timeout_s,
            extra_body=extra_body,
        )

    provider.chat = capture_chat
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
    transport = retained_transport_evidence(
        dict(planner_evidence.get("transport_evidence") or {})
    )
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
    planner_config = PROTOCOL["planner"]
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
        "source_sha256_matches": source_sha256 == EXPECTED_SOURCE_SHA256,
        "source_observation_matches": (
            observation_record["line_number"] == 5
            and observation_sha256 == EXPECTED_OBSERVATION_CANONICAL_SHA256
        ),
        "source_state_matches": actual_source_state == EXPECTED_SOURCE_STATE,
        "source_predecessor_is_exact_tls_eof": (
            predecessor_call["data"].get("call_index") == 0
            and predecessor_call["data"].get("plan_kind") == "root"
            and predecessor_transport.get("attempt_count") == 1
            and predecessor_transport.get("retry_count") == 0
            and predecessor_attempt.get("error_chain")
            == ["APIConnectionError", "ConnectError", "ConnectError", "SSLEOFError"]
        ),
        "offline_request_fingerprint_matches": (
            request_shape == EXPECTED_REQUEST_METADATA
        ),
        "captured_request_matches_offline_request": (
            all(captured_request.get(key) == value for key, value in request_shape.items())
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
        "single_provider_chat_call": provider_chat_call_count == 1,
        "single_transport_request": request_count == 1,
        "zero_retries": retry_count == 0,
        "within_latency_gate": (
            isinstance(duration_ms, int)
            and duration_ms <= MAX_ACCEPTABLE_DURATION_MS
        ),
        "real_llm_call": planner_evidence.get("real_llm_call") is True,
        "schema_valid": planner_evidence.get("schema_valid") is True,
        "root_plan": (
            plan.get("plan_kind") == "root"
            and plan.get("status") == "planning"
        ),
        "exact_five_node_graph": len(subtasks) == EXPECTED_SUBTASK_COUNT,
        "exact_expected_action": actions == [EXPECTED_ACTION],
        "no_probe_exception": not probe_exception,
    }
    passed = all(criteria.values())

    return {
        "$schema": (
            "workspace/evals/schemas/"
            "stone_pickaxe_sp003_phase147_root_provider_recovery_probe.schema.json"
        ),
        "type": "stone_pickaxe_sp003_root_provider_recovery_probe",
        "schema_version": 1,
        "phase": PHASE,
        "policy_id": POLICY_ID,
        "task_id": "SP-003",
        "purpose": "recover_from_phase_146_first_root_provider_tls_eof",
        "predecessor_commit": current_head(),
        "started_at_utc": started_at_utc,
        "ended_at_utc": ended_at_utc,
        "passed": passed,
        "decision": (
            "permit_one_new_parent_bound_baseline_authorization"
            if passed
            else "hold_live_authorization_provider_root_recovery_failed"
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
            "sha256": source_sha256,
            "immutable": True,
            "rewritten": False,
            "observation_line_number": observation_record["line_number"],
            "observation_canonical_sha256": observation_sha256,
            "predecessor_call_id": SOURCE_CALL_ID,
            "predecessor_call_index": predecessor_call["data"].get("call_index"),
            "predecessor_request_sha256": predecessor_call["data"]
            .get("provider_metadata", {})
            .get("request_sha256", ""),
            "predecessor_error_chain": predecessor_attempt.get("error_chain", []),
            "state": actual_source_state,
        },
        "expected_plan_kind": "root",
        "expected_action": EXPECTED_ACTION,
        "request": {
            **captured_request,
            "precomputed_request_sha256": request_shape["request_sha256"],
            "provider_request_sha256": provider_metadata.get("request_sha256", ""),
        },
        "provider_chat_call_count": provider_chat_call_count,
        "request_count": request_count,
        "retry_count": retry_count,
        "transport_evidence": transport,
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
                "provider_chat_call_count": evidence["provider_chat_call_count"],
                "request_count": evidence["request_count"],
                "retry_count": evidence["retry_count"],
                "duration_ms": evidence["duration_ms"],
                "wall_duration_ms": evidence["wall_duration_ms"],
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
