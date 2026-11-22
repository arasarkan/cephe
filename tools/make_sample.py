#!/usr/bin/env python3
"""Generate the sample project: a 4-storey apartment block with front, back, right and left elevations,
an A-A section and a floor plan on one sheet, with the clutter of a real office drawing (dimensions,
axes, level marks, title frame). Brick on the corner bays and a stone plinth wrap around all four
facades, so cross-facade consistency can be checked. Units: cm.

  python tools/make_sample.py examples/ornek_proje.dwg     (or .dxf)
"""
import sys
from pathlib import Path

import ezdxf
from ezdxf.addons import odafc
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.inputs.dwg import find_oda  # noqa: E402

FH, FLOORS, PARAPET, PLINTH = 300, 4, 90, 60
TOP = FH * FLOORS


def setup(doc):
    for name, color, lw in [
        ("CEPHE", 7, 50), ("PENCERE", 4, 25), ("KORKULUK", 3, 18), ("ZEMIN", 7, 70), ("OLCU", 1, 13),
        ("YAZI", 2, 13), ("TARAMA", 8, 9), ("TAS_KAPLAMA", 8, 9), ("AKS", 6, 13), ("KOT", 5, 13),
        ("PAFTA", 7, 35), ("DUVAR", 7, 50), ("KESIT", 7, 70), ("MOBILYA", 8, 13),
    ]:
        doc.layers.add(name, color=color, lineweight=lw)
    doc.header["$INSUNITS"] = 5
    doc.dimstyles.new("CM", dxfattribs={"dimtxt": 15, "dimasz": 12, "dimexe": 8, "dimexo": 8})
    w = doc.blocks.new("PENCERE_140x160")
    w.add_lwpolyline([(0, 0), (140, 0), (140, 160), (0, 160)], close=True)
    w.add_lwpolyline([(6, 6), (134, 6), (134, 154), (6, 154)], close=True)
    w.add_line((70, 6), (70, 154))
    w.add_line((6, 110), (134, 110))
    w.add_lwpolyline([(-8, -6), (148, -6), (148, 0), (-8, 0)], close=True)
    s = doc.blocks.new("MERDIVEN_PENCERE_60x200")
    s.add_lwpolyline([(0, 0), (60, 0), (60, 200), (0, 200)], close=True)
    s.add_lwpolyline([(5, 5), (55, 5), (55, 195), (5, 195)], close=True)
    d = doc.blocks.new("BALKON_KAPI_100x240")
    d.add_lwpolyline([(0, 0), (100, 0), (100, 240), (0, 240)], close=True)
    d.add_lwpolyline([(6, 6), (94, 6), (94, 234), (6, 234)], close=True)
    d.add_line((6, 200), (94, 200))
    r = doc.blocks.new("KORKULUK_320")
    r.add_line((0, 100), (320, 100), dxfattribs={"layer": "KORKULUK"})
    r.add_line((0, 95), (320, 95), dxfattribs={"layer": "KORKULUK"})
    for x in range(0, 321, 12):
        r.add_line((x, 0), (x, 95), dxfattribs={"layer": "KORKULUK"})


def hatch(msp, layer, pattern, scale, rects):
    h = msp.add_hatch(color=8, dxfattribs={"layer": layer})
    h.set_pattern_fill(pattern, scale=scale)
    for x0, y0, x1, y1 in rects:
        h.paths.add_polyline_path([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def annotate(msp, ox, oy, W, title, axes):
    for i, x in enumerate(axes):
        msp.add_line((ox + x, oy - 250), (ox + x, oy + TOP + 300), dxfattribs={"layer": "AKS", "linetype": "CENTER"})
        msp.add_circle((ox + x, oy - 290), 40, dxfattribs={"layer": "AKS"})
        msp.add_text(str(i + 1), height=35, dxfattribs={"layer": "AKS"}).set_placement(
            (ox + x, oy - 290), align=TextEntityAlignment.MIDDLE_CENTER)
    for f in range(FLOORS + 1):
        y = oy + f * FH
        msp.add_line((ox + W + 80, y), (ox + W + 260, y), dxfattribs={"layer": "KOT"})
        msp.add_text(f"+{f * 3:.2f}", height=18, dxfattribs={"layer": "KOT"}).set_placement((ox + W + 140, y + 8))
    msp.add_linear_dim(base=(ox, oy - 120), p1=(ox, oy), p2=(ox + W, oy), dimstyle="CM",
                       dxfattribs={"layer": "OLCU"}).render()
    msp.add_linear_dim(base=(ox - 150, oy), p1=(ox, oy), p2=(ox, oy + TOP + PARAPET), angle=90, dimstyle="CM",
                       dxfattribs={"layer": "OLCU"}).render()
    msp.add_mtext(f"{title}  1/100", dxfattribs={"layer": "YAZI", "char_height": 45}).set_location(
        (ox + W / 2 - 300, oy - 420))


def shell(msp, ox, oy, W, corner):
    """Outline, slab bands, plinth, parapet, ground line; brick on the corner bays, stone plinth."""
    c = {"layer": "CEPHE"}
    msp.add_line((ox - 400, oy), (ox + W + 400, oy), dxfattribs={"layer": "ZEMIN"})
    msp.add_lwpolyline([(ox, oy), (ox + W, oy), (ox + W, oy + TOP + PARAPET), (ox, oy + TOP + PARAPET)],
                       close=True, dxfattribs=c)
    msp.add_line((ox - 20, oy + TOP), (ox + W + 20, oy + TOP), dxfattribs=c)
    msp.add_line((ox - 20, oy + TOP + 20), (ox + W + 20, oy + TOP + 20), dxfattribs=c)
    msp.add_line((ox, oy + PLINTH), (ox + W, oy + PLINTH), dxfattribs=c)
    for f in range(1, FLOORS):
        msp.add_line((ox, oy + f * FH), (ox + W, oy + f * FH), dxfattribs=c)
        msp.add_line((ox, oy + f * FH + 15), (ox + W, oy + f * FH + 15), dxfattribs=c)
    for x in (corner, W - corner):  # corner bay joints
        msp.add_line((ox + x, oy + PLINTH), (ox + x, oy + TOP), dxfattribs=c)
    hatch(msp, "TARAMA", "BRICK", 4, [(ox, oy + PLINTH, ox + corner, oy + TOP),
                                      (ox + W - corner, oy + PLINTH, ox + W, oy + TOP)])
    hatch(msp, "TAS_KAPLAMA", "ANSI31", 10, [(ox, oy, ox + W, oy + PLINTH)])


def window_grid(msp, ox, oy, xs, floors=range(FLOORS)):
    for f in floors:
        for x in xs:
            msp.add_blockref("PENCERE_140x160", (ox + x, oy + f * FH + 90), dxfattribs={"layer": "PENCERE"})


def front(msp, ox, oy, W=1600):
    shell(msp, ox, oy, W, 360)
    c = {"layer": "CEPHE"}
    msp.add_lwpolyline([(ox + 700, oy), (ox + 900, oy), (ox + 900, oy + 260), (ox + 700, oy + 260)], close=True, dxfattribs=c)
    msp.add_line((ox + 800, oy), (ox + 800, oy + 260), dxfattribs={"layer": "PENCERE"})
    msp.add_lwpolyline([(ox + 660, oy + 260), (ox + 940, oy + 260), (ox + 940, oy + 285), (ox + 660, oy + 285)],
                       close=True, dxfattribs=c)
    window_grid(msp, ox, oy, (120, 400, 1060, 1340), floors=[0])
    for f in range(1, FLOORS):
        y = oy + f * FH + 15
        window_grid(msp, ox, oy, (120, 400, 1060, 1340), floors=[f])
        msp.add_blockref("BALKON_KAPI_100x240", (ox + 750, y), dxfattribs={"layer": "PENCERE"})
        msp.add_lwpolyline([(ox + 640, y - 15), (ox + 960, y - 15), (ox + 960, y), (ox + 640, y)], close=True, dxfattribs=c)
        msp.add_blockref("KORKULUK_320", (ox + 640, y))
    annotate(msp, ox, oy, W, "ÖN CEPHE", (0, 560, 1040, 1600))


def back(msp, ox, oy, W=1600):
    shell(msp, ox, oy, W, 360)
    window_grid(msp, ox, oy, (120, 400, 1060, 1340))
    for f in range(FLOORS):  # stair window strip in the middle, half a floor up
        msp.add_blockref("MERDIVEN_PENCERE_60x200", (ox + 770, oy + f * FH + 150), dxfattribs={"layer": "PENCERE"})
    msp.add_lwpolyline([(ox + 560, oy), (ox + 660, oy), (ox + 660, oy + 230), (ox + 560, oy + 230)],
                       close=True, dxfattribs={"layer": "CEPHE"})  # service door
    annotate(msp, ox, oy, W, "ARKA CEPHE", (0, 560, 1040, 1600))


def side(msp, ox, oy, title, W=1000):
    shell(msp, ox, oy, W, 200)
    window_grid(msp, ox, oy, (300, 560))
    annotate(msp, ox, oy, W, title, (0, 500, 1000))


def section(msp, ox, oy, W=1000):
    c = {"layer": "KESIT"}
    msp.add_line((ox - 300, oy), (ox + W + 300, oy), dxfattribs={"layer": "ZEMIN"})
    msp.add_lwpolyline([(ox, oy), (ox + W, oy), (ox + W, oy + TOP + PARAPET), (ox, oy + TOP + PARAPET)], close=True, dxfattribs=c)
    for f in range(1, FLOORS + 1):
        y = oy + f * FH
        msp.add_lwpolyline([(ox, y - 20), (ox + W, y - 20), (ox + W, y), (ox, y)], close=True, dxfattribs=c)
        h = msp.add_hatch(color=7, dxfattribs={"layer": "KESIT"})
        h.paths.add_polyline_path([(ox, y - 20), (ox + W, y - 20), (ox + W, y), (ox, y)])
    msp.add_mtext("A-A KESİTİ  1/100", dxfattribs={"layer": "YAZI", "char_height": 45}).set_location(
        (ox + W / 2 - 250, oy - 300))


def plan(msp, ox, oy, W=1600, D=1000, t=25):
    for poly in ([(0, 0), (W, 0), (W, D), (0, D)], [(t, t), (W - t, t), (W - t, D - t), (t, D - t)]):
        msp.add_lwpolyline([(ox + x, oy + y) for x, y in poly], close=True, dxfattribs={"layer": "DUVAR"})
    for x in (560, 1040):
        msp.add_lwpolyline([(ox + x, oy + t), (ox + x + 15, oy + t), (ox + x + 15, oy + D - t), (ox + x, oy + D - t)],
                           close=True, dxfattribs={"layer": "DUVAR"})
    msp.add_mtext("NORMAL KAT PLANI  1/100", dxfattribs={"layer": "YAZI", "char_height": 45}).set_location(
        (ox + W / 2 - 350, oy - 200))


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/ornek_proje.dwg")
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2018", setup=True)
    setup(doc)
    msp = doc.modelspace()
    front(msp, 0, 0)
    side(msp, 2600, 0, "SAĞ YAN CEPHE")
    back(msp, 0, -2600)
    side(msp, 2600, -2600, "SOL YAN CEPHE")
    section(msp, 4800, 0)
    plan(msp, 4500, -2400)
    msp.add_lwpolyline([(-900, -3400), (6700, -3400), (6700, 2000), (-900, 2000)], close=True, dxfattribs={"layer": "PAFTA"})
    msp.add_mtext("ÖRNEK KONUT  -  MİMARİ PROJE", dxfattribs={"layer": "PAFTA", "char_height": 40}).set_location((5000, -3300))
    if out.suffix.lower() == ".dxf":
        doc.saveas(out)
    else:
        find_oda()
        odafc.export_dwg(doc, str(out), version="R2018", replace=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
