"""Spike: does a trivial same-task-id cache of past successful selectors
actually reduce selector drift when wired into a real, live run?

scripts/spike_selector_memory.py answered a cheaper, offline question
first, before this one touched a live model or browser: is there
anything to retrieve at all? Yes, decisively (17/17 real selector_drift
failures had a PASSED run of the exact same task_id somewhere in this
project's history, and 0/17 needed a different task's example). This
script tests the live effect of actually using that: inject the
successful selectors/text from every PASSED historical run of
task_04_saucedemo_checkout (the taxonomy's single worst task, 10 of the
17 real drift failures, see docs/milestones/failure-taxonomy.md) as a
hint appended to the system prompt, and compare against a baseline with
no hint, same task, same repetition count, same live model and browser.

Throwaway, kept as a permanent record the way the other spikes are.

One real methodological risk this deliberately guards against: running
the same task back-to-back several times in one persistent browser
session (browser/actions.py's BrowserSession holds a single page for the
life of the process) would leak saucedemo's login/cart state between
repetitions. A real benchmark pass never hits this, because eleven other
tasks run in between and naturally reset it. So this script restarts the
browser service fresh before every single repetition, and interleaves
the two conditions (baseline, hint, baseline, hint, ...) rather than
blocking them, so neither a stateful leak nor a time-of-day drift in the
model can bias one condition more than the other.

Run with the venv active and `ollama serve` already running, from the
repo root (needs `agent`/`benchmark` importable):
    python -m scripts.spike_selector_memory_live

Finding (2026-09-18, two independent batches, REPS_PER_CONDITION=3 each,
12 live runs total against the real local model and browser): **zero
selector_drift failures in either condition, across all 12 runs.**
Every baseline run passed; every hint run passed. That means this spike
cannot answer the question it was built to test: there is nothing to
reduce, because the failure it set out to fix never showed up live at
all, on either arm, despite this task's historical selector_drift rate
being 10/25 scored runs (40%) in the same logs/ this experiment's own
hint was built from.

The two batches also produced byte-for-byte identical step counts per
condition (baseline: 15, 15, 13; hint: 13, 13, 13 -- both times, in that
exact order), which is itself informative: this setup is close to
deterministic given a fixed prompt and task, not genuinely resampling
each run. So the historical 40% failure rate almost certainly isn't
sampling variance in the model's own decisions at all; it is more likely
explained by the fact that logs/ blends runs from before and after real
fixes (Milestone 6's click() bug, PR #13's report_done semantics), the
same caveat benchmark/report.py's own docstring already names for
aggregating across milestones. Re-running this exact experiment today
mostly measures *today's* code, which may simply be far more reliable on
this task than the stale aggregate suggests, not evidence the hint did
anything.

**What the hint condition did show, consistently and for free: every
hint run took exactly 13 steps; baseline took 15 steps in 4 of 6 runs and
13 in the other 2.** Given model inference dominates cost (Milestone 10
part 1) and the token-cost multiplier compounds with every added step
(Milestone 10 part 3), a same-task hint that reliably shortens the
trajectory by up to 2 steps is a real, if modest and unverified-on-
failures, latency/cost effect, not the failure-rate fix this spike set
out to measure. Whether it generalizes, and whether it actually reduces
drift on a version of the code that still produces drift live, are both
still open; this result does not settle either. The right next step, if
this is worth pursuing further, is running this same script against a
task/site combination still producing real selector_drift failures on
current code, not against one that has apparently already stopped.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx

from agent import loop as agent_loop
from agent.prompts import system_prompt as base_system_prompt
from benchmark.failure_taxonomy import classify_failure
from benchmark.runner import load_tasks, run_and_score
from scripts.spike_selector_memory import load_records, successful_targets

TASK_ID = "task_04_saucedemo_checkout"
REPS_PER_CONDITION = 3
BROWSER_PORT = 8001
BROWSER_URL = f"http://localhost:{BROWSER_PORT}"


def build_hint(task_id: str) -> str:
    """Every distinct successful (tool, target) pair from every PASSED
    historical run of this exact task, deduplicated but order-preserving,
    formatted as a system-prompt hint. Empty string if history has
    nothing (callers should treat that as "no hint available")."""
    seen: set[tuple[str, str]] = set()
    targets = []
    for record in load_records():
        if record["task_id"] != task_id or record["passed"] is not True:
            continue
        for target in successful_targets(record):
            key = (target["tool"], target["target"])
            if key not in seen:
                seen.add(key)
                targets.append(target)
    if not targets:
        return ""
    lines = "\n".join(f"- {t['tool']}(target={t['target']!r})" for t in targets)
    return (
        "\n\nHint from a previous successful run of this exact task: these "
        "actions worked, in roughly this order:\n" + lines
    )


def start_browser_service() -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "browser.server:app",
            "--port",
            str(BROWSER_PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=Path(__file__).parent.parent,
    )
    for _ in range(60):
        try:
            httpx.get(f"{BROWSER_URL}/get_page_state", timeout=1)
            return proc
        except httpx.HTTPError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("browser service did not become reachable in time")


def stop_browser_service(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_one(task: dict, hint: str, run_index: int) -> dict:
    if hint:
        agent_loop.system_prompt = lambda t, tools: base_system_prompt(t, tools) + hint
    else:
        agent_loop.system_prompt = base_system_prompt
    return run_and_score(task, run_index=run_index)


def main() -> None:
    task = next(t for t in load_tasks() if t["id"] == TASK_ID)
    hint = build_hint(TASK_ID)
    if not hint:
        print(f"No historical hint available for {TASK_ID}, nothing to test.")
        return
    print(f"Hint built from history:{hint}\n")

    results = {"baseline": [], "hint": []}
    conditions = ["baseline", "hint"] * REPS_PER_CONDITION  # interleaved, not blocked

    for i, condition in enumerate(conditions):
        proc = start_browser_service()
        try:
            record = run_one(task, hint if condition == "hint" else "", run_index=i)
        finally:
            stop_browser_service(proc)

        passed = record["passed"]
        category = None if passed else classify_failure(record)
        results[condition].append({"passed": passed, "category": category})
        print(
            f"[{i + 1}/{len(conditions)}] {condition}: "
            f"{'PASS' if passed else f'FAIL ({category})'}, "
            f"steps={record['steps']}"
        )

    agent_loop.system_prompt = base_system_prompt  # restore

    print()
    for condition, runs in results.items():
        passed_count = sum(1 for r in runs if r["passed"])
        drift_count = sum(1 for r in runs if r["category"] == "selector_drift")
        print(
            f"{condition}: {passed_count}/{len(runs)} passed, "
            f"{drift_count}/{len(runs)} selector_drift"
        )


if __name__ == "__main__":
    main()
