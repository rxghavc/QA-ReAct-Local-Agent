"""Thin wrapper around Ollama's /api/chat endpoint.

The Milestone 1 spike (scripts/spike_tool_calling.py) found that
qwen2.5-coder:14b never emits Ollama's native `message.tool_calls`, but
reliably returns a well-formed JSON tool call in `content` instead. This
module implements the structured-JSON-output fallback that finding calls
for, rather than trusting `tool_calls`.
"""

from __future__ import annotations

import json
import os
import re

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
PLANNER_MODEL = "qwen2.5-coder:14b"

_TOOL_CALL_TAG_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
# Only the *opening* fence is matched. An earlier version required the
# closing fence too, and a live run produced an unterminated fence
# (```json, a complete JSON object, then nothing), which left the
# backticks in place and failed the whole step. raw_decode already stops
# after the first JSON value, so a trailing fence needs no handling.
_CODE_FENCE_OPEN_RE = re.compile(r"^`{3,}[ \t]*(?:json)?[ \t]*\r?\n?", re.IGNORECASE)


def ollama_chat(
    model: str, messages: list[dict], tools: list[dict] | None = None
) -> dict:
    """Returns the full /api/chat response, not just `message`.

    `prompt_eval_count` (tokens in the resent prompt) and `eval_count`
    (tokens generated this step) live alongside `message` at the top
    level of Ollama's response rather than inside it, so a caller that
    wants the token accounting from docs/ai-infra-and-observability.md's
    item 3 needs the whole thing. agent/loop.py reads `response["message"]`
    for the tool call and the two count fields for token totals.
    """
    response = httpx.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "tools": tools or [],
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def extract_tool_call(message: dict, tool_names: set[str]) -> dict | None:
    """Parse a tool call out of an Ollama chat message.

    Checks native `tool_calls` first, but falls back to parsing the first
    JSON object out of `content` since that's the only reliable path on
    qwen2.5-coder:14b. The model sometimes front-loads several JSON objects
    in one response instead of one tool call per turn, so only the first
    well-formed object is taken (json.JSONDecoder().raw_decode), matching
    the parser proven in scripts/spike_tool_calling.py.

    Also strips a leading ```json markdown fence. The spike never hit this
    (it only ever saw bare or <tool_call>-wrapped JSON), but the live
    Milestone 3 loop did on its first real run, and Milestone 8's first
    full-suite run then produced an *unterminated* fence that the
    closing-fence-requiring version of this parser rejected outright,
    losing two whole tasks to "no parseable tool call" on step 0. Each
    time the model has surprised this parser it has been a new shape of
    the same surprise, so it strips what it recognises and leans on
    raw_decode to ignore whatever trails the JSON.
    """
    if message.get("tool_calls"):
        call = message["tool_calls"][0]["function"]
        return {"name": call["name"], "arguments": call.get("arguments", {})}

    content = (message.get("content") or "").strip()
    match = _TOOL_CALL_TAG_RE.search(content)
    if match:
        content = match.group(1).strip()

    content = _CODE_FENCE_OPEN_RE.sub("", content, count=1).strip()

    try:
        parsed, _ = json.JSONDecoder().raw_decode(content)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict) and parsed.get("name") in tool_names:
        return {"name": parsed["name"], "arguments": parsed.get("arguments", {})}
    return None
