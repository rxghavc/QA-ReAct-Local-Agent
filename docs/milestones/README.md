# Milestone write-ups

Here are full, detailed accounts of each completed build milestone: what was built, why, how it was verified (with real commands and real output), and what went wrong along the way.

- [01: Tool-calling spike](01-tool-calling-spike.md), does the local planner model actually support tool calling, and how that was tested before writing any real agent code.
- [02: Browser tool layer](02-browser-tool-layer.md), building and proving the Playwright + FastAPI browser control layer, independent of any model.
- [03: Minimal ReAct loop](03-react-loop.md), wiring the model up to the browser layer for the first time, and the two real bugs the first live run surfaced.
- [04: Dockerize](04-dockerize.md), getting the agent and browser containers to actually talk to each other, and the one-line networking bug that had to be found first.
- [05: Task suite and scorer](05-task-suite-scorer.md), building an actual benchmark with a programmatic scorer instead of a human reading a trace, and the two real failures its first run caught.