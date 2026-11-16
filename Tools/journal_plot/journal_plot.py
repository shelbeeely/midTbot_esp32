#!/usr/bin/env python3
"""journal_plot - turn vector journal pages (SVG) into midTbot G-code with pen pressure.

Lay a page out in Inkscape (or any SVG editor), convert text to single-line
strokes (Inkscape: Extensions > Text > Hershey Text), then:

    python3 journal_plot.py page.svg                 # -> page.gcode
    python3 journal_plot.py page.svg -p my_pen.toml --preview page_preview.svg
    python3 journal_plot.py --test-pattern -o pressure_test.gcode

How pressure is chosen for each stroke (first match wins):
  1. data-pressure="0..1" on the element or any parent group/layer
  2. the stroke width in the layout, mapped from width_min..width_max (mm)
  3. the profile's default pressure
Within a stroke, pressure is then shaped by taper_in/taper_out (light
entry and exit like a real pen) and down_boost (brush lettering: thin
upstrokes, full pressure on downstrokes).

Strokes are grouped by pen: data-pen="name" on an element/group, else the
Inkscape layer name. Before each pen the plotter pauses (M0) with the servo
at the pen-touch angle so you can mount the pen and set its height.

Pressure maps onto the servo Z axis set up in Firmware/FluidNC/midtbot_s3.yaml:
z_up (pen up), z_touch (tip just touching), z_max (full pressure).
See Docs/journal_pages.md for calibration.
"""

from __future__ import annotations

import argparse
import copy
import math
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

PX_TO_MM = 25.4 / 96.0  # svgelements works in CSS px

DEFAULTS: dict[str, dict] = {
    "pen": {
        "z_up": 5.0,        # servo Z for travel moves
        "z_touch": 0.0,     # servo Z where the tip just touches the paper
        "z_max": -2.0,      # servo Z for full pressure
        "z_hover": 0.6,     # how far above z_touch to drop quickly before landing gently
        "force_curve": [],  # optional [[z, grams], ...] measured with a scale
    },
    "motion": {
        "draw_feed": 1500.0,   # mm/min along the paper while drawing
        "plunge_feed": 600.0,  # mm/min for the gentle last bit of a pen drop
        "dwell_down": 0.08,    # s to wait after landing, before moving
        "dwell_up": 0.12,      # s to wait after lifting, before travelling
        "park_x": 0.0,         # where to stop for pen changes (machine coords)
        "park_y": 0.0,
    },
    "pressure": {
        "default": 0.5,     # 0..1 for strokes with no data-pressure / stroke width
        "min": 0.1,         # floor: entry/exit pressure, keeps the pen inking
        "width_min": 0.2,   # layout stroke width (mm) that means pressure 0
        "width_max": 2.0,   # layout stroke width (mm) that means pressure 1
        "taper_in": 1.0,    # mm to ramp up at the start of a stroke (0 = off)
        "taper_out": 1.5,   # mm to ramp down at the end of a stroke (0 = off)
        "down_boost": 0.0,  # 0..1: how much lighter upstrokes are than downstrokes
        "smooth": 1.0,      # mm window used to smooth stroke direction
    },
    "page": {
        "origin_x": 0.0,    # machine X of the page's lower-left corner
        "origin_y": 0.0,    # machine Y of the page's lower-left corner
        "flip_x": False,
        "flip_y": True,     # SVG y grows downward; machine y grows upward
        "swap_xy": False,   # rotate the page 90 degrees on the machine
        "max_x": 100.0,     # usable machine travel; set to match config.yaml
        "max_y": 100.0,
        "step": 0.25,       # mm between samples along curves and pressure ramps
        "tolerance": 0.02,  # mm allowed when removing redundant points
        "optimize": True,   # reorder strokes to cut travel (never reverses them)
    },
}

PEN_OVERRIDABLE = set(DEFAULTS["pressure"]) | set(DEFAULTS["motion"]) | {"z_max"}
PEN_OVERRIDABLE -= {"park_x", "park_y"}
Z_TOLERANCE = 0.01  # servo units allowed when removing redundant points


# --------------------------------------------------------------------------
# Profile


def flat_defaults() -> dict:
    cfg = {}
    for section in DEFAULTS.values():
        cfg.update(copy.deepcopy(section))
    return cfg


def load_profile(path: Path | None) -> tuple[dict, dict[str, dict]]:
    """Return (settings, per-pen overrides) from a TOML profile."""
    cfg = flat_defaults()
    pens: dict[str, dict] = {}
    if path is None:
        return cfg, pens
    if tomllib is None:
        sys.exit("Reading a profile needs Python 3.11+ (tomllib).")
    data = tomllib.loads(Path(path).read_text())
    for section, values in data.items():
        if section == "pens":
            for name, over in values.items():
                bad = set(over) - PEN_OVERRIDABLE
                if bad:
                    sys.exit(f"profile [pens.{name!r}]: keys not allowed per pen: {sorted(bad)}")
                pens[name] = dict(over)
            continue
        if section not in DEFAULTS:
            sys.exit(f"profile: unknown section [{section}]")
        bad = set(values) - set(DEFAULTS[section])
        if bad:
            sys.exit(f"profile [{section}]: unknown keys {sorted(bad)}")
        cfg.update(values)
    validate(cfg)
    return cfg, pens


def validate(cfg: dict) -> None:
    if not cfg["z_max"] < cfg["z_touch"] < cfg["z_up"]:
        sys.exit("profile: need z_max < z_touch < z_up")
    if cfg["width_max"] <= cfg["width_min"]:
        sys.exit("profile: width_max must be larger than width_min")
    if not 0 <= cfg["min"] <= 1 or not 0 <= cfg["default"] <= 1:
        sys.exit("profile: pressure min/default must be within 0..1")
    if not 0 <= cfg["down_boost"] <= 1:
        sys.exit("profile: down_boost must be within 0..1")
    curve = cfg["force_curve"]
    if curve:
        pts = sorted(curve, key=lambda zg: -zg[0])
        grams = [g for _, g in pts]
        if any(b <= a for a, b in zip(grams, grams[1:])):
            sys.exit("profile: force_curve grams must increase as z goes down")


def pen_cfg(cfg: dict, pens: dict[str, dict], pen: str) -> dict:
    if pen not in pens:
        return cfg
    merged = dict(cfg)
    merged.update(pens[pen])
    validate(merged)
    return merged


# --------------------------------------------------------------------------
# Pressure -> servo Z


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolation; xs ascending; extrapolates linearly."""
    if len(xs) == 1:
        return ys[0]
    i = 1
    while i < len(xs) - 1 and x > xs[i]:
        i += 1
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def make_z_map(cfg: dict):
    """Return f(pressure 0..1) -> servo Z."""
    zt, zm = cfg["z_touch"], cfg["z_max"]
    curve = cfg["force_curve"]
    if not curve:
        return lambda p: zt + p * (zm - zt)
    pts = sorted(curve, key=lambda zg: zg[0])  # z ascending, grams descending
    zs = [z for z, _ in pts]
    gs = [g for _, g in pts]
    g_touch = _interp(zt, zs, gs)
    g_max = _interp(zm, zs, gs)
    gs_up, zs_up = gs[::-1], zs[::-1]  # grams ascending for the inverse

    def z_of(p: float) -> float:
        z = _interp(g_touch + p * (g_max - g_touch), gs_up, zs_up)
        return min(zt, max(zm, z))

    return z_of


# --------------------------------------------------------------------------
# Strokes


@dataclass
class Stroke:
    pts: list[tuple[float, float]]  # page coordinates in mm, SVG orientation (y down)
    base: float                     # target pressure 0..1
    pen: str
    cfg: dict                       # settings in force for this stroke


def resample(pts: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """Insert points so no gap is longer than step (keeps the originals)."""
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        n = max(1, math.ceil(d / step))
        for k in range(1, n + 1):
            out.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
    return out


def stroke_pressures(stroke: Stroke) -> list[float]:
    """Pressure (0..1) at every point of a stroke."""
    c = stroke.cfg
    pts = stroke.pts
    n = len(pts)
    s = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        s.append(s[-1] + math.hypot(x1 - x0, y1 - y0))
    total = s[-1]

    # Direction: fraction of each segment that runs down the page.
    b = c["down_boost"]
    if b > 0 and n > 1:
        seg = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d = math.hypot(x1 - x0, y1 - y0)
            seg.append(max(0.0, (y1 - y0) / d) if d > 0 else 0.0)
        down = [seg[0]] + [(seg[i - 1] + seg[i]) / 2 for i in range(1, n - 1)] + [seg[-1]]
        half = c["smooth"] / 2
        if half > 0:
            smoothed, lo, hi, acc = [], 0, 0, 0.0
            for i in range(n):
                while hi < n and s[hi] <= s[i] + half:
                    acc += down[hi]
                    hi += 1
                while s[lo] < s[i] - half:
                    acc -= down[lo]
                    lo += 1
                smoothed.append(acc / (hi - lo))
            down = smoothed
        target = [stroke.base * (1 - b * (1 - d)) for d in down]
    else:
        target = [stroke.base] * n

    pmin = c["min"]
    tin, tout = c["taper_in"], c["taper_out"]
    out = []
    for si, t in zip(s, target):
        e = 1.0
        if tin > 0:
            e = min(e, si / tin)
        if tout > 0:
            e = min(e, (total - si) / tout)
        e = max(0.0, min(1.0, e))
        e = e * e * (3 - 2 * e)  # smoothstep: soft start/end of the ramp
        t = max(pmin, t)
        out.append(pmin + (t - pmin) * e)
    return out


def simplify(pts: list[tuple[float, float]], zs: list[float], tol: float, ztol: float) -> list[int]:
    """Indices to keep: Ramer-Douglas-Peucker on XY plus Z (pressure)."""
    n = len(pts)
    if n < 3:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        worst, wi = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            t = ((px - ax) * dx + (py - ay) * dy) / l2 if l2 > 0 else 0.0
            t = max(0.0, min(1.0, t))
            exy = math.hypot(px - (ax + t * dx), py - (ay + t * dy)) / tol
            ez = abs(zs[i] - (zs[a] + t * (zs[b] - zs[a]))) / ztol
            e = max(exy, ez)
            if e > worst:
                worst, wi = e, i
        if worst > 1:
            keep[wi] = True
            stack.append((a, wi))
            stack.append((wi, b))
    return [i for i in range(n) if keep[i]]


# --------------------------------------------------------------------------
# SVG input

INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"


def base_pressure(element, c: dict) -> float:
    v = element.values.get("data-pressure")
    if v is not None:
        return max(0.0, min(1.0, float(v)))
    if "stroke-width" in element.values:
        sw = getattr(element, "implicit_stroke_width", None) or element.stroke_width
        w = float(sw) * PX_TO_MM
        return max(0.0, min(1.0, (w - c["width_min"]) / (c["width_max"] - c["width_min"])))
    return c["default"]


def load_svg(path: Path, cfg: dict, pens: dict[str, dict]):
    """Parse an SVG page into strokes. Returns (strokes, (page_w, page_h), notes)."""
    from svgelements import SVG, Close, Line, Move, Path as SvgPath, Shape, Text

    svg = SVG.parse(str(path), reify=True)
    page_w = float(svg.width) * PX_TO_MM
    page_h = float(svg.height) * PX_TO_MM
    strokes: list[Stroke] = []
    n_text = n_fill_only = 0

    for e in svg.elements():
        if isinstance(e, Text):
            n_text += 1
            continue
        if not isinstance(e, Shape):
            continue
        if e.stroke is None or e.stroke.value is None:
            if e.fill is not None and e.fill.value is not None:
                n_fill_only += 1
            continue
        pen = str(e.values.get("data-pen") or e.values.get(INKSCAPE_LABEL) or "pen")
        c = pen_cfg(cfg, pens, pen)
        base = base_pressure(e, c)
        path = e if isinstance(e, SvgPath) else SvgPath(e)
        for sub in path.as_subpaths():
            pts: list[tuple[float, float]] = []
            for seg in sub:
                if isinstance(seg, Move):
                    pts = [(seg.end.x * PX_TO_MM, seg.end.y * PX_TO_MM)]
                    continue
                if seg.start is None or seg.end is None:
                    continue
                if not pts:
                    pts = [(seg.start.x * PX_TO_MM, seg.start.y * PX_TO_MM)]
                if isinstance(seg, (Close, Line)):
                    pts.append((seg.end.x * PX_TO_MM, seg.end.y * PX_TO_MM))
                    continue  # straight: resample() fills in the points
                length = seg.length(error=1e-4) * PX_TO_MM
                k = max(2, math.ceil(length / c["step"]))
                for i in range(1, k + 1):
                    p = seg.point(i / k)
                    pts.append((p.x * PX_TO_MM, p.y * PX_TO_MM))
            if pts:
                strokes.append(Stroke(resample(pts, c["step"]), base, pen, c))

    notes = []
    if n_text:
        notes.append(f"skipped {n_text} <text> element(s): convert text with Extensions > Text > Hershey Text first")
    if n_fill_only:
        notes.append(f"skipped {n_fill_only} filled shape(s) with no stroke")
    return strokes, (page_w, page_h), notes


# --------------------------------------------------------------------------
# Test pattern


def test_pattern(cfg: dict) -> tuple[list[Stroke], tuple[float, float]]:
    """Pressure ladder + tapers + brush-style loops on an 80 x 60 mm page."""
    strokes = []
    flat = dict(cfg, taper_in=0.0, taper_out=0.0, down_boost=0.0)
    levels = [0.0, 0.25, 0.5, 0.75, 1.0]
    for i, p in enumerate(levels):  # row 1: flat lines, one per pressure level
        y = 8 + i * 5
        strokes.append(Stroke(resample([(5, y), (35, y)], cfg["step"]), p, "pen", flat))
    taper = dict(cfg, taper_in=max(cfg["taper_in"], 3.0), taper_out=max(cfg["taper_out"], 4.0), down_boost=0.0)
    for i, p in enumerate(levels):  # row 2: the same with long tapers
        y = 8 + i * 5
        strokes.append(Stroke(resample([(45, y), (75, y)], cfg["step"]), p, "pen", taper))
    brush = dict(cfg, down_boost=max(cfg["down_boost"], 0.7))
    loops = []
    for k in range(400):  # row 3: a looping "llll" so downstrokes read heavier
        t = k / 399 * 6 * math.pi
        loops.append((8 + 10.5 * t / math.pi - 6 * math.sin(t), 46 - 7.2 * math.cos(t)))
    strokes.append(Stroke(resample(loops, cfg["step"]), 1.0, "pen", brush))
    return strokes, (80.0, 60.0)


# --------------------------------------------------------------------------
# Ordering, G-code and preview


def order_strokes(strokes: list[Stroke], optimize: bool) -> list[Stroke]:
    """Group by pen (first-seen order), then nearest-neighbour within each pen."""
    pens: dict[str, list[Stroke]] = {}
    for s in strokes:
        pens.setdefault(s.pen, []).append(s)
    ordered = []
    for group in pens.values():
        if not optimize or len(group) < 3:
            ordered.extend(group)
            continue
        remaining = list(group)
        cx, cy = remaining[0].pts[0]
        while remaining:
            j = min(range(len(remaining)),
                    key=lambda i: (remaining[i].pts[0][0] - cx) ** 2 + (remaining[i].pts[0][1] - cy) ** 2)
            s = remaining.pop(j)
            ordered.append(s)
            cx, cy = s.pts[-1]
    return ordered


def fmt(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class Mapper:
    def __init__(self, page: tuple[float, float], cfg: dict):
        self.w, self.h = page
        self.c = cfg

    def __call__(self, x: float, y: float) -> tuple[float, float]:
        c = self.c
        if c["flip_x"]:
            x = self.w - x
        if c["flip_y"]:
            y = self.h - y
        if c["swap_xy"]:
            x, y = y, x
        return x + c["origin_x"], y + c["origin_y"]


@dataclass
class Plotted:
    stroke: Stroke
    idx: list[int]
    pressures: list[float]
    zs: list[float]


def plan(strokes: list[Stroke]) -> list[Plotted]:
    out = []
    for s in strokes:
        pressures = stroke_pressures(s)
        z_of = make_z_map(s.cfg)
        zs = [z_of(p) for p in pressures]
        idx = simplify(s.pts, zs, s.cfg["tolerance"], Z_TOLERANCE)
        out.append(Plotted(s, idx, pressures, zs))
    return out


def to_gcode(plotted: list[Plotted], page: tuple[float, float], cfg: dict, source: str,
             pen_setup: bool = True) -> tuple[list[str], dict]:
    m = Mapper(page, cfg)
    up = cfg["z_up"]
    lines = [
        f"(journal_plot: {source})",
        f"(page {fmt(page[0])} x {fmt(page[1])} mm, z_up {fmt(up)}, z_touch {fmt(cfg['z_touch'])}, "
        f"z_max {fmt(cfg['z_max'])})",
        "G21 G90 G94",
        f"G0 Z{fmt(up)}",
    ]
    stats = {"strokes": 0, "draw_mm": 0.0, "travel_mm": 0.0, "pens": [], "min_xy": [1e9, 1e9], "max_xy": [-1e9, -1e9]}
    cur = (cfg["park_x"], cfg["park_y"])
    pen = None

    def track(x, y):
        stats["min_xy"] = [min(stats["min_xy"][0], x), min(stats["min_xy"][1], y)]
        stats["max_xy"] = [max(stats["max_xy"][0], x), max(stats["max_xy"][1], y)]

    for p in plotted:
        s, c = p.stroke, p.stroke.cfg
        if s.pen != pen:
            pen = s.pen
            stats["pens"].append(pen)
            lines.append(f"(--- pen: {pen} ---)")
            if pen_setup:
                lines += [
                    f"G0 X{fmt(cfg['park_x'])} Y{fmt(cfg['park_y'])}",
                    f"G0 Z{fmt(cfg['z_touch'])}",
                    f"(Mount '{pen}' so the tip just touches the paper, tighten the clamp, then resume)",
                    "M0",
                    f"G0 Z{fmt(up)}",
                    f"G4 P{fmt(c['dwell_up'])}",
                ]
                cur = (cfg["park_x"], cfg["park_y"])
        pts = [m(*s.pts[i]) for i in p.idx]
        zs = [p.zs[i] for i in p.idx]
        x0, y0 = pts[0]
        stats["travel_mm"] += math.hypot(x0 - cur[0], y0 - cur[1])
        hover = min(up, c["z_touch"] + c["z_hover"])
        lines += [
            f"G0 X{fmt(x0)} Y{fmt(y0)}",
            f"G0 Z{fmt(hover)}",
            f"G1 Z{fmt(zs[0])} F{fmt(c['plunge_feed'])}",
            f"G4 P{fmt(c['dwell_down'])}",
        ]
        track(x0, y0)
        last_f = None
        for (xa, ya), (xb, yb), za, zb in zip(pts, pts[1:], zs, zs[1:]):
            dxy = math.hypot(xb - xa, yb - ya)
            stats["draw_mm"] += dxy
            # FluidNC applies F along the XYZ vector; scale it so the pen
            # still moves across the paper at draw_feed while Z changes.
            f = c["draw_feed"] if dxy < 1e-9 else c["draw_feed"] * min(4.0, math.hypot(dxy, zb - za) / dxy)
            word = ""
            if last_f is None or abs(f - last_f) > 0.03 * last_f:
                word = f" F{fmt(f)}"
                last_f = f
            lines.append(f"G1 X{fmt(xb)} Y{fmt(yb)} Z{fmt(zb)}{word}")
            track(xb, yb)
        lines += [f"G0 Z{fmt(up)}", f"G4 P{fmt(c['dwell_up'])}"]
        cur = pts[-1]
        stats["strokes"] += 1

    lines += [f"G0 Z{fmt(up)}", f"G0 X{fmt(cfg['park_x'])} Y{fmt(cfg['park_y'])}", "M2"]
    pen_time = stats["strokes"] * (cfg["dwell_down"] + cfg["dwell_up"] + 0.25)
    stats["minutes"] = stats["draw_mm"] / cfg["draw_feed"] + stats["travel_mm"] / 6000 + pen_time / 60
    return lines, stats


def preview_svg(plotted: list[Plotted], page: tuple[float, float], w_min=0.12, w_max=1.2) -> str:
    """Page-orientation SVG where line width shows the planned pressure."""
    colors = ["#1a1a1a", "#1f5fbf", "#b8322e", "#2f8a3c", "#8a4fbf", "#c27a12"]
    pen_color: dict[str, str] = {}
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(page[0])}mm" height="{fmt(page[1])}mm" '
        f'viewBox="0 0 {fmt(page[0])} {fmt(page[1])}">',
        '<rect width="100%" height="100%" fill="#fbf8f1"/>',
    ]
    levels = 16
    for p in plotted:
        color = pen_color.setdefault(p.stroke.pen, colors[len(pen_color) % len(colors)])
        pts = p.stroke.pts
        if len(pts) == 1:
            r = (w_min + p.pressures[0] * (w_max - w_min)) / 2
            out.append(f'<circle cx="{fmt(pts[0][0])}" cy="{fmt(pts[0][1])}" r="{fmt(r)}" fill="{color}"/>')
            continue
        run, run_level = [pts[0]], None
        for i in range(1, len(pts)):
            q = (p.pressures[i - 1] + p.pressures[i]) / 2
            level = round(q * (levels - 1))
            if run_level is not None and level != run_level:
                out.append(_poly(run, run_level, levels, w_min, w_max, color))
                run = [pts[i - 1]]
            run.append(pts[i])
            run_level = level
        out.append(_poly(run, run_level, levels, w_min, w_max, color))
    out.append("</svg>")
    return "\n".join(out)


def _poly(run, level, levels, w_min, w_max, color):
    w = w_min + (level / (levels - 1)) * (w_max - w_min)
    d = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in run)
    return (f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{fmt(w)}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


# --------------------------------------------------------------------------
# CLI


def check_bounds(stats: dict, cfg: dict) -> list[str]:
    (x0, y0), (x1, y1) = stats["min_xy"], stats["max_xy"]
    if stats["strokes"] == 0:
        return []
    if x0 < -1e-6 or y0 < -1e-6 or x1 > cfg["max_x"] + 1e-6 or y1 > cfg["max_y"] + 1e-6:
        return [f"drawing spans X {fmt(x0)}..{fmt(x1)}, Y {fmt(y0)}..{fmt(y1)} mm but the machine "
                f"area is 0..{fmt(cfg['max_x'])} x 0..{fmt(cfg['max_y'])} mm"]
    return []


def run(source: str, strokes, page, cfg, out: Path, preview: Path | None, force: bool, pen_setup: bool) -> int:
    plotted = plan(order_strokes(strokes, cfg["optimize"]))
    lines, stats = to_gcode(plotted, page, cfg, source, pen_setup)
    problems = check_bounds(stats, cfg)
    for msg in problems:
        print(f"{source}: {'warning' if force else 'error'}: {msg}", file=sys.stderr)
    if problems and not force:
        print("  (move the drawing, change origin_x/origin_y, or pass --force)", file=sys.stderr)
        return 1
    out.write_text("\n".join(lines) + "\n")
    if preview:
        preview.write_text(preview_svg(plotted, page))
    pens = ", ".join(stats["pens"]) or "none"
    print(f"{source} -> {out}: {stats['strokes']} strokes, {stats['draw_mm'] / 1000:.2f} m of ink, "
          f"pens: {pens}, about {stats['minutes']:.0f} min" + (f", preview {preview}" if preview else ""))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("svg", nargs="*", type=Path, help="page layout(s) to plot; one .gcode per page")
    ap.add_argument("-p", "--profile", type=Path, help="TOML profile (see profile.example.toml)")
    ap.add_argument("-o", "--output", type=Path, help="output .gcode (single page or --test-pattern)")
    ap.add_argument("--preview", type=Path, nargs="?", const=True,
                    help="also write an SVG preview with line width = pressure (default name: <page>_preview.svg)")
    ap.add_argument("--test-pattern", action="store_true", help="plot a pressure calibration card instead of an SVG")
    ap.add_argument("--keep-order", action="store_true", help="plot strokes in document order")
    ap.add_argument("--no-pen-setup", action="store_true", help="no M0 pen-mount pause before each pen")
    ap.add_argument("--force", action="store_true", help="write G-code even if it leaves the machine area")
    args = ap.parse_args(argv)

    cfg, pens = load_profile(args.profile)
    if args.keep_order:
        cfg["optimize"] = False

    def preview_path(out: Path) -> Path | None:
        if args.preview is None:
            return None
        if args.preview is True:
            return out.with_name(out.stem + "_preview.svg")
        return args.preview

    if args.test_pattern:
        out = args.output or Path("pressure_test.gcode")
        strokes, page = test_pattern(cfg)
        return run("test pattern", strokes, page, cfg, out, preview_path(out), args.force, not args.no_pen_setup)

    if not args.svg:
        ap.error("give one or more SVG pages, or --test-pattern")
    if args.output and len(args.svg) > 1:
        ap.error("-o only works with a single page")
    status = 0
    for svg in args.svg:
        out = args.output or svg.with_suffix(".gcode")
        strokes, page, notes = load_svg(svg, cfg, pens)
        for note in notes:
            print(f"{svg}: note: {note}", file=sys.stderr)
        status |= run(str(svg), strokes, page, cfg, out, preview_path(out), args.force, not args.no_pen_setup)
    return status


if __name__ == "__main__":
    sys.exit(main())
