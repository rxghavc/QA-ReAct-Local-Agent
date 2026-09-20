"""ReAct orchestration loop: reason -> act -> observe."""

from __future__ import annotations

import json

from agent.ollama_client import PLANNER_MODEL, extract_tool_call, ollama_chat
from agent.prompts import system_prompt
from agent.tools import TOOLS, execute_tool

TERMINAL_TOOLS = {"report_done", "report_blocked"}
_TOOL_NAMES = {tool["function"]["name"] for tool in TOOLS}


def run_task(task: str, max_steps: int = 15) -> dict:
    messages = [
        {"role": "system", "content": system_prompt(task, TOOLS)},
        {"role": "user", "content": task},
    ]
    trace: list[dict] = []
    previous_failed_call: dict | None = None
    consecutive_failed_calls = 0

    for step in range(max_steps):
        message = ollama_chat(PLANNER_MODEL, messages, tools=TOOLS)
        messages.append(message)
        call = extract_tool_call(message, _TOOL_NAMES)

        if call is None:
            trace.append(
                {
                    "step": step,
                    "error": "no parseable tool call",
                    "content": message.get("content"),
                }
            )
            return {"outcome": "stuck", "steps": step + 1, "trace": trace}

        if call["name"] in TERMINAL_TOOLS:
            trace.append({"step": step, "tool_call": call})
            outcome = "done" if call["name"] == "report_done" else "blocked"
            summary = call["arguments"].get("summary") or call["arguments"].get(
                "reason"
            )
            return {
                "outcome": outcome,
                "summary": summary,
                "steps": step + 1,
                "trace": trace,
            }

        result = execute_tool(call)
        trace.append({"step": step, "tool_call": call, "result": result})
        messages.append({"role": "tool", "content": json.dumps(result)})

        if result.get("success") is False and call == previous_failed_call:
            consecutive_failed_calls += 1
        elif result.get("success") is False:
            previous_failed_call = call
            consecutive_failed_calls = 1
        else:
            previous_failed_call = None
            consecutive_failed_calls = 0

        if consecutive_failed_calls == 2:
            trace.append(
                {
                    "step": step,
                    "stuck_nudge": True,
                    "content": "The same tool call failed repeatedly. Try a different approach.",
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": "The same tool call failed repeatedly. Try a different approach.",
                }
            )
            consecutive_failed_calls = 0

    return {"outcome": "max_steps", "steps": max_steps, "trace": trace}


if __name__ == "__main__":
    # Hardcoded Tier-1 task: basic navigation + form login, checked manually
    # by reading the trace below rather than a scorer.
    result = run_task(
        "Go to https://the-internet.herokuapp.com/login, log in with "
        "username 'tomsmith' and password 'SuperSecretPassword!', and "
        "report done once you see the logged-in confirmation message."
    )
    print(json.dumps(result, indent=2, default=str))
