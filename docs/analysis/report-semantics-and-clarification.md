# Report semantics and clarification

## Why this was fixed

This work addressed a concrete problem in the agent loop: the project had a semantic mismatch around `report_done` and `report_blocked`, and the clarification trigger was being declared but never meaningfully used. The fixes were driven by real task failures, not by abstract prompt theory.

1. `task_11_impossible_login` was stuck at 0/3. The agent accurately narrated the login failure and then called `report_done` anyway, a tool-semantics mismatch, not a hallucination.
2. `task_10_invalid_login_rejected`'s success check asserted a DOM fact saucedemo produces unconditionally for that username, so it passed 3/3 whether or not the agent ever looked at the error, testing nothing about Tier 4's stated purpose.
3. `ask_clarification` had been declared on every turn and called 0 times across 36 task runs.

All three are measured, live-model findings, not code review guesses, so the fix for each needed the same discipline: change something specific, re-measure with `--repeat 3`, and read the result rather than assume the fix worked because it looked reasonable.

## Fix 1: report_done vs report_blocked, and why it took two tries

**First attempt: an abstract rule.** Added to `agent/prompts.py`: "report_done means the goal was achieved, not that you finished attempting it or successfully observed that it failed." Measured over three passes of the full suite. Result: **`task_11` stayed at 0/3.** Every run still ended with `self_report: "done"` and a summary reading "Login failed with message: 'Your username is invalid!'", identical in shape to the Milestone 8 baseline. The abstract framing changed nothing at all.

**Second attempt: a bright-line trigger plus a worked example.** Replaced the abstract rule with a concrete conditional: check whether the page shows the specific outcome the instruction describes, or an error instead; if it's the error, call `report_blocked`, even when the instruction's own wording says "report done once you see X." Then a worked example matching task_11's exact scenario almost verbatim, ending on "accurately describing a failure is not the same as the task succeeding." Measured the same way. Result: **3/3, all three passes**, `self_report: "blocked"` every time, with summaries like "Login failed: No confirmation message found."

**Why this matters beyond this one task.** This is the same lesson Milestone 6 already taught for self-correction prompting, now confirmed a second time on an unrelated behavior: `qwen2.5-coder:14b` responds to a concrete "if you see X, do Y, here is exactly what that looks like" instruction, and does not reliably act on a conceptual distinction, however clearly it is stated. Two data points is not a law, but it is now a pattern worth assuming rather than a one-off.

## Fix 2: tightening task_10's check

The old check, `dom_text_contains` on `h3[data-test="error"]`, asserted something saucedemo does unconditionally when you log in as `locked_out_user`: it does not depend on the agent reading anything. Switched to `report_contains` with `expected: "locked out"`, which requires the agent's own `report_done` summary to actually quote the error text. This can still not be satisfied by a hallucinated success, since it additionally requires `outcome == "done"`, so a blocked run that happens to mention "locked out" in its reason does not pass either.

Measured: **still 3/3**, now for the right reason, confirmed directly by `self_report_correct: true` on every run and summaries that genuinely quote the real error ("Epic sadface: Sorry, this user has been locked out."). The harder bar held.

## The ask_clarification experiment: a partial result, reported as one

Applied the same bright-line-trigger-plus-worked-example pattern that fixed report_done/report_blocked: a trigger condition (a superlative ranking word with no stated criterion, on a page with no single obvious answer for it) and a worked example closely matching `task_12`'s own scenario ("add the best book to the basket" with no single top-rated or cheapest book). Measured as its own isolated 3-pass run, layered on top of the already-confirmed Fix 1 and Fix 2 state, so the effect stays attributable to this change specifically.

**Result: it fired for the first time ever.** `needs_clarification` was called correctly on `task_12` in 1 of 3 runs, after 0 calls across every prior measurement in this project's history (36 runs at Milestone 8, then again through Fix 1's two iterations). The other 2 runs reverted to `report_blocked` after failing to find an "Add to basket" button, never engaging with the ambiguity question at all, a selector-hunting failure crowding out the ambiguity reasoning rather than a prompt-adherence miss.

**Checked for the failure mode explicitly named as a reason to remove the tool: false positives.** Went through all 36 logs from this run. `needs_clarification` appears exactly once, only on `task_12`, never on any of the other 11 tasks across all three passes. The "if it over-triggers, remove it" condition from the original plan did not fire either.

**Verdict: keep the tool, prompting alone only partially closes the gap.** 1/3 beats 0/3, and with zero false positives there's no cost being paid for the improvement, but it's not reliable, and the failure mode when it doesn't fire is different in kind from the report_done case. Closing it further would mean detecting the ambiguity trigger before the agent starts acting on the page, deterministically, rather than relying on the model to reason its way there under pressure from a stuck selector. That's a bigger change than a prompt tweak, so it's tracked as open future work rather than claimed as solved.

## The metrics, and why the aggregate mean is not the headline

Three passes, all three changes present (the final, `ask_clarification`-included configuration):

```
suite pass rate over 3 scored runs: min 58%, max 92%, mean 75%
```

| Pass rate | Tasks |
|---|---|
| 3/3 (100%) | saucedemo login, logout, dynamic loading, JS confirm dialog, pagination count, invalid-login rejection, **impossible task** |
| 2/3 (67%) | the-internet login, add to cart |
| 1/3 (33%) | checkout, **ambiguous instruction** |
| 0/3 (0%) | table extraction |

Traced the worst individual pass (58%, three tasks failing) through the actual traces rather than assuming it meant something. `task_01`, `task_03`, and `task_04` all failed on genuine Playwright selector-timeout or stale-navigation errors that specific run, all correctly self-reported as blocked (`self_report_correct: true` on each), unrelated to any of the three changes above. That is the suite's already-documented run-to-run variance (see [Benchmark trustworthiness](benchmark-trustworthiness.md) and Milestone 7), not a regression this work introduced.

**What is actually trustworthy here is the two deltas with a clear before/after mechanism, not the aggregate mean of three noisy passes:** `task_11` went from 0/3 to 3/3, and `ask_clarification` went from 0 calls in 36 runs to 1 correct call in 3, with no regression anywhere else. A mean computed from three passes on a suite with this much known variance is not a number to lean on by itself; these two specific, mechanistically-explained deltas are.

## What this establishes

- `report_done` vs `report_blocked` semantics on the negative-test tier: fixed, confirmed 3/3 across three passes, and the fix required a concrete trigger example, not an abstract rule.
- `task_10`'s check now genuinely tests observation, not a DOM side effect the agent merely caused.
- `ask_clarification` is demonstrably usable (fired correctly, zero false positives) but not yet reliable (1/3). Kept, not removed, with the gap named rather than hidden.

## What's next

Landed as PR #13, alongside PR #14's headed-mode toggle and ad-hoc task CLI (see `docs/how-to-run.md`) for filming the eventual demo. The next planned work is observability and serving infra, not more prompt tuning against a three-sample measurement: see `docs/ai-infra-and-observability.md` for the plan.