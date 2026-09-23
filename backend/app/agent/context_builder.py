from __future__ import annotations

import math
import re
from dataclasses import asdict
from typing import Any

from app.agent.types import (
    AgentState,
    AttachmentPayload,
    AttachmentWindow,
    ContextManifest,
    ContextPacket,
    QueryEnvelope,
)
from app.core.config import Settings
from app.prompts.agent import (
    ROOT_AGENT_SYSTEM_PROMPT,
    attachment_block,
    attachment_window_prompt,
    oversized_query_window_prompt,
    runtime_context_prompt,
)


def estimate_tokens(value: str) -> int:
    """Conservative dependency-free estimate for mixed Chinese/English text."""
    cjk = len(re.findall(r"[\u3400-\u9fff]", value))
    other = max(0, len(value) - cjk)
    return max(1, cjk + math.ceil(other / 3.2))


def _page_bounds(payload: AttachmentPayload, start: int, end: int) -> tuple[int | None, int | None]:
    pages = [
        entry
        for entry in payload.page_ranges
        if int(entry.get("char_end") or 0) > start and int(entry.get("char_start") or 0) < end
    ]
    starts = [int(item["page_start"]) for item in pages if item.get("page_start") is not None]
    ends = [int(item["page_end"]) for item in pages if item.get("page_end") is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


def split_attachment(payload: AttachmentPayload, max_text_tokens: int) -> list[AttachmentWindow]:
    """Split a document without gaps. Paragraph boundaries are preferred but never required."""
    if max_text_tokens < 256:
        raise ValueError("attachment window budget is too small")
    text = payload.text
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        low = start + 1
        high = len(text)
        hard_end = low
        while low <= high:
            middle = (low + high) // 2
            if estimate_tokens(text[start:middle]) <= max_text_tokens:
                hard_end = middle
                low = middle + 1
            else:
                high = middle - 1
        end = hard_end
        if hard_end < len(text):
            search_start = start + max(1, (hard_end - start) // 2)
            candidates = [
                text.rfind("\n\n", search_start, hard_end),
                text.rfind("\n", search_start, hard_end),
                text.rfind("。", search_start, hard_end),
            ]
            boundary = max(candidates)
            if boundary > start:
                end = boundary + (1 if text[boundary] != "\n" else 0)
        if end <= start:
            end = hard_end
        spans.append((start, end))
        start = end
    total = len(spans)
    windows: list[AttachmentWindow] = []
    for index, (start, end) in enumerate(spans, start=1):
        page_start, page_end = _page_bounds(payload, start, end)
        windows.append(
            AttachmentWindow(
                document_id=payload.document_id,
                document_version_id=payload.document_version_id,
                name=payload.name,
                window_index=index,
                window_count=total,
                char_start=start,
                char_end=end,
                page_start=page_start,
                page_end=page_end,
                text=text[start:end],
            )
        )
    return windows


class ContextBuilder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _base_layers(
        self,
        envelope: QueryEnvelope,
        history: list[dict[str, Any]],
        summary: dict[str, Any] | None,
        state: AgentState,
        notebook_index: str,
        evidence: list[dict[str, Any]],
        skill_catalog: list[dict[str, Any]],
        tool_catalog: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        layers: dict[str, int] = {}
        system = ROOT_AGENT_SYSTEM_PROMPT
        layers["system_prompt"] = estimate_tokens(system)
        recent: list[dict[str, Any]] = []
        for item in history:
            entry: dict[str, Any] = {
                "role": item.get("role", "user"),
                "content": item.get("content", ""),
            }
            if item.get("tool_calls"):
                entry["tool_calls"] = item["tool_calls"]
            if item.get("tool_call_id"):
                entry["tool_call_id"] = item["tool_call_id"]
            recent.append(entry)
        history_text = str(recent)
        layers["recent_turns"] = estimate_tokens(history_text)
        layers["conversation_summary"] = estimate_tokens(str(summary or {}))
        layers["agent_state"] = estimate_tokens(str(asdict(state)))
        layers["notebook_index"] = estimate_tokens(notebook_index)
        layers["evidence"] = estimate_tokens(str(evidence))
        layers["skill_catalog"] = estimate_tokens(str(skill_catalog))
        layers["tool_catalog"] = estimate_tokens(str(tool_catalog))
        context_message = {
            "role": "system",
            "content": runtime_context_prompt(
                summary,
                asdict(state),
                notebook_index,
                evidence,
                skill_catalog,
                tool_catalog,
            ),
        }
        return [{"role": "system", "content": system}, context_message, *recent], layers

    def build_packets(
        self,
        envelope: QueryEnvelope,
        *,
        history: list[dict[str, Any]],
        summary: dict[str, Any] | None,
        state: AgentState,
        notebook_index: str = "",
        evidence: list[dict[str, Any]] | None = None,
        skill_catalog: list[dict[str, Any]] | None = None,
        tool_catalog: list[dict[str, Any]] | None = None,
    ) -> list[ContextPacket]:
        evidence = evidence or []
        skill_catalog = skill_catalog or []
        tool_catalog = tool_catalog or []
        budget = self.settings.effective_input_budget
        packing_budget = int(budget * 0.95)
        compression_omissions: list[dict[str, Any]] = []
        summary_update: dict[str, Any] | None = None
        base, layers = self._base_layers(
            envelope,
            history,
            summary,
            state,
            notebook_index,
            evidence,
            skill_catalog,
            tool_catalog,
        )
        query_tokens = estimate_tokens(envelope.query)
        base_tokens = sum(layers.values())
        layers["current_query"] = query_tokens
        attachment_tokens = sum(estimate_tokens(item.text) for item in envelope.attachments)
        if base_tokens + query_tokens + attachment_tokens <= packing_budget:
            content = envelope.query + "".join(
                attachment_block(item) for item in envelope.attachments
            )
            manifest = ContextManifest(
                model_context_window=self.settings.model_context_window,
                effective_input_budget=budget,
                estimated_tokens=base_tokens + query_tokens + attachment_tokens,
                layers=layers | {"current_attachments": attachment_tokens},
                attachments=[
                    {
                        "document_id": item.document_id,
                        "document_version_id": item.document_version_id,
                        "name": item.name,
                        "char_start": 0,
                        "char_end": len(item.text),
                        "full_text": True,
                    }
                    for item in envelope.attachments
                ],
                omissions=compression_omissions,
                mode="single",
            )
            return [
                ContextPacket(
                    messages=[*base, {"role": "user", "content": content}],
                    manifest=manifest,
                    summary_update=summary_update,
                )
            ]

        if not envelope.attachments:
            per_window_budget = packing_budget - base_tokens - 512
            if per_window_budget < 256:
                raise ValueError("fixed context layers leave no room for query processing")
            query_payload = AttachmentPayload(
                document_id="current-query",
                document_version_id="current-query",
                name="当前超长Query",
                media_type="text/plain",
                instruction="完整处理原始Query的每个窗口",
                text=envelope.query,
            )
            query_windows = split_attachment(query_payload, per_window_budget)
            packets: list[ContextPacket] = []
            for window in query_windows:
                instruction = oversized_query_window_prompt(window)
                window_tokens = estimate_tokens(window.text)
                manifest = ContextManifest(
                    model_context_window=self.settings.model_context_window,
                    effective_input_budget=budget,
                    estimated_tokens=base_tokens + window_tokens,
                    layers=layers | {"current_query_window": window_tokens},
                    attachments=[window.manifest_entry()],
                    omissions=compression_omissions,
                    mode="windowed",
                )
                packets.append(
                    ContextPacket(
                        messages=[*base, {"role": "user", "content": instruction}],
                        manifest=manifest,
                        attachment_window=window,
                        summary_update=summary_update,
                    )
                )
            return packets

        per_window_budget = packing_budget - base_tokens - query_tokens - 512
        if per_window_budget < 256:
            raise ValueError("fixed context layers leave no room for attachment processing")
        all_windows: list[AttachmentWindow] = []
        for attachment in envelope.attachments:
            all_windows.extend(split_attachment(attachment, per_window_budget))
        packets: list[ContextPacket] = []
        for window in all_windows:
            instruction = attachment_window_prompt(envelope.query, window)
            window_tokens = estimate_tokens(window.text)
            manifest = ContextManifest(
                model_context_window=self.settings.model_context_window,
                effective_input_budget=budget,
                estimated_tokens=base_tokens + query_tokens + window_tokens,
                layers=layers
                | {"current_query": query_tokens, "current_attachment_window": window_tokens},
                attachments=[window.manifest_entry()],
                omissions=compression_omissions,
                mode="windowed",
            )
            packets.append(
                ContextPacket(
                    messages=[*base, {"role": "user", "content": instruction}],
                    manifest=manifest,
                    attachment_window=window,
                    summary_update=summary_update,
                )
            )
        return packets
