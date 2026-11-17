"""The ordered event timeline: what the artist does, in order, with timing and pressure samples.

Lessons built in (see LESSONS.md): the replay follows drawing order (rough -> construction ->
value shapes -> forms -> accents); each phase is compressed to a time budget with no per-stroke
minimum, so tens of thousands of tone strokes still fit.
"""
from __future__ import annotations

import math
import random
import zlib

from analyse import PX


def stable_rng(name, seed=0):
    """Seeds from crc32: Python's hash() changes every run, which reshuffles every pass."""
    return random.Random(zlib.crc32(name.encode()) + seed)


def samples(path_px, p, speed, rng=None, loose=0.0):
    """Ordered (x, y, t, pressure) samples for one stroke: slow into and out of the mark, tapered ends."""
    pts = [path_px[0]]
    for a, b in zip(path_px, path_px[1:]):
        n = max(1, int(math.dist(a, b) / 3))
        pts += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1)]
    if loose and rng is not None:
        ph, ph2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
        q = []
        for i, (x, y) in enumerate(pts):
            j = loose * (2.2 * math.sin(ph + i * 0.09) + 0.8 * math.sin(ph2 + i * 0.31))
            if 0 < i < len(pts) - 1:
                ax, ay = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
                d = math.hypot(ax, ay) or 1
                x, y = x - ay / d * j, y + ax / d * j
            q.append((x, y))
        pts = q
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) or 1.0
    s = t = 0.0
    out = []
    for i, q in enumerate(pts):
        if i:
            d = math.dist(pts[i - 1], q)
            s += d
            t += d / (speed * (0.45 + 0.55 * math.sin(math.pi * min(1, max(0, s / total))) ** 0.6))
        u = s / total
        ramp = min(1.0, u / 0.12, (1 - u) / 0.2) if total > 12 else 1.0
        pr = max(0.05, p * (0.4 + 0.6 * max(0, ramp)) * (1 + 0.08 * math.sin(i * 0.7)))
        out.append((round(float(q[0]), 1), round(float(q[1]), 1), round(float(t), 4), round(float(min(1, pr)), 3)))
    return out


class Timeline:
    def __init__(self):
        self.events = []
        self.rng = stable_rng("timeline")

    def select(self, tool, ink, layer, phase):
        self.events.append(dict(type="select", tool=tool, ink=ink, layer=layer, phase=phase))

    def strokes(self, items, ink, phase, layer="ink", tool="pen", speed=280, loose=0.0):
        if not items:
            return
        self.select(tool, ink, layer, phase)
        for pts, p in items:
            if len(pts) >= 2:
                self.events.append(dict(type="stroke", layer=layer, tool=tool, ink=ink, phase=phase,
                                        pts=samples([(x * PX, y * PX) for x, y in pts], p, speed, self.rng, loose)))

    def erase(self, pts, phase):
        self.events.append(dict(type="erase", layer="rough", phase=phase,
                                pts=samples([(x * PX, y * PX) for x, y in pts], 0.9, 260)))

    def travel(self, pt, phase):
        self.events += [dict(type="travel", to=[float(pt[0]) * PX, float(pt[1]) * PX], vspeed=420, phase=phase),
                        dict(type="pause", vdur=0.25, phase=phase)]

    def undo(self, phase):
        self.events += [dict(type="pause", vdur=0.3, phase=phase), dict(type="undo", layer="rough", phase=phase),
                        dict(type="pause", vdur=0.4, phase=phase)]

    def fade_rough(self, to, phase):
        self.events += [dict(type="pause", vdur=0.5, phase=phase), dict(type="opacity", layer="rough", to=to, vdur=1.2, phase=phase),
                        dict(type="new_layer", layer="ink", phase=phase)]

    def pace(self, budgets):
        """Give each phase its share of video time, in proportion to how long each mark takes to draw."""
        for ph, budget in budgets.items():
            evs = [e for e in self.events if e.get("phase") == ph and e["type"] in ("stroke", "erase")]
            tot = sum(e["pts"][-1][2] for e in evs) or 1.0
            for e in evs:
                e["adur"] = e["pts"][-1][2]
                e["vdur"] = budget * e["adur"] / tot
                if ph in ("gesture", "construction"):
                    e["vdur"] = max(0.1, e["vdur"])     # early marks stay watchable; tone has no floor
        for e in self.events:
            if e["type"] in ("stroke", "erase"):
                e.setdefault("vdur", 0.05)
                e.setdefault("adur", e["pts"][-1][2])
