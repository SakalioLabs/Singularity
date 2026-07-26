import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "m4_provider_recovery_probe.py"
SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_provider_recovery_probe.schema.json"
)
AUDIT_PATH = (
    ROOT / "workspace" / "evals" / "m4_provider_recovery_probe_tooling_audit.json"
)
SOURCE_COMMIT = "a" * 40

SPEC = importlib.util.spec_from_file_location("m4_provider_recovery_probe", SCRIPT_PATH)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class FakeProcess:
    def __init__(self, stdout: str = "", *, times_out: bool = False):
        self.stdout = stdout
        self.times_out = times_out
        self.communicate_count = 0
        self.killed = False

    def communicate(self, timeout=None):
        self.communicate_count += 1
        if self.times_out and self.communicate_count == 1:
            raise subprocess.TimeoutExpired(cmd=["probe"], timeout=timeout)
        return self.stdout, ""

    def kill(self):
        self.killed = True


def _factory(process: FakeProcess):
    def create(*_args, **_kwargs):
        return process

    return create


def _validate(evidence: dict):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(evidence)


def test_recovered_worker_passes_gate_without_authorizing_probe25():
    response_sha = "b" * 64
    worker = {
        "provider_result_observed": True,
        "ok": True,
        "elapsed_s": 1.25,
        "error_type": None,
        "http_status": None,
        "credit_error": False,
        "response_nonempty": True,
        "response_sha256": response_sha,
    }
    process = FakeProcess(json.dumps(worker))

    evidence = PROBE.run_probe(
        source_commit=SOURCE_COMMIT,
        popen_factory=_factory(process),
    )

    _validate(evidence)
    assert evidence["result"]["classification"] == "provider_recovered"
    assert evidence["decision"]["recovery_gate_passed"] is True
    assert evidence["decision"]["probe_25_authorized"] is False
    assert evidence["request"]["attempt_count"] == 1
    assert evidence["request"]["automatic_retry_count"] == 0


def test_credit_error_is_observed_and_fails_closed():
    worker = {
        "provider_result_observed": True,
        "ok": False,
        "elapsed_s": 2.5,
        "error_type": "AuthenticationError",
        "http_status": 401,
        "credit_error": True,
        "response_nonempty": False,
        "response_sha256": None,
    }
    evidence = PROBE.run_probe(
        source_commit=SOURCE_COMMIT,
        popen_factory=_factory(FakeProcess(json.dumps(worker))),
    )

    _validate(evidence)
    assert evidence["result"]["classification"] == "fixed_provider_unavailable"
    assert evidence["result"]["credit_error"] is True
    assert evidence["decision"]["recovery_gate_passed"] is False
    assert evidence["decision"]["probe_25_authorized"] is False


def test_supervisor_timeout_kills_worker_and_still_builds_evidence():
    process = FakeProcess(times_out=True)

    evidence = PROBE.run_probe(
        source_commit=SOURCE_COMMIT,
        popen_factory=_factory(process),
        supervisor_timeout_s=0.01,
    )

    _validate(evidence)
    assert process.killed is True
    assert process.communicate_count == 2
    assert evidence["result"]["classification"] == "probe_indeterminate"
    assert evidence["result"]["provider_result_observed"] is False
    assert evidence["result"]["supervisor_terminated_worker"] is True
    assert evidence["decision"]["probe_25_authorized"] is False


def test_invalid_worker_output_is_indeterminate_without_retry():
    evidence = PROBE.run_probe(
        source_commit=SOURCE_COMMIT,
        popen_factory=_factory(FakeProcess("not-json")),
    )

    _validate(evidence)
    assert evidence["result"]["classification"] == "probe_indeterminate"
    assert evidence["result"]["error_type"] == "WorkerOutputInvalid"
    assert evidence["request"]["automatic_retry_count"] == 0


def test_atomic_output_is_exclusive_and_contains_no_credential(tmp_path):
    eval_root = tmp_path / "workspace" / "evals"
    output = eval_root / "probe.json"
    evidence = PROBE.build_evidence(
        source_commit=SOURCE_COMMIT,
        worker_result={
            "provider_result_observed": False,
            "ok": False,
            "elapsed_s": 25.0,
            "error_type": "SupervisorTimeout",
            "http_status": None,
            "credit_error": False,
            "response_nonempty": False,
            "response_sha256": None,
        },
        supervisor_terminated_worker=True,
    )

    written = PROBE.write_evidence(output, evidence, eval_root=eval_root)
    assert json.loads(written.read_text(encoding="utf-8")) == evidence
    assert "secret-test-value" not in written.read_text(encoding="utf-8")
    assert not list(output.parent.glob(".*.tmp"))
    with pytest.raises(FileExistsError):
        PROBE.write_evidence(output, evidence, eval_root=eval_root)


def test_output_outside_eval_root_and_invalid_commit_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        PROBE.build_evidence(
            source_commit="not-a-commit",
            worker_result={},
            supervisor_terminated_worker=False,
        )
    with pytest.raises(RuntimeError):
        PROBE.write_evidence(
            tmp_path / "outside.json",
            {},
            eval_root=tmp_path / "workspace" / "evals",
        )


def test_tooling_audit_binds_script_schema_and_prior_indeterminate_evidence():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    implementation = audit["implementation"]
    root_cause = audit["root_cause"]

    for path_key, hash_key in (
        ("script_path", "script_sha256"),
        ("schema_path", "schema_sha256"),
    ):
        path = ROOT / implementation[path_key]
        assert PROBE.hashlib.sha256(path.read_bytes()).hexdigest() == (
            implementation[hash_key]
        )
    source = ROOT / root_cause["source_path"]
    assert PROBE.hashlib.sha256(source.read_bytes()).hexdigest() == (
        root_cause["source_sha256"]
    )
    assert audit["validation"]["focused_test_pass_count"] == 7
    assert audit["decision"]["live_provider_request_run"] is False
    assert audit["decision"]["probe_25_authorized"] is False
    assert audit["decision"]["changes_blocked_threshold_count"] is False
