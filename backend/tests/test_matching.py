from __future__ import annotations

"""Matching engine unit tests — synthetic data, no DB."""

from app.services.matching import (
    cosine_similarity,
    embed_text,
    jaccard_overlap,
    match_score,
    tokenize,
)


def test_tokenize_basic() -> None:
    assert "python" in tokenize("Need a Python FastAPI expert")


def test_embed_deterministic() -> None:
    a = embed_text("React TypeScript dashboard")
    b = embed_text("React TypeScript dashboard")
    assert a == b
    assert len(a) == 384
    # unit-ish norm
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_similar_profiles_score_higher() -> None:
    portfolio = "Senior Python FastAPI engineer. PostgreSQL, Docker, React."
    good = "Looking for a FastAPI developer with Python and PostgreSQL experience."
    bad = "Need a logo designer for a bakery brand identity package."
    assert match_score(portfolio, good) > match_score(portfolio, bad)
    # Keyword overlap should clearly separate related vs unrelated leads.
    assert jaccard_overlap(portfolio, good) > jaccard_overlap(portfolio, bad)


def test_cosine_identical() -> None:
    v = embed_text("hello world")
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_empty() -> None:
    assert cosine_similarity([], [1.0]) == 0.0
