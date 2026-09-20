"""Spike: does qwen2.5-coder:14b-instruct-q8_0 fit and help, or just cost more?

docs/context-optimization-plan.md's third idea, explicitly gated on a
VRAM feasibility check before running anything: current Q4_K_M is ~9GB;
Q8_0 is 15.70GB (confirmed via the Ollama registry's manifest metadata,
no download needed to learn that); fp16 is 29.55GB, which alone exceeds
this machine's whole 24GB unified-memory budget and was ruled out
without ever being pulled. Q8_0 leaves ~8.3GB nominal headroom, tight
but not obviously infeasible, so it's the only variant worth actually
running.

The claim being tested, from docs/ai-infra-and-observability.md: 4-bit
quantization degrades structured-output reliability before fluent
prose, plausibly contributing to this project's three distinct
malformed-JSON shapes (Milestones 1, 3, 8). Measures pass rate, the
regression gate, unparseable_model_output count, and latency (model
inference already dominates tool execution by ~35x, so a slower model
is a real cost, not a rounding error) against the current baseline.

Swaps agent.loop.PLANNER_MODEL for the duration of the run rather than
adding a permanent model-selection knob, the same throwaway-script
pattern as scripts/spike_selector_memory_live.py: this is a speculative,
lowest-priority idea, not a feature to build in before knowing whether
it's worth shipping at all.

Run with the venv active, `ollama serve` running, and
`qwen2.5-coder:14b-instruct-q8_0` already pulled, from the repo root:
    python -m scripts.spike_quantization [--repeat N] [--smoke-test]
"""

from __future__ import annotations

import argparse
import time

from agent import loop as agent_loop
from benchmark.failure_taxonomy import classify_failure
from benchmark.runner import load_tasks, per_run_pass_rates, run_suite_repeated

Q8_MODEL = "qwen2.5-coder:14b-instruct-q8_0"


def smoke_test() -> None:
    """One short task, no suite overhead: does the model even load and
    complete a task in a reasonable time, before committing to a full
    --repeat comparison."""
    task = next(t for t in load_tasks() if t["id"] == "task_02_saucedemo_login")
    agent_loop.PLANNER_MODEL = Q8_MODEL
    start = time.monotonic()
    result = agent_loop.run_task(task["instruction"], max_steps=task["max_steps"])
    elapsed = time.monotonic() - start
    agent_loop.PLANNER_MODEL = "qwen2.5-coder:14b"
    print(
        f"smoke test: outcome={result['outcome']} steps={result['steps']} "
        f"wall_clock={elapsed:.1f}s model_seconds_total={result['model_seconds_total']}"
    )


def main(repeat: int) -> None:
    agent_loop.PLANNER_MODEL = Q8_MODEL
    try:
        runs = run_suite_repeated(repeat=repeat)
    finally:
        agent_loop.PLANNER_MODEL = "qwen2.5-coder:14b"

    rates = per_run_pass_rates(runs)
    print(f"Q8_0 pass rates: {[f'{r:.0%}' for r in rates]}")
    print(f"Q8_0 mean pass rate: {sum(rates) / len(rates):.0%}")

    scored = [r for run in runs for r in run if r["skipped"] is None]
    unparseable = sum(
        1
        for r in scored
        if r["passed"] is False and classify_failure(r) == "unparseable_model_output"
    )
    avg_model_seconds = sum(r["model_seconds_total"] for r in scored) / len(scored)
    print(f"unparseable_model_output failures: {unparseable}/{len(scored)} scored runs")
    print(f"avg model_seconds_total per task run: {avg_model_seconds:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="run one short task only, to check the model loads and completes at all",
    )
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test()
    else:
        main(args.repeat)
