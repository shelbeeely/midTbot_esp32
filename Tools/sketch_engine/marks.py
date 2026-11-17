"""Mark-making. Every function returns strokes as [(points_in_units, pressure), ...] in drawing order.

Lessons built in (see LESSONS.md):
- tone is laid in patches of parallel strokes, never scattered dashes
- within a patch the pen zig-zags from row to row without lifting, the way hatching is drawn by hand
- tone is ordered outward from the focal point, patch by patch, so the drawing grows instead of speckling in
- spacing comes from the line's real width: a gel line can't get lighter, only further apart
"""
from __future__ import annotations

import math
import random

import numpy as np

from analyse import PX


def zigzag_hatch(study, mask, target, line_units, rng, angle_offset=0.0, tile=1.6, min_t=0.04, focus=(0, 0),
                 jitter=0.06, run=(3, 9), max_cov=0.92, p=(0.35, 0.75)):
    """Hatch where `target` (array 0..1 coverage wanted, canvas px) asks for ink, inside `mask`."""
    H, W = mask.shape
    tpx = tile * PX
    step = tpx * 0.85
    tiles = []
    y = rng.uniform(0, step)
    while y < H:
        x = rng.uniform(0, step)
        while x < W:
            cx, cy = x + rng.uniform(-step / 4, step / 4), y + rng.uniform(-step / 4, step / 4)
            ix, iy = int(min(W - 1, max(0, cx))), int(min(H - 1, max(0, cy)))
            if mask[iy, ix]:
                tiles.append((float(ix), float(iy)))
            x += step
        y += step
    fx, fy = focus[0] * PX, focus[1] * PX
    tiles.sort(key=lambda c: (round(math.hypot(c[0] - fx, c[1] - fy) / (tpx * 2.5)), math.atan2(c[1] - fy, c[0] - fx)))
    lw = line_units * PX
    out = []

    def inside(x, y):
        ix, iy = int(x), int(y)
        return 0 <= ix < W and 0 <= iy < H and mask[iy, ix]

    for cx, cy in tiles:
        ss = [target[int(min(H - 1, max(0, cy + dy))), int(min(W - 1, max(0, cx + dx)))]
              for dx, dy in ((0, 0), (5, 3), (-4, 4), (3, -5), (-4, -3))]
        t = float(sum(ss) / len(ss))
        if t < min_t:
            continue
        a = float(study.angle[int(cy), int(cx)]) + angle_offset + rng.gauss(0, jitter)
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        pitch = max(lw * 1.1, lw / min(max_cov, t))
        half = tpx * rng.uniform(0.45, 0.6)
        rows = []
        k = -half + rng.uniform(0, pitch)
        while k < half:
            L = tpx * rng.uniform(0.8, 1.15) / 2
            ox, oy = cx + nx * k, cy + ny * k
            # keep the stretch of this row that lies inside the region, around its middle
            s0, s1 = 0.0, 0.0
            while s0 > -L and inside(ox + dx * (s0 - 1), oy + dy * (s0 - 1)):
                s0 -= 1
            while s1 < L and inside(ox + dx * (s1 + 1), oy + dy * (s1 + 1)):
                s1 += 1
            if s1 - s0 >= 3 and inside(ox, oy):
                s0 += rng.uniform(0, 1.5); s1 -= rng.uniform(0, 1.5)
                rows.append(((ox + dx * s0, oy + dy * s0), (ox + dx * s1, oy + dy * s1)))
            else:
                rows.append(None)
            k += pitch * rng.uniform(0.85, 1.15)
        # join rows into zig-zag runs; lift the pen every few rows or where a row is missing
        if pitch > 5.0 * PX / 10:                      # sparse: separate strokes, no zig-zag joins
            for r in rows:
                if r is not None:
                    a0, a1 = r if rng.random() < 0.5 else (r[1], r[0])
                    out.append(([(a0[0] / PX, a0[1] / PX), (a1[0] / PX, a1[1] / PX)], rng.uniform(*p)))
            continue
        chain, flip, n_run = [], False, rng.randint(*run)
        for r in rows + [None]:
            if r is None or len(chain) >= 2 * n_run:
                if len(chain) >= 2:
                    pr = rng.uniform(*p) * (0.75 + 0.25 * min(1.0, t / 0.6))
                    out.append(([(x / PX, y / PX) for x, y in chain], pr))
                chain, n_run = [], rng.randint(*run)
                if r is None:
                    continue
            a0, a1 = (r[1], r[0]) if flip else r
            chain += [a0, a1]
            flip = not flip
    return out


def arc_bands(arcs, line_units, rng, darkness=0.9, p=(0.7, 0.9)):
    """Narrow curved bands (rims of glasses, bands of cloth) drawn as strokes running along the band.
    arcs: (cx, cy, rx, ry, deg, start, end, width_units)."""
    out = []
    for cx, cy, rx, ry, deg, a0, a1, w in arcs:
        n = max(1, int(w * darkness / line_units))
        rot = math.radians(deg)
        for i in range(n):
            off = (i + 0.5) / n * w - w / 2
            s0, s1 = a0 + rng.uniform(0, 4), a1 - rng.uniform(0, 4)
            pts = []
            for k in range(int(abs(s1 - s0) / 4) + 2):
                t = math.radians(s0 + (s1 - s0) * k / (int(abs(s1 - s0) / 4) + 1))
                x, y = (rx + off) * math.cos(t), (ry + off) * math.sin(t)
                pts.append((cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot)))
            out.append((pts if i % 2 == 0 else pts[::-1], rng.uniform(*p)))
    return out


def strands(study, mask, target, line_units, rng, length=(5, 12), cell=0.8, curve=0.25, p=(0.4, 0.7), focus=(0, 0)):
    """Long single strokes following the flow (hair), density from target."""
    H, W = mask.shape
    seeds = []
    c = cell * PX
    y = 0.0
    while y < H:
        x = 0.0
        while x < W:
            sx, sy = x + rng.uniform(0, c), y + rng.uniform(0, c)
            ix, iy = int(min(W - 1, sx)), int(min(H - 1, sy))
            if mask[iy, ix]:
                sx, sy = min(sx, W - 1), min(sy, H - 1)
                L = rng.uniform(*length) * PX
                prob = float(target[iy, ix]) * c * c / (L * line_units * PX)
                while prob > 0:
                    if rng.random() < min(1.0, prob):
                        seeds.append((sx, sy, L))
                    prob -= 1
            x += c
        y += c
    fx, fy = focus[0] * PX, focus[1] * PX
    seeds.sort(key=lambda s: (round(math.hypot(s[0] - fx, s[1] - fy) / 40), s[0]))
    out = []
    for sx, sy, L in seeds:
        bend = rng.uniform(-curve, curve)
        pts, px, py, s = [(sx, sy)], sx, sy, 0.0
        a0 = float(study.angle[int(sy), int(sx)])
        while s < L:
            ix, iy = int(px), int(py)
            if not (0 <= ix < W and 0 <= iy < H and mask[iy, ix]):
                break
            a = float(study.angle[iy, ix])
            if math.cos(a - a0) < 0:
                a += math.pi
            a0 = a
            a += bend * s / L
            px, py = px + 4 * math.cos(a), py + 4 * math.sin(a)
            s += 4
            pts.append((px, py))
        if len(pts) > 3:
            out.append(([(x / PX, y / PX) for x, y in pts], rng.uniform(*p)))
    return out


def scribble(path, rng, width=1.2, loops=1.2, p=0.35, step=0.3):
    """A looping, wandering line travelling along `path` (units)."""
    seg = [math.dist(a, b) for a, b in zip(path, path[1:])]
    L = sum(seg)
    if L < 1:
        return []
    n = max(8, int(L / step))
    ph = rng.uniform(0, 6.28)

    def at(s):
        for (a, b), l in zip(zip(path, path[1:]), seg):
            if s <= l or l == seg[-1]:
                f = 0 if l == 0 else min(1, s / l)
                return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), (b[0] - a[0]) / (l or 1), (b[1] - a[1]) / (l or 1)
            s -= l
        return path[-1], 1, 0
    pts = []
    for i in range(n + 1):
        t = i / n
        (cx, cy), tx, ty = at(t * L)
        a = ph + t * L * loops * 2.2 + rng.uniform(-0.2, 0.2)
        r = width * (0.6 + 0.4 * math.sin(t * 7 + ph))
        pts.append((cx + r * (math.cos(a) * tx - math.sin(a) * ty * 0.8), cy + r * (math.cos(a) * ty + math.sin(a) * tx * 0.8)))
    out, k = [], 0
    while k < len(pts) - 2:
        m = rng.randint(25, 70)
        out.append((pts[k:k + m + 1], p * rng.uniform(0.8, 1.1)))
        k += m
    return out


def contours(traced, rng, lo=0.25, hi=0.85):
    """Inked contours from traced edges: confident where the photo's edge is sharp, broken where it is soft."""
    out = []
    for pts, s in traced:
        p = lo + (hi - lo) * s
        if s < 0.3 and len(pts) > 4:                          # soft edge: a few broken touches
            k = 0
            while k < len(pts) - 1:
                m = rng.randint(2, 4)
                out.append((pts[k:k + m + 1], p))
                k += m + rng.randint(1, 2)
        else:
            out.append((pts, p))
    return out


def loose_line(pts, rng, wobble=0.35, over=0.4):
    """A construction line: overshoots a little and wanders (units)."""
    if len(pts) < 2:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[1]
    d = math.dist(pts[0], pts[1]) or 1
    pre = (x0 - (x1 - x0) / d * over, y0 - (y1 - y0) / d * over)
    (xa, ya), (xb, yb) = pts[-2], pts[-1]
    d = math.dist(pts[-2], pts[-1]) or 1
    post = (xb + (xb - xa) / d * over, yb + (yb - ya) / d * over)
    q = [pre] + list(pts) + [post]
    ph = rng.uniform(0, 6.28)
    return [(x + wobble * math.sin(ph + i * 0.7) * 0.5, y + wobble * math.cos(ph + i * 0.9) * 0.5) for i, (x, y) in enumerate(q)]
