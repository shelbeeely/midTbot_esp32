#!/usr/bin/env python3
"""sketch_engine: draw a photo the way an artist works a hand sketch, and replay it.

    python3 sketch.py run examples/raccoon.toml            # stills, report, SVG
    python3 sketch.py run examples/raccoon.toml --video    # + drawing-app replay video
    python3 sketch.py grid examples/raccoon.toml           # gridded reference, for measuring regions

The subject file names the photo, the page, and a few regions and features measured off the gridded
reference. Everything else (values, directions, edges, ordering, pacing) comes from the photo and
from the defaults in LESSONS.md.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit("Python 3.11+ is needed (tomllib)")

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyse as A                      # noqa: E402
import marks as M                        # noqa: E402
import replay as R                       # noqa: E402
from export import svg                   # noqa: E402
from palette import PALETTES, TIPS       # noqa: E402
from timeline import Timeline, stable_rng  # noqa: E402

FINISH = {1: 1.0, 2: 0.85, 3: 0.6, 4: 0.3}          # how far each priority is carried
TILE = {1: 1.3, 2: 1.6, 3: 2.2, 4: 3.0}
CROSS = (0.26, 1.05)                               # cross-hatch angles 15-60 degrees apart (radians)
BUDGET = {"gesture": 12.0, "construction": 22.0, "contours": 16.0, "tone": 75.0, "accents": 10.0}


def load(path):
    cfg = tomllib.loads(open(path).read())
    cfg["_dir"] = os.path.dirname(os.path.abspath(path))
    return cfg


def build_study(cfg):
    cu = cfg["canvas_units"]
    rgb = A.load_photo(os.path.join(cfg["_dir"], cfg["photo"]), cu, cfg.get("crop"))
    regs = []
    for r in cfg["region"]:
        if r.get("rest"):
            m = np.ones(rgb.shape[:2], bool)
        else:
            m = A.poly_mask(rgb.shape[:2], r.get("polygons", []), r.get("ellipses", []), r.get("arcs", []))
        pr = r.get("priority", 2)
        r.setdefault("finish", FINISH[pr])
        regs.append((r["name"], m, r))
    return A.Study(rgb, regs)


def outline(mask, eps_units=1.2):
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return []
    c = max(cs, key=cv2.contourArea)
    ap = cv2.approxPolyDP(c, eps_units * A.PX, True)[:, 0, :] / A.PX
    return [tuple(map(float, p)) for p in ap] + [tuple(map(float, ap[0]))]


def run(cfg, out, video=False):
    os.makedirs(out, exist_ok=True)
    st = build_study(cfg)
    pal = PALETTES[cfg.get("palette", "g2")]
    cu, page = cfg["canvas_units"], cfg["page_mm"]
    Wpx, Hpx = int(cu[0] * A.PX), int(cu[1] * A.PX)
    line_mm = TIPS[cfg.get("tip", "g2-0.38")]
    line_units = line_mm * cu[0] / page[0]
    canvas_kw = dict(W=Wpx, H=Hpx, palette=cfg.get("palette", "g2"), ink_model=cfg.get("ink_model", "gel"),
                     line_px=line_units * A.PX, title=cfg.get("title", "sketch"))
    focus = cfg.get("focus", [cu[0] / 2, cu[1] / 2])
    T = Timeline()
    report = {"stages": []}

    def measure(stage):
        img = R.still(T.events, **canvas_kw)
        like = st.likeness(img)
        main = [v for r, v in zip(st.regions, like.values()) if r["cfg"].get("priority", 2) <= 2]
        report["stages"].append(dict(stage=stage, error=round(float(np.mean(main)), 4), regions={k: round(v, 4) for k, v in like.items()}))
        print(f"  {stage:14} value error {np.mean(main):.3f}  " + "  ".join(f"{k} {v:.3f}" for k, v in like.items()))
        return img

    # ---------------------------------------------------------------- 1. gesture: big shapes, loose
    rng = stable_rng("gesture")
    big = [r for r in st.regions if not r["cfg"].get("rest") and r["cfg"].get("priority", 2) <= 3]
    items = []
    for g in cfg.get("gesture", []):
        items.append((M.loose_line(g["points"], rng, wobble=0.5), 0.28))
    for r in big:
        o = outline(r["mask"], 1.6)
        if len(o) > 3:
            n = max(2, len(o) // 6)
            for k in range(n):
                seg = o[k * len(o) // n: (k + 1) * len(o) // n + 1]
                items.append((M.loose_line(seg, rng, wobble=0.6, over=0.3), 0.3))
    T.strokes(items, "PWK" if "PWK" in pal else next(iter(pal)), "gesture", layer="rough", tool="pencil", speed=170, loose=0.6)

    # ---------------------------------------------------------------- 2. construction, with a correction or two
    rng = stable_rng("construction")
    pencil = "PWK" if "PWK" in pal else next(iter(pal))
    feats = []
    for f in cfg.get("feature", []):
        tr = st.trace(f["box"], lo=f.get("lo", 18), hi=f.get("hi", 46), min_len=f.get("min_len", 1.0), cap=f.get("cap", 30))
        feats.append((f, tr))
    if cfg.get("corrections", True) and big:
        o = outline(big[0]["mask"], 1.6)
        cx, cy = np.mean([p[0] for p in o]), np.mean([p[1] for p in o])
        wrong = [(cx + (x - cx) * 1.06 + 0.9, cy + (y - cy) * 1.06 + 0.7) for x, y in o]
        T.strokes([(M.loose_line(wrong, rng, wobble=0.4), 0.3)], pencil, "construction", layer="rough", tool="pencil", speed=170)
        for f, _ in feats[:3]:                       # compare against the landmarks
            b = f["box"]
            T.travel(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), "construction")
        T.erase(wrong, "construction")
        T.strokes([(M.loose_line(o, rng, wobble=0.3), 0.32)], pencil, "construction", layer="rough", tool="pencil", speed=170)
    for i, (f, tr) in enumerate(feats):
        items = [(pts, 0.22 + 0.25 * s) for pts, s in tr]
        if i == 0 and cfg.get("corrections", True) and items:
            pts0 = [(x + 0.8, y + 0.6) for x, y in items[0][0]]       # placed a little off: undo, then again
            T.strokes([(pts0, items[0][1])], pencil, "construction", layer="rough", tool="pencil", speed=170)
            T.travel(pts0[0], "construction")
            T.undo("construction")
        T.strokes(items, pencil, "construction", layer="rough", tool="pencil", speed=170, loose=0.15)
    T.fade_rough(0.32, "contours")
    measure("construction")

    # ---------------------------------------------------------------- 3. contours from the photo's own edges
    rng = stable_rng("contours")
    for f, tr in feats:
        T.strokes(M.contours(tr, rng, study=st), f.get("ink", "BLK"), "contours", speed=200)

    # ---------------------------------------------------------------- 4. tone, in the guides' order:
    #   shadow shapes first (one ink, one angle), then midtones at a second angle, then the darks at a third,
    #   then build up only what is still too light. Light shapes stay bare paper.
    order = sorted(st.regions, key=lambda r: r["cfg"].get("priority", 2))
    G = st.groups
    def tone_layer(r, ink, tgt, layer, rng):
        c = r["cfg"]
        if c.get("kind") == "eye":
            return []
        if c.get("arcs") and not c.get("polygons") and not c.get("ellipses"):
            return M.arc_bands(c["arcs"], line_units, rng, darkness=0.95) if layer == 3 else []
        if c.get("kind") == "hair":
            return M.strands(st, r["mask"], tgt, line_units, rng, length=tuple(c.get("strand_length", (4, 10))), focus=focus)
        r.setdefault("angles", [0.0])
        while len(r["angles"]) < layer:
            r["angles"].append(r["angles"][-1] + rng.choice((-1, 1)) * rng.uniform(*CROSS))
        return M.zigzag_hatch(st, r["mask"], tgt, line_units, rng, angle_offset=r["angles"][layer - 1],
                              tile=c.get("tile", TILE[c.get("priority", 2)]), focus=focus)
    layers = [("shadow shapes", lambda D, lt: np.where(G == 2, 0.25 + 0.15 * D, 0), 0),
              ("midtones", lambda D, lt: np.where(G >= 1, 0.12 + 0.25 * D, lt * np.clip(D - 0.05, 0, 1)), 1),
              ("darks", lambda D, lt: np.where(G == 2, 0.35 * np.clip((D - 0.5) / 0.5, 0, 1) + 0.12, 0), 2)]
    for li, (lname, target, ink_pos) in enumerate(layers, start=1):
        for r in order:
            c = r["cfg"]
            inks = [k for k in c.get("inks", []) if k in pal]
            if not inks or not r["mask"].any():
                continue
            ink = inks[min(ink_pos, len(inks) - 1)] if ink_pos < 2 else inks[-1]
            D = st.dark * r["mask"]
            # light shapes stay nearly bare; light_tone lets pale skin keep a whisper of its form
            tgt = (c["finish"] * c.get("share", 0.6) / 0.6 * target(D, c.get("light_tone", 0.04)) * r["mask"]).astype(np.float32)
            T.strokes(tone_layer(r, ink, tgt, li, stable_rng(f"{lname} {r['name']}")), ink, "tone")
        img = measure(lname)

    # ---------------------------------------------------------------- 5. build up what is still too light, darkest ink
    for it in range(cfg.get("fill_passes", 2)):
        rd = 1 - cv2.GaussianBlur(img.mean(axis=2).astype(np.float32), (0, 0), 2)
        for r in order:
            c = r["cfg"]
            inks = [k for k in c.get("inks", []) if k in pal]
            if not inks or c.get("priority", 2) > 3 or c.get("arcs") or c.get("kind") == "eye":
                continue
            want = cv2.GaussianBlur(st.dark * c["finish"], (0, 0), 2)
            res = np.clip(want - rd, 0, 1) * r["mask"] * (G >= 1) * 1.1
            if res.max() < 0.06:
                continue
            T.strokes(tone_layer(r, inks[-1], res.astype(np.float32), 4 + it, stable_rng(f"fill {it} {r['name']}")), inks[-1], "tone")
        img = measure(f"fill {it + 1}")

    # ---------------------------------------------------------------- eyes: the guides' sequence, iris -> pupil -> lashes
    for r in st.regions:
        c = r["cfg"]
        if c.get("kind") != "eye":
            continue
        rng = stable_rng("eye " + r["name"])
        parts = M.eye(*c["center"], c["iris"], rng, highlight=tuple(c.get("highlight", (-0.35, -0.35))),
                      width=c.get("width"), tilt=math.radians(c.get("tilt", 0)))
        inks = [k for k in c.get("inks", []) if k in pal] or ["BLK"]
        T.strokes(parts["iris"], inks[0], "accents", speed=120)
        T.strokes(parts["pupil"], inks[-1], "accents", speed=120)
        T.strokes(parts["lash"], inks[-1], "accents", speed=160)

    # ---------------------------------------------------------------- 6. accents: the sharpest darks, scribbled silhouettes
    rng = stable_rng("accents")
    dark_ink = "BLK" if "BLK" in pal else list(pal)[-1]
    for f, tr in feats:
        strong = [(pts, 0.85) for pts, s in tr if s > 0.55]
        T.strokes(strong, f.get("accent_ink", dark_ink), "accents", speed=180)
    for s in cfg.get("scribble", []):
        T.strokes(M.scribble(s["points"], rng, width=s.get("width", 1.2), p=s.get("p", 0.35)), s["ink"], "accents")
    img = measure("accents")

    # ---------------------------------------------------------------- outputs
    T.pace(BUDGET)
    Image.fromarray((img * 255).astype(np.uint8)).save(os.path.join(out, "drawing.png"))
    ref = Image.fromarray((st.rgb * 255).astype(np.uint8))
    side = Image.new("RGB", (Wpx * 2 + 10, Hpx), "white")
    side.paste(ref, (0, 0)); side.paste(Image.fromarray((img * 255).astype(np.uint8)), (Wpx + 10, 0))
    side.save(os.path.join(out, "compare.jpg"), quality=88)
    json.dump(dict(events=T.events), open(os.path.join(out, "events.json"), "w"))
    n = svg(T.events, pal, (Wpx, Hpx), page, os.path.join(out, "drawing.svg"), cfg.get("title", ""))
    report.update(strokes=sum(1 for e in T.events if e["type"] == "stroke"), svg_strokes=n)
    json.dump(report, open(os.path.join(out, "report.json"), "w"), indent=1)
    print(f"  {report['strokes']} strokes -> {out}")
    if video:
        secs = R.video(T.events, os.path.join(out, "replay.mp4"), **canvas_kw)
        print(f"  replay {secs:.0f} s")
    return report


def grid(cfg, out):
    os.makedirs(out, exist_ok=True)
    cu = cfg["canvas_units"]
    rgb = A.load_photo(os.path.join(cfg["_dir"], cfg["photo"]), cu, cfg.get("crop"))
    im = Image.fromarray((rgb * 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    f = ImageFont.load_default(size=13)
    for v in range(0, int(cu[0]) + 1, 5):
        d.line([(v * A.PX, 0), (v * A.PX, im.height)], fill=(255, 255, 0) if v % 10 == 0 else (110, 110, 0))
        if v % 10 == 0:
            d.text((v * A.PX + 2, 2), str(v), fill=(255, 255, 0), font=f)
    for v in range(0, int(cu[1]) + 1, 5):
        d.line([(0, v * A.PX), (im.width, v * A.PX)], fill=(0, 255, 255) if v % 10 == 0 else (0, 110, 110))
        if v % 10 == 0:
            d.text((2, v * A.PX + 2), str(v), fill=(0, 255, 255), font=f)
    im.save(os.path.join(out, "grid.jpg"), quality=88)
    print("grid", os.path.join(out, "grid.jpg"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "grid"])
    ap.add_argument("subject")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--video", action="store_true")
    a = ap.parse_args(argv)
    cfg = load(a.subject)
    out = a.out or os.path.join("out", os.path.splitext(os.path.basename(a.subject))[0])
    return run(cfg, out, a.video) if a.cmd == "run" else grid(cfg, out)


if __name__ == "__main__":
    main()
