"""Tests for AlertManager (webhook alerting for persistent output failures)."""

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
