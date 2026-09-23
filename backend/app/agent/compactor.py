from __future__ import annotations

import json
from typing import Any

from app.agent.context_builder import estimate_tokens
from app.agent.messages import clear_old_tool_results, sanitize_messages
from app.core.config import Settings
from app.prompts.agent import CONTEXT_COMPACT_SYSTEM_PROMPT, context_compact_prompt

SUMMARY_PREFIX = "[较早对话摘要]"


class ContextCompactor:
    """Claude Code style two-tier context compaction.

    Tier 1 is deterministic (clear old tool results, then drop oldest turns).
    Tier 2 calls the model to summarize the remaining older turns.
    """

    def __init__(self, settings: Settings, provider: Any) -> None:
        self.settings = settings
        self.provider = provider

    @staticmethod
    def _partition(
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        prompt_systems: list[dict[str, Any]] = []
        summary_systems: list[dict[str, Any]] = []
        convo: list[dict[str, Any]] = []
        for item in messages:
            if item.get("role") != "system":
                convo.append(item)
            elif str(item.get("content") or "").startswith(SUMMARY_PREFIX):
                summary_systems.append(item)
            else:
                prompt_systems.append(item)
        return prompt_systems + summary_systems, convo

    @staticmethod
    def _turns(convo: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        turns: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for item in convo:
            if item.get("role") == "user" and current:
                turns.append(current)
                current = []
            current.append(item)
        if current:
            turns.append(current)
        return turns

    @staticmethod
    def _flatten(turns: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return [item for turn in turns for item in turn]

    def _recent_split(
        self, systems: list[dict[str, Any]], convo: list[dict[str, Any]], keep: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        turns = self._turns(convo)
        older_turns = turns[:-keep] if len(turns) > keep else []
        recent_turns = turns[-keep:] if turns else []
        older = [*systems, *self._flatten(older_turns)]
        recent = self._flatten(recent_turns)
        return older, recent

    async def compact(
        self, messages: list[dict[str, Any]], *, keep_recent_turns: int | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        budget = self.settings.effective_input_budget
        trim_threshold = int(budget * self.settings.context_trim_threshold)
        summary_threshold = int(budget * self.settings.context_summary_threshold)
        keep = keep_recent_turns or self.settings.context_keep_recent_turns
        omissions: list[dict[str, Any]] = []
        current = [dict(item) for item in messages]
        if estimate_tokens(str(current)) < trim_threshold:
            return current, omissions, None

        systems, convo = self._partition(current)
        older, recent = self._recent_split(systems, convo, keep)

        older, cleared = clear_old_tool_results(
            older, self.settings.context_keep_recent_tool_results
        )
        if cleared:
            omissions.append(
                {"layer": "messages", "reason": "0.6: cleared old tool result contents"}
            )
        current = [*older, *recent]

        if estimate_tokens(str(current)) < summary_threshold:
            return sanitize_messages(current), omissions, None

        systems, convo = self._partition(current)
        older, recent = self._recent_split(systems, convo, keep)
        older_convo = [item for item in older if item.get("role") != "system"]
        if not older_convo:
            # Recent turns alone exceed the threshold: drop all but the latest.
            turns = self._turns(
                [item for item in current if item.get("role") != "system"]
            )
            if len(turns) > 1:
                latest = self._flatten(turns[-1:])
                compacted = [*systems, *latest]
                omissions.append({"layer": "messages", "reason": "0.75: dropped old turns"})
                return sanitize_messages(compacted), omissions, None
            return sanitize_messages(current), omissions, None
        previous_summary = " ".join(
            str(item.get("content") or "")
            for item in systems
            if str(item.get("content") or "").startswith(SUMMARY_PREFIX)
        )
        try:
            response = await self.provider.invoke(
                [
                    {"role": "system", "content": CONTEXT_COMPACT_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": context_compact_prompt(
                            previous_summary,
                            json.dumps(older_convo, ensure_ascii=False, default=str),
                        ),
                    },
                ],
                [],
            )
        except Exception:
            omissions.append({"layer": "messages", "reason": "0.75: summary failed, kept as is"})
            return sanitize_messages(current), omissions, None

        prompt_systems = [
            item
            for item in systems
            if not str(item.get("content") or "").startswith(SUMMARY_PREFIX)
        ]
        summary_message = {
            "role": "system",
            "content": f"{SUMMARY_PREFIX}\n{response.content}",
        }
        compacted = [*prompt_systems, summary_message, *recent]
        if estimate_tokens(str(compacted)) >= summary_threshold:
            turns = self._turns(recent)
            if len(turns) > keep:
                compacted = [*prompt_systems, summary_message, *self._flatten(turns[-keep:])]
                omissions.append(
                    {"layer": "messages", "reason": "0.75: trimmed turns after summary"}
                )
        omissions.append({"layer": "messages", "reason": "0.75: older turns summarized"})
        return sanitize_messages(compacted), omissions, response.content
