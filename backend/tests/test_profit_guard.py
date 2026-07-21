"""Profit Guard circuit breaker — must stop before exceeding Max_API_Budget."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.profit_guard import (
    BudgetState,
    EffortLevel,
    ProfitGuard,
    TokenUsage,
    budget_ratio,
    budget_state,
    classify_effort,
    compute_max_budget,
    estimate_cost,
    init_budget,
    select_model,
    usage_fraction,
    would_exceed,
)


def _contract(**kwargs):
    defaults = dict(
        agreed_price=1000.0,
        agreed_scope="simple bug fix script",
        is_payment_verified=True,
        effort_level="medium",
        max_api_budget=0.0,
        cumulative_api_cost=0.0,
        budget_warning_sent=False,
        emergency_extensions=0,
        status="active",
        completeness_pct=0.0,
        execution_draft=None,
        client_display_name="Acme",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _lead(**kwargs):
    defaults = dict(id=uuid4(), title="Acme API", pipeline_status="in_progress")
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_medium_budget_is_10_percent() -> None:
    assert budget_ratio(EffortLevel.MEDIUM) == 0.10
    assert compute_max_budget(1000.0, EffortLevel.MEDIUM) == 100.0


def test_high_budget_is_10_percent() -> None:
    assert budget_ratio(EffortLevel.HIGH) == 0.10
    assert compute_max_budget(1000.0, EffortLevel.HIGH) == 100.0


def test_classify_high_for_expensive_or_complex() -> None:
    assert classify_effort("landing page", 500) == EffortLevel.MEDIUM
    assert classify_effort("microservice architecture", 800) == EffortLevel.HIGH
    assert classify_effort("bug fix", 5000) == EffortLevel.HIGH


def test_estimate_cost_positive() -> None:
    cost = estimate_cost("gpt-5.6", 100_000, 50_000)
    assert cost > 0
    # 100k in * $5/M + 50k out * $20/M = 0.5 + 1.0 = 1.5
    assert abs(cost - 1.5) < 1e-9


def test_estimate_cost_exact_match_not_substring() -> None:
    # Regression: 'gpt-5.5' is a substring of 'gpt-5.5-extra'. The old loop matched
    # the cheaper 'gpt-5.5' (2.5/10.0) rate and under-charged by 2x, silently
    # doubling the effective spend cap. Must resolve to the exact 5.0/20.0 rate.
    cost = estimate_cost("gpt-5.5-extra", 1_000_000, 1_000_000)
    assert abs(cost - 25.0) < 1e-9  # 5.0 + 20.0, not the buggy 12.5
    # Unknown variants still resolve via longest-prefix to their base family.
    assert abs(estimate_cost("gpt-5.6-turbo", 1_000_000, 0) - 5.0) < 1e-9


def test_circuit_breaker_refuses_overshoot(monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(
        "app.services.profit_guard.notify_profit_guard_triggered",
        lambda **kw: alerts.append("triggered"),
    )
    monkeypatch.setattr(
        "app.services.profit_guard.notify_budget_pause",
        lambda **kw: alerts.append("pause"),
    )
    monkeypatch.setattr(
        "app.services.profit_guard.notify_budget_warning",
        lambda **kw: alerts.append("warn"),
    )

    c = _contract(max_api_budget=1.0, cumulative_api_cost=0.95)
    lead = _lead()
    guard = ProfitGuard(c, lead)  # type: ignore[arg-type]

    # This usage costs ~1.5 USD — must NOT be applied past the $1 cap
    usage = TokenUsage(input_tokens=100_000, output_tokens=50_000, model="gpt-5.6")
    assert would_exceed(c, usage.input_tokens, usage.output_tokens, usage.model)

    with pytest.raises(HTTPException) as exc:
        guard.charge(usage)
    assert exc.value.status_code == 402
    # Cumulative must stay under/at budget — never go negative-margin
    assert c.cumulative_api_cost <= c.max_api_budget + 1e-9
    assert c.cumulative_api_cost == 0.95  # charge rejected, not applied
    assert c.status == "paused_for_budget_extension"
    assert "triggered" in alerts


def test_charge_within_budget_accumulates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.profit_guard.notify_budget_warning", lambda **kw: None)
    monkeypatch.setattr("app.services.profit_guard.notify_profit_guard_triggered", lambda **kw: None)
    monkeypatch.setattr("app.services.profit_guard.notify_budget_pause", lambda **kw: None)

    c = _contract(max_api_budget=10.0, cumulative_api_cost=0.0)
    guard = ProfitGuard(c, _lead())  # type: ignore[arg-type]
    # tiny usage
    usage = TokenUsage(input_tokens=1000, output_tokens=500, model="claude-sonnet-5")
    state = guard.charge(usage)
    assert state == BudgetState.OK
    assert c.cumulative_api_cost > 0
    assert c.cumulative_api_cost < 10.0


def test_warning_at_90_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    warns: list[dict] = []
    monkeypatch.setattr(
        "app.services.profit_guard.notify_budget_warning",
        lambda **kw: warns.append(kw),
    )
    monkeypatch.setattr("app.services.profit_guard.notify_profit_guard_triggered", lambda **kw: None)
    monkeypatch.setattr("app.services.profit_guard.notify_budget_pause", lambda **kw: None)

    c = _contract(max_api_budget=1.0, cumulative_api_cost=0.89)
    guard = ProfitGuard(c, _lead())  # type: ignore[arg-type]
    # ~$0.015 sonnet — pushes over 90%
    usage = TokenUsage(input_tokens=2000, output_tokens=500, model="claude-sonnet-5")
    guard.charge(usage)
    assert c.budget_warning_sent is True
    assert len(warns) == 1
    assert usage_fraction(c) >= 0.90


def test_fallback_model_near_limit() -> None:
    c = _contract(max_api_budget=100.0, cumulative_api_cost=86.0, effort_level="high")
    assert budget_state(c) == BudgetState.FALLBACK
    model = select_model(c)
    assert "sonnet" in model.lower() or "llama" in model.lower() or "claude" in model.lower()


def test_warn_state_is_reachable_at_90_percent() -> None:
    """Regression: WARN (>=90%) must not be shadowed by FALLBACK (>=85%).

    Previously the FALLBACK branch was checked first, so budget_state could
    never return WARN — the >=90% band silently degraded to FALLBACK and the
    distinct warning tier was dead code.
    """
    # 85%-90% band stays FALLBACK.
    c_fallback = _contract(max_api_budget=100.0, cumulative_api_cost=87.0, effort_level="high")
    assert budget_state(c_fallback) == BudgetState.FALLBACK

    # 90%+ band (below exhaustion) is now correctly WARN.
    c_warn = _contract(max_api_budget=100.0, cumulative_api_cost=93.0, effort_level="high")
    assert budget_state(c_warn) == BudgetState.WARN

    # Near the cap we still protect margin with the cheaper Tier-2 model,
    # even in the WARN band — never bounce back up to the elite model.
    model = select_model(c_warn)
    assert "sonnet" in model.lower() or "llama" in model.lower() or "claude" in model.lower()


def test_exhausted_select_raises() -> None:
    c = _contract(max_api_budget=10.0, cumulative_api_cost=10.0)
    with pytest.raises(HTTPException) as exc:
        select_model(c)
    assert exc.value.status_code == 402


def test_init_budget_and_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.profit_guard.notify_profit_guard_triggered", lambda **kw: None)
    monkeypatch.setattr("app.services.profit_guard.notify_budget_pause", lambda **kw: None)

    c = _contract(agreed_price=1000.0, agreed_scope="simple fix", max_api_budget=0)
    init_budget(c)
    assert c.effort_level == "medium"
    assert c.max_api_budget == 100.0

    lead = _lead(pipeline_status="paused_for_budget_extension")
    c.status = "paused_for_budget_extension"
    c.cumulative_api_cost = 100.0
    guard = ProfitGuard(c, lead)  # type: ignore[arg-type]
    guard.authorize_extension(0.05)
    assert c.emergency_extensions == 1
    assert c.max_api_budget == 150.0  # 100 + 50 (5% of 1000)
    assert c.status == "active"
    assert lead.pipeline_status == "in_progress"


def test_token_heavy_loop_never_exceeds_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate many expensive generations — cumulative must stay ≤ max."""
    monkeypatch.setattr("app.services.profit_guard.notify_budget_warning", lambda **kw: None)
    monkeypatch.setattr("app.services.profit_guard.notify_profit_guard_triggered", lambda **kw: None)
    monkeypatch.setattr("app.services.profit_guard.notify_budget_pause", lambda **kw: None)

    c = _contract(max_api_budget=2.0, cumulative_api_cost=0.0)
    lead = _lead()
    guard = ProfitGuard(c, lead)  # type: ignore[arg-type]
    heavy = TokenUsage(input_tokens=50_000, output_tokens=25_000, model="gpt-5.6")
    # each call ≈ 0.75 USD
    stopped = False
    for _ in range(20):
        if would_exceed(c, heavy.input_tokens, heavy.output_tokens, heavy.model):
            with pytest.raises(HTTPException):
                guard.charge(heavy)
            stopped = True
            break
        guard.charge(heavy)
    assert stopped
    assert c.cumulative_api_cost <= c.max_api_budget + 1e-9
