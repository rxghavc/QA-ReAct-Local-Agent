"""Trims old tool-result payloads out of the growing message history.

Milestone 10 part 3 measured why this matters: agent/loop.py resends the
full conversation to Ollama every step with no prefix-cache reuse, and a
13-step checkout task actually billed 29,583 prompt tokens against 2,810
if the shared prefix had been reused
(docs/milestones/token-cost-accounting.md). The plan's own "context
length management... may need to summarize/truncate older steps"
question (docs/context-optimization-plan.md) is answered here with
deterministic code, not a model call: the same lesson agent/routing.py
already learned in Milestone 7 (a model is worse than structural code
at this kind of judgment) applies to "should something summarize the
history" too.

Two policies, both trimming only *tool*-role messages (the bulky
navigate/click/get_page_state results), never the assistant tool-call
messages that show what the model actually decided to do, and never the
most recent `keep_last` tool results:

- "partial": keeps `url`/`title` (small, and plausibly load-bearing for
  "which page am I on" narrative continuity across a multi-step task)
  but drops the bulky `headings`/`clickable` fields, which are
  superseded by the next fresher result anyway.
- "full": drops everything except `success` (and `error`, if the call
  failed), on the theory that only the most recent `keep_last` results'
  page-state detail is ever actually needed.

Which policy, and how large `keep_last` can be, without costing pass
rate or self-report accuracy is exactly the open question
docs/context-optimization-plan.md says the benchmark suite should
answer, not something decided here.
"""

from __future__ import annotations

import json

_PARTIAL_KEEP_KEYS = ("success", "url", "title", "error")
_FULL_KEEP_KEYS = ("success", "error")


def _trimmed_content(content: str, policy: str) -> str:
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(result, dict):
        return content
    keep_keys = _PARTIAL_KEEP_KEYS if policy == "partial" else _FULL_KEEP_KEYS
    trimmed = {k: result[k] for k in keep_keys if k in result}
    return json.dumps(trimmed)


def trim_history(messages: list[dict], keep_last: int, policy: str) -> None:
    """Mutates `messages` in place. Idempotent (re-trimming an
    already-trimmed message is a no-op), so this is safe to call once
    per step rather than needing to track what has already been done.
    A tool message whose content isn't valid JSON, which this project's
    own code should never write, is left untouched rather than risking
    corrupting history that can't be safely trimmed.
    """
    if policy not in ("partial", "full") or keep_last < 0:
        return
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    old_indices = tool_indices if keep_last == 0 else tool_indices[:-keep_last]
    for i in old_indices:
        messages[i]["content"] = _trimmed_content(messages[i]["content"], policy)
