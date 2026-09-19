"""Milestone 1 spike: I want to know if qwen2.5-coder:14b reliably support Ollama's native
tool-calling format for a multi-step ReAct-style loop.

This is throwaway. It exists only to de-risk agent/loop.py before it gets
built for real.

Finding (2026-09-19, Ollama 0.34.1, qwen2.5-coder:14b Q4_K_M): native
tool-calling does not work. Across 15 trials, the model never once emitted
Ollama's structured `message.tool_calls` field, and never once wrapped its
answer in the `<tool_call></tool_call>` tags its own chat template (see
`ollama show qwen2.5-coder:14b --template`) explicitly instructs it to use,
even when the tag requirement was repeated directly in the user turn. This
held regardless of prompt wording, so it looks like a limitation of this
model/quantization rather than a prompting problem.

What it does reliably: return a well-formed JSON object matching the
requested tool schema at the start of `content`, just without the wrapper
tags. So per the plan's own contingency, agent/ollama_client.py should use
the structured-JSON-output pattern below (call Ollama without relying on
`tool_calls`, parse `content` as JSON, validate against the tool schema)
rather than native tool-calling. See extract_tool_call() for the parser,
proven against both single-turn and multi-turn trials below.

Second finding: when a task description implies several steps up front, the
model sometimes ignores "call exactly one tool per turn" and emits multiple
JSON objects back to back on separate lines instead of just the next one.
The parser below copes with this by decoding only the first JSON object in
content (json.JSONDecoder().raw_decode) and discarding anything after it,
rather than requiring the whole string to parse as one JSON value. The real
agent loop should keep this same defensive parsing rather than assuming the
model will always emit exactly one object.

Run with the venv active and `ollama serve` already running:
    python scripts/spike_tool_calling.py
"""

import json
import re

import httpx

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5-coder:14b"

TOOLS = [
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
            "description": "Click the element matching the given visible text",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_done",
            "description": "Call this once the task has been completed",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}

SYSTEM_PROMPT = (
    "You are a web automation agent. You can only interact with the page "
    "through the provided tools. Call exactly one tool per turn. When the "
    "task is complete, call report_done."
)

TOOL_CALL_TAG_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)


def chat(messages: list[dict]) -> dict:
    response = httpx.post(
        OLLAMA_URL,
        json={"model": MODEL, "messages": messages, "tools": TOOLS, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def extract_tool_call(message: dict) -> dict | None:
    """The structured-JSON-output fallback: don't trust message.tool_calls,
    parse content directly. Handles both the tagged form the model was
    supposed to use and the untagged form it actually uses in practice.
    """
    if message.get("tool_calls"):
        call = message["tool_calls"][0]["function"]
        return {"name": call["name"], "arguments": call.get("arguments", {})}

    content = (message.get("content") or "").strip()
    match = TOOL_CALL_TAG_RE.search(content)
    if match:
        content = match.group(1).strip()

    # The model sometimes front-loads its whole multi-step plan as several
    # JSON objects on separate lines instead of one tool call per turn.
    # Take just the first well-formed object and ignore the rest, rather
    # than requiring the entire string to be exactly one JSON blob.
    try:
        parsed, _ = json.JSONDecoder().raw_decode(content)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict) and parsed.get("name") in TOOL_NAMES:
        return {"name": parsed["name"], "arguments": parsed.get("arguments", {})}
    return None


def run_single_turn_trials(task: str, n: int = 5) -> tuple[int, int]:
    """How often does a single user turn produce a tool call the fallback parser accepts?"""
    successes = 0
    for i in range(n):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        result = chat(messages)
        message = result["message"]
        call = extract_tool_call(message)
        ok = call is not None
        successes += ok
        print(
            f"  trial {i + 1}: native={bool(message.get('tool_calls'))} parsed={call} ok={ok}"
        )
    print(f"  -> {successes}/{n} valid tool calls for {task!r}\n")
    return successes, n


def run_multi_turn_trial(task: str, max_steps: int = 5) -> None:
    """Can the model consume a fake tool result and keep the loop moving using the fallback parser?"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    for step in range(max_steps):
        result = chat(messages)
        message = result["message"]
        messages.append(message)
        call = extract_tool_call(message)
        print(f"  step {step}: content={message.get('content')!r} parsed={call}")

        if call is None:
            print("  -> no parseable tool call, stopping")
            return

        if call["name"] == "report_done":
            print("  -> model called report_done, loop ended cleanly")
            return

        fake_result = {
            "status": "ok",
            "detail": f"{call['name']} executed with args {call['arguments']}",
        }
        messages.append({"role": "tool", "content": json.dumps(fake_result)})

    print("  -> hit max_steps without report_done")


if __name__ == "__main__":
    print("=== Single-turn tool-call reliability (structured-JSON fallback parser) ===")
    run_single_turn_trials("Navigate to https://saucedemo.com")
    run_single_turn_trials("Click the button labeled 'Login'")

    print("=== Multi-turn ReAct-style loop (structured-JSON fallback parser) ===")
    run_multi_turn_trial(
        "Go to https://saucedemo.com and then click the 'Login' button. "
        "Report done once you've clicked it."
    )
