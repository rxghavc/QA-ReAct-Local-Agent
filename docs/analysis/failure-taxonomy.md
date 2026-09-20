# Failure taxonomy

## Why this exists

The project needed a way to explain why tasks failed instead of only reporting a pass/fail aggregate. The method was explicit: read real failed runs by hand first, identify the actual failure modes, and only then write rules to classify them. This follows the same pattern the project used elsewhere after a false start: a classifier trained on tidy fixtures was not trusted until it had been checked against real traces.

`logs/` contains the full run history for the project. Across the recorded milestone runs, 63 were failures, and each one was inspected before any classification rule was added.

## What the real failures actually looked like

Grouped by hand from the 63 real failed runs, before any code existed:

- **Selector drift.** By far the largest group. The model guesses a CSS selector or a visible-text string that never matches anything real on the page (`.btn_primary:first-child`, `#add-to-cart-sauce-labs-backpack`, `get_by_text("CHECKOUT")` when the real text is different), and `Locator.click`/`Locator.wait_for` times out. Concentrated in `task_03`, `task_04`, `task_05`, and `task_12`'s hunt for an "Add to basket"/"Add to cart" button.
- **Hallucinated success.** A click "succeeds" (no Playwright error) against the wrong element, and `report_done` gets called with no verification step in between; or `extract_text` succeeds but returns the wrong table row's value, and that wrong value gets confidently reported. Two different mechanisms, same higher-level defect: the self-report says done, reality says no.
- **The negative tier's own two failure modes**, already named in Milestone 8 and the report_done fix: `task_11` narrating its own failure accurately and then calling `report_done` anyway (a tool-semantics mismatch, not a hallucination), and `task_12` never engaging with what "best" means at all.
- **A genuinely different browser-layer error**: `task_08` guessing `:contains(...)`, a jQuery pseudo-class that does not exist in a real browser's `querySelectorAll`, throwing a JavaScript `SyntaxError` rather than a plain timeout. Worth its own category, not folded into selector drift, because the fix is different: teach the model what CSS actually supports, not "try a different selector."
- **The site itself failing**, from Milestone 7's `the-internet.herokuapp.com` outage: a page titled "Application Error" with an otherwise-normal-looking navigate result, and one case of a raw network-level `net::ERR_TIMED_OUT`.
- **A malformed model response** the parser can't read at all: the two Milestone 8 unterminated-fence cases, `outcome: "stuck"`.
- **One case that didn't fit any of the above**, read in full rather than forced into a bucket: the agent clicked, correctly noticed via `get_page_state` that the URL and headings hadn't changed, and correctly called `report_blocked`, exactly the right behavior, but the underlying click had silently done nothing (landed on an inert element), so the task still failed. This is a real, previously-documented bug shape (Milestone 3's `#login`-is-a-form-id issue, and its Milestone 7 recurrence), just caught this time instead of hallucinated past. It stays `unclassified` rather than being forced into an existing bucket it doesn't really fit.

**Two categories the plan's own suggested list named, "premature give-up" and "context overflow", have zero real examples anywhere in these 238 runs.** Every `report_blocked` in this corpus that looked at first glance like giving up early turned out, on reading the actual trace, to be either a real site outage or a real selector failure after multiple genuine attempts. Inventing a rule for a pattern that has never happened would be guessing, not categorizing, so neither is in the taxonomy. That absence is itself worth stating rather than quietly ignoring.

## A false positive caught before shipping

The first version of the `environment_flakiness` rule checked whether a `navigate` call returned a page with empty `headings` and empty `clickable` lists, on the theory that a broken page has nothing on it. Run against the real 63 failures, it classified 23 of them as environment flakiness, more than a third. Reading a sample of those 23 instead of trusting the count: saucedemo's real, healthy login page also has empty `headings` and empty `clickable`, because its submit button is an `<input>` element, and Playwright's `all_inner_texts()` returns nothing for an element that has no inner text, an attribute value doesn't count. The rule was flagging a normal, working page as an outage on every single saucedemo task.

Fixed by checking the actual distinguishing signal instead of a generic proxy: the page's title is literally `"Application Error"` for the-internet's real crash page, and a real network failure shows up as a `net::ERR_*` string in a failed tool result. Re-run against the same 63 failures, `environment_flakiness` dropped from 23 to 5, which matches the actual count of real outage-affected runs from Milestone 7. This is exactly the kind of mistake the plan's "validate on real captured inputs" discipline exists to catch, and it would have shipped quietly wrong if the count alone had been trusted instead of the underlying examples.

## What the taxonomy looks like, run for real

`python -m benchmark.report` (all 238 logs, spanning every milestone and fix in this project, not a single comparable configuration):

```
Failure taxonomy (fix the largest bucket first):
  selector_drift: 17
  hallucinated_success: 16
  ambiguity_not_recognized: 13
  tool_semantics_mismatch: 6
  environment_flakiness: 5
  invalid_selector_syntax: 3
  unparseable_model_output: 2
  unclassified: 1
```

This blends code from before and after every fix this project has landed, so it is a historical record, not a live measurement of the current agent; the right use of this table on a single, current configuration is the same one `--repeat` already established for pass rate, several runs, not one.

## What this establishes

- `benchmark/failure_taxonomy.py`'s `classify_failure` categorizes a failed run's real cause from its trace, in priority order (most specific and most actionable checked first), with every category backed by at least one real captured example, committed as a test fixture in `tests/fixtures/failure_taxonomy/` since `logs/` itself is gitignored.
- `benchmark/report.py` surfaces the breakdown automatically whenever there are failures, ordered so the largest bucket is first, matching the plan's own "fix the largest bucket first" instruction.
- The taxonomy's biggest bucket, selector drift, points at the same underlying weak spot Milestone 5 already named: the model has no reliable strategy for picking a selector on a page it hasn't seen, and tries a different wrong guess each time rather than reliably falling back to text matching early. That's now a number to watch move, not just a recurring anecdote.

## What's next

Per `docs/ai-infra-and-observability.md`: token/cost accounting per step next, then a regression gate sized to the measured ~58-92% noise band. Selector drift being the largest bucket is a real candidate for the "fix the largest bucket, re-run, show the number move" postmortem-style work the plan calls out, once observability itself is done.