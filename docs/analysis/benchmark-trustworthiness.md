# Benchmark trustworthiness

## Why this mattered

The benchmark had two issues that were not caused by the agent itself: some tasks were being scored during site outages, and a single run was being treated like a trustworthy measurement. Fixing both before publishing a project-wide report was the right move, because a metrics summary built on bad data is worse than no summary at all.

## Problem 1: an unreachable site scores as an agent failure

During Milestone 7's A/B comparison of the routing checkpoint, `the-internet.herokuapp.com` started returning HTTP 503 partway through, confirmed with `curl` while the run was in flight. Three of the suite's tasks depend on that site. The outage hit them inconsistently across the two halves of the comparison, so one half scored 4/7 and the other 2/7 for reasons that had nothing to do with the code being compared.

Worse, a run like this is indistinguishable from a real agent failure by just reading the log: the planner navigates, gets an "Application Error" page back, correctly calls `report_blocked`, and the scorer records a fail. Nothing in that trace says "the site was down," it looks exactly like the agent gave up on a working page.

**Fix: `benchmark/health.py` pre-flights every task's target site before running it.** A task whose site returns 400 or above is skipped rather than scored (`passed=None`), so an outage shrinks the denominator instead of quietly depressing the pass rate. Anything under HTTP 400 counts as reachable, deliberately, since a redirect or a login wall is not an outage, and the scorer's job is to judge whether the agent handled what it found, not whether the page looked exactly as expected.

## Problem 2: one run is not a measurement

Also from Milestone 7: six full suite runs of identical code produced 7/7, 7/7, 4/7, 2/7, 4/7, 5/7. That is real agent variance, not measurement noise from the harness, and no single run of the suite can distinguish a genuine regression from this baseline wobble.

**Fix: `--repeat N` on `benchmark/runner.py`.** Runs the whole suite N times back to back and reports each task's own pass rate across the runs, plus the min/max/mean spread for the suite as a whole. This turned "is the pass rate different" from an unanswerable question into a well-posed one: compare spreads, not points.

## A bug `--repeat` exposed, that would have silently destroyed data

Adding `--repeat` surfaced a latent problem in the existing log-writing code: log filenames only had second granularity (`<task_id>_<timestamp>.json`). A repeated run of the same task within the same second overwrote its own earlier pass's log file, and `benchmark/report.py` then read three runs' worth of intended data as if it were one. This would have made every `--repeat` measurement quietly wrong in a way that produced a plausible-looking but incorrect report, exactly the kind of silent data-loss bug that is worse than a crash. Filenames now carry a run index suffix (`_run0`, `_run1`, ...) so repeated passes of the same task in the same second cannot collide.

## What this establishes

- A task whose dependency is down is now distinguishable from a task the agent actually failed, in the report output itself, not just in someone's memory of "oh right, that site was flaky that day."
- `--repeat N` makes every subsequent measurement in this project (Milestone 8's metrics report, the two fixes before Milestone 9, any future A/B) a spread rather than a single number, which is the only honest way to report a pass rate on a suite this variable.
- The filename collision bug is a reminder that adding a new capability (repeated runs) to existing code can silently break an assumption (second-granularity uniqueness) that was true before the capability existed and stopped being true the moment it was used the way it was designed to be used.

## What's next

These two fixes are prerequisites, not the milestone itself. With them in place, Milestone 8's twelve-task, four-tier suite (see [08: Tier 4, negative tests and the first metrics report](08-tier4-and-negative-tests.md)) can report a number anyone can trust the shape of.