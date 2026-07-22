from __future__ import annotations

"""CAPTCHA / MFA pause interceptor for optional Playwright sessions.

REFUSED: marketplace login automation (Upwork/Fiverr). This only pauses
allowed-source or user-driven browser sessions when anti-bot UI appears.
"""

import base64
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from app.core.config import settings
from app.services.notify import notify_captcha_intervention

# In-memory pause registry (ponytail: Redis if multi-worker)
_PAUSES: Dict[str, "CaptchaPause"] = {}
_LOCK = threading.Lock()

_CAPTCHA_PATTERNS = [
    re.compile(r"captcha", re.I),
    re.compile(r"recaptcha|hcaptcha|turnstile|cf-challenge", re.I),
    re.compile(r"verify\s+you\s+are\s+human", re.I),
    re.compile(r"unusual\s+traffic", re.I),
    re.compile(r"two[- ]factor|2fa|mfa|one[- ]time\s+(?:code|password)|otp", re.I),
    re.compile(r"enter\s+(?:the\s+)?(?:sms|text)\s+code", re.I),
    re.compile(r"security\s+check", re.I),
]


@dataclass
class CaptchaPause:
    pause_id: str
    lead_id: Optional[str]
    reason: str
    page_url: str
    screenshot_path: Optional[str]
    screenshot_b64: Optional[str]
    created_at: datetime
    resolved: bool = False
    resume_event: threading.Event = field(default_factory=threading.Event)


def html_looks_like_captcha(html_or_text: str) -> Optional[str]:
    """Return matched reason if page content looks like CAPTCHA/MFA."""
    if not html_or_text:
        return None
    sample = html_or_text[:80_000]
    for pat in _CAPTCHA_PATTERNS:
        m = pat.search(sample)
        if m:
            return f"anti-bot/MFA signal: {m.group(0)[:80]}"
    return None


def create_pause(
    *,
    reason: str,
    page_url: str = "",
    lead_id: Optional[str] = None,
    screenshot_bytes: Optional[bytes] = None,
) -> CaptchaPause:
    """Pause automation, persist screenshot, fire critical webhook."""
    pause_id = str(uuid4())
    shot_path: Optional[str] = None
    shot_b64: Optional[str] = None
    if screenshot_bytes:
        out_dir = Path(settings.captcha_screenshot_dir or "./data/captcha_pauses")
        out_dir.mkdir(parents=True, exist_ok=True)
        shot_path = str(out_dir / f"{pause_id}.png")
        Path(shot_path).write_bytes(screenshot_bytes)
        shot_b64 = base64.b64encode(screenshot_bytes[:500_000]).decode("ascii")

    pause = CaptchaPause(
        pause_id=pause_id,
        lead_id=lead_id,
        reason=reason,
        page_url=page_url,
        screenshot_path=shot_path,
        screenshot_b64=shot_b64,
        created_at=datetime.now(timezone.utc),
    )
    with _LOCK:
        _PAUSES[pause_id] = pause

    notify_captcha_intervention(
        pause_id=pause_id,
        reason=reason,
        page_url=page_url,
        lead_id=lead_id or "",
        screenshot_path=shot_path,
    )
    return pause


def wait_for_resume(pause_id: str, *, timeout_sec: Optional[float] = None) -> bool:
    """Block until human resumes. timeout_sec=None → wait indefinitely (no crash)."""
    with _LOCK:
        pause = _PAUSES.get(pause_id)
    if pause is None:
        return False
    if timeout_sec is None:
        pause.resume_event.wait()
        return pause.resolved
    return pause.resume_event.wait(timeout=timeout_sec) and pause.resolved


def resume_pause(pause_id: str) -> bool:
    with _LOCK:
        pause = _PAUSES.get(pause_id)
        if pause is None:
            return False
        pause.resolved = True
        pause.resume_event.set()
        return True


def get_pause(pause_id: str) -> Optional[CaptchaPause]:
    with _LOCK:
        return _PAUSES.get(pause_id)


def list_open_pauses() -> list:
    with _LOCK:
        return [p for p in _PAUSES.values() if not p.resolved]


def intercept_page_content(
    *,
    html: str,
    page_url: str = "",
    lead_id: Optional[str] = None,
    screenshot_bytes: Optional[bytes] = None,
    wait: bool = True,
) -> Optional[CaptchaPause]:
    """If CAPTCHA/MFA detected → pause + alert; optionally block until resume."""
    reason = html_looks_like_captcha(html)
    if not reason:
        return None
    pause = create_pause(
        reason=reason,
        page_url=page_url,
        lead_id=lead_id,
        screenshot_bytes=screenshot_bytes,
    )
    if wait:
        # Do not timeout — wait for human (tests can resume in another thread)
        wait_for_resume(pause.pause_id, timeout_sec=None)
    return pause


def playwright_check_and_pause(page: Any, *, lead_id: Optional[str] = None) -> Optional[CaptchaPause]:
    """Call from a Playwright Page after navigation. Optional dependency."""
    from app.services.playwright_stealth import MarketplaceAutomationRefused, assert_url_allowed

    try:
        html = page.content()
        url = getattr(page, "url", "") or ""
        if url:
            assert_url_allowed(url)
    except MarketplaceAutomationRefused:
        raise
    except Exception as exc:
        return create_pause(reason=f"page read failed: {exc}", lead_id=lead_id)

    reason = html_looks_like_captcha(html)
    if not reason:
        return None

    shot: Optional[bytes] = None
    try:
        shot = page.screenshot(full_page=False)
    except Exception:
        shot = None

    pause = create_pause(
        reason=reason,
        page_url=str(url),
        lead_id=lead_id,
        screenshot_bytes=shot,
    )
    # Freeze the automation thread until human resumes
    wait_for_resume(pause.pause_id, timeout_sec=None)
    return pause
