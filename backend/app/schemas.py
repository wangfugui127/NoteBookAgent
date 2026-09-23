from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import ResourceMode, RunStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class NotebookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""


class NotebookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class NotebookView(ORMModel):
    id: str
    title: str
    description: str
    created_at: datetime


class ConversationCreate(BaseModel):
    notebook_id: str
    title: str = "New conversation"


class ResourceSelectionUpdate(BaseModel):
    mode: ResourceMode


class AgentRunCreate(BaseModel):
    conversation_id: str
    query: str = Field(min_length=1)
    attachment_ids: list[str] = Field(default_factory=list)
    attachment_instructions: dict[str, str] = Field(default_factory=dict)
    approval_mode: Literal["read_only", "confirm", "auto"] | None = None


class UserSettingsView(BaseModel):
    approval_mode: Literal["read_only", "confirm", "auto"]


class UserSettingsUpdate(BaseModel):
    approval_mode: Literal["read_only", "confirm", "auto"]


class AgentRunView(ORMModel):
    id: str
    conversation_id: str
    status: RunStatus
    query: str
    error_message: str | None
    created_at: datetime


class ApprovalResolve(BaseModel):
    decision: Literal["approved", "rejected"]


class ContextManifestView(BaseModel):
    model_context_window: int
    effective_input_budget: int
    estimated_tokens: int
    layers: dict[str, int]
    attachments: list[dict[str, Any]]
    omissions: list[dict[str, Any]]


class EvalCaseInput(BaseModel):
    case_key: str = ""
    question: str = Field(min_length=1)
    expected_tools: list[str] = Field(default_factory=list)
    expected_source_titles: list[str] = Field(default_factory=list)
    required_keywords: list[str] = Field(default_factory=list)


class EvalCaseUpdate(BaseModel):
    case_key: str | None = None
    question: str | None = Field(default=None, min_length=1)
    expected_tools: list[str] | None = None
    expected_source_titles: list[str] | None = None
    required_keywords: list[str] | None = None


class EvalDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class EvalDatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class EvalImportRequest(BaseModel):
    cases: list[EvalCaseInput] = Field(default_factory=list)
    replace: bool = False


class EvalRunCreate(BaseModel):
    notebook_id: str
    allow_missing: bool = False


class EvalCaseView(ORMModel):
    id: str
    case_key: str
    question: str
    expected_tools: list[str]
    expected_source_titles: list[str]
    required_keywords: list[str]
    ordinal: int


class EvalDatasetView(ORMModel):
    id: str
    name: str
    description: str
    created_at: datetime


class EvalDatasetDetail(EvalDatasetView):
    cases: list[EvalCaseView]


class EvalRunView(ORMModel):
    id: str
    notebook_id: str
    dataset_id: str | None
    dataset_name: str
    status: str
    total_cases: int
    completed_cases: int
    passed_cases: int
    current_case_key: str | None
    metrics: dict[str, Any]
    error_message: str | None
    created_at: datetime


class EvalCaseResultView(ORMModel):
    id: str
    case_key: str
    ordinal: int
    question: str
    status: str
    expected_tools: list[str]
    actual_tools: list[str]
    expected_source_titles: list[str]
    matched_sources: list[str]
    missing_sources: list[str]
    required_keywords: list[str]
    matched_keywords: list[str]
    answer: str | None
    route_score: float | None
    retrieval_score: float | None
    citation_score: float | None
    keyword_score: float | None
    total_score: float | None
    passed: bool
    latency_ms: int | None
    agent_run_id: str | None
    error_message: str | None
    detail: dict[str, Any]
