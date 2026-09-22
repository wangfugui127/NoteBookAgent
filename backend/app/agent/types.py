from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RiskLevel = Literal["read", "write", "destructive"]


@dataclass(slots=True)
class AttachmentPayload:
    document_id: str
    document_version_id: str
    name: str
    media_type: str
    instruction: str
    text: str
    page_ranges: list[dict[str, int | None]] = field(default_factory=list)


@dataclass(slots=True)
class QueryEnvelope:
    query: str
    attachments: list[AttachmentPayload] = field(default_factory=list)


@dataclass(slots=True)
class AttachmentWindow:
    document_id: str
    document_version_id: str
    name: str
    window_index: int
    window_count: int
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    text: str

    def manifest_entry(self) -> dict[str, Any]:
        return asdict(self) | {"text": None}


@dataclass(slots=True)
class ContextManifest:
    model_context_window: int
    effective_input_budget: int
    estimated_tokens: int = 0
    layers: dict[str, int] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    omissions: list[dict[str, Any]] = field(default_factory=list)
    mode: Literal["single", "windowed"] = "single"


@dataclass(slots=True)
class ContextPacket:
    messages: list[dict[str, Any]]
    manifest: ContextManifest
    attachment_window: AttachmentWindow | None = None
    summary_update: dict[str, Any] | None = None


@dataclass(slots=True)
class ToolSummary:
    name: str
    description: str
    risk: RiskLevel
    source: str = "native"


@dataclass(slots=True)
class ToolObservation:
    ok: bool
    tool_name: str
    content: dict[str, Any]
    error_code: str | None = None
    truncated: bool = False


@dataclass(slots=True)
class AgentState:
    run_id: str
    notebook_id: str
    user_id: str
    round_no: int = 0
    tasks: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    loaded_skills: dict[str, str] = field(default_factory=dict)
    active_tool_allowlist: list[str] | None = None
    graph_degraded: bool = False
    cancelled: bool = False
