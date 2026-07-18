from __future__ import annotations

"""Settings validators — payment step-up auto-enable."""

import pytest
from pydantic import ValidationError


def test_totp_secret_forces_payment_stepup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Construct a fresh Settings instance — do not rebind the process singleton."""
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PAYMENT_STEPUP_REQUIRED", "false")
    monkeypatch.setenv("PAYMENT_STEPUP_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    monkeypatch.setenv(
        "FIELD_ENCRYPTION_KEY", "u-mVc6PRVzrLQk8ZZXGK8WpvIjRTpsQ2AG6-iiqIKvk="
    )
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")

    from app.core.config import Settings, get_settings

    get_settings.cache_clear()
    try:
        s = Settings()
    except ValidationError as exc:
        pytest.fail(f"Settings rejected valid test env: {exc}")
    assert s.payment_stepup_required is True
    # Leave cache clear so the next get_settings() rebuilds from conftest env.
    get_settings.cache_clear()
