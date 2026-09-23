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
