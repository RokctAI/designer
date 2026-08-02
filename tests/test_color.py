import math

from designer.color import (
    contrast_ratio,
    delta_e,
    nearest_color,
    oklab_to_rgb,
    parse_color,
    rgb_to_oklab,
    to_hex,
)


def test_parse_hex_forms():
    assert parse_color("#1a56db") == (26, 86, 219)
    assert parse_color("1A56DB") == (26, 86, 219)
    assert parse_color("#fff") == (255, 255, 255)
    assert parse_color("rgb(26, 86, 219)") == (26, 86, 219)
    assert parse_color("white") == (255, 255, 255)
    assert parse_color("none") is None
    assert parse_color("url(#grad)") is None


def test_to_hex_round_trip():
    assert to_hex((26, 86, 219)) == "#1a56db"


def test_oklab_round_trip():
    for rgb in [(0, 0, 0), (255, 255, 255), (26, 86, 219), (245, 158, 11)]:
        back = oklab_to_rgb(rgb_to_oklab(rgb))
        assert all(abs(a - b) <= 1 for a, b in zip(rgb, back))


def test_oklab_white_is_l1():
    L, a, b = rgb_to_oklab((255, 255, 255))
    assert math.isclose(L, 1.0, abs_tol=1e-3)
    assert abs(a) < 1e-3 and abs(b) < 1e-3


def test_contrast_extremes():
    assert math.isclose(contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, rel_tol=1e-3)
    assert math.isclose(contrast_ratio((128, 128, 128), (128, 128, 128)), 1.0)


def test_delta_e_ordering():
    blue = (26, 86, 219)
    assert delta_e(blue, (30, 90, 210)) < delta_e(blue, (245, 158, 11))


def test_nearest_color():
    tokens = [(26, 86, 219), (245, 158, 11), (255, 255, 255)]
    idx, dist = nearest_color((250, 160, 20), tokens)
    assert idx == 1
    assert dist < 0.05
