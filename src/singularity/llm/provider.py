"""LLM provider abstraction — supports OpenAI, Anthropic, DeepSeek, and local models via Ollama."""
import json
import logging
import hashlib
import math
import time
from typing import Optional

from singularity.core.config import LLMConfig

logger = logging.getLogger("singularity.llm")


class LLMProvider:
    """Swappable LLM backend that supports multiple providers."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None
        self.last_call_metadata: dict = {}
        self._init_client()

    def _init_client(self):
        provider = self.config.provider.lower()
        if provider == "openai":
            import openai
            kwargs = {"api_key": self.config.api_key}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self._client = openai.OpenAI(**kwargs)
        elif provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.config.api_key)
        elif provider == "ollama":
            import openai
            self._client = openai.OpenAI(
                base_url=self.config.base_url or "http://localhost:11434/v1",
                api_key="ollama",
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

    def chat(
        self,
        messages: list[dict],
        response_format: Optional[dict] = None,
        timeout_s: Optional[float] = None,
        extra_body: Optional[dict] = None,
    ) -> str:
        """Send a chat completion request and return the response text."""
        provider = self.config.provider.lower()
        logger.debug(f"LLM call ({provider}): {len(messages)} messages")
        started_at = time.monotonic()
        request_payload = json.dumps(messages, sort_keys=True, ensure_ascii=True, default=str)
        response = None
        bounded_timeout = None
        if timeout_s is not None:
            try:
                candidate_timeout = float(timeout_s)
            except (TypeError, ValueError) as exc:
                raise ValueError("timeout_s must be a finite positive number") from exc
            if not math.isfinite(candidate_timeout) or candidate_timeout <= 0:
                raise ValueError("timeout_s must be a finite positive number")
            bounded_timeout = candidate_timeout

        request_metadata = {
            "provider": provider,
            "base_url": str(self.config.base_url or "").rstrip("/"),
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": dict(response_format or {}),
            "extra_body": dict(extra_body or {}),
            "request_message_count": len(messages),
            "request_sha256": hashlib.sha256(request_payload.encode("utf-8")).hexdigest(),
            "timeout_s": round(bounded_timeout, 3) if bounded_timeout is not None else None,
            "max_retries": 0 if bounded_timeout is not None else None,
            "forced_json_tool": bool(
                provider == "openai"
                and getattr(self.config, "use_forced_json_tool", False)
            ),
        }
        self.last_call_metadata = dict(request_metadata)

        if provider in ("openai", "ollama"):
            kwargs = {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            }
            forced_json_tool = bool(
                provider == "openai"
                and getattr(self.config, "use_forced_json_tool", False)
            )
            if forced_json_tool:
                kwargs["tools"] = [{
                    "type": "function",
                    "function": {
                        "name": "submit_json",
                        "description": "Submit the required JSON response.",
                        "parameters": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                }]
                kwargs["tool_choice"] = {
                    "type": "function",
                    "function": {"name": "submit_json"},
                }
            elif response_format and provider == "openai":
                kwargs["response_format"] = response_format
            if extra_body:
                kwargs["extra_body"] = dict(extra_body)
            client = self._client
            if bounded_timeout is not None:
                if hasattr(client, "with_options"):
                    client = client.with_options(timeout=bounded_timeout, max_retries=0)
                else:
                    kwargs["timeout"] = bounded_timeout
            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message
            text = message.content or ""
            finish_reason = str(getattr(choice, "finish_reason", "") or "")
            reasoning_content = str(getattr(message, "reasoning_content", "") or "")
            tool_calls = list(getattr(message, "tool_calls", None) or [])
        elif provider == "anthropic":
            # Anthropic uses a different message format
            system_msg = ""
            user_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_msg = msg["content"]
                else:
                    user_messages.append(msg)
            client = self._client
            kwargs = {
                "model": self.config.model,
                "max_tokens": self.config.max_tokens,
                "system": system_msg,
                "messages": user_messages,
            }
            if bounded_timeout is not None:
                if hasattr(client, "with_options"):
                    client = client.with_options(timeout=bounded_timeout, max_retries=0)
                else:
                    kwargs["timeout"] = bounded_timeout
            response = client.messages.create(
                **kwargs,
            )
            text = response.content[0].text if response.content else ""
            finish_reason = str(getattr(response, "stop_reason", "") or "")
            reasoning_content = ""
            tool_calls = []
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        response_content_source = "content"
        if (
            not text.strip()
            and bool(getattr(self.config, "use_forced_json_tool", False))
            and len(tool_calls) == 1
        ):
            function = getattr(tool_calls[0], "function", None)
            function_name = str(getattr(function, "name", "") or "")
            arguments = str(getattr(function, "arguments", "") or "").strip()
            if function_name == "submit_json" and arguments:
                try:
                    parsed_arguments = json.loads(arguments)
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_arguments = None
                if isinstance(parsed_arguments, dict):
                    text = arguments
                    response_content_source = "forced_json_tool_arguments"
        if (
            not text.strip()
            and reasoning_content.strip()
            and bool(getattr(self.config, "use_reasoning_json_fallback", False))
        ):
            reasoning_candidate = reasoning_content.strip()
            try:
                parsed_reasoning = json.loads(reasoning_candidate)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed_reasoning = None
            if isinstance(parsed_reasoning, dict):
                text = reasoning_candidate
                response_content_source = "reasoning_content_json_fallback"

        usage = getattr(response, "usage", None)
        prompt_tokens = self._usage_value(usage, "prompt_tokens", "input_tokens")
        completion_tokens = self._usage_value(usage, "completion_tokens", "output_tokens")
        total_tokens = self._usage_value(usage, "total_tokens")
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens
        self.last_call_metadata = {
            **request_metadata,
            "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "response_id": str(getattr(response, "id", "") or ""),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "finish_reason": finish_reason,
            "reasoning_content_byte_count": len(reasoning_content.encode("utf-8")),
            "response_content_source": response_content_source,
            "duration_ms": int((time.monotonic() - started_at) * 1000),
        }
        logger.debug(f"LLM response: {text[:200]}")
        return text

    def reset_client(self):
        """Replace the provider client after a retryable transport failure."""
        previous = self._client
        close = getattr(previous, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        self._client = None
        self._init_client()

    def _usage_value(self, usage, *names):
        for name in names:
            value = getattr(usage, name, None) if usage is not None else None
            if value is None and isinstance(usage, dict):
                value = usage.get(name)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None
