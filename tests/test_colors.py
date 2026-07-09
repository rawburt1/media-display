from PIL import Image

from mediainfo.colors import dominant_colors, to_hex


def _half_and_half_image(width: int = 64, height: int = 64) -> Image.Image:
    """Left half pure red, right half pure blue - gives dominant_colors an
    unambiguous, predictable palette to extract."""
    img = Image.new("RGB", (width, height), (255, 0, 0))
    for x in range(width // 2, width):
        for y in range(height):
            img.putpixel((x, y), (0, 0, 255))
    return img


def test_dominant_colors_finds_both_halves():
    colors = dominant_colors(_half_and_half_image(), count=4)
    assert (255, 0, 0) in colors
    assert (0, 0, 255) in colors


def test_dominant_colors_orders_most_prevalent_first():
    # 3/4 red, 1/4 blue - red must come first.
    img = Image.new("RGB", (64, 64), (255, 0, 0))
    for x in range(48, 64):
        for y in range(48, 64):
            img.putpixel((x, y), (0, 0, 255))
    colors = dominant_colors(img, count=4)
    assert colors[0] == (255, 0, 0)


def test_to_hex():
    assert to_hex((255, 0, 0)) == "#ff0000"
    assert to_hex((0, 128, 255)) == "#0080ff"
    assert to_hex((0, 0, 0)) == "#000000"
