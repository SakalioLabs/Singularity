"""Keep the forced planner tool schema portable across OpenAI-compatible APIs."""

from __future__ import annotations

from types import SimpleNamespace

from singularity.core.config import LLMConfig
from singularity.llm.provider import LLMProvider


class _Completions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        function = SimpleNamespace(
            name="submit_json",
            arguments=(
                '{"schema_version":"stone-pickaxe-plan-v1",'
                '"plan_kind":"continuation","goal":"test","status":"blocked",'
                '"reasoning":"test","subtasks":[],"actions":[]}'
            ),
        )
        message = SimpleNamespace(
            content="",
            reasoning_content="",
            tool_calls=[SimpleNamespace(function=function)],
        )
        choice = SimpleNamespace(message=message, finish_reason="tool_calls")
        return SimpleNamespace(
            choices=[choice],
            id="forced-json-schema-test",
            usage=None,
        )


class _Client:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_Completions())

    def with_options(self, **_kwargs):
        return self


def test_forced_json_tool_declares_array_item_schemas(monkeypatch):
    monkeypatch.setattr(LLMProvider, "_init_client", lambda self: None)
    provider = LLMProvider(
        LLMConfig(
            provider="openai",
            model="gemini-3.6-flash-high",
            api_key="test-key",
            base_url="http://127.0.0.1:8317/v1",
            use_forced_json_tool=True,
        )
    )
    provider._client = _Client()

    response = provider.chat(
        [{"role": "user", "content": "Return a plan."}],
        response_format={"type": "json_object"},
        timeout_s=15,
        extra_body={"thinking": {"type": "disabled"}},
    )

    assert response
    request = provider._client.chat.completions.kwargs
    properties = request["tools"][0]["function"]["parameters"]["properties"]
    assert properties["subtasks"]["items"] == {"type": "object"}
    assert properties["actions"]["items"] == {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "parameters": {"type": "object"},
        },
        "required": ["type", "parameters"],
    }
    assert request["tool_choice"]["function"]["name"] == "submit_json"
    assert provider.last_call_metadata["forced_json_tool"] is True
