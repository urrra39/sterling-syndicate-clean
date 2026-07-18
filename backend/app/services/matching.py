from __future__ import annotations

"""Deterministic hashing embedder + cosine similarity + skill overlap.

No torch / sentence-transformers required (keeps local + CI lean). Quality comes
from (1) unigram+bigram hashing features and (2) an explicit token-overlap
boost so shared skills dominate noise. Optional neural backends can still be
swapped in later via EMBEDDING_MODEL without changing call sites.
"""

import hashlib
import math
import re
from typing import List, Sequence, Set

EMBEDDING_DIM = 384
_TOKEN_RE = re.compile(r"[a-z0-9+#.]{2,}", re.I)

# Ultra-common words that add noise to overlap scoring (keep skill-ish tokens).
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "you",
        "your",
        "our",
        "are",
        "is",
        "to",
        "of",
        "in",
        "on",
        "a",
        "an",
        "we",
        "be",
        "or",
        "as",
        "at",
        "by",
        "from",
        "this",
        "that",
        "need",
        "looking",
        "experience",
        "developer",
        "engineer",
        "senior",
        "junior",
        "project",
        "work",
        "job",
        "role",
        "team",
        "please",
        "will",
        "can",
        "have",
        "has",
        "etc",
    }
)


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def _features(tokens: Sequence[str]) -> List[str]:
    """Unigrams + adjacent bigrams for denser hashing features."""
    feats = list(tokens)
    for a, b in zip(tokens, tokens[1:]):
        feats.append(f"{a}_{b}")
    return feats


def embed_text(text: str, dim: int = EMBEDDING_DIM) -> List[float]:
    """Hashing-trick embedding — stable, offline, no model download."""
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    for feat in _features(tokens):
        h = hashlib.sha256(feat.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        # Bigrams weigh slightly more — they encode skill phrases (fastapi_python).
        weight = 1.25 if "_" in feat else 1.0
        vec[idx] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _content_tokens(text: str) -> Set[str]:
    return {t for t in tokenize(text) if t not in _STOP and len(t) > 2}


def jaccard_overlap(portfolio_text: str, lead_text: str) -> float:
    """Token Jaccard on non-stopwords — explicit skill/keyword overlap."""
    a = _content_tokens(portfolio_text)
    b = _content_tokens(lead_text)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def match_score(portfolio_text: str, lead_text: str) -> float:
    """Blend hashing cosine with keyword Jaccard; clamp to [0, 1]."""
    cosine = cosine_similarity(embed_text(portfolio_text), embed_text(lead_text))
    cosine = max(0.0, cosine)
    overlap = jaccard_overlap(portfolio_text, lead_text)
    # Overlap gets a strong voice so shared skills beat random hash collisions.
    score = (0.55 * cosine) + (0.45 * overlap)
    return round(min(1.0, max(0.0, score)), 4)
