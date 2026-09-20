# Context optimization, idea 3: a Q8 side-by-side, and a negative result

## What prompted this

`docs/context-optimization-plan.md`'s third and lowest-priority idea, explicitly gated on a VRAM feasibility check before running anything. The claim to test, from `docs/ai-infra-and-observability.md`: `qwen2.5-coder:14b` runs at Ollama's default Q4_K_M quantization, and 4-bit quantization degrades structured-output reliability before fluent prose, plausibly contributing to this project's three distinct malformed-JSON shapes across Milestones 1, 3, and 8.

## The feasibility check, done without downloading anything large

Ollama's registry exposes manifest metadata over a small HTTP call, so the real size of each candidate quantization could be checked before pulling gigabytes of anything:

- Current: Q4_K_M, ~9GB (confirmed via `ollama show qwen2.5-coder:14b`).
- `14b-instruct-fp16`: 29.55GB. **Ruled out immediately** — this alone exceeds the entire documented 24GB unified-memory budget, before accounting for the OS, the browser, or anything else. Never pulled.
- `14b-instruct-q8_0`: 15.70GB. Leaves roughly 8.3GB nominal headroom, tight but not obviously infeasible. The only candidate worth actually running.

A one-task smoke test came first, before committing to a full suite run: `task_02_saucedemo_login` completed successfully on Q8_0 (`outcome=done`, 5 steps, 50.9s wall clock), with system memory free dropping from 27% to 20% and no swapping or instability. Confirmed it fits before spending a full suite's worth of time on it.

## Ruling out a confound before trusting the result

Before treating any pass-rate difference as a quantization effect, `ollama show --modelfile` was compared for both tags. **Identical `TEMPLATE`, identical `SYSTEM` prompt, no `PARAMETER` overrides in either** — same instruct-tuned checkpoint family, same chat template, same default sampling. The only real variable between the two runs is quantization level, not a different model variant or a hidden temperature difference.

## What the live comparison found

`python -m scripts.spike_quantization --repeat 2`, same task suite, same live browser, `agent.loop.PLANNER_MODEL` swapped to `qwen2.5-coder:14b-instruct-q8_0` for the duration:

```
Q8_0 pass rates: 75%, 67% (mean 71%)
Q4_K_M baseline (this same day, 3 runs): 83%, 92%, 92% (mean 89%)

unparseable_model_output failures: 0/24 scored Q8_0 runs
avg model_seconds_total per task run: 43.2s (Q8_0) vs 26.5s (Q4_K_M baseline)
```

**Q8_0 was both slower and less reliable than Q4_K_M, not more reliable.** Its best pass (75%) sits below Q4_K_M's worst pass (83%) — a real gap, not overlapping noise, though this is 2 runs against Q4's 3, a smaller sample than this project normally insists on, and is reported as suggestive rather than exhaustively confirmed for that reason. `selector_drift` reappeared at Q8_0 (3 failures) despite being zero across the most recent 36 Q4_K_M runs post the aria-hidden fix (`docs/milestones/context-optimization.md`) — since that fix is a browser-layer change unaffected by which model is running, this means Q8_0 itself made worse target-selection decisions on this suite, not that the old crowded-observation bug came back.

**The specific mechanism the plan hypothesized never showed up in either model**: `unparseable_model_output` was 0 for Q8_0, matching Q4_K_M's own already-low historical rate (2/63 total, ever). Quantization-degraded JSON formatting was not the failure mode here. What actually differed was task execution and target selection quality (`selector_drift`, `hallucinated_success`), not output formatting.

## What this establishes

- **Higher precision didn't help, and this small sample suggests it may have actively hurt**, both on speed (model inference already dominates cost by ~35x, so a ~1.6x slower model is a real cost, not a rounding error) and on pass rate. Not shipping.
- **The plan's specific hypothesis (quantization → malformed JSON) wasn't supported.** This project's real malformed-JSON incidents (Milestones 1, 3, 8) most likely trace to the chat-template issue Milestone 1 already diagnosed, not quantization, at least as far as this test can tell.
- `qwen2.5-coder:14b-instruct-q8_0` (15GB) was deleted after this measurement, consistent with the plan's own framing of this as the lowest-priority, most speculative idea, not worth keeping disk space allocated to once measured.
- This closes `docs/context-optimization-plan.md`'s third and final idea. All three ideas in that plan are now measured: idea 1 (history trimming) shipped as an under-delivering opt-in, idea 2 (payload shrinking) shipped as a real bug fix, idea 3 (quantization) was tested and rejected on measurement, the same treatment Milestone 7's 3b routing proposals got.