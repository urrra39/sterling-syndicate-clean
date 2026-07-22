from __future__ import annotations

"""Dual-provider LLM router with anti-overthinking structured outputs.

Routing:
  - analytical (score/filter/JSON) → Claude Sonnet 5, temp≈0.1, thinking disabled
  - creative (cover letter) → GPT-5.5, temp=0.6
"""

import json
import re
from enum import Enum
from typing import Any, Dict, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings

T = TypeVar("T", bound=BaseModel)


class TaskKind(str, Enum):
    ANALYTICAL = "analytical"
    CREATIVE = "creative"


class LLMError(Exception):
    """Provider call failed or returned unusable content."""


def complete_text(
    *,
    system: str,
    user: str,
    kind: TaskKind,
    temperature: Optional[float] = None,
    max_tokens: int = 1200,
) -> str:
    """Plain-text completion routed by task kind.

    Analytical work prefers Anthropic, but transparently falls back to OpenAI
    when only an OpenAI key is configured — so provider_available(ANALYTICAL)
    (which is True whenever *either* provider is usable) never lies.
    """
    if kind == TaskKind.ANALYTICAL:
        temp = 0.1 if temperature is None else temperature
        if settings.anthropic_api_key:
            return _anthropic_text(system, user, temperature=temp, max_tokens=max_tokens)
        if settings.effective_openai_key:
            # No Anthropic key but OpenAI is configured — honor the analytical
            # request on OpenAI (low temperature) rather than raising.
            return _openai_text(system, user, temperature=temp, max_tokens=max_tokens)
        raise LLMError("No analytical LLM provider configured (Anthropic or OpenAI)")
    temp = 0.6 if temperature is None else temperature
    return _openai_text(system, user, temperature=temp, max_tokens=max_tokens)


def complete_json(
    *,
    system: str,
    user: str,
    schema: Type[T],
    kind: TaskKind = TaskKind.ANALYTICAL,
    model: Optional[str] = None,
) -> T:
    """Force structured JSON — no CoT. Validates against a Pydantic schema."""
    schema_name = schema.__name__
    schema_dict = schema.model_json_schema()
    anti_cot = (
        "ANTI-OVERTHINKING: Do NOT reason out loud. Do NOT use chain-of-thought. "
        f"Respond with a single JSON object matching schema {schema_name} only. "
        "No markdown fences, no preamble."
    )
    full_system = f"{system}\n\n{anti_cot}\n\nJSON Schema:\n{json.dumps(schema_dict)}"

    if kind == TaskKind.ANALYTICAL:
        # Prefer Anthropic for structured analytical JSON; fall back to OpenAI's
        # json_schema mode when only an OpenAI key is present, so callers that
        # gated on provider_available(ANALYTICAL) actually get a result.
        if settings.anthropic_api_key:
            raw = _anthropic_json(
                full_system, user, schema_dict, schema_name, model=model
            )
        elif settings.effective_openai_key:
            raw = _openai_json(full_system, user, schema_dict, schema_name)
        else:
            raise LLMError("No analytical LLM provider configured (Anthropic or OpenAI)")
    else:
        raw = _openai_json(full_system, user, schema_dict, schema_name)

    try:
        return schema.model_validate(_parse_json_object(raw))
    except (ValidationError, ValueError) as exc:
        raise LLMError(f"Structured output failed validation: {exc}") from exc


def _openai_headers() -> Dict[str, str]:
    key = settings.effective_openai_key
    if not key:
        raise LLMError("OPENAI_API_KEY (or LLM_API_KEY) not configured")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _openai_text(system: str, user: str, *, temperature: float, max_tokens: int) -> str:
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    # Prefer configured writer model; fall back to legacy LLM_MODEL
    model = settings.openai_writer_model or settings.llm_model
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }
    # gpt-5.x supports reasoning.effort — keep low for creative drafts to avoid overthinking
    if model.startswith("gpt-5"):
        payload["reasoning_effort"] = "low"
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(url, headers=_openai_headers(), json=payload)
            if resp.status_code >= 400:
                # Retry without reasoning_effort for older-compatible gateways
                payload.pop("reasoning_effort", None)
                payload.pop("max_completion_tokens", None)
                payload["max_tokens"] = max_tokens
                resp = client.post(url, headers=_openai_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"].get("content")
            if not content or not str(content).strip():
                # Null/empty content (content filter, or reasoning consumed the
                # whole token budget) — raise so the caller's offline fallback
                # fires instead of returning the literal string "None".
                raise LLMError("OpenAI returned empty content")
            return str(content).strip()
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"OpenAI request failed: {exc}") from exc


def _openai_json(
    system: str, user: str, schema_dict: Dict[str, Any], schema_name: str
) -> str:
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    model = settings.openai_writer_model or settings.llm_model
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": _strictify_schema(schema_dict),
            },
        },
    }
    if model.startswith("gpt-5"):
        payload["reasoning_effort"] = "none"
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(url, headers=_openai_headers(), json=payload)
            if resp.status_code >= 400:
                # Fallback: json_object mode
                payload["response_format"] = {"type": "json_object"}
                payload.pop("reasoning_effort", None)
                resp = client.post(url, headers=_openai_headers(), json=payload)
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"]).strip()
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"OpenAI JSON request failed: {exc}") from exc


def _anthropic_headers() -> Dict[str, str]:
    if not settings.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY not configured")
    return {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _anthropic_text(system: str, user: str, *, temperature: float, max_tokens: int) -> str:
    url = settings.anthropic_base_url.rstrip("/") + "/v1/messages"
    payload: Dict[str, Any] = {
        "model": settings.anthropic_scout_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        # Anti-overthinking: disable adaptive thinking for analytical speed
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "low"},
    }
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(url, headers=_anthropic_headers(), json=payload)
            if resp.status_code >= 400:
                # Some gateways reject thinking/output_config — retry bare
                payload.pop("thinking", None)
                payload.pop("output_config", None)
                resp = client.post(url, headers=_anthropic_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
            return "\n".join(parts).strip()
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"Anthropic request failed: {exc}") from exc


def _anthropic_json(
    system: str,
    user: str,
    schema_dict: Dict[str, Any],
    schema_name: str,
    *,
    model: Optional[str] = None,
) -> str:
    url = settings.anthropic_base_url.rstrip("/") + "/v1/messages"
    payload: Dict[str, Any] = {
        "model": model or settings.anthropic_scout_model,
        "max_tokens": 1024,
        "temperature": 0.1,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "low"},
        "tool_choice": {"type": "tool", "name": schema_name},
        "tools": [
            {
                "name": schema_name,
                "description": f"Return a {schema_name} object",
                "input_schema": _strictify_schema(schema_dict),
            }
        ],
    }
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(url, headers=_anthropic_headers(), json=payload)
            if resp.status_code >= 400:
                payload.pop("thinking", None)
                payload.pop("output_config", None)
                payload.pop("tool_choice", None)
                payload.pop("tools", None)
                resp = client.post(url, headers=_anthropic_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            for block in data.get("content", []):
                if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                    return json.dumps(block["input"])
                if block.get("type") == "text":
                    return str(block.get("text", "")).strip()
            raise LLMError("Anthropic returned no usable content")
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"Anthropic JSON request failed: {exc}") from exc


def _strictify_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """OpenAI strict mode wants additionalProperties:false on objects."""
    out = json.loads(json.dumps(schema))

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" or "properties" in node:
            node.setdefault("additionalProperties", False)
        for v in node.values():
            if isinstance(v, dict):
                walk(v)
            elif isinstance(v, list):
                for item in v:
                    walk(item)

    walk(out)
    return out


def _parse_json_object(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError(f"No JSON object in model output: {raw[:200]}")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def provider_available(kind: TaskKind) -> bool:
    if kind == TaskKind.ANALYTICAL:
        # The analytical execution path (complete_text / complete_json with
        # TaskKind.ANALYTICAL) strictly calls Anthropic — an OpenAI key alone
        # cannot service it. Only report availability when the Anthropic key is
        # present so callers fall back deterministically instead of raising.
        return bool(settings.anthropic_api_key)
    return bool(settings.effective_openai_key)
