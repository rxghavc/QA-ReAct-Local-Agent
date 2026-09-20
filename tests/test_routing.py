"""Unit tests for agent/routing.py's deterministic same-failure check.

The three "same mistake" cases below are the real ones from the
2026-09-17 benchmark run that the rejected llama3.2:3b classifier got
wrong (see scripts/spike_3b_routing.py), and the "different" cases are
the controls that caught a prompt which had learned to always answer
"same". They are kept as regression tests so a future change to this
function has to keep getting both groups right, not just the first.
"""

from agent.routing import failure_target, is_same_failure


def _click(**arguments):
    return {"name": "click", "arguments": arguments}


def test_failure_target_prefers_selector_then_text_then_url():
    assert failure_target(_click(selector="#a", text="Login")) == "a"
    assert failure_target(_click(text="Login")) == "login"
    assert failure_target({"name": "navigate", "arguments": {"url": "HTTP://X"}}) == (
        "http x"
    )


def test_failure_target_reduces_a_target_to_a_word_sequence():
    """Case, whitespace and separators all normalise away, so a visible
    label and the selector for the same control become comparable."""
    assert failure_target(_click(text="  CHECKOUT:   YOUR  INFORMATION ")) == (
        "checkout your information"
    )
    assert failure_target(_click(selector="#add-to-cart-sauce-labs-backpack")) == (
        "add to cart sauce labs backpack"
    )
    assert failure_target(_click(selector="#user_name")) == "user name"


def test_failure_target_is_empty_when_no_target_was_named():
    assert failure_target({"name": "get_page_state", "arguments": {}}) == ""
    assert failure_target({"name": "click"}) == ""


def test_same_failure_when_only_capitalisation_differs():
    assert (
        is_same_failure(
            _click(text="Checkout"), "no match", _click(text="CHECKOUT"), "no match"
        )
        is True
    )


def test_same_failure_when_the_planner_pads_the_label_it_is_guessing():
    assert (
        is_same_failure(
            _click(text="CHECKOUT"),
            "no match",
            _click(text="CHECKOUT: YOUR INFORMATION"),
            "no match",
        )
        is True
    )


def test_same_failure_across_different_tools_aimed_at_one_selector():
    assert (
        is_same_failure(
            _click(selector=".bm-burger-menu"),
            "no clickable element matched",
            {"name": "wait_for", "arguments": {"selector": ".bm-burger-menu"}},
            "timed out waiting for selector",
        )
        is True
    )


def test_different_failures_aimed_at_unrelated_targets():
    assert (
        is_same_failure(
            _click(text="Shopping Cart (1)"),
            "no match",
            {"name": "wait_for", "arguments": {"selector": "#finish"}},
            "timed out",
        )
        is False
    )
    assert (
        is_same_failure(
            {"name": "type_text", "arguments": {"selector": "#password"}},
            "no input matched",
            _click(text="CHECKOUT"),
            "no match",
        )
        is False
    )
    assert (
        is_same_failure(
            {"name": "navigate", "arguments": {"url": "https://nope.invalid"}},
            "ERR_NAME_NOT_RESOLVED",
            _click(selector=".bm-burger-menu"),
            "no match",
        )
        is False
    )


def test_same_failure_when_a_label_and_a_selector_name_one_control():
    """The live task_03 miss this rule exists for: the planner tried the
    add-to-cart button by visible text, then by its selector. One
    mistake wearing two spellings, which exact matching cannot see."""
    assert (
        is_same_failure(
            _click(text="Add to cart"),
            "no clickable element matched",
            {
                "name": "wait_for",
                "arguments": {"selector": "#add-to-cart-sauce-labs-backpack"},
            },
            "timed out waiting for selector",
        )
        is True
    )
    assert (
        is_same_failure(
            _click(text="Login"), "e", _click(selector="#login-button"), "e"
        )
        is True
    )


def test_containment_matches_whole_words_only():
    """Treating separators as word breaks must not make unrelated targets
    look alike: 'art' is not the 'smart button', and '#a' is not
    '#aside'."""
    assert (
        is_same_failure(_click(text="Art"), "e", _click(selector="#smart-button"), "e")
        is False
    )
    assert (
        is_same_failure(
            _click(text="Cart"), "e", _click(selector="#chart-container"), "e"
        )
        is False
    )
    assert (
        is_same_failure(_click(selector="#a"), "e", _click(selector="#aside"), "e")
        is False
    )
    assert (
        is_same_failure(
            _click(selector="#user-name"), "e", _click(selector="#password"), "e"
        )
        is False
    )
    assert (
        is_same_failure(_click(text="Login"), "e", _click(text="Logout"), "e") is False
    )


def test_short_targets_are_only_matched_exactly():
    assert (
        is_same_failure(_click(selector="#a"), "e", _click(selector="#a"), "e") is True
    )


def test_no_target_is_conservatively_not_the_same_failure():
    """A missed dedup costs one ordinary retry, while a wrong "same"
    suppresses a re-plan the planner actually needed."""
    assert is_same_failure({"name": "click"}, "e", _click(text="Login"), "e") is False
    assert is_same_failure(_click(text="Login"), "e", {"name": "click"}, "e") is False
