"""Tests for _HealthTracker's output-error bookkeeping."""

from mediainfo.orchestrator_health import _HealthTracker


def test_output_error_since_set_on_first_error():
    tracker = _HealthTracker()
    tracker.record_output_error(0, "boom", now=1000.0)

    assert tracker.output_error_since[0] == 1000.0


def test_output_error_since_unchanged_by_subsequent_errors():
    tracker = _HealthTracker()
    tracker.record_output_error(0, "boom", now=1000.0)
    tracker.record_output_error(0, "boom again", now=1100.0)

    assert tracker.output_error_since[0] == 1000.0  # still the original streak start
    assert tracker.output_errors[0] == ("boom again", 1100.0)  # message/timestamp still latest


def test_output_error_since_cleared_on_success():
    tracker = _HealthTracker()
    tracker.record_output_error(0, "boom", now=1000.0)
    tracker.record_output_success(0)

    assert 0 not in tracker.output_error_since
    assert 0 not in tracker.output_errors


def test_as_dict_includes_failing_for_seconds():
    tracker = _HealthTracker()
    tracker.record_output_error(0, "boom", now=1000.0)
    tracker.record_output_error(0, "boom again", now=1100.0)

    data = tracker.as_dict(now=1150.0)

    assert data["output_errors"][0]["ago_seconds"] == 50.0  # since the latest error
    assert data["output_errors"][0]["failing_for_seconds"] == 150.0  # since the streak began


def test_independent_outputs_tracked_separately():
    tracker = _HealthTracker()
    tracker.record_output_error(0, "boom", now=1000.0)
    tracker.record_output_error(1, "boom", now=1050.0)
    tracker.record_output_success(0)

    assert 0 not in tracker.output_error_since
    assert tracker.output_error_since[1] == 1050.0
