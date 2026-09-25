"""
Google Gemini provider (official `google-genai` SDK, Gemini Developer API).

All Gemini-specific formats live here:
  - neutral JSON-Schema tool specs  → types.FunctionDeclaration
  - neutral conversation messages   → types.Content (functionCall / functionResponse parts)
  - GenerateContentResponse         → neutral ModelTurn
  - SDK / HTTP errors               → ClapAIError with short, user-facing messages

Uses the Gemini Developer API with an API key (GEMINI_API_KEY), never Vertex AI,
so no Google Cloud billing project is involved. Tools are executed by CLAP's own
agent loop: automatic function calling is disabled.
"""

from __future__ import annotations

import json
import logging
import re
import threading

import httpx
from google import genai
from google.genai import errors, types

from ai.base import AIProvider, ClapAIError, ModelTurn, ToolCall

log = logging.getLogger("clap.ai.gemini")

REQUEST_TIMEOUT_MS = 60_000
# Transient server errors are retried; 429 (quota) is not, to avoid burning quota.
RETRY = types.HttpRetryOptions(attempts=3, initial_delay=1.0, http_status_codes=[500, 502, 503, 504])

_BLOCKED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}
_MALFORMED = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}


# ── Tool schemas ──────────────────────────────────────────────────────────────

def function_declarations(tools: list[dict]) -> list[types.Tool]:
    """Neutral JSON-Schema tool specs → one Gemini Tool with function declarations."""
    decls = []
    for spec in tools:
        params = spec.get("parameters") or {}
        kwargs = {"name": spec["name"], "description": spec.get("description", "")}
        if params.get("properties"):            # Gemini rejects empty object schemas
            kwargs["parameters_json_schema"] = params
        decls.append(types.FunctionDeclaration(**kwargs))
    return [types.Tool(function_declarations=decls)] if decls else []


# ── Conversation adapter ──────────────────────────────────────────────────────

def _json_object(value) -> dict:
    """Function responses must be JSON objects."""
    data = json.loads(json.dumps(value, default=str))
    return data if isinstance(data, dict) else {"result": data}


def to_contents(messages: list[dict]) -> list[types.Content]:
    """Neutral CLAP messages → Gemini contents (consecutive same-role turns merged)."""
    contents: list[types.Content] = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            text = str(msg.get("content") or "").strip()
            if not text:
                continue
            content = types.Content(role="user", parts=[types.Part(text=text)])
        elif role == "assistant":
            raw = msg.get("raw")
            if isinstance(raw, types.Content):
                content = raw  # exact replay, incl. thought signatures on function calls
            else:
                parts = []
                if msg.get("content"):
                    parts.append(types.Part(text=str(msg["content"])))
                for call in msg.get("tool_calls") or []:
                    parts.append(types.Part(function_call=types.FunctionCall(
                        id=call.id, name=call.name, args=call.args)))
                if not parts:
                    continue
                content = types.Content(role="model", parts=parts)
        elif role == "tool":
            parts = [
                types.Part(function_response=types.FunctionResponse(
                    id=r.get("id"), name=r["name"], response=_json_object(r.get("content"))))
                for r in msg.get("results") or []
            ]
            if not parts:
                continue
            content = types.Content(role="user", parts=parts)
        else:
            continue

        if contents and contents[-1].role == content.role:
            prev = contents[-1]
            contents[-1] = types.Content(role=prev.role, parts=[*(prev.parts or []), *(content.parts or [])])
        else:
            contents.append(content)
    return contents


def parse_response(response: types.GenerateContentResponse) -> ModelTurn:
    """Gemini response → neutral ModelTurn."""
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        return ModelTurn(finish="blocked")

    candidates = response.candidates or []
    if not candidates:
        return ModelTurn(finish="empty")
    candidate = candidates[0]
    reason = candidate.finish_reason.name if candidate.finish_reason else "STOP"
    content = candidate.content
    parts = (content.parts if content else None) or []

    texts, calls = [], []
    for part in parts:
        if part.function_call is not None and part.function_call.name:
            fc = part.function_call
            calls.append(ToolCall(name=fc.name, args=dict(fc.args or {}), id=fc.id))
        elif part.text and not part.thought:
            texts.append(part.text)

    turn = ModelTurn(text="".join(texts).strip(), tool_calls=calls, raw=content)
    if calls:
        turn.finish = "stop"
    elif reason in _MALFORMED:
        turn.finish = "malformed"
    elif reason in _BLOCKED:
        turn.finish = "blocked"
    elif reason == "MAX_TOKENS":
        turn.finish = "max_tokens"
    elif not turn.text:
        turn.finish = "empty"
    return turn


# ── Errors ────────────────────────────────────────────────────────────────────

def _details_text(exc: errors.APIError) -> str:
    try:
        return json.dumps(exc.details, default=str)
    except Exception:
        return str(exc.details)


def _retry_delay(details: str) -> int | None:
    match = re.search(r'"retryDelay":\s*"(\d+)(?:\.\d+)?s"', details)
    return int(match.group(1)) if match else None


def to_clap_error(exc: Exception, model: str) -> ClapAIError:
    """Map SDK / transport errors to short user-facing messages (no raw traces)."""
    if isinstance(exc, errors.APIError):
        code, status = exc.code, str(exc.status or "")
        message, details = str(exc.message or ""), _details_text(exc)
        if "API_KEY_INVALID" in details or "API key not valid" in message or "API key expired" in message:
            return ClapAIError("The Gemini API key is invalid.")
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            if re.search(r"limit:\s*0\b", message):
                return ClapAIError(
                    f"The Gemini model {model} has no free-tier quota for this key. "
                    "Set GEMINI_MODEL to a model included in your plan.")
            if "PerDay" in details or "per day" in message.lower():
                return ClapAIError("Gemini's daily quota has been reached. Please try again later.")
            delay = _retry_delay(details)
            wait = f" Try again in {delay} seconds." if delay else " Please try again shortly."
            return ClapAIError("Gemini quota has been reached." + wait)
        if code == 404 or status == "NOT_FOUND":
            return ClapAIError(f"The Gemini model {model} is not available. Check GEMINI_MODEL.")
        if "location is not supported" in message.lower():
            return ClapAIError("The Gemini API is not available in your region.")
        if code in (401, 403) or status in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
            return ClapAIError("The Gemini API key is not permitted to use this model.")
        if code == 503 or status == "UNAVAILABLE":
            return ClapAIError("Gemini is temporarily overloaded. Try again in a moment.")
        if code == 504 or status == "DEADLINE_EXCEEDED":
            return ClapAIError("The AI service took too long to respond.")
        if isinstance(exc, errors.ServerError):
            return ClapAIError("The AI service is temporarily unavailable. Try again in a moment.")
        return ClapAIError("The AI service rejected the request.")
    if isinstance(exc, httpx.TimeoutException):
        return ClapAIError("The AI service took too long to respond.")
    if isinstance(exc, httpx.TransportError):
        return ClapAIError("CLAP cannot reach the AI service.")
    return ClapAIError("CLAP cannot reach the AI service.")


# ── Provider ──────────────────────────────────────────────────────────────────

class GeminiProvider(AIProvider):
    """AIProvider for the Gemini Developer API."""

    name = "gemini"

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        if not api_key:
            raise ClapAIError("Gemini API key is not configured.")
        super().__init__(model)
        http_kwargs = {"timeout": REQUEST_TIMEOUT_MS, "retry_options": RETRY}
        if base_url:  # tests / proxies only
            http_kwargs["base_url"] = base_url
        http = types.HttpOptions(**http_kwargs)
        # One reusable client; vertexai=False keeps CLAP on the Gemini Developer API.
        self._client = genai.Client(api_key=api_key, vertexai=False, http_options=http)
        self._tools_cache: tuple[int, list[types.Tool]] | None = None
        self._lock = threading.Lock()

    def _tools(self, tools: list[dict]) -> list[types.Tool]:
        with self._lock:
            key = id(tools)
            if self._tools_cache is None or self._tools_cache[0] != key:
                self._tools_cache = (key, function_declarations(tools))
            return self._tools_cache[1]

    def _config(self, system: str, tools: list[dict]) -> types.GenerateContentConfig:
        declared = self._tools(tools)
        return types.GenerateContentConfig(
            system_instruction=system,
            tools=declared or None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _call(self, contents: list[types.Content], config: types.GenerateContentConfig):
        try:
            return self._client.models.generate_content(model=self.model, contents=contents, config=config)
        except (errors.APIError, httpx.HTTPError) as exc:
            log.error("Gemini request failed: %s %s", type(exc).__name__, getattr(exc, "message", "") or exc)
            raise to_clap_error(exc, self.model) from exc

    def generate(self, system: str, messages: list[dict], tools: list[dict]) -> ModelTurn:
        contents = to_contents(messages)
        config = self._config(system, tools)
        turn = parse_response(self._call(contents, config))
        if turn.finish in ("malformed", "empty"):
            # Transient model hiccup: one retry before reporting it.
            log.warning("Gemini returned a %s response; retrying once", turn.finish)
            turn = parse_response(self._call(contents, config))
        return turn

    def list_models(self) -> list[dict]:
        """Models this key can use for generateContent (for `python -m ai models`)."""
        out = []
        try:
            for m in self._client.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" in actions:
                    out.append({"name": (m.name or "").removeprefix("models/"),
                                "display_name": m.display_name or ""})
        except (errors.APIError, httpx.HTTPError) as exc:
            raise to_clap_error(exc, self.model) from exc
        return out
