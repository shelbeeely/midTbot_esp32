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


# --------------------------------------------------------------------------
# Multipen (one pen body, several colour refills)

MULTI_PROFILE = HERE.parent / "profile.multipen.example.toml"
MULTI_EXAMPLE = HERE.parent / "examples" / "multipen_page.svg"


def test_multipen_strokes_map_to_nearest_colour():
    c, pens = jp.load_profile(MULTI_PROFILE)
    strokes, _, _ = jp.load_svg(MULTI_EXAMPLE, c, pens)
    assert {s.pen for s in strokes} == {"black", "red", "blue", "green"}
    for s in strokes:
        assert s.cfg["slot"] == s.pen
        assert s.cfg["axis"] == "Z"  # one pen body: every colour shares the lift servo


def test_multipen_gcode_switches_colours_without_pausing(tmp_path):
    out = tmp_path / "mp.gcode"
    assert jp.main([str(MULTI_EXAMPLE), "-p", str(MULTI_PROFILE), "-o", str(out)]) == 0
    text = out.read_text()
    lines = text.splitlines()
    assert text.count("M0") == 1  # only the one-time pen height setup
    # setup selects black, so the black section must not select it again
    black = lines.index(next(l for l in lines if l.startswith("(--- pen: black")))
    assert lines[black + 1] != "G0 A0"
    # every other colour runs its own select sequence right after its header
    c, _ = jp.load_profile(MULTI_PROFILE)
    for colour in ("red", "blue", "green"):
        i = lines.index(next(l for l in lines if l.startswith(f"(--- pen: {colour}")))
        sel = c["slots"][colour]["select"]
        assert lines[i + 1:i + 1 + len(sel)] == sel
    # never two words for the same axis in one move
    for line in lines:
        words = [w[0] for w in line.split()[1:] if w[0] in "XYZABC"]
        assert len(words) == len(set(words)), line


def test_multipen_uses_each_colours_touch_height(tmp_path):
    out = tmp_path / "mp.gcode"
    jp.main([str(MULTI_EXAMPLE), "-p", str(MULTI_PROFILE), "-o", str(out)])
    lines = out.read_text().splitlines()
    c, pens = jp.load_profile(MULTI_PROFILE)
    red = jp.slot_cfg(c, "red")
    expected = jp.make_z_map(red)(red["min"])  # strokes start at the pressure floor
    i = lines.index(next(l for l in lines if l.startswith("(--- pen: red")))
    plunge = next(l for l in lines[i:] if l.startswith("G1 Z"))
    assert plunge.startswith(f"G1 Z{jp.fmt(expected)} ")


def test_slot_offset_moves_the_carriage_not_the_ink(tmp_path):
    prof = tmp_path / "p.toml"
    prof.write_text(
        '[slots.black]\ncolor = "#000000"\n'
        '[slots.red]\ncolor = "#ff0000"\noffset_x = 0.5\noffset_y = -0.25\n'
    )
    svg = tmp_path / "two.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm" viewBox="0 0 50 50">'
        '<path d="M10,10 L30,10" stroke="#000" fill="none"/>'
        '<path d="M10,10 L30,10" stroke="#f00" fill="none"/></svg>'
    )
    out = tmp_path / "two.gcode"
    assert jp.main([str(svg), "-p", str(prof), "-o", str(out), "--keep-order"]) == 0
    starts = [l for l in out.read_text().splitlines() if l.startswith("G0 X")]
    (bx, by), (rx, ry) = [tuple(float(w[1:]) for w in l.split()[1:3]) for l in starts[1:3]]
    assert (bx - rx, by - ry) == pytest.approx((0.5, -0.25))


def test_explicit_layer_slot_beats_colour_matching(tmp_path):
    prof = tmp_path / "p.toml"
    prof.write_text(
        '[slots.black]\ncolor = "#000000"\n[slots.red]\ncolor = "#ff0000"\n'
        '[pens."Notes"]\nslot = "black"\ndown_boost = 0.3\n'
    )
    svg = tmp_path / "l.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'width="50mm" height="50mm" viewBox="0 0 50 50">'
        '<g inkscape:groupmode="layer" inkscape:label="Notes">'
        '<path d="M10,10 L30,10" stroke="#f00" fill="none"/></g></svg>'
    )
    c, pens = jp.load_profile(prof)
    (s,) = jp.load_svg(svg, c, pens)[0]
    assert s.cfg["slot"] == "black" and s.cfg["down_boost"] == 0.3


@pytest.mark.parametrize("body", [
    '[slots.a]\naxis = "Q"\n',
    '[slots.a]\ncolor = "reddish"\n',
    '[slots.a]\nspeed = 3\n',
    '[pens."Ink"]\nslot = "nope"\n',
])
def test_bad_slot_profiles_are_rejected(tmp_path, body):
    prof = tmp_path / "bad.toml"
    prof.write_text(body)
    with pytest.raises(SystemExit):
        jp.load_profile(prof)


def test_offset_test(tmp_path):
    with pytest.raises(SystemExit):
        jp.main(["--offset-test", "-o", str(tmp_path / "x.gcode")])  # no slots defined
    out = tmp_path / "off.gcode"
    assert jp.main(["--offset-test", "-p", str(MULTI_PROFILE), "-o", str(out)]) == 0
    text = out.read_text()
    for colour in ("black", "blue", "red", "green"):
        assert f"(--- pen: {colour}," in text


def test_manual_slot_keeps_a_separate_pen_out_of_the_multipen(tmp_path):
    prof = tmp_path / "p.toml"
    prof.write_text(
        '[slots.black]\ncolor = "#000000"\nselect = "G0 A0"\n'
        '[pens."Brush pen"]\nslot = "manual"\ndown_boost = 0.5\n'
    )
    svg = tmp_path / "m.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'width="50mm" height="50mm" viewBox="0 0 50 50">'
        '<g inkscape:groupmode="layer" inkscape:label="Brush pen">'
        '<path d="M10,10 L30,10" stroke="#000" fill="none"/></g>'
        '<path d="M10,20 L30,20" stroke="#000" fill="none"/></svg>'
    )
    c, pens = jp.load_profile(prof)
    strokes = jp.load_svg(svg, c, pens)[0]
    assert [(s.pen, s.cfg["slot"]) for s in strokes] == [("Brush pen", None), ("black", "black")]
    out = tmp_path / "m.gcode"
    assert jp.main([str(svg), "-p", str(prof), "-o", str(out), "--keep-order"]) == 0
    text = out.read_text()
    # one pause for the brush pen and one for the multipen's height setup
    assert text.count("M0") == 2


# --------------------------------------------------------------------------
# Simulated pens (Pilot G2 tips) in the preview

G2_PROFILE = HERE.parent / "profile.g2.example.toml"
RACCOON = HERE.parent / "examples" / "raccoon_sketch.svg"


def test_tip_sets_the_preview_line_width():
    c = cfg(tip="g2-0.7")
    assert jp.preview_width(c, 0.5) == pytest.approx(0.39)
    assert jp.preview_width(c, 1.0) == pytest.approx(0.39 * 1.13)
    assert jp.preview_width(c, 0.0) == pytest.approx(0.39 * 0.87)
    # every G2 tip is known, and a bigger ball gives a wider line
    widths = [jp.preview_width(cfg(tip=t), 0.5) for t in ("g2-0.38", "g2-0.5", "g2-0.7", "g2-1.0")]
    assert widths == sorted(widths) and widths[0] < widths[-1]


def test_explicit_line_width_wins_and_no_pen_keeps_the_old_preview():
    assert jp.preview_width(cfg(tip="g2-0.7", line_width=0.3, line_flex=0.0), 1.0) == pytest.approx(0.3)
    assert jp.preview_width(cfg(), 0.5) == pytest.approx(0.12 + 0.5 * 1.08)


def test_unknown_tip_is_rejected(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[pen]\ntip = "g2-0.9"\n')
    with pytest.raises(SystemExit):
        jp.load_profile(bad)


def test_raccoon_plots_with_four_g2_pens(tmp_path):
    out = tmp_path / "raccoon.gcode"
    preview = tmp_path / "raccoon_preview.svg"
    assert jp.main([str(RACCOON), "-p", str(G2_PROFILE), "-o", str(out), "--preview", str(preview)]) == 0
    text = out.read_text()
    # one pen-change pause per tip, boldest first
    assert text.count("M0") == 4
    order = [text.index(f"pen: G2 {t} ") for t in ("1.0", "0.7", "0.5", "0.38")]
    assert order == sorted(order)
    # the preview only uses widths a G2 can make, all in one ink colour
    svg = preview.read_text()
    widths = {float(w) for w in re.findall(r'stroke-width="([\d.]+)"', svg)}
    assert min(widths) >= 0.26 * 0.87 - 1e-3 and max(widths) <= 0.52 * 1.13 + 1e-3
    assert set(re.findall(r'stroke="(#[0-9a-f]+)"', svg)) == {"#141418"}
    # gel pens are never pressed past their own z_max
    assert min(float(z) for z in re.findall(r"Z(-?[\d.]+)", text)) >= -1.0 - 1e-9


def test_skyline_plots_with_g2_pens(tmp_path):
    out = tmp_path / "skyline.gcode"
    skyline = HERE.parent / "examples" / "skyline_sketch.svg"
    assert jp.main([str(skyline), "-p", str(G2_PROFILE), "-o", str(out)]) == 0
    text = out.read_text()
    # three tips are used, boldest first, and the fine pen does the towers, sky and water
    assert text.count("M0") == 3
    order = [text.index(f"pen: G2 {t} ") for t in ("0.7", "0.5", "0.38")]
    assert order == sorted(order)


# --------------------------------------------------------------------------
# Translucent inks (ballpoint, pencil) in the preview

BALLPOINT = HERE.parent / "profile.ballpoint4.example.toml"


def test_ink_strength_follows_pressure():
    c = cfg(ink_min=0.1, ink_max=0.82)
    assert jp.preview_ink(c, 0.0) == pytest.approx(0.1)
    assert jp.preview_ink(c, 1.0) == pytest.approx(0.82)
    assert jp.preview_ink(cfg(), 0.3) == 1.0          # default pens stay opaque


def test_bad_ink_range_is_rejected(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[pen]\nink_min = 0.9\nink_max = 0.5\n")
    with pytest.raises(SystemExit):
        jp.load_profile(bad)


def test_ballpoint_multipen_layers_colours_in_the_preview(tmp_path):
    svg = tmp_path / "two.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm" viewBox="0 0 40 30">'
        '<path data-pressure="0.2" d="M5,5 L35,25" stroke="#d62a34" fill="none"/>'
        '<path data-pressure="0.9" d="M5,25 L35,5" stroke="#263eac" fill="none"/></svg>')
    out, preview = tmp_path / "two.gcode", tmp_path / "two_preview.svg"
    assert jp.main([str(svg), "-p", str(BALLPOINT), "-o", str(out), "--preview", str(preview)]) == 0
    text, pv = out.read_text(), preview.read_text()
    assert "pen: red, slot red" in text and "pen: blue, slot blue" in text
    assert text.count("M0") == 1                       # one pen: colours change without stopping
    assert "mix-blend-mode:multiply" in pv
    op = {c: max(float(o) for o in re.findall(rf'stroke="{c}"[^>]*stroke-opacity="([\d.]+)"', pv))
          for c in ("#d62a34", "#263eac")}
    assert op["#d62a34"] < op["#263eac"]               # the firmer stroke is the more solid one
    # the gel-pen preview is unchanged: opaque, no blending
    out2, pv2 = tmp_path / "g.gcode", tmp_path / "g_preview.svg"
    assert jp.main([str(svg), "-p", str(G2_PROFILE), "-o", str(out2), "--preview", str(pv2)]) == 0
    assert "stroke-opacity" not in pv2.read_text()
