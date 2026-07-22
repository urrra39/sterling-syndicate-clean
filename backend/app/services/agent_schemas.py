from __future__ import annotations

"""Pydantic schemas for agent structured outputs (anti-CoT JSON)."""

from typing import Optional

from pydantic import BaseModel, Field


class ScoutScore(BaseModel):
    match_score: float = Field(..., ge=0.0, le=1.0)
    category: Optional[str] = None
    should_pursue: bool = True
    one_line_fit: str = Field(..., max_length=240)


class NegotiationDrafts(BaseModel):
    hold_firm: str = Field(..., max_length=1200)
    smaller_scope: str = Field(..., max_length=1200)
    clarifying_questions: str = Field(..., max_length=1200)
    # Scope Creep Defense (Sonnet 5)
    scope_creep_detected: bool = False
    out_of_scope_summary: str = Field(default="", max_length=500)
    budget_extension_draft: str = Field(
        default="",
        max_length=1500,
        description="Polite decline of free extras + proposed budget extension",
    )
    proposed_extension_amount: Optional[float] = Field(default=None, ge=0)


class ReflectionUpdate(BaseModel):
    lesson: str = Field(..., max_length=500)
    instruction_delta: str = Field(..., max_length=800)
