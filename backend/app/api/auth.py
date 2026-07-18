from __future__ import annotations

"""Authentication routes: signup, login, current user, password reset."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.rate_limit import client_key, rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    MessageResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserPublic,
)
from app.services.email import send_password_reset_email

router = APIRouter()

# Cookie configuration
_COOKIE_NAME = "sterling_access_token"
_COOKIE_MAX_AGE = settings.access_token_expire_minutes * 60

# Dedicated anti-abuse budget for the unauthenticated password-reset endpoint,
# which sends email — a prime target for automated email-bombing. Far tighter
# than the global API limit.
_FORGOT_PW_LIMIT = 5
_FORGOT_PW_WINDOW_SECONDS = 900  # 5 requests / 15 min per client
_AUTH_LIMIT = 20
_AUTH_WINDOW_SECONDS = 900  # 20 login/signup attempts / 15 min per client


def _set_auth_cookie(response: Response, token: str) -> None:
    """Attach JWT as an HttpOnly cookie.

    Production uses SameSite=None + Secure so a split-origin SPA (e.g. two
    *.onrender.com hosts on the public-suffix list) can still send the cookie
    on credentialed cross-origin fetches. Localhost uses Lax without Secure.
    The JWT is NEVER returned in the JSON body — that would re-expose it to XSS.
    """
    if settings.is_production:
        secure = True
        samesite: str = "none"
    else:
        secure = False
        samesite = "lax"
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    """Remove the auth cookie (must mirror Secure/SameSite used at set time)."""
    if settings.is_production:
        response.delete_cookie(
            key=_COOKIE_NAME, path="/", secure=True, samesite="none"
        )
    else:
        response.delete_cookie(
            key=_COOKIE_NAME, path="/", secure=False, samesite="lax"
        )


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    payload: UserCreate, request: Request, response: Response, db: DbSession
) -> TokenResponse:
    """Register a new freelancer workspace (tenant owner) and set the auth cookie."""
    rate_limit(
        client_key(request, "auth-signup"),
        limit=_AUTH_LIMIT,
        window_seconds=_AUTH_WINDOW_SECONDS,
    )
    invite_required = (settings.signup_invite_code or "").strip()
    if invite_required:
        provided = (payload.invite_code or "").strip()
        if not provided or provided != invite_required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Valid invite code required for signup.",
            )

    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Normalize skills: strip, lowercase, dedupe, drop empties
    skills = sorted(
        {s.strip().lower() for s in payload.skills if s and s.strip()}
    )

    # Each signup creates its own single-tenant workspace; the creator is owner.
    user = User(
        name=payload.name.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        skills=skills,
        role="owner",
        portfolio_summary=(
            payload.portfolio_summary.strip()
            if payload.portfolio_summary
            else None
        ),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        subject=user.id,
        extra_claims={"tv": user.token_version},
    )
    _set_auth_cookie(response, token)
    # Cookie-only: never put the JWT in the JSON body (XSS-stealable).
    return TokenResponse(
        access_token="",
        user=UserPublic.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: UserLogin, request: Request, response: Response, db: DbSession
) -> TokenResponse:
    """Authenticate with email/password and set the HttpOnly auth cookie."""
    rate_limit(
        client_key(request, "auth-login"),
        limit=_AUTH_LIMIT,
        window_seconds=_AUTH_WINDOW_SECONDS,
    )
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        # Same message for both cases — avoid user enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    token = create_access_token(
        subject=user.id,
        extra_claims={"tv": user.token_version},
    )
    _set_auth_cookie(response, token)
    return TokenResponse(
        access_token="",
        user=UserPublic.model_validate(user),
    )


@router.get("/me", response_model=UserPublic)
def me(current_user: CurrentUser) -> UserPublic:
    """Return the authenticated user's public profile."""
    return UserPublic.model_validate(current_user)


@router.post("/logout")
def logout(response: Response) -> MessageResponse:
    """Clear the auth cookie."""
    _clear_auth_cookie(response)
    return MessageResponse(message="Logged out successfully.")


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: DbSession
) -> MessageResponse:
    """Issue a single-use reset token and email a reset link.

    Always returns the same message to avoid user enumeration.
    Rate-limited per client (IP-aware, XFF-aware) to mitigate email bombing.
    """
    # Both an IP bucket and an email bucket: stops one host hammering the endpoint
    # AND stops a distributed flood targeting a single victim's inbox.
    rate_limit(
        client_key(request, "forgot-pw-ip"),
        limit=_FORGOT_PW_LIMIT,
        window_seconds=_FORGOT_PW_WINDOW_SECONDS,
    )
    rate_limit(
        f"forgot-pw-email:{payload.email.lower()}",
        limit=_FORGOT_PW_LIMIT,
        window_seconds=_FORGOT_PW_WINDOW_SECONDS,
    )

    generic = MessageResponse(
        message="If an account exists for that email, a reset link has been sent."
    )
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not user.is_active:
        return generic

    # Invalidate prior unused tokens for this user
    prior = db.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used.is_(False),
        )
    ).all()
    for t in prior:
        t.used = True
        t.used_at = datetime.now(timezone.utc)

    raw_token = secrets.token_urlsafe(32)
    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.password_reset_token_ttl_minutes),
    )
    db.add(reset)
    db.commit()

    reset_link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={raw_token}"
    send_password_reset_email(to=user.email, reset_link=reset_link)
    return generic


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, db: DbSession) -> MessageResponse:
    """Verify a reset token and set the new password."""
    token_hash = _hash_token(payload.token)
    reset = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    if reset is None or reset.used:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or used token")

    expires = reset.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token expired")

    user = db.get(User, reset.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

    user.password_hash = hash_password(payload.new_password)
    # Increment token_version to invalidate all existing sessions/JWTs
    user.token_version = (user.token_version or 0) + 1
    reset.used = True
    reset.used_at = datetime.now(timezone.utc)
    db.commit()
    return MessageResponse(message="Password reset successful. You can now sign in.")
