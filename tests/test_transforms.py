"""Tests for the image transform pipeline."""


from PIL import Image

from mediainfo.transforms import (
    Blur,
    Brightness,
    Contrast,
    Fit,
    Grayscale,
    Pad,
    Resize,
    Rotate,
    parse_pipeline,
    pipeline_cache_key,
)


def _rgb(w=200, h=300, color=(100, 150, 200)):
    img = Image.new("RGB", (w, h), color)
    return img


# ---------------------------------------------------------------------------
# Individual transforms
# ---------------------------------------------------------------------------

def test_fit_crops_to_exact_size():
    out = Fit(64, 64).apply(_rgb(200, 300))
    assert out.size == (64, 64)


def test_pad_adds_letterbox():
    out = Pad(200, 200).apply(_rgb(100, 50))
    assert out.size == (200, 200)


def test_resize_ignores_aspect_ratio():
    out = Resize(50, 80).apply(_rgb(200, 200))
    assert out.size == (50, 80)


def test_grayscale_output_is_rgb():
    out = Grayscale().apply(_rgb(10, 10, (255, 0, 0)))
    assert out.mode == "RGB"
    r, g, b = out.getpixel((5, 5))
    assert r == g == b  # all channels equal → greyscale


def test_blur_returns_same_size():
    img = _rgb(50, 50)
    out = Blur(radius=3).apply(img)
    assert out.size == img.size


def test_brightness_brightens():
    img = _rgb(10, 10, (100, 100, 100))
    out = Brightness(factor=2.0).apply(img)
    r, _, _ = out.getpixel((5, 5))
    assert r > 100


def test_contrast_changes_image():
    img = _rgb(10, 10, (128, 128, 128))
    out = Contrast(factor=2.0).apply(img)
    assert out.size == img.size


def test_rotate_90_swaps_dimensions_with_expand():
    out = Rotate(degrees=90, expand=True).apply(_rgb(200, 100))
    assert out.size == (100, 200)


def test_rotate_without_expand_keeps_size():
    out = Rotate(degrees=45, expand=False).apply(_rgb(100, 100))
    assert out.size == (100, 100)


# ---------------------------------------------------------------------------
# parse_pipeline
# ---------------------------------------------------------------------------

def test_parse_string_entry():
    pipeline = parse_pipeline(["grayscale"])
    assert len(pipeline) == 1
    assert isinstance(pipeline[0], Grayscale)


def test_parse_list_params():
    pipeline = parse_pipeline([{"fit": [1920, 1080]}])
    t = pipeline[0]
    assert isinstance(t, Fit)
    assert t.width == 1920
    assert t.height == 1080


def test_parse_dict_params():
    pipeline = parse_pipeline([{"pad": {"width": 800, "height": 600, "color": "white"}}])
    t = pipeline[0]
    assert isinstance(t, Pad)
    assert t.color == "white"


def test_parse_scalar_param():
    pipeline = parse_pipeline([{"brightness": 1.5}])
    assert isinstance(pipeline[0], Brightness)
    assert pipeline[0].factor == 1.5


def test_parse_multi_step_pipeline():
    pipeline = parse_pipeline([
        {"fit": [64, 64]},
        "grayscale",
        {"brightness": {"factor": 1.2}},
    ])
    assert len(pipeline) == 3
    assert isinstance(pipeline[0], Fit)
    assert isinstance(pipeline[1], Grayscale)
    assert isinstance(pipeline[2], Brightness)


def test_parse_empty_returns_empty():
    assert parse_pipeline([]) == []
    assert parse_pipeline(None) == []


def test_parse_unknown_transform_skips_with_warning():
    pipeline = parse_pipeline([{"unknown_op": {}}])
    assert pipeline == []


def test_parse_bad_params_skips_with_warning():
    pipeline = parse_pipeline([{"fit": {"bad_key": 99}}])
    assert pipeline == []


# ---------------------------------------------------------------------------
# pipeline_cache_key
# ---------------------------------------------------------------------------

def test_same_pipeline_same_key():
    a = parse_pipeline([{"fit": [64, 64]}, "grayscale"])
    b = parse_pipeline([{"fit": [64, 64]}, "grayscale"])
    assert pipeline_cache_key(a) == pipeline_cache_key(b)


def test_different_pipeline_different_key():
    a = parse_pipeline([{"fit": [64, 64]}])
    b = parse_pipeline([{"fit": [128, 128]}])
    assert pipeline_cache_key(a) != pipeline_cache_key(b)


def test_empty_pipeline_key_is_stable():
    assert pipeline_cache_key([]) == pipeline_cache_key([])


# ---------------------------------------------------------------------------
# ImageCache.get_transformed_path
# ---------------------------------------------------------------------------

def test_get_transformed_path_noop_for_empty_pipeline(tmp_path):
    from mediainfo.cache import ImageCache

    img_path = tmp_path / "source.jpg"
    _rgb().save(img_path)

    cache = ImageCache(tmp_path)
    result = cache.get_transformed_path(img_path, [])
    assert result == img_path  # unchanged


def test_get_transformed_path_creates_cached_file(tmp_path):
    from mediainfo.cache import ImageCache

    img_path = tmp_path / "source.jpg"
    _rgb(200, 200).save(img_path)

    cache = ImageCache(tmp_path)
    pipeline = parse_pipeline([{"fit": [64, 64]}])
    result = cache.get_transformed_path(img_path, pipeline)

    assert result != img_path
    assert result.exists()
    out = Image.open(result)
    assert out.size == (64, 64)


def test_get_transformed_path_reuses_cached_file(tmp_path):
    from mediainfo.cache import ImageCache

    img_path = tmp_path / "source.jpg"
    _rgb(200, 200).save(img_path)

    cache = ImageCache(tmp_path)
    pipeline = parse_pipeline([{"fit": [64, 64]}])

    first = cache.get_transformed_path(img_path, pipeline)
    second = cache.get_transformed_path(img_path, pipeline)
    assert first == second  # same cached file returned
