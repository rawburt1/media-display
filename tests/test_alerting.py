"""Tests for AlertManager (webhook alerting for persistent source or
output failures)."""

from unittest.mock import patch

from mediainfo.alerting import AlertManager
from mediainfo.config import AlertConfig


def _config(**kwargs):
    defaults = dict(
        enabled=True,
        webhook_url="https://example.com/webhook",
        error_threshold_seconds=300,
        repeat_interval_seconds=3600,
    )
    defaults.update(kwargs)
    return AlertConfig(**defaults)


@patch("mediainfo.alerting.requests.post")
def test_does_nothing_when_disabled(mock_post):
    manager = AlertManager(_config(enabled=False))
    manager.check({0: "pixoo"}, {0: 0.0}, now=1000.0)
    mock_post.assert_not_called()


@patch("mediainfo.alerting.requests.post")
def test_does_nothing_without_webhook_url(mock_post):
    manager = AlertManager(_config(webhook_url=""))
    manager.check({0: "pixoo"}, {0: 0.0}, now=1000.0)
    mock_post.assert_not_called()


@patch("mediainfo.alerting.requests.post")
def test_does_not_alert_before_threshold(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check({0: "pixoo"}, {0: 800.0}, now=1000.0)  # only failing 200s
    mock_post.assert_not_called()


@patch("mediainfo.alerting.requests.post")
def test_alerts_once_threshold_elapsed(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0)  # failing 300s

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["output"] == "pixoo"
    assert kwargs["json"]["duration_seconds"] == 300.0


@patch("mediainfo.alerting.requests.post")
def test_does_not_repeat_alert_within_repeat_interval(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300, repeat_interval_seconds=3600))
    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0)
    manager.check({0: "pixoo"}, {0: 700.0}, now=2000.0)  # still failing, well within repeat window

    mock_post.assert_called_once()


@patch("mediainfo.alerting.requests.post")
def test_repeats_alert_after_repeat_interval_elapses(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300, repeat_interval_seconds=3600))
    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0)
    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0 + 3601)

    assert mock_post.call_count == 2


@patch("mediainfo.alerting.requests.post")
def test_recovery_resets_alert_state(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300, repeat_interval_seconds=3600))
    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0)
    assert mock_post.call_count == 1

    manager.check({0: "pixoo"}, {}, now=1100.0)  # recovered - no longer in error_since
    mock_post.reset_mock()

    # Fails again shortly after recovery - should alert again on its own
    # fresh threshold, not be suppressed by the old repeat window.
    manager.check({0: "pixoo"}, {0: 1100.0}, now=1100.0 + 300)
    assert mock_post.call_count == 1


@patch("mediainfo.alerting.requests.post")
def test_unknown_output_label_falls_back_to_index(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check({}, {0: 700.0}, now=1000.0)

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["output"] == "output #0"


@patch("mediainfo.alerting.requests.post")
def test_send_failure_is_caught_and_logged(mock_post):
    mock_post.side_effect = ConnectionError("no network")
    manager = AlertManager(_config(error_threshold_seconds=300))

    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0)  # must not raise


@patch("mediainfo.alerting.requests.post")
def test_multiple_outputs_alerted_independently(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check({0: "pixoo", 1: "ulanzi"}, {0: 700.0, 1: 999.0}, now=1000.0)

    assert mock_post.call_count == 1
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["output"] == "pixoo"


# ---------------------------------------------------------------------------
# source_error_since (mirrors the output_error_since tests above, but via
# the source_error_since parameter rather than the required positional args)
# ---------------------------------------------------------------------------


@patch("mediainfo.alerting.requests.post")
def test_source_does_not_alert_before_threshold(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check({}, {}, now=1000.0, source_error_since={"vinyl": 800.0})  # only failing 200s
    mock_post.assert_not_called()


@patch("mediainfo.alerting.requests.post")
def test_source_alerts_once_threshold_elapsed(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check({}, {}, now=1000.0, source_error_since={"vinyl": 700.0})  # failing 300s

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["source"] == "vinyl"
    assert kwargs["json"]["kind"] == "source"
    assert kwargs["json"]["duration_seconds"] == 300.0


@patch("mediainfo.alerting.requests.post")
def test_source_does_not_repeat_alert_within_repeat_interval(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300, repeat_interval_seconds=3600))
    manager.check({}, {}, now=1000.0, source_error_since={"vinyl": 700.0})
    manager.check({}, {}, now=2000.0, source_error_since={"vinyl": 700.0})

    mock_post.assert_called_once()


@patch("mediainfo.alerting.requests.post")
def test_source_recovery_resets_alert_state(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300, repeat_interval_seconds=3600))
    manager.check({}, {}, now=1000.0, source_error_since={"vinyl": 700.0})
    assert mock_post.call_count == 1

    manager.check({}, {}, now=1100.0, source_error_since={})  # recovered
    mock_post.reset_mock()

    manager.check({}, {}, now=1100.0 + 300, source_error_since={"vinyl": 1100.0})
    assert mock_post.call_count == 1


@patch("mediainfo.alerting.requests.post")
def test_source_and_output_alerting_are_independent(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300, repeat_interval_seconds=3600))
    # Output alert fires and enters its own repeat window...
    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0, source_error_since={})
    assert mock_post.call_count == 1

    # ...a source starting to fail at the same moment must still alert on
    # its own schedule, not be suppressed by the output's repeat window.
    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0, source_error_since={"vinyl": 700.0})
    assert mock_post.call_count == 2
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["source"] == "vinyl"


@patch("mediainfo.alerting.requests.post")
def test_source_send_failure_is_caught_and_logged(mock_post):
    mock_post.side_effect = ConnectionError("no network")
    manager = AlertManager(_config(error_threshold_seconds=300))

    manager.check({}, {}, now=1000.0, source_error_since={"vinyl": 700.0})  # must not raise


@patch("mediainfo.alerting.requests.post")
def test_multiple_sources_alerted_independently(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check({}, {}, now=1000.0, source_error_since={"vinyl": 700.0, "kodi": 999.0})

    assert mock_post.call_count == 1
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["source"] == "vinyl"


# ---------------------------------------------------------------------------
# check_watchdog (M7 - a stalled/dead orchestrator poll loop)
# ---------------------------------------------------------------------------


@patch("mediainfo.alerting.requests.post")
def test_watchdog_does_nothing_when_disabled(mock_post):
    manager = AlertManager(_config(enabled=False))
    manager.check_watchdog(700.0, now=1000.0)
    mock_post.assert_not_called()


@patch("mediainfo.alerting.requests.post")
def test_watchdog_does_nothing_before_first_tick(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check_watchdog(None, now=1000.0)
    mock_post.assert_not_called()


@patch("mediainfo.alerting.requests.post")
def test_watchdog_does_not_alert_before_threshold(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check_watchdog(800.0, now=1000.0)  # only stale 200s
    mock_post.assert_not_called()


@patch("mediainfo.alerting.requests.post")
def test_watchdog_alerts_once_threshold_elapsed(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check_watchdog(700.0, now=1000.0)  # stale 300s

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["watchdog"] == "orchestrator poll loop"
    assert kwargs["json"]["duration_seconds"] == 300.0


@patch("mediainfo.alerting.requests.post")
def test_watchdog_does_not_repeat_alert_within_repeat_interval(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300, repeat_interval_seconds=3600))
    manager.check_watchdog(700.0, now=1000.0)
    manager.check_watchdog(700.0, now=2000.0)  # still stale, well within repeat window

    mock_post.assert_called_once()


@patch("mediainfo.alerting.requests.post")
def test_watchdog_recovery_lets_a_fresh_stall_alert_on_its_own_threshold(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300, repeat_interval_seconds=3600))
    manager.check_watchdog(700.0, now=1000.0)
    assert mock_post.call_count == 1

    manager.check_watchdog(None, now=1100.0)  # recovered - a fresh heartbeat came in
    mock_post.reset_mock()

    # Stalls again shortly after recovery - alerts again on its own fresh
    # threshold, not suppressed by the old repeat window.
    manager.check_watchdog(1100.0, now=1100.0 + 300)
    assert mock_post.call_count == 1


@patch("mediainfo.alerting.requests.post")
def test_watchdog_and_output_alerting_are_independent(mock_post):
    manager = AlertManager(_config(error_threshold_seconds=300))
    manager.check({0: "pixoo"}, {0: 700.0}, now=1000.0)
    manager.check_watchdog(700.0, now=1000.0)

    assert mock_post.call_count == 2
    kinds = {call.kwargs["json"]["kind"] for call in mock_post.call_args_list}
    assert kinds == {"output", "watchdog"}
