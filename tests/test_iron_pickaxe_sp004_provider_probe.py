from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/iron_pickaxe_sp004_provider_probe.py"


def _module():
    spec = importlib.util.spec_from_file_location("sp004_provider_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProvider:
    def __init__(self, config, *, error: Exception | None = None):
        self.config = config
        self.error = error
        self.last_call_metadata = {}
        self.calls = []

    def chat(self, messages, response_format=None, timeout_s=None, extra_body=None):
        self.calls.append(
            {
                "messages": messages,
                "response_format": response_format,
                "timeout_s": timeout_s,
                "extra_body": extra_body,
            }
        )
        self.last_call_metadata = {
            "provider": "openai",
            "base_url": self.config.base_url,
            "model": self.config.model,
            "response_format": response_format,
            "extra_body": extra_body,
            "timeout_s": timeout_s,
            "max_retries": 0,
            "forced_json_tool": self.config.use_forced_json_tool,
            "response_content_source": "forced_json_tool_arguments",
        }
        if self.error:
            raise self.error
        return '{"status":"ok","stage":"acquire_cobblestone"}'


class FakeAuthenticationError(RuntimeError):
    status_code = 401


def test_probe_passes_exact_single_request_zero_retry(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("SINGULARITY_LLM_API_KEY", "test-only-secret")
    created = []

    def factory(config):
        provider = FakeProvider(config)
        created.append(provider)
        return provider

    evidence = module.run_probe(
        base_url=module.DEFAULT_BASE_URL,
        model=module.DEFAULT_MODEL,
        provider_factory=factory,
    )

    assert evidence["passed"] is True
    assert all(evidence["criteria"].values())
    assert evidence["attempt_count"] == 1
    assert evidence["retry_count"] == 0
    assert evidence["minecraft_process_started"] is False
    assert evidence["gameplay_action_count"] == 0
    assert evidence["response_byte_count"] > 0
    assert "test-only-secret" not in json.dumps(evidence)
    assert len(created[0].calls) == 1
    assert created[0].calls[0]["timeout_s"] == module.REQUEST_TIMEOUT_S


def test_probe_normalizes_openai_compatible_base_url(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("SINGULARITY_LLM_API_KEY", "test-only-secret")
    created = []

    def factory(config):
        provider = FakeProvider(config)
        created.append(provider)
        return provider

    evidence = module.run_probe(
        base_url="http://192.168.3.27:8317/",
        model=module.DEFAULT_MODEL,
        provider_factory=factory,
    )

    assert evidence["passed"] is True
    assert evidence["base_url"] == "http://192.168.3.27:8317/v1"
    assert created[0].config.base_url == "http://192.168.3.27:8317/v1"
    assert module.normalize_base_url("http://example.test/v1/") == (
        "http://example.test/v1"
    )


def test_probe_retains_provider_failure_without_retry(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("SINGULARITY_LLM_API_KEY", "test-only-secret")
    created = []

    def factory(config):
        provider = FakeProvider(config, error=RuntimeError("Error code: 502"))
        created.append(provider)
        return provider

    evidence = module.run_probe(
        base_url=module.DEFAULT_BASE_URL,
        model=module.DEFAULT_MODEL,
        provider_factory=factory,
    )

    assert evidence["passed"] is False
    assert evidence["decision"] == "hold_live_episode_provider_unavailable"
    assert evidence["classification"] == "provider_transport_or_protocol_failed"
    assert evidence["error_type"] == "RuntimeError"
    assert evidence["attempt_count"] == 1
    assert evidence["retry_count"] == 0
    assert evidence["automatic_retry_attempted"] is False
    assert len(created[0].calls) == 1


def test_probe_classifies_authentication_failure(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("SINGULARITY_LLM_API_KEY", "test-only-secret")

    def factory(config):
        return FakeProvider(config, error=FakeAuthenticationError("invalid key"))

    evidence = module.run_probe(
        base_url=module.DEFAULT_BASE_URL,
        model=module.DEFAULT_MODEL,
        provider_factory=factory,
    )

    assert evidence["passed"] is False
    assert evidence["classification"] == "provider_authentication_failed"
    assert evidence["decision"] == (
        "hold_live_episode_provider_authentication_failed"
    )
    assert evidence["http_status"] == 401
    assert evidence["attempt_count"] == 1
    assert evidence["retry_count"] == 0
    assert evidence["minecraft_process_started"] is False


def test_probe_output_is_exclusive_and_eval_scoped(tmp_path) -> None:
    module = _module()
    output = ROOT / "workspace/evals/test_sp004_provider_probe_output.json"
    output.unlink(missing_ok=True)
    try:
        module.write_evidence(output, {"passed": False})
        assert json.loads(output.read_text(encoding="utf-8")) == {"passed": False}
        try:
            module.write_evidence(output, {"passed": True})
        except FileExistsError:
            pass
        else:
            raise AssertionError("probe output must refuse overwrite")

        outside = tmp_path / "outside.json"
        try:
            module.write_evidence(outside, {"passed": False})
        except RuntimeError as exc:
            assert "workspace/evals" in str(exc)
        else:
            raise AssertionError("probe output escaped workspace/evals")
    finally:
        output.unlink(missing_ok=True)
