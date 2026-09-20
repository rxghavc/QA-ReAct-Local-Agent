"""Unit tests for benchmark/trend.py."""

from benchmark import trend


def test_append_entry_writes_one_json_line(tmp_path):
    path = tmp_path / "trend.jsonl"
    entry = trend.append_entry([0.83, 0.92], 0.80, True, path=path)

    assert entry["num_runs"] == 2
    assert entry["pass_rates"] == [0.83, 0.92]
    assert entry["min_pass_rate"] == 0.83
    assert entry["max_pass_rate"] == 0.92
    assert entry["mean_pass_rate"] == 0.875
    assert entry["gate_threshold"] == 0.80
    assert entry["gate_passed"] is True
    assert "measured_at" in entry
    assert path.read_text().count("\n") == 1


def test_append_entry_is_additive_across_calls(tmp_path):
    path = tmp_path / "trend.jsonl"
    trend.append_entry([0.9], 0.55, True, path=path)
    trend.append_entry([0.4], 0.55, False, path=path)

    entries = trend.load_entries(path)
    assert len(entries) == 2
    assert entries[0]["gate_passed"] is True
    assert entries[1]["gate_passed"] is False


def test_load_entries_returns_empty_list_when_no_file_exists(tmp_path):
    assert trend.load_entries(tmp_path / "does_not_exist.jsonl") == []


def test_format_trend_reports_no_history_when_empty():
    assert "No trend history" in trend.format_trend([])


def test_format_trend_renders_each_entry():
    entries = [
        {
            "measured_at": "2026-09-18T19:00:00Z",
            "commit": "abc1234",
            "num_runs": 3,
            "pass_rates": [0.83, 0.92, 0.92],
            "min_pass_rate": 0.83,
            "mean_pass_rate": 0.89,
            "max_pass_rate": 0.92,
            "gate_threshold": 0.80,
            "gate_passed": True,
        }
    ]

    output = trend.format_trend(entries)

    assert "abc1234" in output
    assert "83%" in output
    assert "89%" in output
    assert "92%" in output
    assert "PASS" in output


def test_format_trend_handles_a_missing_commit_gracefully():
    entries = [
        {
            "measured_at": "2026-09-18T19:00:00Z",
            "commit": None,
            "num_runs": 2,
            "pass_rates": [0.5, 0.5],
            "min_pass_rate": 0.5,
            "mean_pass_rate": 0.5,
            "max_pass_rate": 0.5,
            "gate_threshold": 0.55,
            "gate_passed": False,
        }
    ]

    output = trend.format_trend(entries)

    assert "?" in output
    assert "FAIL" in output
