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


# ---------------------------------------------------------------------------
# source_error_since (mirrors output_error_since above, but driven by
# record_backoff/clear_backoff rather than record_output_error/_success)
# ---------------------------------------------------------------------------

def _backoff_state():
    from mediainfo.orchestrator_health import _BackoffState
    return _BackoffState(delay=5.0, next_attempt=0.0)


def test_source_error_since_set_on_first_error():
    tracker = _HealthTracker()
    tracker.record_backoff("kodi", _backoff_state(), now=1000.0)

    assert tracker.source_error_since["kodi"] == 1000.0


def test_source_error_since_unchanged_by_subsequent_errors():
    tracker = _HealthTracker()
    tracker.record_backoff("kodi", _backoff_state(), now=1000.0)
    tracker.record_backoff("kodi", _backoff_state(), now=1100.0)

    assert tracker.source_error_since["kodi"] == 1000.0  # still the original streak start


def test_source_error_since_cleared_on_recovery():
    tracker = _HealthTracker()
    tracker.record_backoff("kodi", _backoff_state(), now=1000.0)
    tracker.clear_backoff("kodi")

    assert "kodi" not in tracker.source_error_since
    assert "kodi" not in tracker.source_backoff


def test_as_dict_includes_source_failing_for_seconds():
    tracker = _HealthTracker()
    tracker.record_backoff("kodi", _backoff_state(), now=1000.0)
    tracker.record_backoff("kodi", _backoff_state(), now=1100.0)

    data = tracker.as_dict(now=1150.0)

    assert data["source_failing_for_seconds"]["kodi"] == 150.0  # since the streak began


def test_independent_sources_tracked_separately():
    tracker = _HealthTracker()
    tracker.record_backoff("kodi", _backoff_state(), now=1000.0)
    tracker.record_backoff("vinyl", _backoff_state(), now=1050.0)
    tracker.clear_backoff("kodi")

    assert "kodi" not in tracker.source_error_since
    assert tracker.source_error_since["vinyl"] == 1050.0
