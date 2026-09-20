# Milestone 7: 3b model routing

## What the plan asked for

The project plan's Model Routing section proposes using both local models purposefully rather than treating the small one as a resource-constraint footnote: `qwen2.5-coder:14b` does the real planning and page-state reasoning, and `llama3.2:3b` handles "cheap, fast checks that don't need deep reasoning." It names two such checks:

1. "Does this page state indicate the task is likely complete?", a binary classifier meant to run after every step, to decide whether to even bother calling the 14b model again.
2. "Is this the same failure as last step?", a dedup check feeding the stuck-detection logic built in Milestone 6.

The plan also says what to report: "latency and step-count with vs. without 3b routing, and whether routing causes any success-rate regression," and explicitly says not to inflate the result.

**Both proposed uses were measured and both were rejected.** The milestone still ships a working same-failure check, which broadens Milestone 6's stuck detection exactly as planned. It just does the check in code, because that is what the measurements supported. `scripts/spike_3b_routing.py` is the reproducible harness, kept as a permanent record the way Milestone 1's tool-calling spike was.

## Use case 1: "is the task complete?", rejected up front

Asked for a single-word yes/no verdict on whether a described page state meant the task was finished, `llama3.2:3b` showed a strong default bias toward "no" that had very little to do with the page content. Confirmed across six or so deliberately varied cases, including one designed to be impossible to get wrong: task "complete checkout", page heading "Thank you for your order!". The model still answered "No."

Asking for one sentence of reasoning before the forced answer fixed that single canonical case but still failed on realistic ones. A page whose only meaningful change was a "Logout" button appearing, which is exactly how the suite's login tasks signal success, was not recognised as a completed login.

One incidental finding from that investigation mattered a great deal later: embedding the page state as a raw Python list or dict repr, which is the shape it arrives in from `BrowserSession._summary()` (for example `headings: ['Secure Area']`), reintroduced the bias even with reasoning-first framing, while describing the same facts in plain prose worked noticeably better. **This model handles code-like syntax pasted into a prompt worse than ordinary English.** Remember that, because it is about to produce a false positive.

A classifier that answers "not done yet" almost regardless of the page is a near-permanent no-op at best and a wrong signal at worst, so it was not wired in.

## Use case 2: the same-failure check, which took three attempts to get right

### Attempt 1: it passed its tests, shipped, and was wrong in production

The dedup check was tested the same reasoning-first, plain-prose way, and it passed everything tried:

- Two similar but different wrong selectors for the same button: "same".
- A click failure against an unrelated `wait_for` timeout: "different".
- Two different wrong selectors for saucedemo's "Add to cart" button: "same".

So it shipped, as `agent.routing.is_same_failure`, wired into `agent/loop.py` to broaden Milestone 6's stuck detection past byte-for-byte identical tool calls. Unit tests covered the parsing, both conservative-`False` fallbacks, and the loop wiring from both directions.

Then the benchmark suite ran for real, and something failed for the first time since Milestone 6. **The checkpoint fired three times and returned the wrong answer all three times.**

In `task_04_saucedemo_checkout`, steps 7, 8 and 9 were three consecutive failed clicks at the same checkout button:

```
step 7  click text='Checkout'                     -> no clickable element matched
step 8  click text='CHECKOUT'                     -> no clickable element matched
step 9  click text='CHECKOUT: YOUR INFORMATION'   -> no clickable element matched
```

That is the exact pattern the check exists for: the planner guessing a different label for the same button each attempt, which exact matching can never catch because no two attempts are identical. The log says `routing_checks: 2` and `stuck_nudge: 0`. Both checks came back "different", so no re-plan nudge ever fired. `task_05_saucedemo_logout` did the same thing with a click on `.bm-burger-menu` followed by a `wait_for` timeout on that same selector, judged "different" again.

Re-tested against those real error strings, five trials each, the picture was unambiguous:

| Pair, all plainly the same mistake | "same" verdicts |
|---|---|
| `'Checkout'` vs `'CHECKOUT'` | 2/5 |
| `'CHECKOUT'` vs `'CHECKOUT: YOUR INFORMATION'` | 2/5 |
| click `.bm-burger-menu` vs `wait_for` the same selector | 0/5 |

So the three wrong answers in the live run were not bad luck, they were the expected rate. The model's own reasoning showed what it was doing: it treated a surface difference in the error text as a difference in strategy, saying "the text 'Checkout' was replaced with 'CHECKOUT', making the Locator's text parameter case-sensitive."

**Why the tests passed and production didn't** is the useful part. The hand-written test cases were short, clean strings like `"no match for .a"`. Real Playwright errors are dense with code-like syntax:

```
no clickable element matched selector=None text='Checkout': Locator.click:
Timeout 5000ms exceeded.
Call log:
  - waiting for get_by_text("Checkout").first
```

That is exactly the input shape this same milestone had already established the model handles badly, in the use-case-1 investigation, a few hours earlier. The finding was there and it was not applied to the thing being built. A test suite made of tidy fixtures validated a component whose real inputs are messy, and the gap did not show up until live failures appeared, which took an entire extra benchmark run because Milestone 6 had made failures rare.

### Attempt 2: the fix that looked like it worked, and was worse

The obvious repair followed directly from that: normalise each failure into a prose sentence before asking the router. A `describe_failure` helper turned the raw error into "The agent tried clicking the button or link labelled Checkout, but nothing clickable on the page matched that", and the prompt was reframed to ask whether the agent was "stuck" or had "moved on", with explicit guidance that changing the wording or capitalisation of a guess still counts as stuck.

All three real cases then scored 5/5. It looked fixed.

It was not fixed. The same harness run against three deliberately-different control pairs (a cart button versus an unrelated `#finish` wait, a failed password field versus a checkout click, a DNS failure versus a burger-menu click) scored **5/5 "stuck" on every single one of those too**. The guidance sentence had simply made "stuck" the favoured answer. The mechanism had become a function that always says yes, which is strictly worse than the original: instead of missing real repeats it would now fire spurious re-plan nudges at a planner that was making perfectly reasonable progress.

**Without negative controls this would have shipped looking like a success**, with three green positive cases to show for it. That is the second methodology lesson of this milestone, and it is a sharper one than the first: a classifier validated only on the cases it is supposed to catch cannot be distinguished from a classifier that catches everything.

### Attempt 3: measuring whether the model can do this at all

At that point the right question was no longer "which prompt works" but "does this model discriminate on this task at all, or is it just echoing the framing it is given?" Two data points already pointed at the latter: use case 1 defaulted to "no", and attempt 2 defaulted to "stuck".

So five prompt strategies were measured against the same six pairs, three real same-mistake pairs and three controls, five trials each. Separation is the worst positive rate minus the best negative rate, so anything at or below zero means the variant cannot tell the two groups apart:

| Variant | POS A | POS B | POS C | NEG D | NEG E | NEG F | separation |
|---|---|---|---|---|---|---|---|
| raw errors, same/different | 0.4 | 0.4 | 0.0 | (not run) | | | n/a |
| prose, pro-stuck guidance | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | +0.0 |
| balanced framing, run 1 | 0.8 | 0.8 | 0.0 | 0.2 | 0.2 | 0.0 | **-0.2** |
| balanced framing, run 2 | 0.4 | 0.8 | 0.2 | 0.6 | 0.4 | 0.4 | **-0.4** |
| narrower same-element, run 1 | 0.8 | 1.0 | 1.0 | 0.6 | 1.0 | 0.6 | **-0.2** |
| narrower same-element, run 2 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | +0.0 |
| few-shot, both runs | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | +0.0 |

**Not one strategy separated the groups.** The variants that do not simply answer "same" every time are unstable on identical inputs between runs, which is its own answer. A negative separation is not just "no better than chance", it means the model ranked genuinely-different failures as *more* alike than the real repeats.

`llama3.2:3b` cannot do this classification, and no amount of prompt engineering inside this milestone's budget changed that.

## What shipped instead

`agent/routing.py`'s `is_same_failure` is now deterministic and makes no model call. The judgement it needs ("were these two failed actions aimed at the same thing?") is a comparison of the targets the planner itself named in its own tool-call arguments. Each target is reduced to a lowercase word sequence, with every non-alphanumeric character treated as a word break, so `#add-to-cart-sauce-labs-backpack` becomes `add to cart sauce labs backpack` and a visible label and the selector for the same control become comparable. Equal targets are the same mistake, and so is a whole-word containment match either way round:

```python
previous_target = failure_target(previous_call)
current_target = failure_target(current_call)
if not previous_target or not current_target:
    return False
if previous_target == current_target:
    return True
shorter, longer = sorted((previous_target, current_target), key=len)
if len(shorter) < MIN_SUBSTRING_TARGET:
    return False
return _contains_whole_words(longer, shorter)
```

Matching on whole words rather than raw substrings is what stops the separator normalisation from inventing new false positives: `art` must not match inside `smart button`, and `#a` must not match inside `#aside`. Targets under three characters are matched only exactly on top of that. Either call naming no target returns `False`, preserving the original conservative bias: a missed dedup costs one ordinary retry, while a wrong "same" suppresses a re-plan the planner actually needed.

It gets every case right, deterministically, with no inference cost and no variance between runs.

The error strings stay in the signature, accepted but not inspected. They carry no signal the targets don't already carry, and the classifier that did read them is the one that got rejected.

The six pairs are now regression tests (`tests/test_routing.py`), positives and controls together, so a future change has to keep getting both groups right rather than just the ones it was built for. A separate loop-level test drives `run_task` through the real function, unmocked, on the actual `'Checkout'` then `'CHECKOUT'` pair from the failing trace, and asserts a nudge fires.

`use_routing` is still threaded through `run_task` and `benchmark/runner.py`, and `python -m benchmark.runner --no-routing` still reproduces Milestone 6's exact-match-only behavior, so the A/B switch and the `routing_checks` metric in every run log survive the change. Routing is still a real, measurable part of the loop. It just no longer spends an inference call to get a less reliable answer.

## The deterministic check, validated live

The suite was then run again both ways with the deterministic check in place. **It fired, and for the first time in this project the stuck-detection mechanism demonstrably changed the planner's behavior mid-task.** From `task_03_saucedemo_add_to_cart`:

```
step 5  click     text='Add to cart'                        -> failed
step 6  wait_for  selector='#add-to-cart-sauce-labs-backpack' -> failed
step 7  click     selector='#add-to-cart-sauce-labs-backpack' -> failed
step 7  STUCK NUDGE FIRED
step 8  get_page_state {}                                    -> ok
```

Steps 6 and 7 aim at the identical selector through two different tools, which is the cross-tool case exact matching can never catch and the rejected classifier scored 0/5 on. The check matched them, the nudge fired, and the planner responded by calling `get_page_state` to re-orient, one of the three things the nudge explicitly suggests. That is the mechanism working exactly as designed, observed in a real trace rather than a unit test.

**It did not rescue the task, and the pass rate did not improve.** `task_03` still hit its step budget, in both configurations. The routing-on run scored 4/7 against routing-off's 5/7, on 48 steps versus 50, and the one task that differed (`task_01`) failed for a reason routing has nothing to do with: a recurrence of the Milestone 3 `#login`-is-a-form-id bug, where the click "succeeds" against the form element, `wait_for('#flash')` times out, and the planner calls `get_page_state`, sees it is still on the login page, and calls `report_done("Logged in successfully")` anyway. The "verify real evidence before reporting done" prompt rule from Milestone 6 failed again, this time with the evidence already fetched and sitting in context.

So the honest claim is narrow and worth stating precisely: **the mechanism is correct, fires on the real cases, and visibly changes what the planner does next. Whether that converts into a higher pass rate is not measurable on a seven-task suite with this much variance, and in this sample it did not.** One task budget saved is not a result.

**That trace also exposed a miss, which has since been fixed.** Steps 5 and 6 are the same mistake too: the same "Add to cart" button, once by visible text and once by selector. The first version of the check judged them different, because `add to cart` is not a substring of `#add-to-cart-sauce-labs-backpack` while the hyphens are in the way, so the nudge fired a step later than it could have. Treating every non-alphanumeric character as a word break fixes it, and this is the case that motivated doing so.

Doing that safely needed a second change, though, which is the more interesting half. Normalising separators makes far more strings look alike, and a plain substring test would then start matching mid-word: `art` inside `smart button`, `cart` inside `chart container`. So containment now has to align on whole words. Both halves were checked together against fourteen cases, the six original ones plus the live miss plus five deliberately-constructed false-positive risks, and all fourteen are in `tests/test_routing.py`. **The same lesson as attempt 2, applied deliberately this time rather than after the fact: a change that makes a matcher more permissive has to be measured against what it should still reject, not just against what it should now catch.**

Replaying both of that run's `task_03` traces through the old and new logic, which is deterministic and so does not need another live run to measure:

| Trace | exact match only | as first shipped | with the fix |
|---|---|---|---|
| routing-on (failures at steps 5, 6, 7, 9) | no nudge | nudge at step 7, 2 checks | **nudge at step 6, 1 check** |
| routing-off (failures at steps 4, 5, 7, 8) | no nudge | n/a, routing disabled | **nudges at steps 5 and 8** |

So the fix intervenes one step earlier on the first trace, and twice on a trace where exact matching never fired at all. Neither of these rescued the task when it ran live, and that remains the honest position: the mechanism now catches the cases it was designed for, measurably earlier, and there is still no evidence that catching them converts into a higher pass rate on a suite this small and this variable.

## The benchmark turned out not to be a stable baseline

Milestone 6 ended on 7/7 and this milestone opened by treating that as a baseline. Four full suite runs later, that was not a safe assumption:

| Run | Result | Notes |
|---|---|---|
| Sample 1, routing on | 7/7 | 0 routing checks, no failed steps at all |
| Sample 1, routing off | 7/7 | 0 routing checks, no failed steps at all |
| Sample 2, routing on | 4/7 | 3 routing checks, the 3b classifier wrong on all three |
| Sample 2, routing off | 2/7 | external outage, see below |
| Sample 3, routing on | 4/7 | 2 routing checks, deterministic, nudge fired correctly |
| Sample 3, routing off | 5/7 | same two genuine failures as sample 3 routing-on |

**Six full runs of the same seven tasks, no code change between the pairs, and the pass rate ranged from 2/7 to 7/7.** Two things came out of that spread, and neither is about routing.

**The suite depends on live third-party sites, and one of them went down in the middle of an experiment.** Partway through sample 2, `the-internet.herokuapp.com` began returning HTTP 503 "Application Error", confirmed directly with `curl` while the run was in flight. That site backs three of the seven tasks (`task_01`, `task_06`, `task_07`), and it hit them inconsistently: one of the three failed in the routing-on run and all three failed in the routing-off run. So sample 2's 4/7 versus 2/7 is not a routing effect, it is an outage that moved between the two halves of the comparison. **A benchmark whose pass rate depends on a third party's uptime cannot support an A/B comparison at all**, and that is a design weakness in the suite rather than a bad run. The plan chose "stable, automation-friendly demo sites" specifically to avoid fragility, and they are still external dependencies. Worth fixing before any optimization work leans on these numbers, most likely with a health check that aborts or marks a run as invalid rather than scoring it, and ideally local fixtures for the tasks that don't specifically need a live site.

**Sample 1's clean sweep was not evidence the agent is reliable.** Two 7/7 runs in a row, with zero failed steps anywhere, made it reasonable to conclude that Milestone 6 had fixed the failure modes and that the routing checkpoint simply had nothing to do. Sample 2 produced two genuine agent failures on saucedemo (`task_04`, `task_05`) of exactly the Milestone 5 class, bad label guesses, with no code change in between. The pass rate on this suite has real run-to-run variance, so **a single run of it is not a measurement**, and the regression tracking the plan describes needs repeated runs per configuration before any pass-rate delta means anything.

## What this milestone establishes

- Both 3b use cases the plan proposed were measured against the live model and both were rejected on evidence, with a reproducible harness kept in `scripts/spike_3b_routing.py`.
- The same-failure check the plan wanted is shipped and working, deterministically, verified against the real failing traces plus controls, and observed firing correctly in a live run where it changed what the planner did next. It did not raise the pass rate in that run, and one nudge is not a result.
- `llama3.2:3b` follows prompt framing rather than content on this class of judgement. Across five strategies, separation never rose above zero.
- Clean fixtures hid a real defect: the component passed tidy hand-written tests and failed on messy production inputs, in a way this milestone's own earlier finding predicted.
- Negative controls are what caught the second attempt. Positives-only validation cannot distinguish a working classifier from one that always says yes.
- The benchmark suite is not yet a stable baseline, for two separate reasons: third-party site outages and genuine run-to-run variance in the agent, measured at 2/7 to 7/7 across six runs of identical code.
- The Milestone 3 `#login`-is-a-form-id failure recurred, with the planner fetching `get_page_state`, seeing it was still on the login page, and reporting success anyway. Milestone 6's "verify before reporting done" prompt rule does not hold reliably, which is more evidence for the same point that milestone made: prompting shifts behavior without guaranteeing it.

The honest summary of the plan's own question, "does 3b routing cut latency or step count," is that the question dissolved. There is no 3b call left in the loop to measure, because the measurement said the call was worse than useless. The check it was meant to perform now costs nothing at all, which is a better outcome than the latency saving the plan was hoping to report, arrived at the opposite way round.

## What's next

Milestone 8 adds the Tier 4 extraction and verification tasks plus the negative tests (an impossible task where correctly reporting failure is the pass condition, and an ambiguous instruction where asking for clarification is), then runs the full suite for a real metrics report. Two things from this milestone should land first or alongside it: site-health handling so an outage invalidates a run instead of silently scoring it as failures, and repeated runs per configuration so a pass rate comes with some idea of its variance.