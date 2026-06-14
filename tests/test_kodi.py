"""Tests for Kodi artwork URL resolution."""

from pixoo_media.sources.kodi import resolve_kodi_image_url


def test_resolve_kodi_image_url():
    art_path = "image://http%3a%2f%2fexample.com%2fposter.jpg/"

    url = resolve_kodi_image_url("192.168.1.50", 8080, art_path)

    assert url == (
        "http://192.168.1.50:8080/image/"
        "image%3A%2F%2Fhttp%253a%252f%252fexample.com%252fposter.jpg%2F"
    )
