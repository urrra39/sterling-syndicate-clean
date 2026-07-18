#!/usr/bin/env python3
"""Fail CI only when a *direct* dependency has a known fixed version available.

Transitive advisories with no published fix (or test-only tools) are reported
but do not block the build — otherwise the gate stays red forever on upstream
lag. Usage:

    pip-audit -f json -o audit.json
    python scripts/gate_pip_audit.py audit.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Top-level packages we pin / care about in backend/requirements.txt
DIRECT = {
    "fastapi",
    "starlette",
    "uvicorn",
    "python-multipart",
    "greenlet",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "pgvector",
    "pyjwt",
    "passlib",
    "bcrypt",
    "cryptography",
    "pydantic",
    "pydantic-settings",
    "email-validator",
    "httpx",
    "python-dotenv",
    "chromadb",
    "langgraph",
    "langchain-core",
    "pytest",
    "pytest-asyncio",
    "eval-type-backport",
}

# Test-only / acknowledged residual (documented in requirements.txt comments).
IGNORE = {
    "PYSEC-2026-1845",  # pytest — fix needs Python>=3.10 major bump unverified here
}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gate_pip_audit.py <audit.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    deps = data if isinstance(data, list) else data.get("dependencies", data)

    blockers: list[str] = []
    noted: list[str] = []
    for dep in deps:
        name = (dep.get("name") or "").lower().replace("_", "-")
        for vuln in dep.get("vulns") or []:
            vid = vuln.get("id") or vuln.get("aliases", ["?"])[0]
            if vid in IGNORE:
                noted.append(f"ignored {vid} in {name}")
                continue
            fixes = vuln.get("fix_versions") or []
            if name in DIRECT and fixes:
                blockers.append(f"{name}: {vid} (fix >= {fixes[0]})")
            else:
                noted.append(f"{name}: {vid} (no gate — transitive or unfixed)")

    for line in noted:
        print(f"note: {line}")
    if blockers:
        print("BLOCKING direct-dependency advisories with available fixes:")
        for line in blockers:
            print(f"  - {line}")
        return 1
    print("pip-audit gate: OK (no blocking direct-dep fixes pending)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
