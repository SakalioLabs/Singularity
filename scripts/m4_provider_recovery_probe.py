"""Run one crash-bounded M4 fixed-provider recovery probe without Minecraft."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = REPOSITORY_ROOT / "workspace" / "evals"
POLICY_ID = "m4-fixed-provider-recovery-probe-v1"
PROFILE = "m4-fixed-v1"
PROTOCOL_SHA256 = "378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d"
PROVIDER = "openai"
BASE_URL = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4-flash"
CLIENT_TIMEOUT_S = 15.0
SUPERVISOR_TIMEOUT_S = 25.0
SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def configured_api_key() -> str:
    return str(
        os.environ.get("SINGULARITY_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def _exception_status(exc: Exception) -> int | None:
    candidate = getattr(exc, "status_code", None)
    if candidate is None:
        candidate = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(candidate) if candidate is not None else None
    except (TypeError, ValueError):
        return None


def _worker_probe() -> dict[str, Any]:
    api_key = configured_api_key()
    if not api_key:
        return {
            "provider_result_observed": True,
            "ok": False,
            "elapsed_s": 0.0,
            "error_type": "CredentialUnavailable",
            "http_status": None,
            "credit_error": False,
            "response_nonempty": False,
            "response_sha256": None,
        }

    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=CLIENT_TIMEOUT_S,
        max_retries=0,
    )
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Reply with exactly OK."}],
            max_tokens=8,
            temperature=0,
        )
        content = str(response.choices[0].message.content or "").strip()
        return {
            "provider_result_observed": True,
            "ok": bool(content),
            "elapsed_s": round(time.monotonic() - started, 3),
            "error_type": None,
            "http_status": None,
            "credit_error": False,
            "response_nonempty": bool(content),
            "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
    except Exception as exc:
        body = getattr(exc, "body", None)
        body_text = (
            json.dumps(body, ensure_ascii=True).lower() if body is not None else ""
        )
        return {
            "provider_result_observed": True,
            "ok": False,
            "elapsed_s": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
            "http_status": _exception_status(exc),
            "credit_error": (
                "creditserror" in body_text or "insufficient balance" in body_text
            ),
            "response_nonempty": False,
            "response_sha256": None,
        }


def _worker_main() -> int:
    print(json.dumps(_worker_probe(), separators=(",", ":"), ensure_ascii=True))
    return 0


def _parse_worker_output(stdout: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in str(stdout or "").splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _run_supervised_worker(
    *,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    supervisor_timeout_s: float = SUPERVISOR_TIMEOUT_S,
) -> tuple[dict[str, Any], bool]:
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    )
    process = popen_factory(
        command,
        cwd=REPOSITORY_ROOT,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )
    started = time.monotonic()
    try:
        stdout, _stderr = process.communicate(timeout=supervisor_timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return (
            {
                "provider_result_observed": False,
                "ok": False,
                "elapsed_s": round(time.monotonic() - started, 3),
                "error_type": "SupervisorTimeout",
                "http_status": None,
                "credit_error": False,
                "response_nonempty": False,
                "response_sha256": None,
            },
            True,
        )

    payload = _parse_worker_output(stdout)
    if payload is None:
        return (
            {
                "provider_result_observed": False,
                "ok": False,
                "elapsed_s": round(time.monotonic() - started, 3),
                "error_type": "WorkerOutputInvalid",
                "http_status": None,
                "credit_error": False,
                "response_nonempty": False,
                "response_sha256": None,
            },
            False,
        )
    return payload, False


def build_evidence(
    *,
    source_commit: str,
    worker_result: dict[str, Any],
    supervisor_terminated_worker: bool,
) -> dict[str, Any]:
    if not SOURCE_COMMIT_RE.fullmatch(str(source_commit or "")):
        raise ValueError("source_commit must be a 40-character lowercase SHA-1")

    provider_result_observed = worker_result.get("provider_result_observed") is True
    recovered = (
        provider_result_observed
        and worker_result.get("ok") is True
        and worker_result.get("response_nonempty") is True
    )
    if recovered:
        decision = "provider_recovered_probe25_still_requires_authorization"
        classification = "provider_recovered"
    elif provider_result_observed:
        decision = "hold_probe25_fixed_provider_unavailable"
        classification = "fixed_provider_unavailable"
    else:
        decision = "hold_probe25_provider_probe_indeterminate"
        classification = "probe_indeterminate"

    return {
        "type": "m4_provider_recovery_probe",
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "generated_at": utc_now(),
        "source_commit": source_commit,
        "profile": PROFILE,
        "protocol_sha256": PROTOCOL_SHA256,
        "provider": {
            "name": PROVIDER,
            "base_url": BASE_URL,
            "model": MODEL,
        },
        "request": {
            "attempt_count": 1,
            "automatic_retry_count": 0,
            "client_timeout_s": CLIENT_TIMEOUT_S,
            "supervisor_timeout_s": SUPERVISOR_TIMEOUT_S,
            "minecraft_started": False,
            "gameplay_action_count": 0,
        },
        "result": {
            "classification": classification,
            "provider_result_observed": provider_result_observed,
            "recovered": recovered,
            "elapsed_s": worker_result.get("elapsed_s"),
            "error_type": worker_result.get("error_type"),
            "http_status": worker_result.get("http_status"),
            "credit_error": worker_result.get("credit_error") is True,
            "response_nonempty": worker_result.get("response_nonempty") is True,
            "response_sha256": worker_result.get("response_sha256"),
            "response_body_retained": False,
            "supervisor_terminated_worker": supervisor_terminated_worker,
        },
        "decision": {
            "value": decision,
            "recovery_gate_passed": recovered,
            "probe_25_authorized": False,
            "counts_toward_bm012_success": False,
            "counts_toward_capability": False,
        },
        "safety": {
            "credential_value_retained": False,
            "worker_stderr_retained": False,
            "output_is_exclusive": True,
            "output_is_atomic": True,
        },
    }


def run_probe(
    *,
    source_commit: str,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    supervisor_timeout_s: float = SUPERVISOR_TIMEOUT_S,
) -> dict[str, Any]:
    worker_result, terminated = _run_supervised_worker(
        popen_factory=popen_factory,
        supervisor_timeout_s=supervisor_timeout_s,
    )
    return build_evidence(
        source_commit=source_commit,
        worker_result=worker_result,
        supervisor_terminated_worker=terminated,
    )


def write_evidence(
    path: Path,
    evidence: dict[str, Any],
    *,
    eval_root: Path = EVAL_ROOT,
) -> Path:
    root = eval_root.resolve()
    output = path if path.is_absolute() else REPOSITORY_ROOT / path
    output = output.resolve()
    if root not in output.parents:
        raise RuntimeError("probe output must be under workspace/evals")
    if output.exists():
        raise FileExistsError(f"probe output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(evidence, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one crash-bounded M4 fixed-provider recovery probe"
    )
    parser.add_argument("--output")
    parser.add_argument("--source-commit")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        return _worker_main()
    if not args.output or not args.source_commit:
        raise SystemExit("--output and --source-commit are required")
    evidence = run_probe(source_commit=args.source_commit)
    write_evidence(Path(args.output), evidence)
    print(
        json.dumps(
            {
                "classification": evidence["result"]["classification"],
                "provider_result_observed": evidence["result"][
                    "provider_result_observed"
                ],
                "recovery_gate_passed": evidence["decision"]["recovery_gate_passed"],
                "probe_25_authorized": False,
            },
            separators=(",", ":"),
        )
    )
    if evidence["decision"]["recovery_gate_passed"]:
        return 0
    return 2 if evidence["result"]["provider_result_observed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
