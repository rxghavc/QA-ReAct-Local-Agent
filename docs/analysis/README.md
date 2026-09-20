# Analysis notes and findings

This folder holds the supporting analysis that grew out of the milestone work. It captures the measured findings, failure patterns, optimization experiments, and decision notes that explain why the project evolved the way it did. The numbered milestone sequence remains in [../milestones/README.md](../milestones/README.md).

## Included topics

- [Benchmark trustworthiness](benchmark-trustworthiness.md): reliability checks, preflight validation, and the rules that make the benchmark results meaningful.
- [Context optimization](context-optimization.md): the actual cost and payload findings behind the trimming and observation-summary changes.
- [Failure taxonomy](failure-taxonomy.md): the hand-classified breakdown of real failed runs and the categories that mattered in practice.
- [Observability per-step timing](observability-per-step-timing.md): timing and bottleneck analysis for the ReAct loop and browser call path.
- [Quantization comparison](quantization-comparison.md): measured tradeoffs between model quantization choices and the actual reliability impact.
- [Regression gate](regression-gate.md): the threshold logic and the rationale for keeping the suite honest over time.
- [Report semantics and clarification](report-semantics-and-clarification.md): the lessons around tool semantics, self-reports, and clarification behavior.
- [Token cost accounting](token-cost-accounting.md): the cost model and the measured effect of context growth on inference spend.
- [Trend tracking](trend-tracking.md): the recorded pass-rate history and the way the benchmark changed over time.

## Purpose

Use this folder when you want the reasoning behind a change, the measured evidence behind a decision, or the lessons learned after the milestone sequence had already established the main project narrative.