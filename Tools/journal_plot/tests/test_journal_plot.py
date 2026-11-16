import math
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import journal_plot as jp  # noqa: E402

EXAMPLE = HERE.parent / "examples" / "sample_page.svg"
PROFILE = HERE.parent / "profile.example.toml"


def cfg(**over):
    c = jp.flat_defaults()
    c.update(over)
    return c


def line_stroke(p0, p1, base, **over):
    c = cfg(**over)
    return jp.Stroke(jp.resample([p0, p1], c["step"]), base, "pen", c)


def test_linear_z_map():
    z = jp.make_z_map(cfg(z_touch=0.0, z_max=-2.0))
    assert z(0) == 0
    assert z(1) == -2
    assert z(0.25) == pytest.approx(-0.5)


def test_force_curve_is_linear_in_grams():
    curve = [[0.0, 20], [-1.0, 60], [-2.0, 80]]
    z = jp.make_z_map(cfg(force_curve=curve))
    assert z(0) == pytest.approx(0.0)
    assert z(1) == pytest.approx(-2.0)
    # 50 g is half way between 20 g and 80 g -> on the steep part of the curve
    assert z(0.5) == pytest.approx(-0.75)


def test_taper_starts_and_ends_light_and_reaches_target():
    s = line_stroke((0, 0), (20, 0), 0.8, min=0.1, taper_in=2.0, taper_out=3.0)
    p = jp.stroke_pressures(s)
    assert p[0] == pytest.approx(0.1)
    assert p[-1] == pytest.approx(0.1)
    assert max(p) == pytest.approx(0.8)
    mid = len(p) // 2
    assert p[mid] == pytest.approx(0.8)


def test_no_taper_is_flat():
    s = line_stroke((0, 0), (10, 0), 0.6, taper_in=0, taper_out=0)
    assert set(round(v, 9) for v in jp.stroke_pressures(s)) == {0.6}


def test_pressure_floor_applies_to_zero_pressure():
    s = line_stroke((0, 0), (10, 0), 0.0, min=0.15, taper_in=0, taper_out=0)
    assert min(jp.stroke_pressures(s)) == pytest.approx(0.15)


def test_down_boost_thins_upstrokes():
    # SVG y grows downward: (0,0)->(0,10) is a downstroke on the page.
    over = dict(down_boost=0.75, taper_in=0, taper_out=0, min=0.0)
    down = jp.stroke_pressures(line_stroke((0, 0), (0, 10), 0.8, **over))
    up = jp.stroke_pressures(line_stroke((0, 10), (0, 0), 0.8, **over))
    across = jp.stroke_pressures(line_stroke((0, 0), (10, 0), 0.8, **over))
    assert down[5] == pytest.approx(0.8)
    assert up[5] == pytest.approx(0.2)
    assert across[5] == pytest.approx(0.2)


def test_simplify_collapses_straight_flat_line():
    pts = jp.resample([(0, 0), (50, 0)], 0.25)
    zs = [-1.0] * len(pts)
    assert jp.simplify(pts, zs, 0.02, 0.01) == [0, len(pts) - 1]


def test_simplify_keeps_pressure_changes():
    pts = jp.resample([(0, 0), (10, 0)], 0.25)
    zs = [0.0 if i < len(pts) // 2 else -1.0 for i in range(len(pts))]
    assert len(jp.simplify(pts, zs, 0.02, 0.01)) > 2


def test_mapper_flips_y_and_offsets():
    m = jp.Mapper((90, 80), cfg(origin_x=5, origin_y=7))
    assert m(0, 0) == (5, 87)       # SVG top-left -> machine top-left
    assert m(90, 80) == (95, 7)     # SVG bottom-right -> machine bottom-right


def test_profile_rejects_unknown_keys(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[pressure]\ntapr_in = 2\n")
    with pytest.raises(SystemExit):
        jp.load_profile(bad)


def test_profile_rejects_bad_z_order(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[pen]\nz_touch = -3.0\n")
    with pytest.raises(SystemExit):
        jp.load_profile(bad)


def test_sample_page_layers_pressures_and_hidden_layer():
    c, pens = jp.load_profile(PROFILE)
    strokes, page, notes = jp.load_svg(EXAMPLE, c, pens)
    assert page == pytest.approx((90, 90))
    assert notes == []
    by_pen = {}
    for s in strokes:
        by_pen.setdefault(s.pen, set()).add(round(s.base, 3))
    # the hidden "Guides" layer must not be plotted
    assert set(by_pen) == {"Brush pen", "Fineliner"}
    assert by_pen["Brush pen"] == {0.9}
    # text 0.35, leaf group 0.5, frame 0.2 (all via inherited/own data-pressure)
    assert by_pen["Fineliner"] == {0.35, 0.5, 0.2}
    # per-pen overrides from the profile reach the strokes
    brush = next(s for s in strokes if s.pen == "Brush pen")
    assert brush.cfg["down_boost"] == 0.6
    fine = next(s for s in strokes if s.pen == "Fineliner")
    assert fine.cfg["z_max"] == -1.0


def test_stroke_width_maps_to_pressure(tmp_path):
    svg = tmp_path / "w.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm" viewBox="0 0 50 50">'
        '<path d="M5,5 L45,5" stroke="#000" stroke-width="1.1" fill="none"/>'
        '<g transform="scale(2)"><path d="M5,10 L20,10" stroke="#000" stroke-width="0.55" fill="none"/></g>'
        '<path d="M5,40 L45,40" stroke="#000" fill="none"/>'
        '<rect x="1" y="1" width="3" height="3" fill="#000"/>'
        '<text x="5" y="30">hello</text>'
        "</svg>"
    )
    c = jp.flat_defaults()
    strokes, _, notes = jp.load_svg(svg, c, {})
    bases = [round(s.base, 3) for s in strokes]
    # 1.1 mm on a 0.2..2.0 scale = 0.5; the scaled group doubles 0.55 mm to 1.1 mm;
    # no stroke-width at all -> default pressure
    assert bases == [0.5, 0.5, c["default"]]
    assert any("Hershey" in n for n in notes)
    assert any("filled" in n for n in notes)


def test_gcode_end_to_end(tmp_path):
    out = tmp_path / "page.gcode"
    preview = tmp_path / "page_preview.svg"
    rc = jp.main([str(EXAMPLE), "-p", str(PROFILE), "-o", str(out), "--preview", str(preview)])
    assert rc == 0
    text = out.read_text()
    assert preview.exists() and "<polyline" in preview.read_text()
    # one pen-mount pause per pen, in layer order
    assert text.count("M0") == 2
    assert text.index("pen: Brush pen") < text.index("pen: Fineliner")
    c, _ = jp.load_profile(PROFILE)
    zs = [float(z) for z in re.findall(r"Z(-?[\d.]+)", text)]
    assert min(zs) >= c["z_max"] - 1e-9 and max(zs) <= c["z_up"] + 1e-9
    # the fineliner is limited to its own z_max of -1.0
    fine = text[text.index("pen: Fineliner"):]
    assert min(float(z) for z in re.findall(r"Z(-?[\d.]+)", fine)) >= -1.0 - 1e-9
    xs = [float(v) for v in re.findall(r"X(-?[\d.]+)", text)]
    ys = [float(v) for v in re.findall(r"Y(-?[\d.]+)", text)]
    assert 0 <= min(xs) and max(xs) <= c["max_x"]
    assert 0 <= min(ys) and max(ys) <= c["max_y"]
    assert text.rstrip().endswith("M2")


def test_out_of_bounds_is_an_error_unless_forced(tmp_path):
    big = tmp_path / "big.svg"
    big.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="150mm" height="20mm" viewBox="0 0 150 20">'
        '<path d="M0,10 L150,10" stroke="#000" fill="none"/></svg>'
    )
    out = tmp_path / "big.gcode"
    assert jp.main([str(big), "-o", str(out)]) == 1
    assert not out.exists()
    assert jp.main([str(big), "-o", str(out), "--force"]) == 0
    assert out.exists()


def test_test_pattern_runs(tmp_path):
    out = tmp_path / "t.gcode"
    assert jp.main(["--test-pattern", "-o", str(out)]) == 0
    assert out.read_text().count("G0 Z5") >= 11


def test_feed_compensates_for_z_motion():
    s = line_stroke((0, 0), (4, 0), 1.0, taper_in=2.0, taper_out=0.0, min=0.0)
    lines, _ = jp.to_gcode(jp.plan([s]), (10, 10), s.cfg, "t", pen_setup=False)
    feeds = [float(f) for f in re.findall(r"^G1 X.*F([\d.]+)", "\n".join(lines), re.M)]
    assert max(feeds) > s.cfg["draw_feed"] * 1.05  # ramp segments go faster along XYZ
    assert min(feeds) == pytest.approx(s.cfg["draw_feed"])
    assert all(not math.isnan(f) for f in feeds)
