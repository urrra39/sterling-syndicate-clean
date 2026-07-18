from __future__ import annotations

"""Pydantic schemas for auth and user profiles."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


ALLOWED_SKILLS = frozenset({
    "python",
    "javascript",
    "typescript",
    "java",
    "kotlin",
    "swift",
    "go",
    "golang",
    "rust",
    "c",
    "c++",
    "c#",
    "php",
    "ruby",
    "scala",
    "elixir",
    "dart",
    "r",
    "sql",
    "html",
    "css",
    "sass",
    "tailwind",
    "bootstrap",
    "react",
    "react native",
    "vue",
    "angular",
    "svelte",
    "nextjs",
    "next.js",
    "nuxt",
    "flutter",
    "electron",
    "vite",
    "webpack",
    "node",
    "nodejs",
    "node.js",
    "express",
    "nestjs",
    "fastapi",
    "django",
    "flask",
    "spring",
    "spring boot",
    "laravel",
    "rails",
    ".net",
    "asp.net",
    "postgresql",
    "postgres",
    "mysql",
    "sqlite",
    "mongodb",
    "redis",
    "elasticsearch",
    "clickhouse",
    "snowflake",
    "bigquery",
    "dynamodb",
    "cassandra",
    "docker",
    "kubernetes",
    "terraform",
    "ansible",
    "linux",
    "bash",
    "nginx",
    "aws",
    "gcp",
    "azure",
    "vercel",
    "cloudflare",
    "ci/cd",
    "github actions",
    "git",
    "graphql",
    "rest",
    "grpc",
    "websockets",
    "oauth",
    "jwt",
    "stripe",
    "kafka",
    "rabbitmq",
    "celery",
    "airflow",
    "spark",
    "etl",
    "dbt",
    "pandas",
    "numpy",
    "scikit-learn",
    "tensorflow",
    "pytorch",
    "opencv",
    "machine learning",
    "deep learning",
    "data science",
    "data engineering",
    "nlp",
    "llm",
    "openai",
    "langchain",
    "rag",
    "prompt engineering",
    "pytest",
    "jest",
    "cypress",
    "playwright",
    "selenium",
    "tdd",
    "figma",
    "ui/ux",
    "ui/ux design",
    "web design",
    "seo",
    "devops",
    "security",
    "penetration testing",
    "blockchain",
    "solidity",
    "web3",
})


class UserCreate(BaseModel):
    """Signup payload."""

    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    skills: List[str] = Field(default_factory=list, max_length=50)
    portfolio_summary: Optional[str] = Field(default=None, max_length=5000)
    # Required only when SIGNUP_INVITE_CODE is set on the server.
    invite_code: Optional[str] = Field(default=None, max_length=128)

    @field_validator("skills")
    @classmethod
    def _known_skills_only(cls, v: List[str]) -> List[str]:
        cleaned = [s.strip().lower() for s in v if s and s.strip()]
        unknown = sorted({s for s in cleaned if s not in ALLOWED_SKILLS})
        if unknown:
            raise ValueError(
                "Unrecognized skills: "
                + ", ".join(unknown)
                + ". Use real skill names like: python, fastapi, react"
            )
        return cleaned


class UserLogin(BaseModel):
    """Login payload."""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserPublic(BaseModel):
    """Safe user representation — never includes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    skills: List[str]
    portfolio_summary: Optional[str] = None
    role: str = "owner"
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Auth success payload.

    ``access_token`` is always empty — the JWT is delivered only via HttpOnly
    cookie so script cannot read it. Kept for API shape compatibility.
    """

    access_token: str = ""
    token_type: str = "bearer"
    user: UserPublic


class MessageResponse(BaseModel):
    """Generic message wrapper."""

    message: str


class ForgotPasswordRequest(BaseModel):
    """Request a password-reset email."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Complete a password reset with the emailed token."""

    token: str = Field(..., min_length=16, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=128)
