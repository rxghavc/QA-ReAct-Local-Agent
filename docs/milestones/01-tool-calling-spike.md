# Milestone 1: Does the local model actually support tool calling?

## What this milestone was actually asking

This project's whole idea is: give an AI agent a task in plain English ("log in to this website"), and have it figure out the individual browser actions needed (go to this page, type this, click that) on its own, using a language model that runs entirely on this laptop, no OpenAI or Anthropic API calls.

For that to work, the model needs to be able to do one specific thing reliably: at each step, instead of just writing a paragraph of text, it needs to output something a computer program can parse automatically, like "call the function `navigate` with the argument `url: https://example.com`". This is called **tool calling** (also "function calling"). Big hosted models (GPT-4, Claude) are trained specifically to do this well. Small models that run on a laptop are much less consistently good at it, and this had never been tested with the specific model this project planned to use.

If the model can't do this reliably, nothing else in the plan works. The agent loop, the browser automation, the benchmark, all of it assumes the model can reliably say "do X with argument Y" in a machine-readable way at every step. So before writing a single line of the real agent, the plan called for a **throwaway spike script** just to answer this one question. If the answer had been "no model can do this reliably," the whole architecture would have needed to change (for example, switching to a much bigger model, or a completely different prompting strategy).

## Background: what is Ollama, and what is "tool calling" here concretely

[Ollama](https://ollama.com) is a program that runs on your own computer and lets you download and run open-source language models locally (instead of calling out to a service over the internet). You ask it a question over a local HTTP API (`http://localhost:11434/api/chat`), and it replies using whatever model you tell it to use.

Ollama's API supports a `tools` parameter: you describe a list of functions the model is allowed to call (name, description, and a JSON schema for the arguments), and the model is supposed to reply with a special `message.tool_calls` field containing which function it wants to call and with what arguments, instead of (or alongside) a plain text reply. This is the "native" tool-calling format this milestone tested.

## The experiment

The spike lives at `scripts/spike_tool_calling.py` and is explicitly a one-off, disposable script, not part of the real agent. It defines three toy tools with JSON schemas (`navigate(url)`, `click(text)`, `report_done(summary)`, a tiny stand-in for the real 10-tool schema built later in Milestone 3) and a system prompt telling the model it's a web automation agent that must call exactly one tool per turn.

It tested three different models available through Ollama, each in two different ways:

1. **Single-turn reliability**: send one user message like "Navigate to https://saucedemo.com" by itself, five times, and check whether the model's reply contains a tool call that a program could actually use (either the native `tool_calls` field, or, as a fallback, a JSON object embedded in the plain text reply that matches the tool schema).
2. **Multi-turn reliability**: simulate an actual back-and-forth loop, up to 5 steps: ask the model what to do, "pretend" to execute whatever it asked for (a fake success result, not a real browser), feed that fake result back to the model as if it were a real observation, and see if the model can chain multiple steps together and eventually call `report_done` to end cleanly. This matters more than the single-turn test, because the real agent loop is entirely multi-turn: one clean tool call in isolation doesn't prove the model can hold a conversation together over several steps.

## How the fallback parser works

The key piece of code in the spike is `extract_tool_call()`. Ollama's native `tool_calls` field is checked first, but if it's empty, the parser instead looks at the model's plain text reply and tries to pull a JSON object out of it:

```python
def extract_tool_call(message: dict) -> dict | None:
    if message.get("tool_calls"):
        call = message["tool_calls"][0]["function"]
        return {"name": call["name"], "arguments": call.get("arguments", {})}

    content = (message.get("content") or "").strip()
    match = TOOL_CALL_TAG_RE.search(content)
    if match:
        content = match.group(1).strip()

    parsed, _ = json.JSONDecoder().raw_decode(content)
    if isinstance(parsed, dict) and parsed.get("name") in TOOL_NAMES:
        return {"name": parsed["name"], "arguments": parsed.get("arguments", {})}
    return None
```

Two details worth calling out, because they came up again later (see the Milestone 3 doc):

- It uses `json.JSONDecoder().raw_decode(content)` instead of `json.loads(content)`. The difference matters: `json.loads` requires the *entire* string to be exactly one JSON value, and throws an error if there's anything else after it. `raw_decode` reads just the first valid JSON object it finds at the start of the string and ignores whatever comes after. This was needed because the model sometimes got ahead of itself and wrote out its whole multi-step plan as several JSON objects back to back in one reply, instead of one tool call per turn as instructed. The parser just takes the first one and throws away the rest, rather than crashing.
- It also checks for a `<tool_call>...</tool_call>` wrapper tag, because Ollama's own chat template for some models explicitly asks the model to wrap its JSON in these tags. Whether it actually does this or not was one of the things being tested.

## What was tested and what happened

| Model | Native tool-call format used? | Do the arguments match the schema? | Completes the full multi-step loop? |
|---|---|---|---|
| `qwen2.5-coder:14b` (via the JSON fallback) | No, 0 out of 15 trials ever produced `message.tool_calls` | Not applicable to the native format, but the fallback-parsed JSON matched the schema every time | **Yes, 100% of trials, clean navigate then click then report_done** |
| `llama3.1:8b` (native tool_calls) | Yes, 10 out of 10 | No. It invented its own argument names instead of using the ones declared in the schema (things like `locator`/`value`/`id` instead of the actual `text` field) | No, 0 out of 3, it broke on `click`'s arguments or never called `report_done` as a real tool call |
| `hermes3:8b` (native tool_calls) | Yes, 10 out of 10, and the arguments were correct | Yes | No, 0 out of 3. It dropped out of the tool-call format entirely after the first step and just started narrating in plain English instead |

The genuinely surprising result: **the model that "failed" at native tool-calling was the only one that actually worked end to end.** `qwen2.5-coder:14b` never once used Ollama's official `tool_calls` mechanism, in 15 separate trials, even when the tag format was spelled out directly in the prompt. But it reliably wrote a correctly-shaped JSON object as the answer to "what do I do next," every single time, across both single-turn and multi-turn trials. The two models that technically supported the "real" tool-calling API both failed to actually complete a multi-step task, for two different reasons (one invented its own argument names, the other lost the format entirely after step one).

This is the core lesson of this milestone: a model advertising or correctly using "tool calling" in isolation tells you almost nothing about whether it can actually carry a multi-step agentic task to completion. That can only be tested directly, by actually running the loop, which is exactly what this spike did before any real code was written.

## The decision

**`qwen2.5-coder:14b` is the planner model, and it will be used through a structured-JSON-output fallback parser, not through Ollama's native tool-calling API.** This was a deliberate, documented decision, not a placeholder to revisit later. It shaped how `agent/ollama_client.py` was actually built in Milestone 3.

One model that was considered but not tested: `Hermes-4-14B` (from NousResearch, built on top of Qwen3-14B, and specifically designed to emit `<tool_call>` tags after showing its reasoning). It has no official entry in Ollama's model library, only unofficial community-uploaded GGUF files, so `hermes3:8b` (an official, same-lineage model) was tested instead, to avoid depending on a third-party binary nobody had vetted.

## Why this was still worth merging as a PR, even though it "failed"

This spike's own headline result was "native tool-calling doesn't work." That's normally the kind of finding that gets thrown away, not merged. It was merged deliberately anyway (PR #2), because the value here isn't a working feature, it's a **reproducible experiment and its result**, which is exactly what justified building the fallback JSON parser instead of the "obvious" native approach. Keeping `scripts/spike_tool_calling.py` in the repo permanently means the reasoning behind that decision is checkable later, not just a claim in a doc.

## What's next

Milestone 2 built the actual browser automation layer (the thing the model's tool calls eventually control), independent of any model, so it could be tested and proven correct on its own first. See `docs/milestones/02-browser-tool-layer.md`.