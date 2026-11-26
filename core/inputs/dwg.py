"""DWG / DXF -> Sheet.

Reads the drawing (DWG through ODA File Converter), explodes blocks, separates building geometry from
annotation, and keeps what the annotation tells us: view titles (as labels) and hatches (as materials).
"""
import glob
import json
import math
import re
from pathlib import Path

import ezdxf
from ezdxf import disassemble
from ezdxf.addons import odafc

from ..geometry import drop_frames, split_views
from ..i18n import UserError
from ..sheet import Hatch, Label, Sheet, Stroke, View

ROOT = Path(__file__).resolve().parents[2]

SKIP_TYPES = {
    "DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION", "LEADER", "MLEADER", "MULTILEADER",
    "TOLERANCE", "POINT", "VIEWPORT", "IMAGE", "WIPEOUT", "RAY", "XLINE", "SOLID", "TRACE", "OLE2FRAME",
    "UNDERLAY", "PDFUNDERLAY", "DWFUNDERLAY", "DGNUNDERLAY",
}
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
# Layer names (English + Turkish office conventions) that hold annotation, not building geometry.
DEFAULT_EXCLUDE = (r"dim|[öo]l[çc][üu]|text|yaz[ıi]|^not|anno|hatch|tara|aks|axis|grid|kot|level|"
                   r"pafta|title|frame|[çc]er[çc]eve|defpoints|vport|viewport|mobil|furn|kesit.?[çc]izgi|kesik|"
                   r"section.?line|symbol|sembol")
DASHED = re.compile(r"center|dash|hidden|phantom|dot|aks|axis|gizli|kesik", re.I)
INSUNITS_PER_M = {1: 39.37, 2: 3.281, 4: 1000.0, 5: 100.0, 6: 1.0, 14: 10.0}  # in, ft, mm, cm, m, dm


class DrawingError(UserError):
    """A problem with the drawing the user can act on (message key from i18n)."""


def find_oda():
    """Point ezdxf at ODA File Converter (its install folder includes the version number)."""
    exe = None
    cfg = ROOT / "config.json"
    if cfg.exists():
        exe = json.loads(cfg.read_text(encoding="utf-8")).get("oda")
    if not exe or not Path(exe).exists():
        found = sorted(glob.glob(r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe"), reverse=True)
        exe = found[0] if found else None
    if not exe:
        raise DrawingError("oda_missing")
    ezdxf.options.set("odafc-addon", "win_exec_path", exe)
    odafc.win_exec_path = exe
    return exe


def load_doc(path):
    path = Path(path)
    try:
        if path.suffix.lower() == ".dwg":
            find_oda()
            return odafc.readfile(str(path))
        try:
            return ezdxf.readfile(str(path))
        except ezdxf.DXFStructureError:
            from ezdxf import recover
            doc, _ = recover.readfile(str(path))
            return doc
    except DrawingError:
        raise
    except Exception as e:
        raise DrawingError("read_failed", kind=type(e).__name__) from e


class Filter:
    def __init__(self, doc, exclude=DEFAULT_EXCLUDE, also_exclude=None, only=None, keep_dashed=False):
        pats = [p for p in (exclude, also_exclude) if p]
        self.exclude = re.compile("|".join(f"(?:{p})" for p in pats), re.I) if pats else None
        self.only = re.compile(only, re.I) if only else None
        self.keep_dashed = keep_dashed
        self.layers = {l.dxf.name.lower(): l for l in doc.layers}
        self.dropped = {}
        self.hatches, self.labels = [], []

    def visible(self, name):
        layer = self.layers.get(name.lower())
        return not (layer is not None and (layer.is_off() or layer.is_frozen()))

    def layer_ok(self, name):
        if not self.visible(name):
            return False
        if self.only:
            return bool(self.only.search(name))
        return not (self.exclude and self.exclude.search(name))

    def linetype(self, e, layer_name):
        lt = e.dxf.get("linetype", "BYLAYER")
        if lt.upper() == "BYLAYER":
            layer = self.layers.get(layer_name.lower())
            lt = layer.dxf.get("linetype", "CONTINUOUS") if layer is not None else "CONTINUOUS"
        return lt

    def lineweight(self, e, layer_name, parent_lw):
        lw = e.dxf.get("lineweight", -1)
        if lw == -2:  # BYBLOCK
            lw = parent_lw
        if lw is None or lw < 0:
            layer = self.layers.get(layer_name.lower())
            lw = layer.dxf.get("lineweight", -3) if layer is not None else -3
        return 25 if lw is None or lw < 0 else lw

    def drop(self, why):
        self.dropped[why] = self.dropped.get(why, 0) + 1


def text_of(e):
    t = e.dxftype()
    if t == "MTEXT":
        return e.plain_text(split=False), e.dxf.get("char_height", 0), e.dxf.insert
    return e.dxf.get("text", ""), e.dxf.get("height", 0), e.dxf.get("insert")


def explode(entities, flt, parent_layer=None, parent_lw=25, depth=0):
    """Yield (entity, layer, lineweight) for building geometry; collect labels and hatches on the way."""
    for e in entities:
        t = e.dxftype()
        layer = e.dxf.get("layer", "0")
        if layer == "0" and parent_layer:  # layer-0 block content takes the INSERT's layer
            layer = parent_layer
        if t in TEXT_TYPES:
            if flt.visible(layer):
                try:
                    text, h, ins = text_of(e)
                    if text and text.strip() and ins is not None:
                        flt.labels.append(Label(text.strip(), ins[0], ins[1], h or 0))
                except Exception:
                    pass
            flt.drop(t)
            continue
        if t in SKIP_TYPES:
            flt.drop(t)
            continue
        if t == "HATCH":
            if flt.visible(layer):
                flt.hatches.append((e, layer))
            flt.drop("HATCH")
            continue
        if t == "INSERT":
            if depth > 12 or not flt.visible(layer):
                continue
            try:  # attributes (title blocks, view titles drawn as blocks) are labels too
                for att in e.attribs:
                    text, h, ins = text_of(att)
                    if text and text.strip():
                        flt.labels.append(Label(text.strip(), ins[0], ins[1], h or 0))
            except Exception:
                pass
            if not flt.layer_ok(layer):
                flt.drop(f"layer {layer}")
                continue
            lw = flt.lineweight(e, layer, parent_lw)
            try:
                yield from explode(e.virtual_entities(), flt, layer, lw, depth + 1)
            except Exception:
                flt.drop("bad INSERT")
            continue
        if not flt.layer_ok(layer):
            flt.drop(f"layer {layer}")
            continue
        if not flt.keep_dashed and DASHED.search(flt.linetype(e, layer)):
            flt.drop("dashed line")
            continue
        yield e, layer, flt.lineweight(e, layer, parent_lw)


def strokes_of(doc, flt):
    out = []
    for e, layer, lw in explode(doc.modelspace(), flt):
        try:
            prims = list(disassemble.to_primitives([e]))
        except Exception:
            flt.drop("unsupported " + e.dxftype())
            continue
        for p in prims:
            try:
                pts = [(v.x, v.y) for v in p.vertices()]
            except Exception:
                continue
            if len(pts) >= 2 and all(math.isfinite(c) for xy in pts for c in xy):
                out.append(Stroke(pts, lw >= 40))
    return out


def hatches_of(flt):
    from ezdxf import path as ezpath
    out = []
    for h, layer in flt.hatches:
        polys = []
        try:
            for p in ezpath.from_hatch(h):
                pts = [(v.x, v.y) for v in p.flattening(1.0)]
                if len(pts) >= 3:
                    polys.append(pts)
        except Exception:
            continue
        if polys:
            pattern = h.dxf.get("pattern_name", "") or ""
            out.append(Hatch(polys, pattern, layer, group=f"{layer}|{pattern}".upper()))
    return out


def units_per_m(doc, views):
    """Drawing units per meter: from $INSUNITS when it is plausible, else guessed from building size.
    The size is a typical drawing on the sheet (median of the sizeable ones, so a site plan or a detail
    doesn't decide): a building plan or elevation is 5-300 m across. Many offices draw in cm while
    $INSUNITS says mm."""
    big = max((v.width * v.height for v in views), default=0)
    sizes = sorted(max(v.width, v.height) for v in views if v.width * v.height >= 0.1 * big)
    size = sizes[len(sizes) // 2] if sizes else 0

    def plausible(upm):
        return 5 <= size / upm <= 300
    declared = INSUNITS_PER_M.get(doc.header.get("$INSUNITS", 0))
    if declared and plausible(declared):
        return declared
    for upm in (1000.0, 100.0, 1.0):  # mm, cm, m
        if plausible(upm):
            return upm
    return declared or 1000.0


def read(path, exclude=DEFAULT_EXCLUDE, also_exclude=None, only=None, keep_dashed=False):
    from ..classify import classify_views
    doc = load_doc(path)
    flt = Filter(doc, exclude, also_exclude, only, keep_dashed)
    strokes = strokes_of(doc, flt)
    if not strokes:
        raise DrawingError("no_lines")
    views = [View(i, bb, g) for i, (bb, g) in enumerate(split_views(drop_frames(strokes)), 1)]
    for h in hatches_of(flt):  # a hatch belongs to the view that contains its center
        cx, cy = (h.bbox[0] + h.bbox[2]) / 2, (h.bbox[1] + h.bbox[3]) / 2
        for v in views:
            if v.bbox[0] <= cx <= v.bbox[2] and v.bbox[1] <= cy <= v.bbox[3]:
                v.hatches.append(h)
                break
    sheet = Sheet(str(path), units_per_m(doc, views), views)
    classify_views(sheet, flt.labels)
    return sheet
