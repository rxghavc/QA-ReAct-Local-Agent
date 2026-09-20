# Token cost accounting

## Why this was worth measuring

The project had a clear architectural suspicion: each step was resending the full growing conversation to the model, and that would make prompt cost grow much faster than the model's own output. The point of this measurement was to turn that suspicion into a real number and check whether the inference cost was being driven by repeated prefix work rather than by the browser or the tool execution itself.

## What changed

Ollama's `/api/chat` response carries `prompt_eval_count` (tokens evaluated for that call's prompt) and `eval_count` (tokens generated) at the top level, alongside `message`, not inside it. `agent/ollama_client.py`'s `ollama_chat` previously threw both away, returning only `response.json()["message"]`; it now returns the whole response, and `agent/loop.py` reads `response["message"]` for the tool call and the two count fields for token accounting.

Every trace entry in `agent/loop.py`'s `run_task` now carries `prompt_tokens` and `completion_tokens` for that step (every step has these, unlike `tool_seconds`, since every step makes a model call but not every step reaches the browser), and the running totals `prompt_tokens_total`/`completion_tokens_total` are returned alongside the existing timing totals. `benchmark/runner.py` carries both into the per-run log record the same way it already carries `model_seconds_total`/`tool_seconds_total`, defaulting to `0` for skipped tasks. `benchmark/report.py` aggregates them the same way too: an average per task, an overall average, printed alongside the existing timing line. Old logs from before this change have neither field; `.get(..., 0)` treats a missing value as `0`, the same backward-compatibility pattern already established for the timing fields and, before that, the `skipped` field.

## What it found, immediately

Two live runs against the real local model and browser service, no benchmark suite involved, the same ad-hoc-CLI methodology Milestone 10 part 1 used:

```
run 1 (task_04's 13-step saucedemo checkout): prompt_tokens per step:
  1768, 1853, 1909, 1965, 2078, 2195, 2306, 2417, 2472, 2527, 2586, 2697, 2810

run 2 (task_02's 5-step saucedemo login): prompt_tokens per step:
  1686, 1764, 1811, 1858, 1932
```

**Prompt tokens grow every single step and never plateau or shrink**, which is itself the finding: if Ollama were reusing the shared prefix between calls the way the planning doc described production serving stacks doing, a later step's `prompt_eval_count` would reflect only the *new* tokens since the last call, not the whole conversation re-evaluated from scratch. It doesn't. Summing `prompt_eval_count` across all of run 1's 13 steps gives **29,583 prompt tokens actually billed**, against **2,810** if the shared prefix had been reused and each step had only paid for its own new suffix (the first call's cost, plus the sum of each step's growth over the previous step). That is a **10.5x cost multiplier from the missing prefix cache alone**, on a single 13-step task. Run 2's shorter 5-step task shows the same shape at smaller scale: 9,051 actual vs. 1,932 ideal, a 4.7x multiplier.

Completion tokens stay small and roughly flat across steps in both runs (17-37 tokens, mostly the size of a single JSON tool call), which is expected: the model's own output length doesn't grow with context length the way the resent input does, so the entire cost-multiplier finding above is a **prompt-side, not completion-side, effect** of the architecture's own choice to resend full history every step.

## What this establishes

- The `docs/ai-infra-and-observability.md` claim about Ollama's limited prefix-cache reuse was a hypothesis about this project's own architecture, framed as a real cost happening today, not a hypothetical future one. It now has a real number: **roughly a 10x prompt-token cost multiplier on a 13-step task**, measured from two live runs rather than assumed from Ollama's general reputation.
- This sharpens, rather than just restates, Milestone 10 part 1's "model inference dominates tool execution by ~35x" finding: model inference is expensive partly *because* every step pays full-context prefill cost again, not only because the model itself is slow to generate.
- This is the same two-live-runs-not-a-benchmark-measurement caveat Milestone 10 part 1 flagged: real evidence for a hypothesis, not a suite-wide measurement the way pass rate is (three passes, spread reported). A natural next use of this same instrumentation is running it across the full suite to see whether the ~10x multiplier holds on shorter and longer tasks alike, or whether it grows with step count as the quadratic-in-steps shape of "resend everything so far, every step" would predict.

## What's next

Per `docs/ai-infra-and-observability.md`: a regression gate sized to the measured ~58-92% pass-rate noise band, the last item in the original observability list before any web UI work. This token-cost finding is also the first real number backing the plan's already-open "context length management... may need to summarize/truncate older steps" question: a ~10x avoidable prompt cost from full-history resend is a concrete reason to prioritize that if this project's token budget or latency ever becomes the binding constraint, though sizing that against the model-inference-dominates finding first would keep it measurement-driven rather than reactive to a single interesting number.