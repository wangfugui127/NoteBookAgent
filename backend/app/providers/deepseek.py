import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings


@dataclass
class ProviderToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResponse:
    content: str = ""
    tool_calls: list[ProviderToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    provider_state: dict[str, Any] = field(default_factory=dict)


TextDeltaCallback = Callable[[str], Awaitable[None]]


class DeepSeekProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key or "missing-key",
            base_url=settings.deepseek_base_url,
        )

    async def invoke(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text_delta: TextDeltaCallback | None = None,
    ) -> ProviderResponse:
        if not self.settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

        stream = await self.client.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools or None,  # type: ignore[arg-type]
            tool_choice="auto" if tools else None,
            max_tokens=self.settings.max_output_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        content_parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage: dict[str, int] = {}
        async for chunk in stream:
            if chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                }
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                if on_text_delta:
                    await on_text_delta(delta.content)
            for tool_delta in delta.tool_calls or []:
                slot = calls.setdefault(tool_delta.index, {"id": "", "name": "", "arguments": ""})
                if tool_delta.id:
                    slot["id"] += tool_delta.id
                if tool_delta.function and tool_delta.function.name:
                    slot["name"] += tool_delta.function.name
                if tool_delta.function and tool_delta.function.arguments:
                    slot["arguments"] += tool_delta.function.arguments

        parsed_calls: list[ProviderToolCall] = []
        for slot in calls.values():
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {"_invalid_json": slot["arguments"]}
            parsed_calls.append(
                ProviderToolCall(id=slot["id"], name=slot["name"], arguments=arguments)
            )
        return ProviderResponse(
            content="".join(content_parts), tool_calls=parsed_calls, usage=usage
        )

    async def close(self) -> None:
        await self.client.close()
