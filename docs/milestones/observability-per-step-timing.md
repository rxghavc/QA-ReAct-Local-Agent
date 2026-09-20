# Observability, part 1: per-step timing breakdown

## What prompted this

The plan's post-MVP "Optimization & Evaluation" section has always said the first step is to "break down time-per-step: model inference vs. Playwright action vs. network/wait, find out where time actually goes before optimizing anything." Nothing in this project measured that before now; `wall_clock_seconds` was tracked per whole task, which cannot distinguish a slow model from a slow browser. `docs/ai-infra-and-observability.md` named this as the cheapest, most-likely-to-reshape-everything-else item to do first, specifically because this project's own architecture (resending the full growing conversation history to the model every single step) predicted model inference would dominate, and that was a hypothesis to check, not an assumption to build on.

## What changed

`agent/loop.py`'s `run_task` now times both sides of every step with `time.monotonic()`: the `ollama_chat` call (model inference) and the `execute_tool` call (the Playwright action, over HTTP to the browser container). Each trace entry carries `model_seconds` for every step, and `tool_seconds` for every step that actually reaches the browser (terminal-tool steps like `report_done` have no tool call, so no `tool_seconds`). The running totals, `model_seconds_total` and `tool_seconds_total`, are returned alongside the existing `outcome`/`steps`/`trace` fields.

`benchmark/runner.py` carries both totals through into the per-run log record, defaulting to `0.0` for skipped tasks (which never ran). `benchmark/report.py` aggregates them the same way it already aggregates steps and wall-clock time: an average per task, and an overall average across all scored runs, printed alongside the existing pass-rate summary. Old logs from before this change have neither field; `report.py` treats a missing value as `0`, so they average in rather than break the report or get silently excluded.

## What it found, immediately

Two live runs of `python -m agent.loop`, no benchmark suite involved, just the ad-hoc CLI:

```
run 1: outcome=done, steps=6, model_seconds_total=100.4, tool_seconds_total=2.1
run 2: outcome=done, steps=5, model_seconds_total=17.6,  tool_seconds_total=0.5
```

**Model inference dominates tool execution by roughly 35x in the second run, and by far more in the first**, which had one outlier step at 69.3 seconds of model time against 0.6 seconds of tool time for the same step. That confirms the hypothesis from the planning doc: Playwright, the part of this system that looks like it should be slow (real browser automation over HTTP), is nowhere close to the actual bottleneck. The model call is. This also means the planning doc's other observation, that this project's growing per-step conversation history is re-processed from scratch by Ollama on every single call with no prefix-cache reuse, is a real cost happening on every task run today, not a theoretical one.

This is one anecdotal pair of runs, not a measured claim the way this project's benchmark numbers are (three passes, spread reported). It's here because it's the first real evidence for a hypothesis, not a substitute for measuring it properly across the suite, which is a natural next use of this same instrumentation.

## What this establishes

- Every future run, benchmark or ad-hoc, now carries a real model-vs-tool time split, not just a black-box wall-clock number.
- The suspicion that model inference (not Playwright, not the browser container) is where time actually goes is now supported by real numbers instead of an architectural guess.
- The `.get(..., 0)` backward-compatibility pattern for a newly-added log field, already established for the `skipped` field in Milestone 7, held again here without needing to touch any historical log.

## What's next

Per `docs/ai-infra-and-observability.md`: a failure taxonomy next, since it's the second item in the plan's own post-MVP list and doesn't depend on this one. Token/cost accounting per step would sharpen the "model inference dominates" finding into an actual cost curve (is it growing linearly or worse across a long task's steps), and is a natural following step once this timing split has been useful for a while.