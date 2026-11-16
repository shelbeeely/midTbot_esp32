#!/usr/bin/env python3
"""Generate a printable controller plate that replaces the midTbot V2 PCB.

The V2 controller PCB is structural: the two NEMA14 motors bolt through it
and the two limit switches are soldered to it. When the brains move to an
off-the-shelf ESP32-S3 board (see Docs/esp32s3_upgrade.md) something still
has to hold the motors and switches in exactly the same places. This script
reads the V2 Gerber outline and Excellon drill file and extrudes a plate with:

  * the board outline (89 x 78 mm, 4 mm corner radius)
  * both 22.5 mm motor-shaft cutouts
  * every 0.14" (M3) hole: motor screws and base/cover mounting screws
  * the two limit-switch footprints (3 terminal holes + 2 locating pegs each)

Everything else on the PCB (headers, vias, sockets) is left off.

Usage:
    python3 make_plate.py                      # writes STL/midt_esp32s3_controller_plate.stl
    python3 make_plate.py --thickness 2.0 --hole-comp 0.25 -o plate.stl

Requires: shapely, trimesh, mapbox_earcut  (pip install shapely trimesh mapbox_earcut)
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GERBER_DIR = REPO / "PCB" / "V2" / "Gerbers"
DEFAULT_OUT = REPO / "STL" / "midt_esp32s3_controller_plate.stl"

INCH = 25.4

# Drill tools (inches) from PCB/V2/Gerbers/drill.drl that the plate keeps.
#   T07 0.0492" - limit switch terminals (3 per switch)
#   T08 0.0827" - limit switch locating pegs (2 per switch)
#   T09 0.1400" - M3 screws (motors, base, cover)
KEEP_TOOLS = {"07", "08", "09"}


def parse_outline(path: Path) -> list[list[tuple[float, float]]]:
    """Return closed contours (in mm) from a DipTrace profile Gerber.

    Handles the subset DipTrace emits for board outlines: inch units,
    FSLAX26Y26, modal coordinates, G01 lines and G02/G03 multi-quadrant arcs.
    """
    text = path.read_text()
    m = re.search(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%", text)
    if not m:
        raise ValueError("no format spec in outline Gerber")
    scale = 10 ** int(m.group(2))
    units = INCH if "%MOIN*%" in text else 1.0

    contours: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    x = y = 0.0
    interp = "G01"

    # Drop extended (%...%) parameter blocks; their info was read above.
    body = re.sub(r"%[^%]*%", "", text.replace("\n", "").replace("\r", ""))
    for raw in body.split("*"):
        block = raw.strip()
        if not block or block.startswith("G04"):
            continue
        g = re.match(r"G0?([123])", block)
        if g:
            interp = f"G0{g.group(1)}"
            block = block[g.end():]
            if not block:
                continue
        coords = dict(re.findall(r"([XYIJ])(-?\d+)", block))
        dcode = re.search(r"D0?([123])$", block)
        if not coords and not dcode:
            continue
        nx = int(coords["X"]) / scale * units if "X" in coords else x
        ny = int(coords["Y"]) / scale * units if "Y" in coords else y
        op = dcode.group(1) if dcode else "1"

        if op == "2":  # move
            if len(current) > 2:
                contours.append(current)
            current = [(nx, ny)]
        elif op == "1":  # draw
            if not current:
                current = [(x, y)]
            if interp == "G01":
                current.append((nx, ny))
            else:
                i = int(coords.get("I", 0)) / scale * units
                j = int(coords.get("J", 0)) / scale * units
                current.extend(_arc_points(x, y, nx, ny, x + i, y + j, interp == "G02"))
        x, y = nx, ny

    if len(current) > 2:
        contours.append(current)
    return contours


def _arc_points(x0, y0, x1, y1, cx, cy, clockwise, step_deg=3.0):
    r = math.hypot(x0 - cx, y0 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if clockwise:
        sweep = a0 - a1
    else:
        sweep = a1 - a0
    sweep %= 2 * math.pi
    if sweep < 1e-9:  # same start and end point: full circle
        sweep = 2 * math.pi
    n = max(2, int(math.degrees(sweep) / step_deg))
    pts = []
    for k in range(1, n + 1):
        a = a0 + (-1 if clockwise else 1) * sweep * k / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def parse_drill(path: Path) -> list[tuple[str, float, float, float]]:
    """Return (tool, diameter_mm, x_mm, y_mm) for every hit in an Excellon file."""
    tools: dict[str, float] = {}
    hits = []
    tool = None
    units = INCH
    for line in path.read_text().splitlines():
        line = line.strip()
        if line in ("METRIC", "M71"):
            units = 1.0
        m = re.match(r"T(\d+)C([\d.]+)$", line)
        if m:
            tools[m.group(1)] = float(m.group(2)) * units
            continue
        m = re.match(r"T(\d+)$", line)
        if m:
            tool = m.group(1)
            continue
        m = re.match(r"X([+-]?\d+)Y([+-]?\d+)$", line)
        if m and tool:
            # DipTrace writes 2.4 leading-zero inch coordinates.
            hx = int(m.group(1)) / 1e4 * units
            hy = int(m.group(2)) / 1e4 * units
            hits.append((tool, tools[tool], hx, hy))
    return hits


def build_plate(thickness: float, hole_comp: float):
    import shapely
    import trimesh
    from shapely import affinity
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    contours = [Polygon(c).buffer(0) for c in parse_outline(GERBER_DIR / "BoardOutline.gbr")]
    contours.sort(key=lambda p: p.area, reverse=True)
    outer, cutouts = contours[0], contours[1:]

    holes = [
        Point(x, y).buffer((d + hole_comp) / 2, resolution=24)
        for tool, d, x, y in parse_drill(GERBER_DIR / "drill.drl")
        if tool in KEEP_TOOLS
    ]
    plate = outer.difference(unary_union(cutouts + holes))

    # Put the board's lower-left corner at the origin.
    minx, miny, _, _ = plate.bounds
    plate = affinity.translate(plate, -minx, -miny)
    # Snap to a 0.1 um grid and drop collinear points; without this the
    # near-duplicate closing points of the Gerber contours leave the
    # extruded mesh non-manifold.
    plate = shapely.set_precision(plate, 1e-4).simplify(0.001)
    mesh = trimesh.creation.extrude_polygon(plate, thickness)
    mesh.merge_vertices()
    return plate, mesh, len(cutouts), len(holes)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--thickness", type=float, default=1.6,
                    help="plate thickness in mm (default 1.6 = same as the PCB, keeps screw and pulley heights)")
    ap.add_argument("--hole-comp", type=float, default=0.2,
                    help="mm added to every hole diameter to make up for printed holes shrinking (default 0.2)")
    args = ap.parse_args()

    plate, mesh, n_cut, n_holes = build_plate(args.thickness, args.hole_comp)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(args.output)
    w = plate.bounds[2] - plate.bounds[0]
    h = plate.bounds[3] - plate.bounds[1]
    print(f"wrote {args.output} : {w:.1f} x {h:.1f} x {args.thickness} mm, "
          f"{n_cut} motor cutouts, {n_holes} drilled holes, watertight={mesh.is_watertight}")


if __name__ == "__main__":
    main()
