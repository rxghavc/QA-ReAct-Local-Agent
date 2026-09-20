"""Spike: would a memory of past successful selectors help fix selector
drift, the failure taxonomy's largest real bucket (17/63, see
docs/milestones/failure-taxonomy.md)?

Thrown together the same way scripts/spike_3b_routing.py was: cheap,
offline, against this project's own real captured data (the 238 real
logs in logs/, gitignored but sitting on disk from every milestone's
runs), before writing a line of embedding code or touching the live
agent loop. The question that actually decides whether retrieval is
worth building at all: for a real selector_drift failure, was the
correct selector/text ever demonstrated by a PASSED run somewhere in
this project's own history? If the answer is usually no, there is
nothing to retrieve, and building a vector store (or any memory at all)
can't fix anything.

A second, sharper question, since this suite runs the same fixed 12
tasks repeatedly rather than paraphrased instructions at runtime: does
the "yes" ever come only from a PASSED run of a genuinely DIFFERENT task
on the same site? That's the case that would actually justify embeddings
or some other similarity search instead of a plain dict keyed by
task_id, since a same-task hit is recoverable with no retrieval
machinery at all, just a cache.

Run with the venv active, no live model or browser needed, from the repo
root (needs `benchmark` importable, so `-m` rather than a bare path):
    python -m scripts.spike_selector_memory

Finding (2026-09-18, all 238 real logs accumulated across every
milestone, 175 passed): **every single real selector_drift failure,
17/17, has a PASSED run of the exact same task_id somewhere in this
project's history.** Zero needed a different task's example (the
cross-task-only bucket below is 0/17). That means, for this specific
benchmark suite, a plain dict keyed by task_id captures the entire
retrieval ceiling: there is no case where cross-task semantic similarity
recovers something a trivial same-task cache wouldn't already. That
result is a direct consequence of how this suite is built, not a claim
about selector memory in general: it re-runs the same fixed 12 tasks
repeatedly rather than paraphrasing instructions at runtime, so "has this
exact task ever passed before" is a strong, cheap signal here in a way
it would not be for varied, ad-hoc user instructions.

So building embeddings or any vector store for this suite as it exists
today would add real complexity (a local embedding model, a similarity
search, a new failure mode if retrieval hands back a stale or wrong
target) for zero measured coverage beyond what a same-task-id dict
already gives for free. If this is worth pursuing further, the next
question is not "does retrieval help" (this answers that: not here, not
yet) but "does a trivial same-task cache actually fix selector drift
when wired into the live loop," which is a different, cheaper experiment
than the one this spike was scoped to test.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from benchmark.failure_taxonomy import classify_failure

LOGS_DIR = Path(__file__).parent.parent / "logs"
_TARGET_TOOLS = {"click", "wait_for", "type_text"}


def _site(record: dict) -> str | None:
    """The domain the task actually ran against, read off the first
    navigate call in the trace. final_state's url is post-task, not
    necessarily the site a blocked/stuck run was even on."""
    for step in record.get("trace", []):
        call = step.get("tool_call", {})
        if call.get("name") == "navigate":
            url = call.get("arguments", {}).get("url", "")
            if url:
                return urlparse(url).netloc
    return None


def successful_targets(record: dict) -> list[dict]:
    """Every (tool, selector-or-text) pair that actually worked in this
    run: the raw material a "what worked before" memory would store."""
    targets = []
    for step in record.get("trace", []):
        call = step.get("tool_call", {})
        result = step.get("result", {})
        if call.get("name") in _TARGET_TOOLS and result.get("success"):
            args = call.get("arguments", {})
            target = args.get("selector") or args.get("text")
            if target:
                targets.append({"tool": call["name"], "target": target})
    return targets


def load_records(logs_dir: Path = LOGS_DIR) -> list[dict]:
    records = []
    for path in sorted(logs_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if record.get("skipped") is not None:
            continue
        records.append(record)
    return records


def main() -> None:
    records = load_records()
    passed = [r for r in records if r["passed"] is True]
    drift_failures = [
        r
        for r in records
        if r["passed"] is False and classify_failure(r) == "selector_drift"
    ]

    passed_targets_by_task: dict[str, list[dict]] = defaultdict(list)
    passed_targets_by_site: dict[str, list[dict]] = defaultdict(list)
    for r in passed:
        targets = successful_targets(r)
        passed_targets_by_task[r["task_id"]].extend(targets)
        site = _site(r)
        if site:
            passed_targets_by_site[site].extend(targets)

    same_task_available = 0
    cross_task_only = 0
    nothing_available = 0
    examples: list[str] = []

    for failure in drift_failures:
        task_id = failure["task_id"]
        site = _site(failure)
        same_task_targets = passed_targets_by_task.get(task_id, [])
        cross_task_targets = passed_targets_by_site.get(site, []) if site else []

        if same_task_targets:
            same_task_available += 1
        elif cross_task_targets:
            cross_task_only += 1
            examples.append(
                f"  {task_id} on {site}: no passed run of this task, but "
                f"{len(cross_task_targets)} successful target(s) exist from "
                f"other tasks on the same site, e.g. {cross_task_targets[0]}"
            )
        else:
            nothing_available += 1

    total = len(drift_failures)
    print(f"Real logs scanned: {len(records)} ({len(passed)} passed)")
    print(f"Real selector_drift failures analyzed: {total}")
    if total:
        print(
            f"  same task has a PASSED run somewhere in history: "
            f"{same_task_available}/{total} ({same_task_available / total:.0%})"
        )
        print(
            f"  no same-task pass, but a different task on the same site "
            f"passed: {cross_task_only}/{total} ({cross_task_only / total:.0%})"
        )
        print(
            f"  nothing usable anywhere (same task or same site): "
            f"{nothing_available}/{total} ({nothing_available / total:.0%})"
        )
    if examples:
        print("\nCross-task-only examples:")
        for line in examples:
            print(line)


if __name__ == "__main__":
    main()
