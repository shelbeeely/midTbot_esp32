"""Study the photo before drawing: values per region, the direction of the forms, the feature edges.

Lessons built in (see LESSONS.md):
- each region gets its own white and black point, measured inside it (never the whole photo)
- features that would fool the value reading (glasses, eyes, brows, lips) can be painted out first
- stroke direction follows the photo's own structure, smoothed, with a per-region fallback angle
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image, ImageOps

PX = 10          # canvas pixels per drawing unit


def load_photo(path, canvas_units, crop=None):
    """Photo -> float RGB array sized to the canvas (canvas_units * PX). crop = [x0, y0, x1, y1] in 0..1."""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if crop:
        w, h = im.size
        im = im.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
    W, H = int(canvas_units[0] * PX), int(canvas_units[1] * PX)
    return np.asarray(im.resize((W, H), Image.LANCZOS), np.float32) / 255


def poly_mask(shape, polys, ellipses=(), arcs=()):
    """Boolean mask from polygons [[(x, y) units...], ...], ellipses [(cx, cy, rx, ry, deg), ...] and
    arcs [(cx, cy, rx, ry, deg, start, end, width_units), ...] (e.g. the rims of glasses)."""
    m = np.zeros(shape, np.uint8)
    for cx, cy, rx, ry, deg, a0, a1, w in arcs:
        cv2.ellipse(m, (int(cx * PX), int(cy * PX)), (int(rx * PX), int(ry * PX)), deg, a0, a1, 1, max(1, int(w * PX)))
    for p in polys:
        cv2.fillPoly(m, [np.round(np.array(p, np.float32) * PX).astype(np.int32)], 1)
    for cx, cy, rx, ry, *rest in ellipses:
        cv2.ellipse(m, (int(cx * PX), int(cy * PX)), (int(rx * PX), int(ry * PX)), rest[0] if rest else 0, 0, 360, 1, -1)
    return m.astype(bool)


class Study:
    def __init__(self, rgb, regions, priorities=None):
        """regions: ordered list of (name, mask, cfg dict); earlier regions win where masks overlap."""
        self.rgb = rgb
        self.H, self.W = rgb.shape[:2]
        self.lum = cv2.GaussianBlur(rgb.mean(axis=2), (0, 0), 1.2)
        self.label = np.full((self.H, self.W), -1, np.int32)
        self.regions = []
        for i, (name, mask, cfg) in enumerate(regions):
            m = mask & (self.label < 0)
            self.label[m] = i
            self.regions.append(dict(name=name, mask=m, cfg=cfg))
        self.dark = np.zeros((self.H, self.W), np.float32)
        self.g_white = float(np.percentile(self.lum, 98))
        self.g_black = float(np.percentile(self.lum, 2))
        for r in self.regions:
            self._calibrate(r)
        self.angle, self.coherence = self._orientation()
        self._apply_guides()
        self.groups, self.group_edge = self.value_groups()

    def _apply_guides(self):
        """Regions can give guide polylines (finger directions, a knuckle line); the stroke direction inside
        that region follows them instead of photo noise."""
        for r in self.regions:
            gl = r["cfg"].get("guides")
            if not gl or not r["mask"].any():
                continue
            segs = [((a[0] + b[0]) / 2 * PX, (a[1] + b[1]) / 2 * PX, math.atan2(b[1] - a[1], b[0] - a[0]))
                    for g in gl for a, b in zip(g, g[1:])]
            ys, xs = np.nonzero(r["mask"])
            c2 = np.zeros(len(xs)); s2 = np.zeros(len(xs))
            for gx, gy, a in segs:
                w = 1.0 / ((xs - gx) ** 2 + (ys - gy) ** 2 + 400.0) ** 1.5
                c2 += w * math.cos(2 * a); s2 += w * math.sin(2 * a)
            self.angle[ys, xs] = 0.5 * np.arctan2(s2, c2)

    def value_groups(self, levels=3, squint=2.5, min_area=1.5, t1=0.28, t2=0.6):
        """Squint and reduce to light / mid / shadow shapes (notan), dropping specks under min_area units².
        Returns (groups 0..levels-1, edge strength 0..1 along group boundaries)."""
        d = cv2.GaussianBlur(self.dark, (0, 0), squint * PX / 2)
        g = np.zeros(d.shape, np.uint8)
        g[d >= t1] = 1
        if levels >= 3:
            g[d >= t2] = 2
        min_px = int(min_area * PX * PX)
        for lv in range(levels):                       # fold specks into the surrounding group
            n, lab, stats, _ = cv2.connectedComponentsWithStats((g == lv).astype(np.uint8), 8)
            for i in range(1, n):
                if stats[i, cv2.CC_STAT_AREA] < min_px:
                    m = lab == i
                    ring = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~m
                    if ring.any():
                        g[m] = np.bincount(g[ring], minlength=levels).argmax()
        gf = cv2.GaussianBlur(g.astype(np.float32), (0, 0), 1.5)
        gx, gy = cv2.Sobel(gf, cv2.CV_32F, 1, 0), cv2.Sobel(gf, cv2.CV_32F, 0, 1)
        edge = np.clip(np.hypot(gx, gy) / 1.2, 0, 1)
        return g, edge

    def _calibrate(self, r):
        cfg, m = r["cfg"], r["mask"]
        if not m.any():
            r["white"] = r["black"] = 0.0
            return
        lum = self.lum
        out = cfg.get("paint_out")
        if out:                                        # glasses, eyes, brows... painted out before reading the skin
            pm = poly_mask(lum.shape, out.get("polygons", []), out.get("ellipses", [])).astype(np.uint8) * 255
            for rx in out.get("rings", []):            # glasses rims: (cx, cy, rx, ry, deg, width_units)
                cv2.ellipse(pm, (int(rx[0] * PX), int(rx[1] * PX)), (int(rx[2] * PX), int(rx[3] * PX)), rx[4], 0, 360, 255,
                            max(1, int(rx[5] * PX)))
            img = (np.clip(self.rgb, 0, 1) * 255).astype(np.uint8)
            lum = cv2.GaussianBlur(cv2.inpaint(img, pm, 9, cv2.INPAINT_TELEA).astype(np.float32) / 255, (0, 0), 3).mean(axis=2)
        vals = lum[m]
        # the region's own lightest/darkest, but never so far in that a light region gets shaded all over
        # (or a dark one washed out): white >= photo white - 0.1, black <= photo black + 0.25
        white = cfg.get("white", max(float(np.percentile(vals, cfg.get("white_pct", 95))), self.g_white - 0.1))
        black = cfg.get("black", min(float(np.percentile(vals, 2)), self.g_black + 0.25))
        if white - black < 0.05:
            black = white - 0.05
        d = np.clip((white - lum) / (white - black), 0, 1) ** cfg.get("gamma", 1.0)
        self.dark[m] = d[m] * cfg.get("depth", 1.0)
        r["white"], r["black"] = white, black

    def _orientation(self):
        g = cv2.GaussianBlur(self.lum, (0, 0), 1.8)
        gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
        jxx, jyy, jxy = (cv2.GaussianBlur(a, (0, 0), 7) for a in (gx * gx, gy * gy, gx * gy))
        theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + math.pi / 2          # along edges, across the gradient
        coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-9)
        # blend toward each region's fallback angle where the photo has no clear direction (axial averaging)
        c2, s2 = np.cos(2 * theta) * coh, np.sin(2 * theta) * coh
        for r in self.regions:
            a = math.radians(r["cfg"].get("angle", -35))
            w = 1 - coh[r["mask"]]
            c2[r["mask"]] += w * math.cos(2 * a)
            s2[r["mask"]] += w * math.sin(2 * a)
        c2, s2 = cv2.GaussianBlur(c2, (0, 0), 6), cv2.GaussianBlur(s2, (0, 0), 6)
        return 0.5 * np.arctan2(s2, c2), coh

    def trace(self, box, sigma=1.4, lo=18, hi=46, min_len=1.2, simplify=0.12, cap=80):
        """Feature edges inside box [x0, y0, x1, y1] (units) as polylines (units) with contrast strength 0..1."""
        x0, y0, x1, y1 = (int(v * PX) for v in box)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.W, x1), min(self.H, y1)
        sub = (cv2.GaussianBlur(self.rgb.mean(axis=2), (0, 0), sigma)[y0:y1, x0:x1] * 255).astype(np.uint8)
        e = cv2.Canny(sub, lo, hi)
        mag = cv2.Laplacian(sub.astype(np.float32), cv2.CV_32F, ksize=3)
        cs, _ = cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        out = []
        for c in cs:
            pts = c[:, 0, :].astype(np.float32)
            pts = pts[: max(2, len(pts) // 2 + 1)]            # a traced edge comes back on itself
            if len(pts) < 4:
                continue
            ap = cv2.approxPolyDP(pts.reshape(-1, 1, 2), simplify * PX, False)[:, 0, :]
            L = float(np.sum(np.hypot(*np.diff(pts, axis=0).T))) / PX
            if L < min_len:
                continue
            ii = np.clip(pts[:, 1].astype(int), 0, sub.shape[0] - 1)
            jj = np.clip(pts[:, 0].astype(int), 0, sub.shape[1] - 1)
            s = float(np.clip(np.abs(mag[ii, jj]).mean() / 60.0, 0, 1))
            out.append(([((x + x0) / PX, (y + y0) / PX) for x, y in ap], s, L))
        out.sort(key=lambda t: -t[1] * t[2])
        return [(p, s) for p, s, _ in out[:cap]]

    def likeness(self, rendered_rgb):
        """Per-region value error between the drawing and the photo's calibrated values (lower is better)."""
        rd = 1 - cv2.GaussianBlur(rendered_rgb.mean(axis=2).astype(np.float32), (0, 0), 4)
        pd = cv2.GaussianBlur(self.dark, (0, 0), 4)
        out = {}
        for r in self.regions:
            if r["mask"].any():
                out[r["name"]] = float(np.abs(rd[r["mask"]] - pd[r["mask"]] * r["cfg"].get("finish", 1.0)).mean())
        return out
