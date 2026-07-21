from __future__ import annotations

"""Profit Guard — hard cap API spend so execution never eats the margin.

Not ASGI middleware: enforcement lives on every elite-model call for a contract.
Formula: Max_API_Budget = Agreed_Price * 0.10 (hard 10% of project revenue).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from fastapi import HTTPException, status

from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Contract
from app.services.notify import notify_budget_pause, notify_budget_warning, notify_profit_guard_triggered

# USD per 1M tokens — approximate public list prices (ponytail: update when rates change)
MODEL_RATES_PER_MTOK: dict[str, Tuple[float, float]] = {
    # (input_$/MTok, output_$/MTok) — approximate public list prices
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-opus-4-20250514": (15.0, 75.0),
    # Legacy / override aliases still recognized for cost estimates
    "gpt-5.6": (5.0, 20.0),
    "gpt-5.5": (2.5, 10.0),
    "gpt-5.5-extra": (5.0, 20.0),
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "llama-3": (0.2, 0.2),
}

DEFAULT_RATES = (3.0, 15.0)

# Master spec: hard-cap API spend at exactly 10% of project revenue
MEDIUM_RATIO = 0.10
HIGH_RATIO = 0.10
EMERGENCY_RATIO = 0.05  # QA / human +5% of agreed price
WARN_FRACTION = 0.90
FALLBACK_FRACTION = 0.85  # switch to Tier-2 before hard stop


class EffortLevel(str, Enum):
    MEDIUM = "medium"
    HIGH = "high"


class BudgetState(str, Enum):
    OK = "ok"
    WARN = "warn"
    FALLBACK = "fallback"
    EXHAUSTED = "exhausted"
    PAUSED = "paused"


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def cost_usd(self) -> float:
        return estimate_cost(self.model, self.input_tokens, self.output_tokens)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    key = model.lower()
    rates = MODEL_RATES_PER_MTOK.get(key)
    if rates is None:
        # No exact match: pick the LONGEST rate key that is a prefix of the model.
        # Order-independent — never substring-match (which under-charged e.g.
        # 'gpt-5.5-extra' at the cheaper 'gpt-5.5' rate).
        best = ""
        for name in MODEL_RATES_PER_MTOK:
            if key.startswith(name) and len(name) > len(best):
                best = name
        rates = MODEL_RATES_PER_MTOK[best] if best else DEFAULT_RATES
    return (input_tokens / 1_000_000.0) * rates[0] + (output_tokens / 1_000_000.0) * rates[1]


def classify_effort(scope: str, agreed_price: float) -> EffortLevel:
    """HIGH for complex / high-paying jobs; MEDIUM otherwise."""
    t = (scope or "").lower()
    complex_markers = (
        "architecture",
        "microservice",
        "distributed",
        "kubernetes",
        "migration",
        "enterprise",
        "realtime",
        "machine learning",
        "security",
    )
    if agreed_price >= 3000 or any(m in t for m in complex_markers):
        return EffortLevel.HIGH
    return EffortLevel.MEDIUM


def budget_ratio(effort: EffortLevel) -> float:
    return HIGH_RATIO if effort == EffortLevel.HIGH else MEDIUM_RATIO


def compute_max_budget(agreed_price: float, effort: EffortLevel, extensions: int = 0) -> float:
    base = agreed_price * budget_ratio(effort)
    return round(base + agreed_price * EMERGENCY_RATIO * max(0, extensions), 4)


def init_budget(contract: Contract, scope: Optional[str] = None) -> Contract:
    """Call when payment is verified (or first execution)."""
    effort = classify_effort(scope or contract.agreed_scope, contract.agreed_price)
    contract.effort_level = effort.value
    contract.max_api_budget = compute_max_budget(
        contract.agreed_price, effort, contract.emergency_extensions or 0
    )
    if contract.cumulative_api_cost is None:
        contract.cumulative_api_cost = 0.0
    return contract


def remaining_budget(contract: Contract) -> float:
    return max(0.0, float(contract.max_api_budget) - float(contract.cumulative_api_cost))


def usage_fraction(contract: Contract) -> float:
    if contract.max_api_budget <= 0:
        return 1.0
    return float(contract.cumulative_api_cost) / float(contract.max_api_budget)


def budget_state(contract: Contract) -> BudgetState:
    if contract.status == "paused_for_budget_extension":
        return BudgetState.PAUSED
    frac = usage_fraction(contract)
    if frac >= 1.0 or remaining_budget(contract) <= 0:
        return BudgetState.EXHAUSTED
    # WARN (>=90%) is the more-severe threshold and MUST be checked before the
    # lower FALLBACK threshold (>=85%); otherwise the FALLBACK branch swallows
    # every high fraction and BudgetState.WARN becomes unreachable dead code.
    if frac >= WARN_FRACTION:
        return BudgetState.WARN
    if frac >= FALLBACK_FRACTION:
        return BudgetState.FALLBACK
    return BudgetState.OK


def elite_model_for(effort: EffortLevel) -> str:
    from app.core.config import settings

    if effort == EffortLevel.HIGH:
        # Prefer configured elite OpenAI; Opus available via ANTHROPIC_OPUS_MODEL for Anthropic path
        return settings.openai_execution_model or "gpt-4o"
    return settings.openai_execution_model_medium or settings.openai_writer_model or "gpt-4o-mini"


def tier2_model() -> str:
    from app.core.config import settings

    return (
        settings.anthropic_tier2_model
        or settings.anthropic_scout_model
        or "claude-sonnet-4-20250514"
    )


def select_model(contract: Contract) -> str:
    """Elite while budget healthy; Tier-2 near limit; none when exhausted/paused."""
    state = budget_state(contract)
    if state in {BudgetState.EXHAUSTED, BudgetState.PAUSED}:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "PROFIT GUARD: API budget depleted or paused. "
                "Authorize a budget extension or review the draft manually."
            ),
        )
    effort = EffortLevel(contract.effort_level or "medium")
    # Near the cap (FALLBACK >=85% or WARN >=90%) drop to the cheaper Tier-2
    # model to protect margin before the hard stop.
    if state in {BudgetState.FALLBACK, BudgetState.WARN}:
        return tier2_model()
    return elite_model_for(effort)


class ProfitGuard:
    """Call-path middleware: charge tokens, warn at 90%, pause at 100%."""

    def __init__(self, contract: Contract, lead: Lead):
        self.contract = contract
        self.lead = lead

    def assert_can_run(self) -> str:
        """Return model id or raise if paused/exhausted."""
        if not self.contract.is_payment_verified:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Execution requires is_payment_verified=True",
            )
        if self.contract.max_api_budget <= 0:
            init_budget(self.contract)
        return select_model(self.contract)

    def charge(self, usage: TokenUsage) -> BudgetState:
        """Add cost; fire webhooks; pause if over budget. Returns new state."""
        cost = usage.cost_usd
        # Refuse charge that would wildly overshoot if already exhausted
        if budget_state(self.contract) in {BudgetState.EXHAUSTED, BudgetState.PAUSED}:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="PROFIT GUARD: refusing further elite API spend",
            )

        projected = float(self.contract.cumulative_api_cost) + cost
        # Hard stop: do not apply spend past 100% — circuit breaker. Cap is enforced
        # on the ledger (cumulative never exceeds max); the real over-spend is
        # prevented upstream by the worst-case pre-flight in _complete_metered.
        if projected > float(self.contract.max_api_budget) + 1e-9:
            self._pause(
                completeness=self.contract.completeness_pct or 0.0,
                reason="projected_over_budget",
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"PROFIT GUARD CIRCUIT BREAKER: call would cost ${cost:.4f} "
                    f"but only ${remaining_budget(self.contract):.4f} remains. "
                    "Draft saved; execution paused."
                ),
            )

        self.contract.cumulative_api_cost = round(projected, 6)
        state = budget_state(self.contract)

        if state in {BudgetState.WARN, BudgetState.FALLBACK} and not self.contract.budget_warning_sent:
            self.contract.budget_warning_sent = True
            notify_budget_warning(
                project_name=self.lead.title or "Project",
                lead_id=str(self.lead.id),
                spent=self.contract.cumulative_api_cost,
                budget=self.contract.max_api_budget,
                pct=usage_fraction(self.contract) * 100,
            )

        if state == BudgetState.EXHAUSTED:
            self._pause(
                completeness=self.contract.completeness_pct or 0.0,
                reason="budget_exhausted",
            )
        return budget_state(self.contract)

    def _pause(self, *, completeness: float, reason: str) -> None:
        self.contract.status = "paused_for_budget_extension"
        self.lead.pipeline_status = PipelineStatus.PAUSED_FOR_BUDGET_EXTENSION.value
        self.contract.completeness_pct = completeness
        name = self.lead.title or self.contract.client_display_name or "Project"
        notify_profit_guard_triggered(
            project_name=name,
            lead_id=str(self.lead.id),
            spent=float(self.contract.cumulative_api_cost),
            budget=float(self.contract.max_api_budget),
        )
        notify_budget_pause(
            project_name=name,
            lead_id=str(self.lead.id),
            completeness_pct=completeness,
            spent=float(self.contract.cumulative_api_cost),
            budget=float(self.contract.max_api_budget),
        )

    def save_draft(self, draft: str, completeness: float) -> None:
        self.contract.execution_draft = draft
        self.contract.completeness_pct = max(0.0, min(100.0, completeness))

    def authorize_extension(self, extra_ratio: float = EMERGENCY_RATIO) -> Contract:
        """Human or QA +5% (default). Unpauses execution."""
        self.contract.emergency_extensions = int(self.contract.emergency_extensions or 0) + 1
        bump = self.contract.agreed_price * extra_ratio
        self.contract.max_api_budget = round(float(self.contract.max_api_budget) + bump, 4)
        self.contract.budget_warning_sent = False
        if self.contract.status == "paused_for_budget_extension":
            self.contract.status = "active"
        if self.lead.pipeline_status == PipelineStatus.PAUSED_FOR_BUDGET_EXTENSION.value:
            self.lead.pipeline_status = PipelineStatus.IN_PROGRESS.value
        return self.contract


def would_exceed(contract: Contract, input_tokens: int, output_tokens: int, model: str) -> bool:
    """Pure check for tests — True if charging this usage would breach the cap."""
    cost = estimate_cost(model, input_tokens, output_tokens)
    return float(contract.cumulative_api_cost) + cost > float(contract.max_api_budget) + 1e-9
