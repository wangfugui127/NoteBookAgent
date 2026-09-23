import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid.uuid4())


LONG_TEXT = Text().with_variant(LONGTEXT, "mysql")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResourceMode(enum.StrEnum):
    summary = "summary"
    full = "full"
    off = "off"


class RunStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_mode: Mapped[str] = mapped_column(String(16), default="confirm")


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notebook(Base, TimestampMixin):
    __tablename__ = "notebooks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(120))
    active_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "document_versions.id",
            name="fk_documents_active_version",
            use_alter=True,
        ),
        nullable=True,
    )
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
    )


class DocumentVersion(Base, TimestampMixin):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    storage_path: Mapped[str] = mapped_column(String(1024))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(24), default="default")
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    graph_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    full_text: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    normalized_markdown: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    parser_name: Mapped[str] = mapped_column(String(64), default="")
    parser_version: Mapped[str] = mapped_column(String(24), default="1")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    document: Mapped[Document] = relationship(back_populates="versions", foreign_keys=[document_id])
    __table_args__ = (UniqueConstraint("document_id", "version_number"),)


class Section(Base, TimestampMixin):
    __tablename__ = "sections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(512), default="")
    ordinal: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DocumentBlock(Base, TimestampMixin):
    __tablename__ = "document_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[str | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(24), index=True)
    text: Mapped[str] = mapped_column(LONG_TEXT)
    markdown: Mapped[str] = mapped_column(LONG_TEXT)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list[float]] = mapped_column(JSON, default=list)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("document_version_id", "ordinal"),)


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[str | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(LONG_TEXT)
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_type: Mapped[str] = mapped_column(String(24), default="paragraph", index=True)
    block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    __table_args__ = (UniqueConstraint("document_version_id", "ordinal"),)


class IngestionJob(Base, TimestampMixin):
    __tablename__ = "ingestion_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")


class ConversationResourceSelection(Base, TimestampMixin):
    __tablename__ = "conversation_resource_selections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    mode: Mapped[ResourceMode] = mapped_column(Enum(ResourceMode), default=ResourceMode.summary)
    __table_args__ = (UniqueConstraint("conversation_id", "document_id"),)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(LONG_TEXT)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    provider_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ConversationSummary(Base, TimestampMixin):
    __tablename__ = "conversation_summaries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    through_message_id: Mapped[str] = mapped_column(String(36))
    summary: Mapped[dict[str, Any]] = mapped_column(JSON)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(LONG_TEXT)
    attachment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), default=RunStatus.pending, index=True
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskItem(Base, TimestampMixin):
    __tablename__ = "task_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    ordinal: Mapped[int] = mapped_column(Integer)


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    provider_call_id: Mapped[str] = mapped_column(String(255), index=True)
    tool_name: Mapped[str] = mapped_column(String(255))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON)
    arguments_hash: Mapped[str] = mapped_column(String(64))
    risk: Mapped[str] = mapped_column(String(24), default="read")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("run_id", "provider_call_id"),)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)


class Checkpoint(Base, TimestampMixin):
    __tablename__ = "checkpoints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    boundary: Mapped[str] = mapped_column(String(80))
    state: Mapped[dict[str, Any]] = mapped_column(JSON)


class Evidence(Base, TimestampMixin):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str | None] = mapped_column(ForeignKey("chunks.id"), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(LONG_TEXT)
    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    retrieval_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)


class Citation(Base, TimestampMixin):
    __tablename__ = "citations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"))
    claim_text: Mapped[str] = mapped_column(Text)


class ExternalPaperResult(Base, TimestampMixin):
    __tablename__ = "external_paper_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    provider_paper_id: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    tool_call_id: Mapped[str] = mapped_column(ForeignKey("tool_calls.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    reason: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16), default="confirm")
    tool_risk: Mapped[str] = mapped_column(String(16), default="write")
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class DocumentProfile(Base, TimestampMixin):
    __tablename__ = "document_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), unique=True, index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    abstract: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    abstract_source: Mapped[str] = mapped_column(String(16), default="missing")
    region: Mapped[str | None] = mapped_column(String(512), nullable=True)
    time_range: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    one_sentence: Mapped[str] = mapped_column(LONG_TEXT, default="")
    data_and_method: Mapped[str] = mapped_column(LONG_TEXT, default="")
    results_conclusion: Mapped[str] = mapped_column(LONG_TEXT, default="")
    contribution_limitations: Mapped[str] = mapped_column(LONG_TEXT, default="")
    profile_text: Mapped[str] = mapped_column(LONG_TEXT, default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    extractor_model: Mapped[str] = mapped_column(String(120), default="")
    extractor_version: Mapped[str] = mapped_column(String(24), default="1")


class RunTranscript(Base, TimestampMixin):
    __tablename__ = "run_transcripts"
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class EvalDataset(Base, TimestampMixin):
    __tablename__ = "eval_datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")


class EvalCase(Base, TimestampMixin):
    __tablename__ = "eval_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="CASCADE"), index=True
    )
    case_key: Mapped[str] = mapped_column(String(120))
    question: Mapped[str] = mapped_column(LONG_TEXT)
    expected_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_source_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("dataset_id", "case_key"),)


class EvalRun(Base, TimestampMixin):
    __tablename__ = "eval_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    completed_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0)
    current_case_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_case_result_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    score_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvalCaseResult(Base, TimestampMixin):
    __tablename__ = "eval_case_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    eval_run_id: Mapped[str] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True
    )
    case_key: Mapped[str] = mapped_column(String(120), default="")
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    question: Mapped[str] = mapped_column(LONG_TEXT)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    expected_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    actual_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_source_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    answer: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    route_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    keyword_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
