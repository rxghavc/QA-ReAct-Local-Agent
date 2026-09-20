# Context and observation-payload optimization: a real bug and a real correction

## What prompted this

`docs/context-optimization-plan.md` scoped two ideas, prioritized and meant to be measured separately: trim old tool-result payloads out of message history (the higher-priority one, aimed directly at Milestone 10 part 3's measured ~10.5x prompt-cost multiplier), and shrink the observation payload itself (second, gated on real payload-size data that didn't exist yet). Both were implemented together on one branch at the user's request. That turned out to matter: measuring them together is exactly what surfaced that the first idea's expected win mostly wasn't there, for a reason worth explaining rather than burying.

## What changed

**`agent/history.py` (new)**: `trim_history(messages, keep_last, policy)`, called once per step in `agent/loop.py`. Two policies, both touching only `tool`-role messages, never the assistant tool-call messages: `"partial"` keeps `url`/`title`/`success`/`error` but drops `headings`/`clickable`; `"full"` keeps only `success`/`error`. Deterministic code, not a model call, per the same lesson `agent/routing.py` already learned in Milestone 7. `history_trim`/`history_keep_last` are threaded through `run_task`, `run_and_score`, `run_suite`, `run_suite_repeated`, and the `benchmark.runner` CLI, off by default (`"none"`).

**`browser/actions.py`'s `_summary()`**: while measuring real observation-payload sizes on the suite's actual pages (the first step `docs/context-optimization-plan.md`'s second idea called for before picking anything to cap), a real, previously invisible bug turned up. On saucedemo, after login, `_summary()`'s clickable-element query (`button, a, input[type=submit]`) returned the slide-out nav menu's links (`About`, `Logout`, `Reset App State`, `All Items`, `Dynamic Catalog`, `Close Menu`) even while that menu was closed. Those six items filled 6 of `MAX_SUMMARY_ITEMS`' 8 slots on every single saucedemo page, crowding out the actual button the task needed. Confirmed directly: `click(text="Continue")` succeeded on `checkout-step-one.html` even though `"Continue"` never appeared in that page's reported `clickable` list, because the real button was pushed out of the 8-item cap by menu chrome that isn't even reachable without first clicking "Open Menu". Root cause, confirmed by inspection: the menu sits under `aria-hidden="true"` while closed (`tabindex="-1"` on each link), and Playwright's own `:visible` pseudo-class does **not** filter these out (they have a real bounding box; they're just translated off-screen). `get_by_role("button")`/`get_by_role("link")` do respect `aria-hidden`, so `_summary()`'s clickable extraction now uses those instead of a raw CSS tag locator, matching the plan's own long-stated design intent ("pass a trimmed accessibility tree, not raw HTML") that the original implementation fell short of. Verified live across a full saucedemo checkout: every step now returns 2-4 real, currently-actionable buttons instead of 8 slots mostly consumed by menu chrome. A regression fixture (an `aria-hidden` link next to a normal one) was added to `tests/fixtures/sample_page.html` and `tests/test_browser_actions.py`.

## What the live measurement found

Two full `--repeat 3` suite passes, same code, same live model and browser, only `history_trim` different:

```
baseline (clickable fix, no trim):     min 75%, max 83%, mean 81% pass rate
                                        avg 12,162 prompt / 183 completion tokens per run
partial trim (keep_last=4):            min 75%, max 92%, mean 83% pass rate
                                        avg 11,374 prompt / 174 completion tokens per run
```

Pass rate held (no regression either way, both inside the suite's known noise band, and both *above* the historical 58/75/92% baseline this suite has been measured at since PR #13 — the clickable fix's own doing, addressed below). **Token savings from trimming were real but small: ~6.5% overall, and on `task_04` (the longest task, where the effect should be largest) a same-code, same-batch comparison showed no measurable difference at all** (29,367 baseline vs. 29,657 trimmed, well inside run-to-run noise).

That result didn't match what `docs/context-optimization-plan.md` predicted, so it got the same treatment the routing spike and the environment_flakiness false positive got: don't trust the number, find the mechanism. A direct isolation test told the real story:

```
ollama_chat(..., tools=TOOLS):   prompt_eval_count = 1674
ollama_chat(..., tools=[]):      prompt_eval_count = 1085
```

**The tool schema alone costs ~589 tokens, resent identically on every single call regardless of conversation history. Combined with the system prompt and task text (~1085 tokens, also constant), a ~1674-token prefix is being fully re-processed on all 13-15 calls of a typical task, every time** — roughly 21,000+ tokens per task from the *constant* part alone, dwarfing the ~1,000-1,500 tokens the conversation actually grows by across all those same steps. History trimming only touches the growing part. Once the clickable fix had already shrunk what each tool result contains, there was barely anything left in the growing part to trim, which is exactly why the token-savings measurement came back flat on the task where it mattered most.

**This means the original ~10.5x multiplier (Milestone 10 part 3) was never really about the size of the resent history. It's about Ollama re-processing the same constant prefix from scratch on every call, because it does not reuse the shared prefix's KV-cache between calls** — precisely the limitation `docs/ai-infra-and-observability.md` already named ("Limited prefix/KV-cache reuse... SGLang's RadixAttention and vLLM's automatic prefix caching exist specifically to make that free"), now backed by a direct measurement instead of an architectural guess. Fixing that for real means a different serving engine, which the plan already treats as a deliberate, documented tradeoff for this project's scope (iteration speed and zero ops burden over throughput), not something to chase from the application layer.

## What this establishes

- **The clickable-visibility fix ships as the new default, unconditionally.** It's a correctness fix (removing misleading, not-currently-actionable information from the model's observation), not a lossy tradeoff, and it measured as a net improvement, not just a non-regression.
- **History trimming ships too, but as an honest opt-in** (`history_trim="none"` by default), not the default. It's free — no pass-rate cost, no new failure surface, fully tested — but its real measured benefit here is much smaller than the plan assumed, and saying so plainly is more useful than shipping it as a headline win it didn't earn. It would matter more on a task whose tool results carry heavier payloads than this suite's pages do post-fix (e.g. a large `extract_text` result), which is a real, different condition than what this suite currently exercises.
- **A speculative, mechanism-first optimization plan can be wrong about *where* a measured cost comes from, even when the top-line number is right.** The 10.5x multiplier was real; the assumption that message-history size was the reason for it wasn't. This is the same class of lesson Milestone 7's 3b spike and the environment_flakiness false positive already taught from different angles: verify the mechanism, not just the headline number, before building around it.

## What's next

`docs/context-optimization-plan.md`'s third idea (a speculative Q8 quantization side-by-side) is unaffected by this and still gated on its own VRAM feasibility check. The regression gate (`benchmark/baseline.json`, min 58%) still holds against these new numbers; both this session's measurements (81% and 83% mean) sit comfortably above its 55% threshold, so no baseline update is needed yet, though a future full re-measurement of the current code would be the honest way to update it rather than assuming today's two runs are enough on their own.