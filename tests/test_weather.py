"""mediainfo/weather.py - current weather from a Home Assistant weather entity."""

import logging
from unittest.mock import MagicMock

import requests

from mediainfo.config import HomeAssistantConfig
from mediainfo.weather import HomeAssistantWeather, make_weather_provider

TOKEN = "secret-token-123"


def _config(**kwargs):
    values = {"enabled": True, "host": "ha.local", "port": 8123, "token": TOKEN}
    values.update(kwargs)
    return HomeAssistantConfig(**values)


def _response(state="rainy", temperature=7.5, unit="°C"):
    resp = MagicMock()
    resp.json.return_value = {
        "state": state,
        "attributes": {"temperature": temperature, "temperature_unit": unit},
    }
    return resp


def test_reads_condition_and_temperature():
    get = MagicMock(return_value=_response())
    weather = HomeAssistantWeather(_config(), get=get)
    assert weather.current("weather.smhi_home") == {
        "condition": "rainy",
        "temperature": 7.5,
        "unit": "°C",
    }
    url = get.call_args.args[0]
    assert url == "http://ha.local:8123/api/states/weather.smhi_home"
    assert get.call_args.kwargs["headers"] == {"Authorization": f"Bearer {TOKEN}"}
    assert get.call_args.kwargs["timeout"] == HomeAssistantWeather.TIMEOUT_SECONDS


def test_uses_https_when_configured():
    get = MagicMock(return_value=_response())
    HomeAssistantWeather(_config(use_ssl=True), get=get).current("weather.home")
    assert get.call_args.args[0].startswith("https://")


def test_result_is_cached_until_it_expires():
    now = [1000.0]
    get = MagicMock(return_value=_response())
    weather = HomeAssistantWeather(_config(), get=get, clock=lambda: now[0])
    weather.current("weather.home")
    now[0] += HomeAssistantWeather.TTL_SECONDS - 1
    weather.current("weather.home")
    assert get.call_count == 1
    now[0] += 2
    weather.current("weather.home")
    assert get.call_count == 2


def test_failure_returns_none_logs_once_and_never_leaks_the_token(caplog):
    now = [0.0]
    get = MagicMock(side_effect=requests.ConnectionError(f"Bearer {TOKEN} refused"))
    weather = HomeAssistantWeather(_config(), get=get, clock=lambda: now[0])
    with caplog.at_level(logging.WARNING):
        assert weather.current("weather.home") is None
        now[0] += HomeAssistantWeather.RETRY_SECONDS + 1
        assert weather.current("weather.home") is None
    assert get.call_count == 2
    assert len(caplog.records) == 1
    assert TOKEN not in caplog.text


def test_unavailable_entity_is_no_weather():
    get = MagicMock(return_value=_response(state="unavailable", temperature=None))
    assert HomeAssistantWeather(_config(), get=get).current("weather.home") is None


def test_entity_ids_that_are_not_plain_weather_entities_are_refused():
    get = MagicMock(return_value=_response())
    weather = HomeAssistantWeather(_config(), get=get)
    for bad in ["", "sensor.temp", "weather.home/../../config", "weather.Home"]:
        assert weather.current(bad) is None
    get.assert_not_called()


def test_provider_only_when_home_assistant_is_set_up():
    assert make_weather_provider({}) is None
    assert make_weather_provider({"homeassistant": _config(enabled=False)}) is None
    assert make_weather_provider({"homeassistant": _config(token="")}) is None
    assert callable(make_weather_provider({"homeassistant": _config()}))
