from __future__ import annotations

"""Portfolio RAG ingestion endpoints."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.rate_limit import client_key, rate_limit
from app.models.agent_memory import AgentMemory
from app.services.rag import ingest_github_repos, retrieve, upsert_documents

router = APIRouter()


class PortfolioDoc(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=40, max_length=50000)
    source: str = Field(default="manual", max_length=200)
    id: Optional[str] = Field(default=None, max_length=64)


class PortfolioIngestRequest(BaseModel):
    documents: List[PortfolioDoc] = Field(..., min_length=1, max_length=50)


class GitHubIngestRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    max_repos: int = Field(default=8, ge=1, le=20)


class IngestResult(BaseModel):
    upserted: int


class MemoryPublic(BaseModel):
    writer_instructions: str
    negotiator_instructions: str
    last_lesson: Optional[str] = None


@router.post("/documents", response_model=IngestResult, status_code=201)
def ingest_documents(
    payload: PortfolioIngestRequest,
    user: CurrentUser,
    request: Request,
) -> IngestResult:
    rate_limit(client_key(request, "rag", str(user.id)), limit=20, window_seconds=60)
    n = upsert_documents(
        str(user.id),
        [d.model_dump() for d in payload.documents],
    )
    return IngestResult(upserted=n)


@router.post("/github", response_model=IngestResult, status_code=201)
def ingest_github(
    payload: GitHubIngestRequest,
    user: CurrentUser,
    request: Request,
) -> IngestResult:
    rate_limit(client_key(request, "rag-gh", str(user.id)), limit=3, window_seconds=300)
    try:
        n = ingest_github_repos(str(user.id), payload.username, max_repos=payload.max_repos)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub ingest failed: {exc}") from exc
    return IngestResult(upserted=n)


@router.get("/search")
def search_portfolio(
    q: str,
    user: CurrentUser,
    k: int = 4,
) -> List[dict]:
    if len(q.strip()) < 3:
        raise HTTPException(status_code=400, detail="Query too short")
    return retrieve(str(user.id), q, k=min(k, 8))


@router.get("/memory", response_model=MemoryPublic)
def get_memory(db: DbSession, user: CurrentUser) -> MemoryPublic:
    mem = db.scalar(select(AgentMemory).where(AgentMemory.user_id == user.id))
    if mem is None:
        mem = AgentMemory(user_id=user.id)
        db.add(mem)
        db.commit()
        db.refresh(mem)
    return MemoryPublic(
        writer_instructions=mem.writer_instructions,
        negotiator_instructions=mem.negotiator_instructions,
        last_lesson=mem.last_lesson,
    )
