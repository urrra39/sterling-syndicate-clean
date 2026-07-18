from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.output_sanitizer import sanitize_optional, sanitize_output


def _http_https_url(v: Optional[str]) -> Optional[str]:
    """Reject javascript:/data:/etc. — only http(s) external links."""
    if v is None:
        return None
    trimmed = v.strip()
    if not trimmed:
        return None
    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an http(s) URL with a host")
    return trimmed


class LeadCreateManual(BaseModel):
    title: str = Field(default="", max_length=500)
    raw_text: str = Field(..., min_length=20, max_length=50000)
    url: Optional[str] = Field(default=None, max_length=2048)
    category: Optional[str] = Field(default=None, max_length=120)

    @field_validator("url")
    @classmethod
    def _safe_url(cls, v: Optional[str]) -> Optional[str]:
        return _http_https_url(v)


class LeadIngestRemote(BaseModel):
    source: str = Field(..., pattern="^(remoteok|weworkremotely)$")
    limit: int = Field(default=15, ge=1, le=50)
    tags: List[str] = Field(default_factory=list, max_length=10)


class LeadStatusUpdate(BaseModel):
    pipeline_status: str = Field(
        ...,
        pattern=(
            "^(new|drafting|sent|negotiating|won|lost|"
            "rejected_tos_violation|rejected_by_sast|"
            "pending_payment_verification|in_progress|"
            "paused_for_budget_extension|paused_for_captcha|"
            "delivered|paid|archived)$"
        ),
    )


class LeadPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    title: str
    raw_text: str
    url: Optional[str] = None
    category: Optional[str] = None
    ingested_at: datetime
    match_score: Optional[float] = None
    pipeline_status: str
    tos_rejection_reason: Optional[str] = None


class ProposalCreateRequest(BaseModel):
    tone: str = Field(default="confident", pattern="^(confident|friendly|concise)$")


class ProposalPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lead_id: UUID
    draft_text: str
    status: str
    generated_by: str
    tone: Optional[str] = None
    created_at: datetime
    sent_at: Optional[datetime] = None

    @field_validator("draft_text")
    @classmethod
    def _clean_draft(cls, v: str) -> str:
        return sanitize_output(v)


class IncomingMessage(BaseModel):
    body: str = Field(..., min_length=1, max_length=20000)


class ReplySuggestion(BaseModel):
    label: str
    body: str
    generated_by: str = "ai_generated"
    scope_creep_detected: bool = False
    out_of_scope_summary: Optional[str] = None

    @field_validator("body")
    @classmethod
    def _clean_body(cls, v: str) -> str:
        return sanitize_output(v)

    @field_validator("out_of_scope_summary")
    @classmethod
    def _clean_summary(cls, v: Optional[str]) -> Optional[str]:
        return sanitize_optional(v)


class ConversationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lead_id: UUID
    direction: str
    body: str
    label: Optional[str] = None
    generated_by: str
    created_at: datetime

    @field_validator("body")
    @classmethod
    def _clean_body(cls, v: str) -> str:
        return sanitize_output(v)


class DeliverableCreate(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)
    checklist: List[str] = Field(default_factory=list, max_length=50)
    status: str = Field(default="pending", pattern="^(pending|in_progress|delivered)$")


class DeliverablePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    description: str
    status: str
    checklist: List[str]


class ContractCreate(BaseModel):
    agreed_scope: str = Field(..., min_length=1, max_length=20000)
    agreed_price: float = Field(..., gt=0, le=10_000_000)
    currency: str = Field(default="USD", max_length=8)
    deadline: Optional[date] = None
    client_display_name: Optional[str] = Field(default=None, max_length=200)
    deliverables: List[DeliverableCreate] = Field(default_factory=list, max_length=50)


class ContractPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lead_id: UUID
    agreed_scope: str
    agreed_price: float
    currency: str
    deadline: Optional[date] = None
    status: str
    is_payment_verified: bool = False
    client_display_name: Optional[str] = None
    payment_claimed_at: Optional[datetime] = None
    payment_verified_at: Optional[datetime] = None
    effort_level: str = "medium"
    max_api_budget: float = 0.0
    cumulative_api_cost: float = 0.0
    budget_warning_sent: bool = False
    execution_draft: Optional[str] = None
    qa_status: str = "pending"
    completeness_pct: float = 0.0
    emergency_extensions: int = 0
    created_at: datetime
    deliverables: List[DeliverablePublic] = []

    @field_validator("execution_draft")
    @classmethod
    def _clean_execution_draft(cls, v: Optional[str]) -> Optional[str]:
        return sanitize_optional(v)


class DeliverableStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|in_progress|delivered)$")
    checklist: Optional[List[str]] = Field(default=None, max_length=50)


class AnalyticsSummary(BaseModel):
    total_leads: int
    proposals_sent: int
    won: int
    lost: int
    win_rate: float
    avg_hours_to_mark_sent: Optional[float] = None
    revenue_by_month: List[dict]
    revenue_by_category: List[dict]
