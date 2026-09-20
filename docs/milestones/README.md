# Milestone write-ups

Here are full, detailed accounts of each completed build milestone (and the fix work between them): what was built, why, how it was verified (with real commands and real output), and what went wrong along the way.

- [01: Tool-calling spike](01-tool-calling-spike.md), does the local planner model actually support tool calling, and how that was tested before writing any real agent code.
- [02: Browser tool layer](02-browser-tool-layer.md), building and proving the Playwright + FastAPI browser control layer, independent of any model.
- [03: Minimal ReAct loop](03-react-loop.md), wiring the model up to the browser layer for the first time, and the two real bugs the first live run surfaced.
- [04: Dockerize](04-dockerize.md), getting the agent and browser containers to actually talk to each other, and the one-line networking bug that had to be found first.
- [05: Task suite and scorer](05-task-suite-scorer.md), building an actual benchmark with a programmatic scorer instead of a human reading a trace, and the two real failures its first run caught.
- [06: Self-correction and dynamic elements](06-self-correction-dynamic-elements.md), why the originally-planned retry mechanism didn't match the real failures, the prompt fix that did, and the brand-new browser-layer bug that same fix accidentally caused.
- [07: 3b model routing](07-model-routing.md), how a 3b classifier passed its tests, shipped, and then got every live activation wrong, why the obvious fix was worse, and what five measured prompt strategies said about using a model this small as a judge at all.
- [08: Tier 4, negative tests and the first metrics report](08-tier4-and-negative-tests.md), the suite reaches twelve tasks and four tiers, and the negative tier scores 0/6: the agent describes failure accurately while signalling success, never notices an ambiguous instruction, and never once calls the tool added for it.
- [Benchmark trustworthiness: two fixes before Milestone 8](benchmark-trustworthiness.md), a live-site outage scoring as an agent failure, real run-to-run variance, and a filename-collision bug that would have silently corrupted repeated measurements.
- [Fixes before Milestone 9: report_done semantics and a real ask_clarification trigger](report-semantics-and-clarification.md), why an abstract prompt rule did nothing and a concrete worked example fixed it, and the first-ever (if unreliable) `ask_clarification` call after 36 runs of silence.