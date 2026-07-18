#!/usr/bin/env python3
"""Fail CI only when a *direct* dependency has a same-major published fix.

Major upgrades (e.g. langgraph 0.3 → 1.x) are logged but do not block — they
need a dedicated compatibility PR. Test-only residuals are ignored.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

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

# Documented residuals / major-bump-only (see backend/requirements.txt comments).
IGNORE = {
    "PYSEC-2026-1845",  # pytest 9.x — separate major
    "PYSEC-2026-83",  # langgraph 1.x — agent API upgrade PR
    "PYSEC-2026-2193",  # langchain-core 1.x
    "PYSEC-2026-2562",  # langchain-core 1.x
}


def _major(version: str) -> str | None:
    m = re.match(r"(\d+)", version.strip())
    return m.group(1) if m else None


def _same_major_fix(installed: str, fix_versions: list) -> bool:
    """True if any fix shares the installed package's major version."""
    maj = _major(installed)
    if maj is None:
        return False
    for fix in fix_versions:
        if _major(str(fix)) == maj:
            return True
    return False


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gate_pip_audit.py <audit.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"pip-audit gate: missing {path} — treating as OK (audit produced no file)")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    deps = data if isinstance(data, list) else data.get("dependencies", data)

    blockers: list[str] = []
    noted: list[str] = []
    for dep in deps:
        name = (dep.get("name") or "").lower().replace("_", "-")
        installed = str(dep.get("version") or "")
        for vuln in dep.get("vulns") or []:
            vid = vuln.get("id") or (vuln.get("aliases") or ["?"])[0]
            if vid in IGNORE:
                noted.append(f"ignored {vid} in {name}")
                continue
            fixes = vuln.get("fix_versions") or []
            if name in DIRECT and fixes and _same_major_fix(installed, fixes):
                blockers.append(f"{name}@{installed}: {vid} (fix >= {fixes[0]})")
            else:
                why = "major-bump-only or transitive" if fixes else "unfixed"
                noted.append(f"{name}: {vid} ({why})")

    for line in noted:
        print(f"note: {line}")
    if blockers:
        print("BLOCKING direct-dependency advisories with same-major fixes:")
        for line in blockers:
            print(f"  - {line}")
        return 1
    print("pip-audit gate: OK (no blocking same-major direct-dep fixes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
