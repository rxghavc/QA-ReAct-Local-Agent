# Local Agentic Web-Testing Agent

A locally-run agentic web-testing tool: given a URL and a plain-language task, an agent plans steps, drives a real browser via Playwright, observes results, and self-corrects on failure, all sandboxed in Docker, running entirely on local models via Ollama.

This README covers what the project is: architecture, tech stack, current measured behavior, and what the engineering process actually found. For the numbered milestone history of the project itself, see [docs/milestones/README.md](docs/milestones/README.md). For the supporting notes, learnings, and deeper analysis, see [docs/analysis/README.md](docs/analysis/README.md). For day-to-day status ("what's done, what's next"), see `CLAUDE.md`.

## Architecture

```
┌──────────────────────┐      HTTP      ┌──────────────────────┐
│   agent container    │  ───────────▶  │  browser container   │
│  (agent/Dockerfile)  │                │ (browser/Dockerfile) │
└──────────────────────┘                └──────────────────────┘
```

- **agent container**: `agent/loop.py` runs the ReAct loop, calling `agent/ollama_client.py` (the structured-JSON fallback parser, since the planner doesn't reliably use Ollama's native tool-calling) and dispatching through `agent/tools.py` to the browser container over HTTP. `agent/prompts.py` builds the system prompt and `agent/routing.py` holds `is_same_failure`, the stuck-detection checkpoint, which is deterministic code with no model call in it. `agent/api.py` is a stub, deliberately unassigned (see Tech Stack below). The agent container talks to **Ollama on the host** (`http://host.docker.internal:11434`), calling only `qwen2.5-coder:14b`; a `llama3.2:3b` routing checkpoint was tried and measured out, there is no 3b call left in the running system.
- **browser container**: `browser/server.py`, a thin FastAPI wrapper around `browser/actions.py`'s `BrowserSession`, one persistent Playwright Chromium page held open for the life of the process. Headless by default; set `BROWSER_HEADLESS=false` when running the browser service locally, not in Docker, to open a real, watchable Chromium window (see `docs/how-to-run.md`).
- **benchmark harness**, outside both containers, driving them the same way a real caller would: `benchmark/runner.py` loads `benchmark/tasks/*.yaml`, pre-flights each task's target site via `benchmark/health.py`, calls `agent.loop.run_task`, and scores the result against the real final browser/report state, never against the agent's own self-report. Every run, pass or fail, is written to `logs/` as one JSON trace; `benchmark/report.py` aggregates those into pass rate, self-report accuracy, and step counts.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Local inference | Ollama, serving `qwen2.5-coder:14b` only | Native tool-calling doesn't work on this model at all; a structured-JSON fallback parser is used instead. A `llama3.2:3b` routing checkpoint was tried and dropped after measurement, there's no 3b call in the running system. |
| Agent orchestration | Python, hand-rolled ReAct loop (`agent/loop.py`) | No LangGraph/CrewAI, by design. |
| Browser automation | Playwright (Python, async) | `browser/actions.py`'s `BrowserSession`; headless by default, `BROWSER_HEADLESS=false` for a watchable window. |
| Sandboxing | Docker Compose | Separate agent and browser containers, talking over the compose network. |
| API layer | FastAPI on the browser side (built and tested); an agent-side HTTP trigger API (`agent/api.py`) is a deliberate, unimplemented stub | The project is CLI-driven end to end; see `docs/how-to-run.md`. |
| Task/benchmark definitions | YAML (`benchmark/tasks/*.yaml`) | One file per task; success conditions checked programmatically, never by the LLM. |
| Logging/tracing | Structured JSON logs per run (`logs/`) | Aggregated by `benchmark/report.py` into pass rate, self-report accuracy, and step counts. |

**Engineering workflow:** every change lands on its own branch and goes through a PR gated by CI (`lint` via ruff, `typecheck` via mypy, `test` via pytest with coverage, `security` via `pip-audit`, and `docker-build`, which also runs a real Chromium-launch smoke test inside the built image) before merging to `main`.

## Design decisions

**Why explicit tools (`navigate`/`click`/`type_text`/...) instead of letting the model drive the browser itself?** Three reasons, in the order they actually mattered while building this:

- **Programmatic scoring depends on it.** Every benchmark task's success condition is a DOM/URL/text assertion checked against real final browser state, never LLM-judged (see Testing Benchmark & Task Suite in `CLAUDE.md`). That's only possible because the model's actions are constrained to a fixed, loggable action set. An agent that writes and executes its own arbitrary browser-control code has no equivalent seam to score against.
- **Self-correction is a designed loop property, not something that falls out of "give the model a browser."** `BrowserSession` methods never raise; a missing selector comes back as `{"success": False, "error": "..."}`, fed back into the model's own context as an observation it can reason about (see Browser Tool Layer). Getting a failed action to look like useful signal instead of a crash was deliberate work, not a side effect of autonomy.
- **The tool layer is what makes the context budget survive.** Passing raw HTML or letting the model script arbitrary DOM queries multiplies tokens per step for no reasoning benefit. Milestone 13 found the actual bottleneck wasn't the model's freedom to act, it was the *shape* of the observation: a raw-CSS clickable-element query was silently including saucedemo's hidden (`aria-hidden="true"`) nav menu, crowding the real button out of an 8-item cap. Fixing the query, not giving the model more autonomy, is what took the mean pass rate from 75% to 89%.

Fully autonomous browsing agents (e.g. computer-use-style tools) are a legitimate different design point, aimed at general-purpose interaction rather than an evaluable, host-agnostic action schema that a benchmark can score. Different goal, different tradeoff, not a strictly better one.

**This is a reactive agent, not a planning one, and that's a scope boundary worth stating precisely rather than leaving implicit.** At each step the model picks its next tool call from the current observation alone (Reason → Act → Observe, one step at a time): there's no lookahead, no multi-step plan committed to in advance, no memory carried between separate task runs, and no learning across episodes, every task starts from the same blank system prompt. What makes this an agent rather than a fixed script is that the action sequence is *decided live*, conditioned on outcome, not that it plans ahead or improves with experience: self-correction on a failed action, a forced re-plan after repeated failure, and model-chosen termination via `report_done`/`report_blocked` are all decisions made turn by turn from whatever the page looks like right now.

**Why both `tests/` and `benchmark/`? They check different things, and neither substitutes for the other.**

- **`tests/`** (pytest, CI-gated on every PR): deterministic, no LLM, no live network, ~13s. Checks that `BrowserSession` methods, tool dispatch, and the scorer behave correctly in isolation against a static local fixture, e.g. that `click` on a missing selector returns `{"success": False, ...}` rather than raising.
- **`benchmark/`** (manual, local only, deliberately not in CI, because it needs a live model and a live browser session): checks whether the *agent* — model, prompt, tool schema, and loop, together — actually completes real tasks, and how reliably. Non-deterministic by nature (this suite has documented run-to-run variance), which is why it's run in repeated passes (`--repeat N`) and reported as a range, not a single number.

In short: the tests catch a broken tool. The benchmark catches a planner that can't use working tools. A green test suite says nothing about whether the agent can actually complete a task.

**Does this generalize beyond the four benchmark sites?** No fine-tuning happens anywhere in this project. `qwen2.5-coder:14b` is the unmodified, stock Ollama model; it has never been trained on saucedemo, `the-internet.herokuapp.com`, demoqa.com, or books.toscrape.com. The benchmark's YAML tasks are evaluation inputs, not training data, and there's no site-specific code path: every run, the model reasons in-context from a live accessibility-tree observation of whatever page it's actually looking at, using the same generic tool set regardless of site. That's the mechanism, and it's genuinely site-agnostic.

What that doesn't mean: that it's equally reliable on any arbitrary real-world site. The benchmark deliberately targets "stable, automation-friendly demo sites... no fragile production sites" (see `CLAUDE.md`'s Testing Benchmark & Task Suite section), which is a real, acknowledged scope limit, not a hidden one. `selector_drift`, still the failure taxonomy's largest bucket even after Milestone 13's fix, is exactly the failure mode you'd expect to see more of on an unfamiliar site's markup, since the agent has no memorized selector map for a page it's never seen; that's the visible symptom of the same generalization the tool-schema design relies on, not evidence against it. Running this against a site outside the current four is untested, not unsound, it just hasn't been measured yet.

## Optimization work

Post-MVP, once the core loop was passing reliably (see `CLAUDE.md`'s Optimization & Evaluation section for the original plan; the supporting write-ups are in [docs/analysis/README.md](docs/analysis/README.md)):

- **Per-step timing breakdown** ([docs/analysis/observability-per-step-timing.md](docs/analysis/observability-per-step-timing.md)): model inference dominates tool execution by roughly 35x per step. Confirmed the plan's own hypothesis before any further optimization was attempted.
- **Failure taxonomy** ([docs/analysis/failure-taxonomy.md](docs/analysis/failure-taxonomy.md)): built by hand-reading all 63 real failed runs in `logs/` before writing a single category, per the plan's own method. Caught a false-positive rule before shipping: an early `environment_flakiness` check misclassified saucedemo's healthy login page as a site outage 23/63 times, because its submit button is an `<input>` with no inner text; fixed to check for an actual outage signal, dropping that bucket to 5/63. `selector_drift` (17/63) was the real largest bucket, later fixed in Milestone 13.
- **Token/cost accounting** ([docs/analysis/token-cost-accounting.md](docs/analysis/token-cost-accounting.md)): summing per-step prompt tokens across one 13-step run gave 29,583 tokens actually billed against 2,810 if the shared prefix had been reused, a **10.5x cost multiplier from Ollama's lack of prefix-cache reuse alone**. A follow-up isolation test in Milestone 13 found the real driver: a constant ~1,674-token tool-schema-plus-system-prompt prefix reprocessed on every call, which dwarfs what the growing conversation history itself adds. That's an infra limitation of Ollama, not something fixable at the app level, so history-trimming (built anyway, see below) delivered near-zero measured savings.
- **Regression gate + trend tracking** ([docs/analysis/regression-gate.md](docs/analysis/regression-gate.md), [docs/analysis/trend-tracking.md](docs/analysis/trend-tracking.md)): `benchmark/regression_gate.py` gates a fresh `--repeat`'d mean against a threshold set strictly below a measured baseline's observed floor, deliberately not at the floor itself, since this suite has already reproduced its floor with no code change. `benchmark/trend.jsonl` records every gate run; the first real recorded run was a genuine gate fail (71% vs. 80%), traced to a known, already-categorized failure mode, and kept in the record as-is rather than re-run away.
- **Context/model experiments, three ideas measured, two rejected on evidence** ([docs/analysis/context-optimization.md](docs/analysis/context-optimization.md), [docs/analysis/quantization-comparison.md](docs/analysis/quantization-comparison.md)): a vector-DB selector-memory spike found 0/17 real `selector_drift` failures needed cross-task retrieval, so it wasn't built. History trimming shipped as opt-in but under-delivered on its own premise (see token accounting above). Q8_0 quantization was measured slower and less reliable (71% vs. 89% mean pass rate, 43.2s vs. 26.5s avg model time) than the shipped Q4_K_M and was not adopted. What did ship and fix a real bug: switching the observation query to `get_by_role()`, fixing the hidden nav-menu bug described above under Design decisions, which is the actual mechanism behind this README's 75%→89% mean pass-rate jump.

## Setup

Requires Python 3.13, Docker Desktop, and [Ollama](https://ollama.com) running locally.

```bash
# Python env
pyenv local 3.13.5          # already pinned via .python-version
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium

# Local model (planner)
ollama pull qwen2.5-coder:14b
```

Model sizing is scaled for a 24GB unified-memory machine, leaving headroom for the browser/Docker/OS. If you have more RAM/VRAM available, `qwen2.5-coder:24b` is a stronger drop-in planner.

For running the benchmark suite, an ad-hoc task, or a watchable headed browser session, see [`docs/how-to-run.md`](docs/how-to-run.md).

## Agent runtime metrics

This suite has genuine run-to-run variance (documented since Milestone 7), so every measurement here is three full passes (`--repeat 3`), not one, and the honest summary is a spread, not a point estimate:

```
suite pass rate over 3 scored runs: min 83%, max 92%, mean 89%
self-report accuracy: 93% (excludes the two negative-tier tasks as circular,
  see Project analysis below)
average steps per task run: 5.6
```

| Task | Tier | Pass rate | Avg steps | Avg wall clock |
|---|---|---|---|---|
| task_01_the_internet_login | 1 | 3/3 (100%) | 5.0 | 27.2s |
| task_02_saucedemo_login | 1 | 3/3 (100%) | 5.0 | 27.0s |
| task_03_saucedemo_add_to_cart | 2 | 3/3 (100%) | 6.0 | 27.1s |
| task_04_saucedemo_checkout | 2 | 3/3 (100%) | 13.7 | 50.8s |
| task_05_saucedemo_logout | 2 | 3/3 (100%) | 7.0 | 30.3s |
| task_06_dynamic_loading | 3 | 3/3 (100%) | 4.0 | 23.0s |
| task_07_js_confirm_dialog | 3 | 3/3 (100%) | 4.0 | 23.6s |
| task_09_pagination_count | 4 | 3/3 (100%) | 4.0 | 24.3s |
| task_10_invalid_login_rejected | 4 | 3/3 (100%) | 5.0 | 30.4s |
| **task_11_impossible_login** | **negative** | **3/3 (100%)** | 6.0 | 27.4s |
| **task_12_ambiguous_instruction** | **negative** | **2/3 (67%)** | 2.0 | 17.7s |
| task_08_table_extraction | 4 | 0/3 (0%) | 6.0 | 29.7s |

**Reproduce this:** `python -m benchmark.runner --repeat 3` (after checking `ollama serve` and the browser service are up), then `python -m benchmark.report --last 36`.

**What moved, and why the aggregate mean is not the headline.** Mean pass rate went from 75% to 89% after a real bug fix, not a lucky run: `browser/actions.py`'s observation summary was returning saucedemo's hidden slide-out nav menu (`aria-hidden="true"` while closed) as if it were clickable, crowding the actual task-relevant button out of an 8-item cap on nearly every saucedemo page. Fixed to use accessibility-tree-aware queries instead of a raw CSS tag locator; `selector_drift`, the failure taxonomy's largest historical bucket, dropped to zero across this measurement's 36 logged runs. `task_08_table_extraction`'s 0/3 is a known, pre-existing weak spot unrelated to this fix (extraction accuracy, not selector matching); `task_12`'s one failure is the suite's already-documented `ask_clarification` unreliability. Full account in [docs/analysis/context-optimization.md](docs/analysis/context-optimization.md); the numbered milestone history is in [docs/milestones/README.md](docs/milestones/README.md).

## Project analysis

What this project actually demonstrates, distilled from the build process rather than asserted:

- **Concrete trigger examples beat abstract rules, and this held twice on unrelated behaviors.** Both Milestone 6's self-correction prompting and the `report_done`/`report_blocked` fix failed on an abstract instruction and succeeded once replaced with a bright-line trigger plus a worked example. This model (`qwen2.5-coder:14b`) responds to "if you see X, do Y, here is exactly what that looks like," not to a conceptual distinction stated clearly.
- **A model's self-report of success is not trustworthy on its own, and that has a name: self-report accuracy.** The negative-test tier's real failure mode wasn't hallucination, it was tool-semantics confusion: the agent narrated its own failure accurately and then called the tool that means "succeeded" anyway, three times out of three, before the fix.
- **Benchmark variance is a finding, not noise to average away.** Six runs of identical code ranged 2/7 to 7/7 before any fix landed. The response was to build `--repeat N` and site-health pre-flighting so a real number could exist, not to cherry-pick a good run or quietly average across an outage.
- **Advertised model capability doesn't predict actual reliability.** The two models that correctly used Ollama's native tool-calling format both failed to complete a multi-step loop; the model whose tool-calling "didn't work" completed every multi-step loop once given a structured-JSON fallback parser. This had to be tested directly; it wasn't visible from either model's spec sheet.
- **Adding a capability is not the same as it being used, discovered three separate times from three different angles.** Milestone 6's prompt rules didn't reliably hold, Milestone 7's 3b routing checkpoint measured zero effect, and Milestone 8's `ask_clarification` tool was called 0 times across 36 runs despite being declared every turn.
- **Validate any model-based judge on real captured inputs, including cases it should reject.** The 3b same-failure classifier passed hand-written test fixtures and then got every live activation wrong, because real Playwright errors are dense with code-like syntax the tidy fixtures never contained.

## Demo

Not recorded yet. `docs/how-to-run.md` covers every mode, including `BROWSER_HEADLESS=false` for a real, watchable Chromium window, an ad-hoc task CLI for pointing the agent at anything, and which existing suite tasks demo well. This section gets a recorded run once that's done.