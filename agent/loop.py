"""ReAct orchestration loop: reason -> act -> observe.

Milestone 3 wired this up end-to-end against one hardcoded Tier-1 task.
Milestone 6 added the stuck-detection re-plan nudge below, after the
Milestone 5 benchmark showed the more common real failure isn't the loop
repeating an identical failing action (what this was originally designed
to catch), it's the model giving up or claiming false success after a
single attempt. See docs/milestones/06-self-correction-dynamic-elements.md
for the full story; this mechanism is kept because it's still a real
failure mode worth catching, not because it turned out to be the main one.

Milestone 7 (see docs/milestones/07-model-routing.md) broadened
stuck-detection with a cheap llama3.2:3b checkpoint (agent.routing.
is_same_failure): two failures don't have to be byte-for-byte identical
to count as "the same mistake twice," just judged the same by the 3b
model. use_routing=False reproduces the Milestone 6 exact-match-only
behavior, kept for the A/B comparison documented in that milestone.
"""

from __future__ import annotations

import json

from agent.ollama_client import PLANNER_MODEL, extract_tool_call, ollama_chat
from agent.prompts import system_prompt
from agent.routing import is_same_failure
from agent.tools import TOOLS, execute_tool

# Each ends the loop with its own outcome rather than being executed
# against the browser. ask_clarification exists for the ambiguous-instruction
# negative test (Milestone 8): "this could mean two things, which did you
# mean?" is a genuinely different answer from "I tried and could not", and
# collapsing it into report_blocked would make that task unscoreable without
# keyword-sniffing the blocked reason.
TERMINAL_OUTCOMES = {
    "report_done": "done",
    "report_blocked": "blocked",
    "ask_clarification": "needs_clarification",
}
TERMINAL_TOOLS = set(TERMINAL_OUTCOMES)
_TOOL_NAMES = {tool["function"]["name"] for tool in TOOLS}
STUCK_THRESHOLD = 2


def _stuck_nudge(call: dict) -> dict:
    return {
        "role": "user",
        "content": (
            f"You've now called {call['name']} with the exact same arguments "
            f"({json.dumps(call['arguments'])}) {STUCK_THRESHOLD} times in a row "
            "and it failed the same way every time. Repeating it again is not "
            "going to work. Try a genuinely different approach: a different "
            "selector, matching by visible text instead of a CSS selector, or "
            "calling get_page_state to re-orient yourself first."
        ),
    }


def run_task(task: str, max_steps: int = 15, use_routing: bool = True) -> dict:
    messages = [
        {"role": "system", "content": system_prompt(task, TOOLS)},
        {"role": "user", "content": task},
    ]
    trace: list[dict] = []
    last_failed_call: dict | None = None
    last_failed_error: str | None = None
    consecutive_failures = 0
    routing_checks = 0

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
            return {
                "outcome": "stuck",
                "steps": step + 1,
                "trace": trace,
                "routing_enabled": use_routing,
                "routing_checks": routing_checks,
            }

        if call["name"] in TERMINAL_TOOLS:
            trace.append({"step": step, "tool_call": call})
            outcome = TERMINAL_OUTCOMES[call["name"]]
            arguments = call["arguments"]
            summary = (
                arguments.get("summary")
                or arguments.get("reason")
                or arguments.get("question")
            )
            return {
                "outcome": outcome,
                "summary": summary,
                "steps": step + 1,
                "trace": trace,
                "routing_enabled": use_routing,
                "routing_checks": routing_checks,
            }

        result = execute_tool(call)
        trace.append({"step": step, "tool_call": call, "result": result})
        messages.append({"role": "tool", "content": json.dumps(result)})

        if result.get("success") is False:
            current_error = str(result.get("error", ""))
            if call == last_failed_call:
                consecutive_failures += 1
            elif (
                last_failed_call is not None
                and last_failed_error is not None
                and use_routing
            ):
                routing_checks += 1
                consecutive_failures = (
                    consecutive_failures + 1
                    if is_same_failure(
                        last_failed_call, last_failed_error, call, current_error
                    )
                    else 1
                )
            else:
                consecutive_failures = 1
            last_failed_call, last_failed_error = call, current_error
        else:
            last_failed_call, last_failed_error, consecutive_failures = None, None, 0

        if consecutive_failures >= STUCK_THRESHOLD:
            messages.append(_stuck_nudge(call))
            trace.append({"step": step, "stuck_nudge": True})
            last_failed_call, last_failed_error, consecutive_failures = None, None, 0

    return {
        "outcome": "max_steps",
        "steps": max_steps,
        "trace": trace,
        "routing_enabled": use_routing,
        "routing_checks": routing_checks,
    }


if __name__ == "__main__":
    # Hardcoded Tier-1 task: basic navigation + form login, checked manually
    # by reading the trace below rather than a scorer (that's Milestone 5).
    result = run_task(
        "Go to https://the-internet.herokuapp.com/login, log in with "
        "username 'tomsmith' and password 'SuperSecretPassword!', and "
        "report done once you see the logged-in confirmation message."
    )
    print(json.dumps(result, indent=2, default=str))
