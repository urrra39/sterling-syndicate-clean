"""Regression tests for the dual-provider LLM router availability logic.

The analytical execution path (`complete_text` / `complete_json` with
`TaskKind.ANALYTICAL`) strictly calls Anthropic. `provider_available` must
therefore only report analytical availability when an Anthropic key is present
— an OpenAI key alone cannot service analytical work, and reporting it as
available would let callers attempt a call that raises instead of taking the
deterministic fallback path.
"""

from __future__ import annotations

import pytest

from app.services.llm_router import TaskKind, provider_available


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch: pytest.MonkeyPatch):
    """Neutralize any ambient keys/env so each test controls its own state."""
    monkeypatch.setattr("app.services.llm_router.settings.anthropic_api_key", None)
    monkeypatch.setattr("app.services.llm_router.settings.openai_api_key", None)
    monkeypatch.setattr("app.services.llm_router.settings.llm_api_key", None)


def _set(monkeypatch, *, anthropic=None, openai=None):
    monkeypatch.setattr(
        "app.services.llm_router.settings.anthropic_api_key", anthropic
    )
    monkeypatch.setattr("app.services.llm_router.settings.openai_api_key", openai)
    monkeypatch.setattr("app.services.llm_router.settings.llm_api_key", openai)


def test_analytical_requires_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI key alone must NOT satisfy the analytical provider check."""
    _set(monkeypatch, anthropic=None, openai="sk-openai-only")
    assert provider_available(TaskKind.ANALYTICAL) is False


def test_analytical_available_with_anthropic_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(monkeypatch, anthropic="sk-ant-123", openai=None)
    assert provider_available(TaskKind.ANALYTICAL) is True


def test_analytical_available_with_both_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(monkeypatch, anthropic="sk-ant-123", openai="sk-openai")
    assert provider_available(TaskKind.ANALYTICAL) is True


def test_analytical_unavailable_with_no_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(monkeypatch, anthropic=None, openai=None)
    assert provider_available(TaskKind.ANALYTICAL) is False


def test_creative_requires_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Creative path uses OpenAI; an Anthropic key alone is insufficient."""
    _set(monkeypatch, anthropic="sk-ant-123", openai=None)
    assert provider_available(TaskKind.CREATIVE) is False


def test_creative_available_with_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(monkeypatch, anthropic=None, openai="sk-openai")
    assert provider_available(TaskKind.CREATIVE) is True
