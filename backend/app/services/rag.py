from __future__ import annotations

"""ChromaDB portfolio RAG — ingest GitHub READMEs / snippets, retrieve for proposals.

Uses the local hashing embedder (no torch). Collection is per-user.
Degrades gracefully if chromadb is not installed.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence

import httpx

from app.core.config import settings
from app.services.matching import EMBEDDING_DIM, embed_text

logger = logging.getLogger("sterling.rag")


class HashingEmbeddingFunction:
    """Chroma-compatible embedding function backed by our hashing embedder."""

    def __call__(self, input: List[str]) -> List[List[float]]:  # noqa: A003 — chroma API
        return [embed_text(t) for t in input]

    def name(self) -> str:
        return "sterling-hashing-384"

    def embed_query(self, input: List[str]) -> List[List[float]]:  # noqa: A003
        return self(input)

    def embed_documents(self, input: List[str]) -> List[List[float]]:  # noqa: A003
        return self(input)


def _client():
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    path = Path(settings.chroma_persist_dir)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _collection(user_id: str):
    client = _client()
    return client.get_or_create_collection(
        name=f"{settings.portfolio_collection}_{user_id.replace('-', '')[:16]}",
        embedding_function=HashingEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )


def upsert_documents(
    user_id: str,
    documents: Sequence[Dict[str, str]],
) -> int:
    """Upsert docs with keys: id, text, source (optional), title (optional)."""
    try:
        if not documents:
            return 0
        col = _collection(user_id)
        # De-dupe by id (last-write-wins). Chroma's upsert rejects duplicate ids
        # in a single batch with DuplicateIDError, which the except below would
        # turn into a silent full-batch drop. Colliding ids are reachable (a root
        # README chunked by two ingest paths, @property/@setter method pairs, etc.).
        by_id: Dict[str, tuple] = {}
        for doc in documents:
            text = (doc.get("text") or "").strip()
            if len(text) < 40:
                continue
            doc_id = doc.get("id") or hashlib.sha256(text.encode()).hexdigest()[:24]
            by_id[doc_id] = (
                text[:12000],
                {
                    "source": doc.get("source") or "manual",
                    "title": (doc.get("title") or "untitled")[:200],
                },
            )
        if not by_id:
            return 0
        ids = list(by_id)
        col.upsert(
            ids=ids,
            documents=[by_id[i][0] for i in ids],
            metadatas=[by_id[i][1] for i in ids],
        )
        return len(ids)
    except Exception as exc:
        logger.warning("RAG upsert skipped: %s", exc)
        return 0


def retrieve(user_id: str, query: str, *, k: int = 4) -> List[Dict[str, Any]]:
    """Return top-k portfolio chunks for RAG context."""
    try:
        col = _collection(user_id)
        if col.count() == 0:
            return []
        result = col.query(query_texts=[query[:4000]], n_results=min(k, max(1, col.count())))
        out: List[Dict[str, Any]] = []
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        for i, text in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            dist = dists[i] if i < len(dists) else None
            out.append(
                {
                    "id": ids[i] if i < len(ids) else None,
                    "text": text,
                    "source": (meta or {}).get("source"),
                    "title": (meta or {}).get("title"),
                    "distance": dist,
                }
            )
        return out
    except Exception as exc:
        logger.warning("RAG retrieve skipped: %s", exc)
        return []


def format_rag_context(chunks: List[Dict[str, Any]]) -> str:
    if not chunks:
        return "(no portfolio evidence retrieved)"
    parts = []
    for i, c in enumerate(chunks, 1):
        title = c.get("title") or "snippet"
        source = c.get("source") or "portfolio"
        parts.append(f"[{i}] {title} ({source})\n{c.get('text', '')[:1500]}")
    return "\n\n".join(parts)


def ingest_github_repos(user_id: str, username: str, *, max_repos: int = 8) -> int:
    """Pull public repo READMEs + AST-chunked source via GitHub API.

    Excludes boilerplate (lockfiles, configs, node_modules paths). No marketplace scraping.
    """
    from app.services.ast_chunking import chunk_source_file, is_boilerplate_path

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "SterlingSyndicate-RAG/0.3",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    docs: List[Dict[str, str]] = []
    with httpx.Client(timeout=45.0, headers=headers, follow_redirects=True) as client:
        repos_resp = client.get(
            f"https://api.github.com/users/{username}/repos",
            params={"sort": "updated", "per_page": max_repos},
        )
        repos_resp.raise_for_status()
        repos = repos_resp.json()
        for repo in repos:
            if not isinstance(repo, dict) or repo.get("fork"):
                continue
            name = repo.get("full_name") or repo.get("name")
            if not name:
                continue
            default_branch = repo.get("default_branch") or "main"

            # README (markdown chunked)
            readme = client.get(f"https://api.github.com/repos/{name}/readme")
            if readme.status_code == 200:
                download = readme.json().get("download_url")
                if download:
                    raw = client.get(download)
                    if raw.status_code == 200 and raw.text.strip():
                        docs.extend(
                            chunk_source_file(f"{name}/README.md", raw.text, max_chunks=6)
                        )
            else:
                desc = repo.get("description") or ""
                if desc:
                    docs.append(
                        {
                            "id": f"gh-{repo.get('id')}-desc",
                            "title": str(name),
                            "source": f"github:{name}",
                            "text": f"Repository {name}\n{desc}\nLanguage: {repo.get('language')}",
                        }
                    )

            # Tree: pull a few source files, AST-chunk, skip boilerplate
            tree_resp = client.get(
                f"https://api.github.com/repos/{name}/git/trees/{default_branch}",
                params={"recursive": "1"},
            )
            if tree_resp.status_code != 200:
                continue
            tree = tree_resp.json().get("tree") or []
            source_paths = []
            for entry in tree:
                if entry.get("type") != "blob":
                    continue
                path = entry.get("path") or ""
                if is_boilerplate_path(path):
                    continue
                if not path.lower().endswith(
                    (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".md")
                ):
                    continue
                # Prefer src/app/lib over root noise
                source_paths.append(path)
            # Cap files per repo to control token/embedding cost
            picked = []
            for path in source_paths:
                if any(seg in path.replace("\\", "/") for seg in ("src/", "app/", "lib/", "backend/", "frontend/")):
                    picked.append(path)
            if not picked:
                picked = source_paths
            for path in picked[:6]:
                file_resp = client.get(
                    f"https://raw.githubusercontent.com/{name}/{default_branch}/{path}"
                )
                if file_resp.status_code != 200 or not file_resp.text.strip():
                    continue
                # Skip huge files
                if len(file_resp.text) > 120_000:
                    continue
                docs.extend(chunk_source_file(f"{name}/{path}", file_resp.text, max_chunks=8))

    return upsert_documents(user_id, docs)


assert EMBEDDING_DIM == 384
