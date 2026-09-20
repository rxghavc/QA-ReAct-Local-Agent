"""Tool definitions exposed to the model, and dispatch to the browser service."""

from __future__ import annotations

import os

import httpx

BROWSER_SERVICE_URL = os.environ.get("BROWSER_SERVICE_URL", "http://localhost:8001")

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Navigate the browser to a URL",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click an element matched by a CSS selector or visible text",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text into the element matched by a CSS selector",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_text",
            "description": "Read the text content of the element matched by a CSS selector",
            "parameters": {
                "type": "object",
                "properties": {"selector": {"type": "string"}},
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a screenshot of the current page, for the trace log",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_for",
            "description": "Wait for an element matched by a CSS selector to become visible",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "timeout_ms": {"type": "integer"},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handle_dialog",
            "description": "Set how the next JS dialog (alert/confirm) should resolve",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["accept", "dismiss"]}
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_state",
            "description": "Cheap re-orientation: current URL, title, and visible headings",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_done",
            "description": "End the task, claiming it is complete",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_blocked",
            "description": "End the task, reporting that it cannot be completed",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": (
                "End the task to ask the user a question, when the "
                "instruction itself is ambiguous and could reasonably mean "
                "more than one thing. Not for a task that is merely hard"
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
]

# report_done/report_blocked/ask_clarification are terminal signals handled by
# the loop itself, not browser actions, so they have no entry here.
_BROWSER_ENDPOINTS: dict[str, tuple[str, str]] = {
    "navigate": ("POST", "/navigate"),
    "click": ("POST", "/click"),
    "type_text": ("POST", "/type_text"),
    "extract_text": ("POST", "/extract_text"),
    "screenshot": ("POST", "/screenshot"),
    "wait_for": ("POST", "/wait_for"),
    "handle_dialog": ("POST", "/handle_dialog"),
    "get_page_state": ("GET", "/get_page_state"),
}


def execute_tool(tool_call: dict) -> dict:
    """Dispatch a parsed tool call to the browser service over HTTP.

    Mirrors BrowserSession's own contract: failures come back as a plain
    dict with success=False rather than a raised exception, whether the
    failure is a Playwright error surfaced by the browser service or the
    browser service being unreachable, so the agent loop can feed either
    back to the model as an observation.
    """
    name = tool_call["name"]
    arguments = tool_call.get("arguments", {})

    if name not in _BROWSER_ENDPOINTS:
        return {"success": False, "error": f"unknown tool {name!r}"}

    method, path = _BROWSER_ENDPOINTS[name]
    url = f"{BROWSER_SERVICE_URL}{path}"
    try:
        if method == "GET":
            response = httpx.get(url, timeout=30)
        else:
            response = httpx.post(url, json=arguments, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as e:
        return {"success": False, "error": f"browser service request failed: {e}"}
    return response.json()
