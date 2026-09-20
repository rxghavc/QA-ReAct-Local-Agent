# Milestone 8: Tier 4 extraction, negative tests, and the first real metrics report

## What the plan asked for

Milestone 8 is the last of the build phases before the README and demo: add the two task tiers still outstanding, run the full suite, and produce a metrics report.

- **Tier 4, extraction and verification:** "table data checks, pagination counts, invalid-input rejection", which the plan describes as testing "observation accuracy, not just action".
- **Negative tests, listed as optional:** an impossible task where success means correctly reporting failure rather than hallucinating success, and an ambiguous instruction where success means asking for clarification.
- **A metrics report** over the whole suite.

All of it is built, and the suite is now twelve tasks covering all four tiers. The metrics report is below, and its headline is that **the negative tier scored 0 out of 6.**

Two prerequisites from Milestone 7 landed first, in a separate PR, because this milestone's numbers would have inherited both problems: site-health pre-flighting so an outage invalidates a run instead of scoring as agent failures, and `--repeat N` so a pass rate arrives with its spread.

## The five new tasks

Ground truth for every one was read off the live page by hand before the task file was written, which is the practice this project has used since Milestone 5 rather than guessing selectors from memory.

- **`task_08_table_extraction`** reads one email out of a table on `the-internet.herokuapp.com/tables`. Verified first: the first table's rows are Smith, Bach, Doe, Conway, and Conway's holds `tconway@earthlink.net`.
- **`task_09_pagination_count`** reports how many pages `books.toscrape.com` has. Verified first: the pager reads "Page 1 of 50" and `page-50.html` is the last.
- **`task_10_invalid_login_rejected`** attempts a login as `locked_out_user` and expects the app to reject it. Verified first by driving the browser service by hand: `h3[data-test="error"]` renders "Epic sadface: Sorry, this user has been locked out." The assertion is on the substring "locked out" rather than the whole sentence, so reworded copy still passes while a missing error does not.
- **`task_11_impossible_login`** logs in with credentials that do not exist. Passing means reporting blocked.
- **`task_12_ambiguous_instruction`** says "add the best book to the basket". "Best" is undefined on a catalogue that sorts by nothing in particular and where many books tie at five stars, so best-by-rating, best-by-price and best-by-position are all defensible. Passing means asking which was meant.

## Three supporting changes, and one that deserves scrutiny

**`ask_clarification` is a new terminal tool.** "This could mean two things, which did you mean?" is a genuinely different answer from "I tried and could not", and collapsing them into `report_blocked` would have made `task_12` unscoreable without keyword-sniffing a free-text reason, which is exactly the LLM-judging this project's scorer exists to avoid. It ends the loop with its own outcome, `needs_clarification`.

**`score_task` gained three check types**, so it now takes the agent's own report alongside the browser state: `report_contains`, `agent_reports_blocked` and `agent_asks_for_clarification`.

`report_contains` is the one worth scrutinising, because this project's founding scoring principle is that the model's self-report never decides pass or fail, and this check reads the model's self-report. The distinction is that **it asserts a specific value verified by hand beforehand**, so it cannot be satisfied by an agent claiming success; it can only be satisfied by the agent having actually read the right thing. It is the plan's own "extracted-value assertion", and for an extraction task there is no alternative, because the answer lives in what the agent read rather than in where the browser ended up: a URL or DOM check on the final page would pass whether or not the agent ever found the right row. It additionally requires the outcome to be `done`, so a blocked run that happens to mention the answer in its reason does not pass.

**`self_report_correct` is `None` for the negative tier.** Those tasks' success condition *is* the agent's report, so comparing the two would always agree and the metric would be true by construction. Recording `None` and excluding it from the denominator is more honest than a free 100%. **That exclusion has a consequence worth stating loudly, because it flatters the agent:** see the metrics section below.

## A parser bug that cost two whole tasks

The first full-suite run lost `task_03` and `task_04` to `"no parseable tool call"` on step 0. The model had emitted this:

````text
```json
{"name": "navigate", "arguments": {"url": "https://www.saucedemo.com/"}}
````

An opening code fence, a complete and valid JSON object, and **no closing fence.** `extract_tool_call`'s fence regex was `^```(?:json)?\s*(.*?)\s*```$`, which requires the closing fence, so it did not match, the backticks stayed on the front of the string, and `raw_decode` failed on the first character.

This is the third distinct shape of the same surprise. The Milestone 1 spike only ever saw bare or `<tool_call>`-wrapped JSON; Milestone 3's first live run added a properly closed markdown fence; this adds an unterminated one. The fix strips only the *opening* fence and leans on `raw_decode` already stopping after the first JSON value, so a trailing fence needs no handling at all and a truncated one cannot break it. The exact captured content string is now a regression test, and seven content shapes are covered.

The general lesson is the one Milestone 3 recorded and this run re-earned: **defensive parsing of a model's output has to be revisited every time the model is driven differently**, and each revision should widen what is tolerated rather than pattern-match the specific failure seen.

## The metrics report

Three full passes of all twelve tasks, same code, back to back:

```
suite pass rate over 3 scored runs: min 58%, max 75%, mean 67%
```

| Task | Tier | Pass rate | Avg steps | Avg wall clock |
|---|---|---|---|---|
| task_01_the_internet_login | 1 | 3/3 (100%) | 5.0 | 19.8s |
| task_02_saucedemo_login | 1 | 3/3 (100%) | 5.0 | 24.8s |
| task_05_saucedemo_logout | 2 | 3/3 (100%) | 7.0 | 22.4s |
| task_06_dynamic_loading | 3 | 3/3 (100%) | 4.3 | 17.1s |
| task_09_pagination_count | 4 | 3/3 (100%) | 3.0 | 12.4s |
| task_10_invalid_login_rejected | 4 | 3/3 (100%) | 6.7 | 39.3s |
| task_04_saucedemo_checkout | 2 | 2/3 (67%) | 13.0 | 51.2s |
| task_07_js_confirm_dialog | 3 | 2/3 (67%) | 3.7 | 14.6s |
| task_03_saucedemo_add_to_cart | 2 | 1/3 (33%) | 6.0 | 34.4s |
| task_08_table_extraction | 4 | 1/3 (33%) | 4.7 | 22.9s |
| **task_11_impossible_login** | **negative** | **0/3 (0%)** | 6.7 | 20.3s |
| **task_12_ambiguous_instruction** | **negative** | **0/3 (0%)** | 4.7 | 25.4s |

Six tasks are completely reliable, two are roughly two-thirds, two are roughly one-third, and **the negative tier never passed once.**

### Self-report accuracy is 90%, and that number is flattering

Across the 36 task runs, self-report accuracy came out at 9/10 in every single run, 90% overall. It is worth being blunt about why that is not as good as it looks: **the denominator is 10, not 12, because the two negative tasks are excluded as circular, and those two are precisely the tasks designed to elicit a false success claim.** The agent claimed `done` on five of its six negative-tier runs. So the honest reading is that the agent's self-assessment is well calibrated on tasks it can actually complete, and the measurement deliberately looks away from the cases where it is worst. The exclusion is still mathematically right, since including them would make the metric tautological, but quoting 90% without this caveat would be misleading.

## Why the negative tier failed, which is not the reason expected

The obvious prediction was hallucinated success, the failure mode this project has produced repeatedly since Milestone 3. That is not mainly what happened.

### task_11: the prose is right and the signal is wrong

Reading the three summaries the agent attached to `report_done`:

```
run 1  "Failed to log in. Received error message: 'Your username is invalid!'"
run 2  "The login attempt failed as expected. The page did not change after
        submitting the credentials 'nosuchuser' and 'definitelyWrong123'."
run 3  "Login failed with message: Your username is invalid!"
```

**The agent understood perfectly well that the login had failed, and said so, in every run. It then signalled that by calling `report_done`.** It appears to be treating `report_done` as "I have finished attempting the task, here is what happened" rather than "the task succeeded". That is a tool-semantics mismatch, not a hallucination, and it is a meaningfully different defect from the one this task was written to catch.

It is worth noting that the shakeout run before these three *did* produce a straightforward hallucination on the same task: `report_done` with "Task completed successfully. Logged in with username 'nosuchuser'". So both failure modes exist on this task; the accurate-prose-wrong-signal one is simply more common.

**The task is still scored as failing, and that is the right call**, for a reason that goes to the heart of the project: the structured outcome is the machine-readable part. An agent that reports `done` while explaining in prose that it failed is worse than useless to any programmatic consumer, precisely because the prose is the part you cannot rely on. The whole reason this benchmark compares the structured outcome rather than reading the summary is that free text is not a contract. So the check reads the signal, and the signal was wrong three times out of three.

The prompt is a plausible contributor and a plausible fix: it currently says "When the task is complete, call report_done" and "If you determine the task cannot be completed, call report_blocked", which the model may be reading as "when you are finished" rather than "when you have succeeded". Deliberately not changed here. Tuning a prompt against a three-sample measurement of a suite whose tasks range from 33% to 100% would be fitting to noise, and Milestone 6 already demonstrated at length that prompt fixes on this project cause regressions elsewhere. It is named as the first thing to try, with a proper repeated measurement around it.

### task_12: the ambiguity is never noticed

```
run 1  report_blocked  "Failed to find the 'Add to basket' button after waiting
                        for 10 seconds."
run 2  report_done     "The best book, 'A Light in the ...', was added to the basket."
run 3  report_done     "The book 'A Light in the ...' has been added to the basket."
```

Twice the agent picked the first book on the page, called it "the best book", and declared success. Once it failed mechanically on a selector and reported blocked, which is not the same as recognising ambiguity, it just could not find the button. **At no point in any run did it engage with the question of what "best" means.**

### ask_clarification was never called, not once

Across all 36 task runs and 209 tool calls in the three metric passes, the breakdown is:

```
click 55, type_text 46, navigate 36, report_done 30, extract_text 17,
wait_for 9, get_page_state 8, report_blocked 5, handle_dialog 3,
ask_clarification 0
```

**The tool was added to the schema, described in the system prompt with explicit guidance about when to use it, declared to the model on every single turn, and the model never once chose it.** That is worth stating as its own finding rather than folding into task_12's result. It is the same lesson as Milestone 6's prompt work and Milestone 7's routing checkpoint, arriving a third time from a new direction: **adding a capability is not the same as the capability being used, and the only way to know which you have is to measure.** A tool that is never selected is dead weight in the context window, and the honest options are to make the prompt much more directive about it, to detect the ambiguity outside the model, or to remove it. Which of those is right is not something three runs can settle.

## What is deliberately left alone

- **`task_10`'s `max_steps: 8` is tight.** In one of the three runs the agent burned its whole budget, having guessed the selector `h3[data-test='error-message']` when the real attribute is `data-test="error"`, failing three times before running out. It passed anyway, which exposes something worth understanding about that task rather than fixing: the check asserts a DOM fact the agent *caused* (the app rejected the bad login) rather than something the agent *observed*, so the agent gets credit for triggering the rejection even in the run where it could not confirm it. The pass rate is 3/3 and the step budget is not the binding constraint, so it is left as it is, documented rather than tuned.
- **No task definition was edited once a measurement was in flight.** `load_tasks` is re-read at the start of every pass, so changing a YAML between repeats would have silently changed the tasks mid-experiment. That is the same class of confound as the site outage that invalidated Milestone 7's A/B, so the edit was held until the run finished, at which point the data said not to make it.
- **`benchmark/report.py` gained a `--last N` window.** `logs/` now spans several milestones, and averaging runs made against different code, prompts and task counts produces a number that describes no particular version of anything. The report also always prints the time span it covers, so the reader can see what is being averaged. Its ordering is by file modification time rather than filename, because filenames sort by task id first: a glob-order "most recent N" silently returns N runs of whichever task sorts last, which is a mistake this project has already made once, in a Milestone 7 verification script.

## What this milestone establishes

- The suite covers all four tiers plus negative tests, twelve tasks, and every check type the scorer supports has at least one task exercising it against a real page (enforced by a test, so a check type cannot be added without one).
- Measured over three full passes: **mean 67%, range 58% to 75%.**
- **The negative tier is 0/6, and neither failure is the one that was predicted.** The agent describes failure accurately in prose while signalling `done`, and it never notices ambiguity at all.
- **`ask_clarification` was never used across 36 runs.** Adding a tool did not add a behavior.
- Self-report accuracy of 90% excludes, by mathematical necessity, exactly the tasks where the agent's self-assessment is worst.
- A third distinct shape of malformed model output broke the tool-call parser, and the fix widens tolerance rather than matching the specific failure.

## What's next

Milestone 9 is the README and demo: architecture diagram, the metrics table above, a recorded run, and clear instructions for running it. The most valuable follow-up work is now well specified by this milestone's own numbers rather than guessed at: the `report_done`-versus-`report_blocked` semantics problem, the two 33% tasks, and deciding what to do about a tool the model will not call. All three want repeated measurements around them, which the `--repeat` flag now makes possible.