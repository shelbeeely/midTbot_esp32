"""Ink palettes.

Pilot G2 Fine Point: the 17 ink codes in Pilot's 2026 catalog. RGB values come from Pilot's PMS
colour-matching guide where it gives one; the others are estimates (MEASURED says which is which).
ROP and GRP are listed by code only in the catalog.
"""

G2 = {
    "BLK": ("Black", (35, 31, 32)), "BLU": ("Blue", (0, 48, 136)), "RED": ("Red", (191, 6, 47)),
    "PPL": ("Purple", (134, 102, 187)), "PNK": ("Pink", (198, 39, 166)), "TRQ": ("Turquoise", (0, 143, 190)),
    "CAR": ("Caramel", (158, 107, 61)), "HGR": ("Hunter Green", (39, 97, 66)), "LIM": ("Lime", (145, 213, 0)),
    "GRN": ("Green", (0, 140, 70)), "BRG": ("Burgundy", (128, 28, 52)), "ORG": ("Orange", (240, 110, 30)),
    "TEA": ("Teal", (0, 128, 128)), "PWK": ("Periwinkle", (120, 130, 220)), "NVY": ("Navy", (30, 40, 95)),
    "ROP": ("ROP", (226, 122, 150)), "GRP": ("GRP", (104, 52, 120)),
}
MEASURED = {"BLK", "BLU", "RED", "PPL", "PNK", "TRQ", "CAR", "HGR", "LIM"}

BALLPOINT4 = {"BLK": ("Black", (30, 30, 36)), "BLU": ("Blue", (38, 62, 172)), "RED": ("Red", (214, 42, 52)),
              "GRN": ("Green", (28, 138, 82))}

# line widths (mm) the tips lay down; 0.7 is Pilot's figure, 0.5 a retailer's, the others estimated
TIPS = {"g2-0.38": 0.26, "g2-0.5": 0.32, "g2-0.7": 0.39, "g2-1.0": 0.52, "ballpoint-1.0": 0.32}

PALETTES = {"g2": G2, "ballpoint4": BALLPOINT4}


def rgb(palette, code):
    return PALETTES[palette][code][1]
