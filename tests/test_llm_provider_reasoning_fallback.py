from __future__ import annotations

from types import SimpleNamespace

from singularity.core.config import LLMConfig
from singularity.llm.provider import LLMProvider


class FakeCompletions:
    def __init__(
        self,
        *,
        content: str,
        reasoning_content: str,
        tool_arguments: str = "",
    ):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_arguments = tool_arguments
        self.calls = 0
        self.kwargs = {}

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        tool_calls = []
        if self.tool_arguments:
            tool_calls = [
                SimpleNamespace(
                    function=SimpleNamespace(
                        name="submit_json",
                        arguments=self.tool_arguments,
                    )
                )
            ]
        message = SimpleNamespace(
            content=self.content,
            reasoning_content=self.reasoning_content,
            tool_calls=tool_calls,
        )
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(
            id="fake-response",
            choices=[choice],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)

    def with_options(self, **_kwargs):
        return self


def _provider(
    *,
    enabled: bool,
    content: str,
    reasoning_content: str,
    forced_tool: bool = False,
    tool_arguments: str = "",
):
    provider = object.__new__(LLMProvider)
    provider.config = LLMConfig(
        provider="openai",
        model="grok-4.5",
        api_key="test-only",
        base_url="http://example.test/v1",
        use_reasoning_json_fallback=enabled,
        use_forced_json_tool=forced_tool,
    )
    completions = FakeCompletions(
        content=content,
        reasoning_content=reasoning_content,
        tool_arguments=tool_arguments,
    )
    provider._client = FakeClient(completions)
    provider.last_call_metadata = {}
    return provider, completions


def test_reasoning_json_fallback_is_disabled_by_default() -> None:
    provider, completions = _provider(
        enabled=False,
        content="",
        reasoning_content='{"status":"planning"}',
    )

    text = provider.chat(
        [{"role": "user", "content": "test"}],
        response_format={"type": "json_object"},
        timeout_s=10,
    )

    assert text == ""
    assert completions.calls == 1
    assert provider.last_call_metadata["response_content_source"] == "content"


def test_reasoning_json_fallback_recovers_one_object_without_retry() -> None:
    provider, completions = _provider(
        enabled=True,
        content="",
        reasoning_content='{"status":"planning","actions":[]}',
    )

    text = provider.chat(
        [{"role": "user", "content": "test"}],
        response_format={"type": "json_object"},
        timeout_s=10,
    )

    assert text == '{"status":"planning","actions":[]}'
    assert completions.calls == 1
    assert provider.last_call_metadata["max_retries"] == 0
    assert provider.last_call_metadata["response_content_source"] == (
        "reasoning_content_json_fallback"
    )


def test_reasoning_fallback_rejects_non_json_and_non_object_content() -> None:
    for reasoning in ("thinking aloud", "[1,2,3]", "```json\n{}\n```"):
        provider, completions = _provider(
            enabled=True,
            content="",
            reasoning_content=reasoning,
        )

        assert (
            provider.chat(
                [{"role": "user", "content": "test"}],
                response_format={"type": "json_object"},
                timeout_s=10,
            )
            == ""
        )
        assert completions.calls == 1
        assert provider.last_call_metadata["response_content_source"] == "content"


def test_forced_json_tool_uses_one_structured_call_without_response_format() -> None:
    provider, completions = _provider(
        enabled=True,
        forced_tool=True,
        content="",
        reasoning_content="planning",
        tool_arguments='{"status":"planning","actions":[]}',
    )

    text = provider.chat(
        [{"role": "user", "content": "test"}],
        response_format={"type": "json_object"},
        timeout_s=10,
    )

    assert text == '{"status":"planning","actions":[]}'
    assert completions.calls == 1
    assert "response_format" not in completions.kwargs
    assert completions.kwargs["tool_choice"]["function"]["name"] == "submit_json"
    assert provider.last_call_metadata["forced_json_tool"] is True
    assert provider.last_call_metadata["response_content_source"] == (
        "forced_json_tool_arguments"
    )
