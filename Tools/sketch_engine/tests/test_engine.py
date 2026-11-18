import json
import os
import subprocess
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import marks as M  # noqa: E402
import sketch  # noqa: E402
from palette import G2, MEASURED, TIPS  # noqa: E402
from timeline import Timeline, stable_rng  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "raccoon.toml")


def test_palette_has_the_17_catalog_inks_and_pms_values():
    assert len(G2) == 17
    assert G2["BLU"][1] == (0, 48, 136) and G2["RED"][1] == (191, 6, 47) and G2["CAR"][1] == (158, 107, 61)
    assert MEASURED <= set(G2)
    assert TIPS["g2-0.7"] == 0.39


def test_seeds_are_stable_across_runs():
    code = "import sys; sys.path.insert(0, %r); from timeline import stable_rng; print(stable_rng('tone face').random())" % ROOT
    a = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout
    b = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": "7"}).stdout
    assert a and a == b


def test_tone_phase_has_no_per_stroke_floor():
    T = Timeline()
    T.strokes([([(0, 0), (1, 0)], 0.5)] * 2000, "BLK", "tone")
    T.pace({"tone": 10.0})
    total = sum(e["vdur"] for e in T.events if e["type"] == "stroke")
    assert total == pytest.approx(10.0, rel=1e-6)


def test_zigzag_hatch_joins_dense_rows_and_respects_the_mask():
    class S:
        angle = np.zeros((200, 200), np.float32)
    mask = np.zeros((200, 200), bool)
    mask[40:160, 40:160] = True
    out = M.zigzag_hatch(S, mask, np.full((200, 200), 0.6, np.float32), 0.13, stable_rng("t"), tile=1.6, focus=(10, 10))
    assert out
    assert any(len(pts) >= 4 for pts, _ in out)                       # connected back-and-forth runs
    for pts, _ in out:
        for x, y in pts:
            assert 3.5 <= x <= 16.5 and 3.5 <= y <= 16.5


@pytest.fixture(scope="module")
def raccoon(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("raccoon"))
    report = sketch.run(sketch.load(EXAMPLE), out)
    return out, report


def test_example_runs_and_value_error_falls_as_the_drawing_develops(raccoon):
    out, report = raccoon
    errs = [s["error"] for s in report["stages"]]
    assert errs[0] > errs[-1] * 2
    assert errs[-1] < 0.2
    names = [s["stage"] for s in report["stages"]]
    assert names.index("shadow shapes") < names.index("midtones") < names.index("darks")
    for f in ("drawing.png", "compare.jpg", "drawing.svg", "events.json", "report.json"):
        assert os.path.exists(os.path.join(out, f))


def test_events_are_in_drawing_order(raccoon):
    out, _ = raccoon
    ev = json.load(open(os.path.join(out, "events.json")))["events"]
    phases = [e["phase"] for e in ev if e["type"] == "stroke"]
    order = ["gesture", "construction", "contours", "tone", "accents"]
    seen = [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]]
    assert [order.index(p) for p in seen] == sorted(order.index(p) for p in seen)
    assert any(e["type"] == "erase" for e in ev) and any(e["type"] == "undo" for e in ev)


def test_svg_plots_with_journal_plot(raccoon, tmp_path):
    out, _ = raccoon
    jp = os.path.join(os.path.dirname(ROOT), "journal_plot")
    r = subprocess.run([sys.executable, os.path.join(jp, "journal_plot.py"), os.path.join(out, "drawing.svg"),
                        "-p", os.path.join(jp, "profile.g2.example.toml"), "-o", str(tmp_path / "d.gcode"), "--force"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "d.gcode").stat().st_size > 1000


# ---------------- practices from drawing guides

def _study_with(dark):
    import analyse as A
    rgb = np.repeat((1 - dark)[..., None], 3, axis=2).astype(np.float32)
    return A.Study(rgb, [("all", np.ones(dark.shape, bool), {"angle": -35})])


def test_value_groups_are_three_clean_shapes():
    rng = np.random.default_rng(1)
    dark = np.zeros((300, 300), np.float32)
    dark[:, 150:] = 0.9                                  # a shadow side
    dark[100:200, 40:110] = 0.45                         # a midtone shape in the light
    dark += rng.normal(0, 0.05, dark.shape).astype(np.float32)
    dark[50, 50] = 1.0                                   # a speck
    st = _study_with(np.clip(dark, 0, 1))
    assert set(np.unique(st.groups)) <= {0, 1, 2}
    import cv2
    for lv in np.unique(st.groups):
        n, _, stats, _ = cv2.connectedComponentsWithStats((st.groups == lv).astype(np.uint8), 8)
        assert all(stats[i, cv2.CC_STAT_AREA] >= 150 for i in range(1, n))     # no specks under 1.5 units^2


def test_eye_mark_leaves_the_highlight_bare():
    parts = M.eye(10, 10, 1.0, stable_rng("eye"), highlight=(-0.35, -0.35))
    hx, hy, hr = 10 - 0.35, 10 - 0.35, 0.28
    for role in ("iris", "pupil"):
        for pts, _ in parts[role]:
            for x, y in pts:
                assert np.hypot(x - hx, y - hy) > hr - 1e-6
    assert parts["lash"] and parts["pupil"]


def test_contours_inside_one_value_shape_are_dropped():
    dark = np.zeros((300, 300), np.float32)
    dark[:, 150:] = 0.9
    st = _study_with(dark)
    inside = ([(3.0, 5.0), (3.0, 25.0)], 0.4)            # in the light, far from the boundary
    on_edge = ([(15.0, 5.0), (15.0, 25.0)], 0.4)         # along the light/shadow boundary
    out = M.contours([inside, on_edge], stable_rng("c"), study=st)
    xs = {round(p[0][0][0]) for p in out}
    assert 15 in xs and 3 not in xs


def test_cross_hatch_angles_are_15_to_60_degrees_apart():
    lo, hi = sketch.CROSS
    assert np.degrees(lo) == pytest.approx(15, abs=0.5) and np.degrees(hi) == pytest.approx(60, abs=0.5)
