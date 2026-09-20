"""Thin wrapper around Ollama's /api/chat endpoint."""

from __future__ import annotations

import json
import os
import re

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
PLANNER_MODEL = "qwen2.5-coder:14b"

_TOOL_CALL_TAG_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def ollama_chat(
    model: str, messages: list[dict], tools: list[dict] | None = None
) -> dict:
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
    return response.json()["message"]


def extract_tool_call(message: dict, tool_names: set[str]) -> dict | None:
    """Parse a tool call out of an Ollama chat message.

    Checks native `tool_calls` first, but falls back to parsing the first
    JSON object out of `content` since that's the only reliable path on
    qwen2.5-coder:14b. The model sometimes front-loads several JSON objects
    in one response instead of one tool call per turn, so only the first
    well-formed object is taken (json.JSONDecoder().raw_decode), matching
    the parser proven in scripts/spike_tool_calling.py.

    Also strips a ```json ... ``` markdown fence around the object. The
    spike never hit this (it only ever saw bare or <tool_call>-wrapped
    JSON), but the live Milestone 3 loop did on its first real run, so the
    fallback parser needs to be defensive about it too.
    """
    if message.get("tool_calls"):
        call = message["tool_calls"][0]["function"]
        return {"name": call["name"], "arguments": call.get("arguments", {})}

    content = (message.get("content") or "").strip()
    match = _TOOL_CALL_TAG_RE.search(content)
    if match:
        content = match.group(1).strip()

    fence_match = _CODE_FENCE_RE.match(content)
    if fence_match:
        content = fence_match.group(1).strip()

    try:
        parsed, _ = json.JSONDecoder().raw_decode(content)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict) and parsed.get("name") in tool_names:
        return {"name": parsed["name"], "arguments": parsed.get("arguments", {})}
    return None