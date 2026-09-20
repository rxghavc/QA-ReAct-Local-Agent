"""System prompts and few-shot examples for the planner and router models."""

from __future__ import annotations


def system_prompt(instruction: str, tools: list[dict]) -> str:
    """Build the planner's system prompt.

    qwen2.5-coder:14b doesn't reliably use Ollama's native tool-calling
    format (see scripts/spike_tool_calling.py), so this spells out the
    expected JSON shape directly rather than relying only on the `tools`
    parameter passed alongside it.
    """
    tool_lines = []
    for tool in tools:
        fn = tool["function"]
        params = ", ".join(fn["parameters"].get("properties", {}))
        tool_lines.append(f"- {fn['name']}({params}): {fn['description']}")

    return (
        "You are a web automation agent. You can only interact with the page "
        "through the tools listed below. Respond with exactly one tool call "
        'per turn, as a single JSON object: {"name": "<tool_name>", '
        '"arguments": {...}}. Do not wrap it in markdown and do not add '
        "commentary outside the JSON object.\n\n"
        f"Task: {instruction}\n\n"
        "Available tools:\n" + "\n".join(tool_lines) + "\n\n"
        "When the task is complete, call report_done with a summary. If you "
        "determine the task cannot be completed, call report_blocked with a "
        "reason instead of guessing or repeating an action that already "
        "failed."
    )
