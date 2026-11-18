"""Mark-making. Every function returns strokes as [(points_in_units, pressure), ...] in drawing order.

Lessons built in (see LESSONS.md):
- tone is laid in patches of parallel strokes, never scattered dashes
- within a patch the pen zig-zags from row to row without lifting, the way hatching is drawn by hand
- tone is ordered outward from the focal point, patch by patch, so the drawing grows instead of speckling in
- spacing comes from the line's real width: a gel line can't get lighter, only further apart
"""
from __future__ import annotations

import math



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
            if s1 - s0 >= 3 and inside(ox, oy) and rng.random() > 0.04:      # now and then a row is skipped
                s0 += rng.uniform(0, 2.5); s1 -= rng.uniform(0, 2.5)
                a_, b_ = (ox + dx * s0, oy + dy * s0), (ox + dx * s1, oy + dy * s1)
                # contour hatching: bow the row a little toward the form's direction at its middle (capped ~10 deg)
                mx, my = (a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2
                am = float(study.angle[int(min(H - 1, max(0, my))), int(min(W - 1, max(0, mx)))])
                turn = math.atan2(math.sin(2 * (am - a)), math.cos(2 * (am - a))) / 2
                turn = max(-0.17, min(0.17, turn))
                bow = math.tan(turn) * (s1 - s0) / 4
                rows.append((a_, (mx + nx * bow, my + ny * bow), b_))
            else:
                rows.append(None)
            k += pitch * rng.uniform(0.7, 1.3)
        # join rows into zig-zag runs; lift the pen every few rows or where a row is missing
        if pitch > 5.0 * PX / 10:                      # sparse: separate strokes, no zig-zag joins
            for r in rows:
                if r is not None:
                    q = list(r) if rng.random() < 0.5 else list(r)[::-1]
                    out.append(([(x / PX, y / PX) for x, y in q], rng.uniform(*p)))
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
            chain += list(r)[::-1] if flip else list(r)
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


def eye(cx, cy, r_iris, rng, highlight=(-0.35, -0.35), width=None, tilt=0.0, iris_ink_p=0.45):
    """An eye drawn the way the guides teach. Returns dict of stroke lists by ink role:
    'iris' (light spokes, then a darker rim), 'pupil' (darkest), 'lash' (upper lid + grouped lash clumps,
    sparse lower lashes). The highlight is left bare. Units throughout."""
    w = width or r_iris * 3.0
    hx, hy, hr = cx + highlight[0] * r_iris, cy + highlight[1] * r_iris, r_iris * 0.28
    def clear(x, y):
        return math.hypot(x - hx, y - hy) > hr
    def cut(pts, p):
        out, run = [], []
        for q in pts:
            if clear(*q):
                run.append(q)
            elif len(run) > 1:
                out.append((run, p)); run = []
            else:
                run = []
        if len(run) > 1:
            out.append((run, p))
        return out
    iris, pupil, lash = [], [], []
    rp = r_iris * 0.42
    for i in range(44):                                   # spokes from the pupil, some stopping short
        a = i / 44 * 2 * math.pi + rng.uniform(-0.05, 0.05)
        r1 = r_iris * rng.uniform(0.7, 1.0)
        iris += cut([(cx + rp * math.cos(a), cy + rp * math.sin(a)), (cx + r1 * math.cos(a), cy + r1 * math.sin(a))], iris_ink_p)
    for k, f in enumerate((1.0, 0.94, 0.88)):            # darker outer rim
        iris += cut([(cx + r_iris * f * math.cos(t / 30 * 2 * math.pi), cy + r_iris * f * math.sin(t / 30 * 2 * math.pi)) for t in range(31)], 0.8)
    rr = rp
    while rr > 0.03:                                     # pupil: the darkest point
        pupil += cut([(cx + rr * math.cos(t / 20 * 2 * math.pi), cy + rr * math.sin(t / 20 * 2 * math.pi)) for t in range(21)], 0.95)
        rr -= 0.06
    def lid(t, upper=True):
        x = cx + (t - 0.5) * w
        h = (r_iris * 1.05 if upper else r_iris * 0.8) * math.sin(math.pi * t)
        y = cy - h if upper else cy + h
        return (x * math.cos(tilt) - (y - cy) * math.sin(tilt) + cx * (1 - math.cos(tilt)), cy + (x - cx) * math.sin(tilt) + (y - cy) * math.cos(tilt))
    for k in range(3):                                    # upper lash line, heavier toward the outer corner
        lash.append(([lid(t / 24) for t in range(int(24 * (0.08 * k)), 25)], 0.9))
    t = 0.25
    while t < 0.98:                                       # lash clumps: a few hairs, flicked outward, tapered
        x, y = lid(t)
        n = rng.randint(2, 4)
        out_a = -math.pi / 2 + (t - 0.4) * 1.6
        for j in range(n):
            a = out_a + rng.uniform(-0.25, 0.25)
            L = r_iris * rng.uniform(0.5, 0.9) * (0.6 + 0.6 * t)
            lash.append(([(x, y), (x + L * 0.5 * math.cos(a), y + L * 0.5 * math.sin(a)),
                          (x + L * math.cos(a + 0.25), y + L * math.sin(a + 0.25))], 0.7))
        t += rng.uniform(0.09, 0.15)
    low = [lid(t / 20, upper=False) for t in range(2, 19)]   # lower lid: broken, light
    for a in range(0, len(low) - 3, 5):
        lash.append((low[a:a + 4], 0.35))
    for t in (0.55, 0.7, 0.82):                           # sparse lower lashes, curving down
        x, y = lid(t, upper=False)
        lash.append(([(x, y), (x + 0.15, y + r_iris * 0.35)], 0.4))
    return dict(iris=iris, pupil=pupil, lash=lash)


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


def contours(traced, rng, lo=0.25, hi=0.85, study=None):
    """Lost and found: a firm line where two value groups meet hard, a broken or no line where tones carry the edge."""
    out = []
    for pts, s in traced:
        if study is not None:
            e = [float(study.group_edge[int(min(study.H - 1, y * PX)), int(min(study.W - 1, x * PX))]) for x, y in pts]
            ge = sum(e) / len(e)
            if ge < 0.06 and s < 0.6:              # inside one value shape: let the tone carry it
                continue
            s = 0.5 * s + 0.5 * min(1.0, ge * 2)
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
