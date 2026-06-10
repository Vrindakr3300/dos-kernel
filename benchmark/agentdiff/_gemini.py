"""A minimal native-Gemini chat caller for the Agent-Diff live loop — $0 to import.

WHY NOT THE OpenAI-COMPAT ENDPOINT THE EXAMPLE USED
---------------------------------------------------
The Agent-Diff example notebook drives an LLM through OpenRouter's OpenAI-compatible
`chat/completions`. The DOS live key is a Google AQ-prefixed access token that the
OpenAI-compat shim REJECTS ("Missing or invalid Authorization header" — it wants a
Bearer key, not this token). The NATIVE `…/models/{model}:generateContent` endpoint with
the `x-goog-api-key` header works with exactly this key (smoked 2026-06-08). So this module
speaks the native Gemini wire format, lifting the proven request shape from
`benchmark/enterpriseops/g3_forgeability.py:_judge_live_gemini`:
  * `contents` (role-tagged parts) + a separate `systemInstruction`,
  * `generationConfig.thinkingConfig.thinkingBudget` so a 2.5-flash model spends a bounded
    number of thinking tokens before emitting text (a 0 budget on a thinking-only model is
    fatal — see `THINKING_ONLY` below),
  * parse `candidates[0].content.parts[*].text`.

MODEL-AWARE THINKING (the docs/231 lesson, lifted verbatim)
-----------------------------------------------------------
`-pro`/`gemini-3` tier models REJECT a 0 thinking budget ("Budget 0 is invalid. This model
only works in thinking mode"), while flash accepts it. A ReAct agent NEEDS some reasoning to
plan tool calls, so we never disable thinking entirely here — we give flash a bounded budget
and pro the API default (omit the cap). The discriminator is the `-pro` substring, the same
one the tau2 runner uses, so a future `gemini-3-flash` still gets the flash path.

PURE-ish: import is free (no network, no key read). The single network call is `chat()`.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Tier substrings whose models REJECT a thinking budget of 0 (thinking-only). We never send
# `thinkingBudget: 0` to these — instead we omit the cap and let the API use its default.
# Matched against the bare model id; `-pro` covers gemini-2.5-pro, gemini-3-pro, … while a
# `gemini-3-flash` still takes the flash (bounded-budget) path. (docs/231 + live_loop.py:222.)
_THINKING_ONLY = ("-pro",)

# The default bounded thinking budget for a flash-tier agent. Big enough that the model can
# plan a curl/tool call, small enough to keep latency + cost down on a 40-step ReAct loop.
_FLASH_THINKING_BUDGET = 512


def gemini_key() -> Optional[str]:
    """The live key: env first (loaded from .env by the runner), else None."""
    return os.environ.get("GEMINI_API_KEY") or None


@dataclass(frozen=True)
class ChatResult:
    """One model turn. `text` is the concatenated candidate text (empty on a blocked/empty
    response); `ok` says whether a usable response came back; `error` carries the failure."""
    text: str
    ok: bool
    error: str = ""
    finish_reason: str = ""


def _to_gemini_payload(messages: list[dict], *, model: str, max_output_tokens: int) -> dict:
    """Map OpenAI-style messages → a native Gemini `generateContent` body.

    `system` messages are concatenated into `systemInstruction`; `user`/`assistant` become
    `contents` with roles `user`/`model` (Gemini's name for the assistant role). Temperature
    is pinned to 0.0 for reproducibility. Thinking budget is model-aware (see module docstring).
    """
    system_parts: list[str] = []
    contents: list[dict] = []
    for m in messages:
        role = m.get("role", "user")
        text = str(m.get("content", ""))
        if role == "system":
            system_parts.append(text)
        else:
            g_role = "model" if role == "assistant" else "user"
            contents.append({"role": g_role, "parts": [{"text": text}]})

    gen_cfg: dict[str, Any] = {"temperature": 0.0, "maxOutputTokens": max_output_tokens}
    bare = model.split("/", 1)[-1].lower()
    if not any(s in bare for s in _THINKING_ONLY):
        # flash-tier: bound the thinking budget so thoughts don't eat the output token cap.
        gen_cfg["thinkingConfig"] = {"thinkingBudget": _FLASH_THINKING_BUDGET}
    # pro-tier: omit thinkingConfig entirely (a 0 budget is fatal; the API default is valid).

    body: dict[str, Any] = {"contents": contents, "generationConfig": gen_cfg}
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    return body


def _extract_text(data: dict) -> tuple[str, str]:
    """Pull the concatenated candidate text + finish reason out of a generateContent reply."""
    cands = data.get("candidates") or []
    if not cands:
        return "", str(data.get("promptFeedback", {}).get("blockReason", "")) or "NO_CANDIDATES"
    cand = cands[0]
    finish = str(cand.get("finishReason", ""))
    parts = (cand.get("content", {}) or {}).get("parts", []) or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return text, finish


def chat(
    messages: list[dict],
    *,
    model: str = "gemini-2.5-flash",
    max_output_tokens: int = 2048,
    max_retries: int = 4,
    timeout: int = 90,
) -> ChatResult:
    """One chat completion via native Gemini. Bounded exponential backoff on transient errors.

    Returns a `ChatResult`; never raises for an API/transport error (the caller decides what an
    empty turn means in the ReAct loop). A missing key returns ok=False with a clear message.
    """
    key = gemini_key()
    if not key:
        return ChatResult(text="", ok=False, error="no GEMINI_API_KEY in environment")

    bare = model.split("/", 1)[-1]  # tolerate a `gemini/` provider prefix
    url = f"{_GEMINI_BASE}/{bare}:generateContent"
    body = json.dumps(_to_gemini_payload(messages, model=bare, max_output_tokens=max_output_tokens)).encode()
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}

    last_err = ""
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            text, finish = _extract_text(data)
            # An empty text with a non-STOP finish (MAX_TOKENS, SAFETY, …) is a usable signal
            # to the ReAct loop, not a transport failure — report it, don't retry.
            return ChatResult(text=text, ok=True, finish_reason=finish)
        except urllib.error.HTTPError as e:
            code = e.code
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            last_err = f"HTTP {code}: {detail}"
            # 429 / 5xx are transient (rate limit / server overload) — back off and retry.
            # 4xx (except 429) is a request bug — fail fast, retrying won't help.
            transient = code == 429 or 500 <= code < 600
            if not transient or attempt == max_retries - 1:
                return ChatResult(text="", ok=False, error=last_err)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt == max_retries - 1:
                return ChatResult(text="", ok=False, error=last_err)
        # exponential backoff: 1.5s, 3s, 6s, … (deterministic — no random in the bench spirit)
        time.sleep(1.5 * (2 ** attempt))
    return ChatResult(text="", ok=False, error=last_err or "exhausted retries")
