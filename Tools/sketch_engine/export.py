"""Plottable SVG: one Inkscape layer per ink, every stroke with its own pressure (for journal_plot)."""
from collections import defaultdict


def svg(events, palette, canvas_px, page_mm, path, note=""):
    k = page_mm[0] / canvas_px[0]
    layers = defaultdict(lambda: defaultdict(list))
    for e in events:
        if e["type"] == "stroke" and e["layer"] == "ink":
            pts = [(x * k, y * k) for x, y, _, _ in e["pts"][::2]] + [(e["pts"][-1][0] * k, e["pts"][-1][1] * k)]
            p = sum(q[3] for q in e["pts"]) / len(e["pts"])
            layers[e["ink"]][round(p * 20) / 20].append(pts)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
           f'width="{page_mm[0]:g}mm" height="{page_mm[1]:g}mm" viewBox="0 0 {page_mm[0]:g} {page_mm[1]:g}">']
    if note:
        out.append(f"  <!-- {note} -->")
    for ink, groups in layers.items():
        name, rgb = palette[ink]
        col = "#%02x%02x%02x" % rgb
        out.append(f'  <g inkscape:groupmode="layer" inkscape:label="{ink}" fill="none" stroke="{col}" stroke-linecap="round">')
        for p, strokes in sorted(groups.items()):
            d = " ".join("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in s) for s in strokes)
            out.append(f'    <path data-pressure="{p:g}" d="{d}"/>')
        out.append("  </g>")
    out.append("</svg>")
    open(path, "w").write("\n".join(out) + "\n")
    return sum(len(v) for g in layers.values() for v in g.values())
