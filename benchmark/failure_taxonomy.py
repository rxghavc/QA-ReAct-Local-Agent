"""Categorizes a failed task run's real cause, from its trace.

Built the way the plan (docs/ai-infra-and-observability.md) said to: by
reading real failed runs out of logs/ first, by hand, to find out what
actually happens, then writing rules for exactly those patterns. Every
category below has at least one real captured example backing it (see
docs/milestones/failure-taxonomy.md for the specific log files). Two
categories the plan's own suggested list named, "premature give-up" and
"context overflow", have zero real examples in this project's logs so
far and are deliberately not included: inventing a rule for a pattern
that has never actually happened would be guessing, not categorizing.

Checked in priority order, most specific/actionable first, since a
single failed run often matches more than one pattern (a selector-drift
run is also, trivially, "not passed"), and the point of a taxonomy is to
say what to fix, not to describe every true fact about the run.
"""

from __future__ import annotations

FAILURE_CATEGORIES = (
    "unparseable_model_output",
    "environment_flakiness",
    "tool_semantics_mismatch",
    "ambiguity_not_recognized",
    "invalid_selector_syntax",
    "selector_drift",
    "hallucinated_success",
    "unclassified",
)

_FAILURE_LANGUAGE = ("fail", "invalid", "did not", "didn't", "unable", "not found")
_NETWORK_ERROR_MARKERS = ("net::err_", "connection refused", "name_not_resolved")


def _tool_results(record: dict) -> list[dict]:
    return [
        step["result"]
        for step in record.get("trace", [])
        if isinstance(step.get("result"), dict)
    ]


def _navigate_results(record: dict) -> list[dict]:
    return [
        step["result"]
        for step in record.get("trace", [])
        if step.get("tool_call", {}).get("name") == "navigate"
        and isinstance(step.get("result"), dict)
    ]


def classify_failure(record: dict) -> str:
    """The category for one failed run. Only meaningful when `passed` is
    False; callers should not call this for a pass or a skip.
    """
    outcome = record.get("self_report")
    summary = (record.get("self_report_summary") or "").lower()
    tool_results = _tool_results(record)
    errors = [
        str(r.get("error", "")).lower()
        for r in tool_results
        if r.get("success") is False
    ]

    # Real example: task_03/task_04 stuck at step 0 on an unterminated
    # ```json fence (Milestone 8's third malformed-output shape).
    if outcome == "stuck":
        return "unparseable_model_output"

    # Real example: the-internet.herokuapp.com returning a page titled
    # "Application Error" mid-run during Milestone 7's A/B comparison.
    # The agent did the right thing (report_blocked); the site, not the
    # agent, failed. Checked on the title specifically, not on an empty
    # headings/clickable list: saucedemo's real, healthy login page also
    # has neither (its button is an <input>, which has no inner text),
    # so that emptiness is not evidence of anything being down, and an
    # earlier version of this rule used it and misclassified saucedemo's
    # entire login flow as an outage.
    if any(r.get("title") == "Application Error" for r in _navigate_results(record)):
        return "environment_flakiness"
    if any(marker in e for e in errors for marker in _NETWORK_ERROR_MARKERS):
        return "environment_flakiness"

    # Negative-tier tasks (self_report_correct is None by construction,
    # see benchmark/runner.py) get their own two buckets, checked before
    # the generic ones below, because for these tasks the real defect is
    # about the terminal signal chosen, not about whichever selector
    # happened to fail this particular run.
    if record.get("self_report_correct") is None:
        # Real example: task_11 pre-fix, "Failed to log in. Received
        # error message: 'Your username is invalid!'" then report_done.
        if outcome == "done" and any(word in summary for word in _FAILURE_LANGUAGE):
            return "tool_semantics_mismatch"
        # Real example: task_12, clicking the first book and calling it
        # "the best book" without ever engaging with what "best" means,
        # or giving up on a selector without ever asking the question.
        return "ambiguity_not_recognized"

    # Real example: task_08 guessing jQuery-only `:contains(...)`, which
    # is not a valid CSS selector and throws a SyntaxError, not a
    # timeout. A different defect from a merely-wrong-but-valid selector.
    if any("syntaxerror" in e for e in errors):
        return "invalid_selector_syntax"

    # Real example: task_03/task_04/task_05/task_12 guessing a CSS
    # selector or visible-text string that never matches anything on the
    # page, timing out on Locator.click or Locator.wait_for. The single
    # largest category in this project's logs by a wide margin.
    if any("timeout" in e and ("locator" in e or "waiting for" in e) for e in errors):
        return "selector_drift"

    # Real example: task_01/task_03, a click succeeding against the
    # wrong element (a heading, a product panel) with no error, and
    # report_done called with no extract_text/get_page_state check
    # first; and task_08, extract_text succeeding but returning the
    # wrong table row's value. Different mechanisms, same higher-level
    # defect: report_done was called, self-report accuracy says it was
    # wrong, and neither of the two more specific buckets above fired.
    if outcome == "done" and record.get("self_report_correct") is False:
        return "hallucinated_success"

    return "unclassified"
