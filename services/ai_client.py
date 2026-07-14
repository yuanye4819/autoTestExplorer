"""Shared synchronous AI API client — used by desktop app and checklist generator."""
from __future__ import annotations

import json
import urllib.request
import urllib.error
import logging

from config import settings

logger = logging.getLogger("autotest")


def call_ai(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.3,
    timeout: int = 20,
) -> str:
    """Call the AI API synchronously and return the response content.
    Returns empty string on failure."""
    try:
        api_key = settings.AI_API_KEY
        api_base = settings.AI_API_BASE
        model_name = model or settings.AI_MODEL

        if not api_key:
            logger.warning("AI API key not configured")
            return ""

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        data = json.dumps({
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode("utf-8")

        req = urllib.request.Request(
            api_base.rstrip("/") + "/chat/completions",
            data=data,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read()) if e.fp else {}
            msg = body.get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        logger.warning(f"AI API HTTP {e.code}: {msg}")
        return ""
    except Exception as e:
        logger.warning(f"AI API call failed: {e}")
        return ""


def test_connection(api_key: str, api_base: str, model: str) -> tuple[bool, str]:
    """Test if the AI API connection works. Returns (ok, message)."""
    try:
        data = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
        }).encode("utf-8")

        req = urllib.request.Request(
            api_base.rstrip("/") + "/chat/completions",
            data=data,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        if "choices" in result:
            return True, "OK: " + result.get("model", model)
        return False, "Unexpected response: " + str(result)[:200]
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read()) if e.fp else {}
            msg = body.get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        return False, f"HTTP {e.code}: {msg}"
    except Exception as e:
        return False, str(e)[:200]
