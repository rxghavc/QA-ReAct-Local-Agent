# Regression tracking over time

## What prompted this

The original plan's "Regression tracking" item, separate from the regression gate itself (Milestone 10 part 4): "re-run the full suite on every meaningful code change and log the pass-rate trend over time... turns the benchmark into a lightweight CI for the agent itself." The gate already answers "did this specific change regress anything," a point-in-time yes/no against a fixed baseline; this answers a different question a single gate run can't: how has the suite actually moved across many measurements. `logs/` can't answer that on its own either, it's gitignored and gets pruned/rotated locally, so nothing about it survives across machines or time by default.

## What changed

`benchmark/trend.py` (new): `append_entry`, `load_entries`, `format_trend`, backed by a committed `benchmark/trend.jsonl`, one small JSON line per real gate run (not the bulky per-task traces `logs/` holds). Each entry records the timestamp, the git commit short SHA at measurement time, the per-pass rates (not pre-averaged, so the spread this project insists matters is still visible later), min/mean/max, the gate threshold that was actually in force, and whether the gate passed.

`benchmark/regression_gate.py` appends to it by default on every run, since a gate run already is the "meaningful code change" checkpoint the plan asked to log against. `--no-record` opts a specific run out, for exploratory measurement that shouldn't pollute the permanent record, the same pattern already established by `--no-routing` and `history_trim`.

## What the first live entry actually caught

Running `python -m benchmark.regression_gate --repeat 2` live to verify this end to end (not just unit-test the pure functions) produced a real `GATE FAIL`, not a clean pass to screenshot:

```
GATE FAIL: mean pass rate 71% over 2 run(s) (75%, 67%) vs. gate threshold 80%
Recorded to trend.jsonl (1 entries total)
```

Rather than treat that as a fluke and quietly re-run until green, it got the same treatment every other unexpected number in this project has: find the mechanism before trusting or dismissing it. `task_07_js_confirm_dialog` failed both runs (0/2), against a 100% pass rate in every prior measurement this session. Reading the actual trace: in both runs, the agent called `handle_dialog(action="accept")` and then `report_done` immediately, **without ever calling `click()` on the "Click for JS Confirm" button that the task instruction explicitly names as the trigger.** No dialog ever fired; `handle_dialog` just set a flag that was never used; the agent claimed success anyway. This is `hallucinated_success`, an already-named category in the failure taxonomy, not a new bug and not something introduced by this session's own changes (nothing here touches dialog handling). It's the suite's documented run-to-run variance surfacing a real, if intermittent, existing weakness, on the very first real measurement this tool ever recorded.

That first entry stays in the committed `trend.jsonl` as-is, a real FAIL, not edited or discarded to make a nicer first data point. Hiding it would defeat the entire purpose of a trend log.

## What this establishes

- The trend record is now genuinely durable and separate from the gate's own pass/fail judgment for any one run: a future reader can see the suite's real trajectory over time, including this first real dip, not just whatever the most recent measurement happened to say.
- The mechanism worked exactly as intended on the very first live use: it caught a real regression signal (even if likely noise rather than a code-caused regression) instead of silently passing, and doing the actual trace-reading work confirmed it wasn't a false alarm from the tooling itself.
- `task_07`'s intermittent hallucinated-success failure (skipping the trigger action before the dialog handler) is now a documented, reproducible-today data point, not just a category name. Not chased further in this pass since it's a known category, but worth returning to if `trend.jsonl` shows `task_07` dipping repeatedly rather than once.

## What's next

This closes the last item ("regression-tracking over time") in Build Phases item 12's stretch list, alongside the already-decided-against WebArena/Mind2Web subset run. `benchmark/trend.jsonl` will accumulate real signal the more it's used; there's nothing to build further here until there's more history to look back on.