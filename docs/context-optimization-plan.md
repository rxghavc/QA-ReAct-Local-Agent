# Context and observation-payload optimization plan

This was a planning doc; ideas 1 and 2 below are now built and measured.
**See `docs/milestones/context-optimization.md` for the outcome, kept
here for the record since the actual finding corrects a real assumption
in this plan, not just confirms it:** idea 2 (the observation payload)
turned up a genuine bug (saucedemo's hidden nav menu crowding out real
buttons) and ships as the new default; idea 1 (history trimming) ships
too, but delivered far smaller token savings than predicted below, once
a live isolation test showed the ~10.5x multiplier this plan is built
around is mostly the constant tool-schema/system-prompt prefix being
re-processed every call, not the growing conversation history. Idea 3
(quantization) is unaffected and still not started.

## Why this, why now

Milestone 10 part 3 turned this project's own architectural guess (no
prefix-cache reuse in the current Ollama setup) into a real number: on a
13-step checkout task, 29,583 prompt tokens were actually billed against
2,810 if the shared prefix had been reused, a ~10.5x cost multiplier
purely from resending the full growing conversation history every step
(see `docs/milestones/token-cost-accounting.md`). That's the plan's own
long-open "context length management... may need to summarize/truncate
older steps" question (still listed under Open Questions/Risks), now
with a number attached instead of a guess.

Separately, a side conversation about whether LangGraph, CrewAI, or a
vector DB would add anything to this project's hand-rolled loop
concluded, after an actual spike (`scripts/spike_selector_memory.py`,
`scripts/spike_selector_memory_live.py`), that none of them address this
specific cost problem: a vector DB is retrieval by embedding similarity,
which has nothing to do with whether the *same* inference engine reuses
already-computed attention state for a repeated prefix. The only levers
that actually touch the real problem are architectural: send less, or
send it more cheaply. That's what this plan scopes.

## What's now measurable, for free

Every idea below can be evaluated with instrumentation this project
already built, not new measurement infra:

- **Token savings**: `prompt_tokens_total`/`completion_tokens_total` per
  run (Milestone 10 part 3), aggregated by `benchmark/report.py`.
- **No pass-rate regression**: `benchmark/regression_gate.py` (Milestone
  10 part 4), already sized to this suite's real 58/75/92% noise band.
- **No self-report-accuracy regression**: already tracked per run.
- **No new failure category**: `benchmark/failure_taxonomy.py`
  (Milestone 10 part 2) classifies any new failure shape that shows up.

So the evaluation protocol for every idea here is the same: implement it
behind a flag, run `python -m benchmark.runner --repeat 3` with the flag
on and off, compare `report.py`'s token/pass-rate output, and run
`regression_gate.py` before considering it safe to make the default.

## Idea 1: trim old tool-result payloads (highest priority)

**The actual redundant cost isn't step count, it's that every step's
`_summary()`/`get_page_state()` result stays in the message list
verbatim forever, superseded by a fresher one the very next step but
never removed.** `agent/loop.py` appends
`{"role": "tool", "content": json.dumps(result)}` every step and never
touches an earlier one again.

**Chosen mechanism: deterministic code, not a model-generated summary.**
This follows the project's own already-established finding
(`agent/routing.py`, Milestone 7): where a structural transform can do
the job, a model call is strictly worse here — more cost, a new
hallucination surface, and (per the 3b spike) this class of model is
worse at "judge/summarize this" tasks than plain code is. The same
reasoning applies to "should an LLM summarize the history": don't add
one, write a pure function.

**Two candidate policies to measure against the current no-trim
baseline, not a single guessed design:**

- **(a) Full trim**: any tool message older than the last N steps has
  its `content` replaced with a minimal marker (e.g. just `success` and
  the tool name), dropping `title`/`url`/`headings`/`clickable`
  entirely.
- **(b) Partial trim**: keep `url`/`title` (cheap, and plausibly load-
  bearing for "which page am I on" narrative continuity across a
  multi-step task) but drop `headings`/`clickable` for anything older
  than N steps, since those are the actually bulky fields and are
  superseded by the next fresher summary anyway.
- **(c) No trim**: today's behavior, the measured baseline
  (29,583 total prompt tokens on the 13-step checkout task).

N (how many recent steps stay untouched) is a real open variable, not
assumed: start with N=3-4 per the original suggestion, but the suite
itself, not a guess, should decide it.

**The real design question — how much history can be dropped before the
model loses what it needs to self-correct or track multi-step
progress — gets answered by running the existing suite, not by
reasoning about it in advance.** Scope: implement trimming as a
parameter (e.g. a `history_trim: Literal["none", "partial", "full"]`
argument threaded through `run_task`, or a small pluggable
`trim_history(messages, keep_last=N)` function called before each model
call). Run all three policies through `--repeat 3` and compare:

- `prompt_tokens_total` averages (the expected win)
- suite pass rate via `regression_gate.py` against the existing baseline
- `self_report_accuracy` specifically (a regression here means trimming
  cost the model the state it needs to know whether it actually
  succeeded, a different and worse failure than a wrong click)
- `task_04` in particular (the longest task, 13-15 steps, where the
  effect should be largest) and any task where the model must recall an
  earlier decision later (did it already add the right item to cart
  before checking out)

Ship whichever policy holds pass rate and self-report accuracy while
cutting tokens; if only (b) holds and (a) regresses, that's the answer
the measurement gives, not one assumed ahead of it.

## Idea 2: shrink the observation payload itself (second, not simultaneous)

**Not starting from zero: `browser/actions.py` already caps both
`headings` and `clickable` at `MAX_SUMMARY_ITEMS = 8` items each**, and
`get_page_state` deliberately returns a narrower shape than
`_summary()` (Milestone 2's "different shapes for different jobs"
decision). What's *not* capped today: per-item text length (a long
product name or button label is sent in full), and there's no dedup of
repeated visible text.

**First step before touching code: measure the real current payload
size on the suite's actual pages** (saucedemo's 6-product inventory
page, cart, two checkout steps; the-internet's pages; books.toscrape's
paginated table; demoqa's forms) — how many characters does a typical
`_summary()` call return today, and how much of that 8-item cap is
usually hit versus mostly-empty. This project doesn't have that number
yet, so no cap should be picked before it exists.

**This is the one idea most directly in tension with the selector-drift
finding, and that has to be named explicitly, not discovered by
accident.** Selector drift (the taxonomy's largest bucket, 17/63) is
already about the model failing to find the right element. If a tighter
cap or truncation cuts the specific clickable element the model actually
needs, that doesn't just fail to help, it actively makes the project's
worst-measured failure mode worse. So any change here needs its own pass-
rate check specifically on `task_03`/`task_04` (the same tasks selector
drift already concentrates in), not just a token-count win taken alone.

**Candidates, once real sizes are known:** truncate long
heading/clickable text to some character cap; dedupe exact-text repeats
(saucedemo's cart badge count and similar can repeat); lower
`MAX_SUMMARY_ITEMS` only if the real size data shows most pages are well
under 8 items already, meaning the cap isn't actually load-bearing.
**Explicitly out of scope for a first pass:** diffing against the
previous call to send only changed elements — that reintroduces the
kind of state-tracking complexity idea 1 is deliberately avoiding by
using a pure function instead of a model call, and doubles the number of
moving parts being measured at once.

**Sequencing: after idea 1 lands and is measured, not alongside it.**
Changing two things at once and seeing a pass-rate move gives no way to
attribute the cause, the same "change one variable, re-run, show the
number move" discipline the failure taxonomy itself was built on.

## Idea 3: quantization side-by-side (speculative, explicitly lowest priority)

**The claim to test**, from `docs/ai-infra-and-observability.md`:
`qwen2.5-coder:14b` runs at whatever Ollama's default quant is (almost
certainly Q4_K_M), and 4-bit quantization degrades structured-output
reliability before fluent prose — a plausible, never-attributed
contributor to the three distinct malformed-JSON shapes this project has
already hit across Milestones 1, 3, and 8, versus the chat-template
issue Milestone 1 already diagnosed as the primary cause.

**Before running anything**: check which quantization tags actually
exist for `qwen2.5-coder:14b` in Ollama's library — don't assume a Q8
tag is pullable without checking — and check the real VRAM cost against
the documented 24GB unified-memory constraint. The plan's own scale-down
decision (24b → 14b) was made specifically to leave headroom for the
browser/Docker/OS stack; a jump toward Q8 (roughly double the current
~9GB) may not fit comfortably alongside a live browser session at all,
and that's a feasibility check, not an assumption, before any comparison
is worth running.

**If it fits**: same harness as ideas 1 and 2 (`--repeat 3`, pass rate,
regression gate), plus the one metric this idea specifically targets —
`unparseable_model_output` count from the failure taxonomy (2/63
historically) — and the latency side of the tradeoff, since a less-
quantized model is slower per token and model inference already
dominates cost by ~35x over tool execution (Milestone 10 part 1).

**Explicitly not started until ideas 1 and 2 are done and this is still
interesting**, the same "last item, not first" sequencing the regression
gate itself used.

## Sequencing and what "done" looks like

1. **Idea 1 (history trimming) first.** Highest measured leverage
   (directly attacks the 10.5x multiplier), lowest implementation risk
   (pure code, no new model call, no new failure surface), and every
   piece of instrumentation needed to evaluate it already exists.
2. **Idea 2 (payload shrinking) second**, gated on real payload-size
   data that doesn't exist yet, and measured separately from idea 1 so a
   regression can be attributed to one change, not two.
3. **Idea 3 (quantization) last**, gated on a feasibility check, and
   only pursued if 1 and 2 haven't already made the parse-failure
   question moot.

Each idea ships, or doesn't, on the same evidence bar as everything else
in this project: a `--repeat 3` measurement against the existing
58/75/92% baseline via the regression gate, not "this should obviously
help." That bar is exactly what the vector-DB spike (this same week)
found the missing ingredient to be, on a different question.