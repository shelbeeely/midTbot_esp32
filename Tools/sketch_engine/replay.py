"""Draw the event timeline: as a still, or as a drawing-app replay video.

The canvas starts blank; pixels appear only where the cursor passes with the brush down.
Rough pencil lives on its own layer (it can be erased, undone and faded); ink goes on top.
Ink models: "gel" sits on the paper in its own colour (overlaps darken a little);
"ballpoint" is translucent and its strength follows pressure.
"""
from __future__ import annotations

import math
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from palette import PALETTES

SS = 2                                          # supersampling
FPS = 30
PAPER = np.array((252, 251, 248), np.float32) / 255
_F = lambda s: ImageFont.load_default(size=s)


class Canvas:
    def __init__(self, W, H, palette="g2", ink_model="gel", line_px=1.3, title="sketch"):
        self.W, self.H = W, H
        self.pal = PALETTES[palette]
        self.ink_model, self.line_px, self.title = ink_model, line_px, title
        self.pencil = np.array(self.pal.get("PWK", ("", (120, 130, 220)))[1], np.float32) / 255 * 0.82
        g = np.random.default_rng(5).random((H * SS // 2 + 1, W * SS // 2 + 1)).astype(np.float32)
        self.grain = np.asarray(Image.fromarray(g).resize((W * SS, H * SS), Image.BILINEAR))
        self.rough = np.zeros((H * SS, W * SS), np.float32)
        self.ink = np.ones((H * SS, W * SS, 3), np.float32)
        self.comp = np.empty((H, W, 3), np.float32)
        self.rough_log = []
        self.rough_op = 1.0
        self.recompose()

    # ---------------------------------------------------------------- marks
    def tile(self, pts, tool, upto=None):
        q = pts if upto is None else pts[: int(upto) + 1]
        if upto is not None and int(upto) + 1 < len(pts):
            f = upto - int(upto)
            a, b = pts[int(upto)], pts[int(upto) + 1]
            q = q + [(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, b[2], b[3])]
        if len(q) < 2:
            return None
        xs, ys = [p[0] * SS for p in q], [p[1] * SS for p in q]
        x0, y0 = max(0, int(min(xs)) - 8), max(0, int(min(ys)) - 8)
        x1, y1 = min(self.W * SS, int(max(xs)) + 8), min(self.H * SS, int(max(ys)) + 8)
        if x1 <= x0 or y1 <= y0:
            return None
        t = Image.new("L", (x1 - x0, y1 - y0), 0)
        d = ImageDraw.Draw(t)
        for a, b in zip(q, q[1:]):
            pr = (a[3] + b[3]) / 2
            if tool == "pencil":
                w, fill = 2.6 + 1.6 * pr, 0.34 + 0.6 * pr
            elif tool == "eraser":
                w, fill = 22, 1.0
            elif self.ink_model == "ballpoint":
                w, fill = self.line_px * SS * (0.85 + 0.3 * pr), 0.1 + 0.72 * pr
            else:
                w, fill = self.line_px * SS * (0.9 + 0.2 * pr), 0.94
            A, B = (a[0] * SS - x0, a[1] * SS - y0), (b[0] * SS - x0, b[1] * SS - y0)
            d.line([A, B], fill=int(255 * fill), width=max(1, round(w)))
            r = w / 2
            d.ellipse([B[0] - r, B[1] - r, B[0] + r, B[1] + r], fill=int(255 * fill))
        m = np.asarray(t, np.float32) / 255
        if tool == "pencil":
            m = m * self.grain[y0:y1, x0:x1]
        return (x0, y0, x1, y1), m

    def recompose(self, box=None):
        x0, y0, x1, y1 = box or (0, 0, self.W * SS, self.H * SS)
        x0, y0 = x0 // SS * SS, y0 // SS * SS
        x1, y1 = min(self.W * SS, -(-x1 // SS) * SS), min(self.H * SS, -(-y1 // SS) * SS)
        r = self.rough[y0:y1, x0:x1, None]
        c = PAPER * (1 - self.rough_op * r * (1 - self.pencil)) * self.ink[y0:y1, x0:x1]
        self.comp[y0 // SS:y1 // SS, x0 // SS:x1 // SS] = c.reshape((y1 - y0) // SS, SS, (x1 - x0) // SS, SS, 3).mean(axis=(1, 3))

    def apply(self, layer, tool, ink, t):
        (x0, y0, x1, y1), m = t
        if layer == "rough":
            s = self.rough[y0:y1, x0:x1]
            if tool == "eraser":
                s *= 1 - m
            else:
                np.maximum(s, m, out=s)
        else:
            s = self.ink[y0:y1, x0:x1]
            m3 = m[..., None]
            if tool == "eraser":
                s += (1 - s) * m3
            else:
                col = np.array(self.pal[ink][1], np.float32) / 255
                if self.ink_model == "ballpoint":
                    s *= 1 - m3 * (1 - col)
                else:
                    s[:] = s * (1 - m3) + m3 * np.minimum(col, s) * (0.85 + 0.15 * s)
        self.recompose((x0, y0, x1, y1))

    def bake(self, e):
        tool = "eraser" if e["type"] == "erase" else e["tool"]
        t = self.tile(e["pts"], tool)
        if t:
            self.apply(e["layer"], tool, e.get("ink"), t)
            if e["layer"] == "rough":
                self.rough_log.append(("erase" if tool == "eraser" else "draw", t))

    def undo_rough(self):
        if not self.rough_log:
            return
        self.rough_log.pop()
        self.rough[:] = 0
        for kind, ((x0, y0, x1, y1), m) in self.rough_log:
            if kind == "erase":
                self.rough[y0:y1, x0:x1] *= 1 - m
            else:
                np.maximum(self.rough[y0:y1, x0:x1], m, out=self.rough[y0:y1, x0:x1])
        self.recompose()

    def play(self, events, upto=None):
        """Apply events without making frames (for stills and between-stage checks)."""
        for e in events[:upto]:
            ty = e["type"]
            if ty in ("stroke", "erase"):
                self.bake(e)
            elif ty == "undo":
                self.undo_rough()
            elif ty == "opacity":
                self.rough_op = e["to"]
                self.recompose()
        return self.image()

    def image(self):
        return np.clip(self.comp, 0, 1)


def still(events, **kw):
    return Canvas(**kw).play(events)


# -------------------------------------------------------------------- the replay video
def video(events, out, W, H, palette="g2", ink_model="gel", line_px=1.3, title="sketch", hold=3.5):
    cv = Canvas(W, H, palette, ink_model, line_px, title)
    pal = cv.pal
    FW, FH = 1280, max(1080, H + 80)
    CX, CY = 262 + (750 - W) // 2, 54
    inks_used = [k for k in pal if any(e.get("ink") == k for e in events if e["type"] == "stroke" and e["layer"] == "ink")]
    st = dict(tool="pencil", ink=next(iter(pal)), layer="rough", ink_layer=False, undo=0, cursor=(W / 2, H / 2), down=False)
    base = Image.new("RGB", (FW, FH), (38, 39, 43))
    d = ImageDraw.Draw(base)
    d.rectangle([0, 0, FW, 40], fill=(28, 29, 32))
    d.text((16, 12), f"Sketchbook  -  {title}", fill=(200, 200, 205), font=_F(15))
    d.text((FW - 120, 12), "Replay", fill=(150, 150, 158), font=_F(15))
    d.rectangle([CX - 2, CY - 2, CX + W + 1, CY + H + 1], outline=(20, 20, 22), width=2)
    d.text((18, 56), "Tools", fill=(140, 140, 148), font=_F(13))
    d.text((18, 290), "Inks", fill=(140, 140, 148), font=_F(13))
    d.text((CX + W + 22, 56), "Layers", fill=(140, 140, 148), font=_F(13))
    tools = [("pencil", "Pencil"), ("pen", "Pen"), ("eraser", "Eraser"), ("undo", "Undo")]

    def ui(f, clock):
        d = ImageDraw.Draw(f, "RGBA")
        for i, (k, name) in enumerate(tools):
            y = 80 + i * 48
            act = st["tool"] == k or (k == "undo" and st["undo"] > 0)
            d.rounded_rectangle([14, y, 236, y + 38], 8, fill=(70, 110, 190) if act else (52, 53, 58))
            d.text((54, y + 11), name, fill=(240, 240, 245) if act else (190, 190, 196), font=_F(14))
        for i, k in enumerate(inks_used):
            x, y = 18 + (i % 2) * 112, 314 + (i // 2) * 40
            act = st["ink"] == k and st["tool"] == "pen"
            d.rounded_rectangle([x - 4, y - 4, x + 104, y + 30], 6, fill=(62, 64, 72) if act else None,
                                outline=(110, 150, 230) if act else None, width=2)
            d.ellipse([x, y, x + 26, y + 26], fill=pal[k][1], outline=(20, 20, 22))
            d.text((x + 34, y + 6), k, fill=(235, 235, 240) if act else (165, 165, 172), font=_F(14))
        rows = ([("Ink", 1.0, st["layer"] == "ink")] if st["ink_layer"] else []) + [("Rough sketch", cv.rough_op, st["layer"] == "rough")]
        for i, (name, op, act) in enumerate(rows):
            x, y = CX + W + 18, 80 + i * 62
            d.rounded_rectangle([x, y, FW - 16, y + 52], 8, fill=(70, 110, 190) if act else (52, 53, 58))
            d.text((x + 12, y + 8), name, fill=(240, 240, 245), font=_F(14))
            d.rectangle([x + 12, y + 32, x + 150, y + 38], fill=(32, 33, 36))
            d.rectangle([x + 12, y + 32, x + 12 + int(138 * op), y + 38], fill=(200, 200, 210))
            d.text((x + 160, y + 27), f"{int(round(op * 100))}%", fill=(210, 210, 216), font=_F(13))
        x = CX + W + 18
        d.text((x, 240), "Brush", fill=(140, 140, 148), font=_F(13))
        d.text((x, 262), {"pencil": "Pencil (pressure)", "pen": "Pen", "eraser": "Soft eraser", "undo": ""}[st["tool"]],
               fill=(215, 215, 220), font=_F(14))
        if st["tool"] == "pen":
            d.text((x, 284), f"{pal[st['ink']][0]} ({st['ink']})", fill=(170, 170, 178), font=_F(13))
        d.text((x, FH - 60), "Drawing time", fill=(140, 140, 148), font=_F(13))
        d.text((x, FH - 40), f"{int(clock // 3600):02d}:{int(clock % 3600 // 60):02d}:{int(clock % 60):02d}", fill=(220, 220, 226), font=_F(18))
        cx, cy = CX + st["cursor"][0], CY + st["cursor"][1]
        r = (11 if st["tool"] == "eraser" else 4) + 3
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(40, 40, 50, 150 if st["down"] else 90), width=1)
        d.ellipse([cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1], outline=(255, 255, 255, 90), width=1)
        if st["down"]:
            d.ellipse([cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5], fill=(30, 30, 40, 200))

    def frame(active, clock):
        c = cv.comp
        if active is not None:
            e, upto = active
            tool = "eraser" if e["type"] == "erase" else e["tool"]
            t = cv.tile(e["pts"], tool, upto)
            if t:
                (x0, y0, x1, y1), _ = t
                sr, si, sc = cv.rough[y0:y1, x0:x1].copy(), cv.ink[y0:y1, x0:x1].copy(), cv.comp.copy()
                cv.apply(e["layer"], tool, e.get("ink"), t)
                c = cv.comp.copy()
                cv.rough[y0:y1, x0:x1], cv.ink[y0:y1, x0:x1] = sr, si
                cv.comp[:] = sc
        f = base.copy()
        f.paste(Image.fromarray((np.clip(c, 0, 1) * 255).astype(np.uint8)), (CX, CY))
        ui(f, clock)
        return f

    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{FW}x{FH}",
                             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                             "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    vt = nf = clock = 0.0
    n = 0

    def emit(active=None):
        nonlocal n
        proc.stdin.write(frame(active, clock).tobytes())
        n += 1

    for e in events:
        ty = e["type"]
        if ty == "select":
            st.update(tool=e["tool"], ink=e["ink"], layer=e["layer"])
        elif ty == "new_layer":
            st.update(ink_layer=True, layer="ink")
        elif ty == "undo":
            st["undo"] = 12
            cv.undo_rough()
        elif ty in ("stroke", "erase"):
            pts = e["pts"]
            if ty == "erase":
                st["tool"] = "eraser"
            sx, sy = pts[0][0], pts[0][1]
            dist = math.dist(st["cursor"], (sx, sy))
            tdur = {"tone": 0.0, "accents": 0.0, "contours": min(0.1, dist / 3000)}.get(e.get("phase"), min(0.35, dist / 1600))
            c0, st["down"] = st["cursor"], False
            while nf <= vt + tdur and tdur > 0:
                u = (nf - vt) / tdur
                st["cursor"] = (c0[0] + (sx - c0[0]) * u, c0[1] + (sy - c0[1]) * u)
                emit(); nf += 1 / FPS
            vt += tdur
            st["cursor"], st["down"] = (sx, sy), True
            dur, T = e["vdur"], pts[-1][2] or 1e-6
            times = [p[2] for p in pts]
            while nf <= vt + dur:
                ta = (nf - vt) / max(dur, 1e-9) * T
                i = max(0, min(len(pts) - 2, int(np.searchsorted(times, ta)) - 1))
                a, b = pts[i], pts[i + 1]
                f = 0 if b[2] == a[2] else min(1, max(0, (ta - a[2]) / (b[2] - a[2])))
                st["cursor"] = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                st["undo"] = max(0, st["undo"] - 1)
                emit((e, i + f)); nf += 1 / FPS
            vt += dur
            clock += e.get("adur", dur)
            cv.bake(e)
            st["cursor"], st["down"] = (pts[-1][0], pts[-1][1]), False
            if ty == "erase":
                st["tool"] = "pencil"
        elif ty == "travel":
            to, c0 = tuple(e["to"]), st["cursor"]
            tdur = max(0.15, math.dist(c0, to) / e.get("vspeed", 420))
            while nf <= vt + tdur:
                u = (nf - vt) / tdur
                st["cursor"] = (c0[0] + (to[0] - c0[0]) * u, c0[1] + (to[1] - c0[1]) * u)
                emit(); nf += 1 / FPS
            vt += tdur; clock += tdur * 2; st["cursor"] = to
        elif ty == "pause":
            while nf <= vt + e["vdur"]:
                st["undo"] = max(0, st["undo"] - 1)
                emit(); nf += 1 / FPS
            vt += e["vdur"]; clock += e["vdur"] * 3
        elif ty == "opacity":
            o0 = cv.rough_op
            while nf <= vt + e["vdur"]:
                cv.rough_op = o0 + (e["to"] - o0) * (nf - vt) / e["vdur"]
                cv.recompose(); emit(); nf += 1 / FPS
            vt += e["vdur"]; cv.rough_op = e["to"]; cv.recompose()
    st["cursor"] = (W + 60, H - 40)
    for _ in range(int(hold * FPS)):
        emit()
    proc.stdin.close(); proc.wait()
    return n / FPS
