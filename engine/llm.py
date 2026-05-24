"""LLM 调用层 — Anthropic Messages API via proxy (mimo-v2.5-pro)."""

from __future__ import annotations

import json
import os
import time
import requests
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResult:
    ok: bool
    output: str
    model: str = ""
    status_code: int | None = None
    latency_ms: int = 0
    usage: dict[str, Any] | None = None
    error: str = ""


def _get_config() -> tuple[str, str, str]:
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    # 去掉代理前缀，直连mimo API
    if "localhost:7897" in base_url:
        base_url = base_url.split("localhost:7897/")[-1]
        if not base_url.startswith("http"):
            base_url = "https://" + base_url
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    model = os.environ.get("ANTHROPIC_MODEL", "mimo-v2.5-pro")
    if not base_url:
        raise RuntimeError("ANTHROPIC_BASE_URL is not set")
    if not token:
        raise RuntimeError("ANTHROPIC_AUTH_TOKEN is not set")
    return base_url, token, model


def call_llm(
    messages: list[dict[str, str]],
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    timeout: int = 120,
) -> LLMResult:
    """Call Anthropic Messages API (non-streaming)."""
    try:
        base_url, token, default_model = _get_config()
    except RuntimeError as e:
        return LLMResult(ok=False, output="", error=str(e))

    resolved_model = model or default_model
    payload: dict[str, Any] = {
        "model": resolved_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if system:
        payload["system"] = system

    url = f"{base_url}/v1/messages"
    headers = {
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    started = time.monotonic()
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        latency_ms = round((time.monotonic() - started) * 1000)
        body = response.json()
        content_blocks = body.get("content", [])
        text = "".join(
            b.get("text", "") for b in content_blocks if b.get("type") == "text"
        )
        return LLMResult(
            ok=True,
            output=text,
            model=body.get("model", resolved_model),
            status_code=response.status_code,
            latency_ms=latency_ms,
            usage=body.get("usage"),
        )
    except requests.exceptions.HTTPError as exc:
        return LLMResult(
            ok=False, output="", model=resolved_model,
            status_code=exc.response.status_code,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=f"HTTP {exc.response.status_code}: {str(exc)[:500]}",
        )
    except Exception as exc:
        return LLMResult(
            ok=False, output="", model=resolved_model,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=str(exc)[:500],
        )


def call_with_retry(messages, *, max_retries=3, **kwargs) -> LLMResult:
    """Call LLM with exponential backoff on 429 errors."""
    for attempt in range(max_retries):
        resp = call_llm(messages, **kwargs)
        if resp.ok or "429" not in resp.error:
            return resp
        time.sleep(2 ** attempt)
    return resp
