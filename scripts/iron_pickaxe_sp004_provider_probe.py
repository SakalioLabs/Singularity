"""Run one bounded SP-004 provider probe without starting Minecraft."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from singularity.core.config import LLMConfig
from singularity.llm.provider import LLMProvider


POLICY_ID = "iron-pickaxe-sp004-provider-recovery-gate-v1"
DEFAULT_BASE_URL = "http://192.168.3.27:8317/v1"
DEFAULT_MODEL = "grok-4.5"
REQUEST_TIMEOUT_S = 15.0
PROBE_GOAL = "SP-004 structured provider probe."
EXPECTED_RESPONSE = {
    "schema_version": "stone-pickaxe-plan-v1",
    "plan_kind": "continuation",
    "goal": PROBE_GOAL,
    "status": "blocked",
    "reasoning": "Provider probe only.",
    "subtasks": [],
    "actions": [],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one zero-retry SP-004 provider probe without Minecraft"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser.parse_args()


def configured_api_key() -> str:
    return str(
        os.environ.get("SINGULARITY_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def normalize_base_url(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("SP-004 provider probe requires a non-empty base URL")
    return base if base.endswith("/v1") else f"{base}/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        text=True,
    ).strip()


def probe_messages() -> list[dict]:
    return [
        {
            "role": "system",
            "content": "Return only one JSON object. Do not use markdown.",
        },
        {
            "role": "user",
            "content": (
                "SP-004 provider recovery probe. Return exactly "
                + json.dumps(EXPECTED_RESPONSE, separators=(",", ":"))
                + "."
            ),
        },
    ]


def exception_http_status(exc: Exception) -> int | None:
    candidate = getattr(exc, "status_code", None)
    if candidate is None:
        candidate = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(candidate) if candidate is not None else None
    except (TypeError, ValueError):
        return None


def failure_classification(error_type: str, http_status: int | None) -> str:
    if http_status in {401, 403} or error_type == "AuthenticationError":
        return "provider_authentication_failed"
    if http_status is not None and http_status >= 500:
        return "provider_unavailable"
    if error_type:
        return "provider_transport_or_protocol_failed"
    return ""


def run_probe(
    *,
    base_url: str,
    model: str,
    provider_factory: Callable[[LLMConfig], LLMProvider] = LLMProvider,
) -> dict:
    api_key = configured_api_key()
    if not api_key:
        raise RuntimeError(
            "probe requires SINGULARITY_LLM_API_KEY or OPENAI_API_KEY"
        )
    normalized_base_url = normalize_base_url(base_url)
    config = LLMConfig(
        provider="openai",
        model=model,
        api_key=api_key,
        base_url=normalized_base_url,
        max_tokens=256,
        temperature=0.0,
        use_forced_json_tool=True,
    )
    provider = provider_factory(config)
    response_text = ""
    parsed_response: object = None
    error_type = ""
    error_message = ""
    http_status = None
    started_at_utc = utc_now()
    started = time.monotonic()
    try:
        response_text = provider.chat(
            probe_messages(),
            response_format={"type": "json_object"},
            timeout_s=REQUEST_TIMEOUT_S,
            extra_body={"thinking": {"type": "disabled"}},
        ).strip()
        parsed_response = json.loads(response_text)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)[:200]
        http_status = exception_http_status(exc)
    elapsed_s = round(time.monotonic() - started, 3)
    metadata = dict(getattr(provider, "last_call_metadata", {}) or {})
    response_sha256 = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
    criteria = {
        "exact_provider": metadata.get("provider") == "openai",
        "exact_base_url": metadata.get("base_url") == normalized_base_url,
        "exact_model": metadata.get("model") == model,
        "json_response_format": metadata.get("response_format")
        == {"type": "json_object"},
        "forced_json_tool": metadata.get("forced_json_tool") is True,
        "structured_output_channel": metadata.get("response_content_source")
        == "forced_json_tool_arguments",
        "thinking_disabled": metadata.get("extra_body")
        == {"thinking": {"type": "disabled"}},
        "bounded_timeout": metadata.get("timeout_s") == REQUEST_TIMEOUT_S,
        "zero_retries": metadata.get("max_retries") == 0,
        "exact_response": parsed_response == EXPECTED_RESPONSE,
        "no_exception": not error_type,
    }
    passed = all(criteria.values())
    classification = failure_classification(error_type, http_status)
    return {
        "type": "iron_pickaxe_sp004_provider_probe",
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "generated_at_utc": utc_now(),
        "started_at_utc": started_at_utc,
        "source_commit": current_head(),
        "provider": "openai_compatible",
        "base_url": normalized_base_url,
        "model": model,
        "passed": passed,
        "decision": (
            "provider_recovered_live_episode_still_requires_explicit_launch"
            if passed
            else (
                "hold_live_episode_provider_authentication_failed"
                if classification == "provider_authentication_failed"
                else "hold_live_episode_provider_unavailable"
            )
        ),
        "classification": "provider_recovered" if passed else classification,
        "criteria": criteria,
        "attempt_count": 1,
        "retry_count": 0,
        "elapsed_s": elapsed_s,
        "response_byte_count": len(response_text.encode("utf-8")),
        "response_sha256": response_sha256,
        "error_type": error_type,
        "error": error_message,
        "http_status": http_status,
        "minecraft_process_started": False,
        "gameplay_action_count": 0,
        "automatic_retry_attempted": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def write_evidence(path: Path, evidence: dict) -> None:
    output = path if path.is_absolute() else REPOSITORY_ROOT / path
    output = output.resolve()
    eval_root = (REPOSITORY_ROOT / "workspace" / "evals").resolve()
    if eval_root not in output.parents:
        raise RuntimeError("probe output must be under workspace/evals")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(evidence, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def main() -> int:
    args = parse_args()
    evidence = run_probe(base_url=args.base_url, model=args.model)
    write_evidence(Path(args.output), evidence)
    print(
        json.dumps(
            {
                "passed": evidence["passed"],
                "decision": evidence["decision"],
                "attempt_count": evidence["attempt_count"],
                "retry_count": evidence["retry_count"],
                "error_type": evidence["error_type"],
            },
            indent=2,
        )
    )
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
