from __future__ import annotations

"""Pytest configuration and shared fixtures."""

import os

# Ensure tests never accidentally hit a real production DB / secrets
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://sterling:change_me_strong_password@localhost:5432/sterling",
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("FORCE_SQLITE", "true")
# Tests run without DinD — allow the documented non-boundary Python fallback
# so sandbox unit tests can exercise timeouts. Production defaults remain false.
os.environ.setdefault("SANDBOX_ALLOW_SUBPROCESS_FALLBACK", "true")
os.environ.setdefault(
    "FIELD_ENCRYPTION_KEY", "u-mVc6PRVzrLQk8ZZXGK8WpvIjRTpsQ2AG6-iiqIKvk="
)

# Clear settings cache AND rebind the module-level singleton so services that
# imported `from app.core.config import settings` see the test env values.
from app.core import config as _config  # noqa: E402

_config.get_settings.cache_clear()
_config.settings = _config.get_settings()
