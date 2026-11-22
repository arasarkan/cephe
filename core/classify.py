"""What each view is: its title on the sheet, its kind (elevation / section / plan) and which way it faces.
Titles are recognized in Turkish and English whatever the UI language."""
import re

from .sheet import View

_TR = str.maketrans("ÇĞİIÖŞÜçğıiöşü", "CGIIOSUcgiiosu")


def norm(text):
    """Uppercase ASCII, so 'Güney Cephesi' and 'GUNEY CEPHESI' compare equal."""
    return re.sub(r"\s+", " ", text.translate(_TR).upper()).strip()


KIND_WORDS = [
    ("section", r"\bKESIT|\bSECTION\b"),
    ("plan", r"\bPLAN|\bVAZIYET|\bSITE\b|\bLAYOUT\b"),
    ("elevation", r"\bCEPHE|\bGORUNUS|\bELEVATION\b|\bFACADE\b"),
]
# compass first (KUZEYDOGU before KUZEY), then relative names
FACING_WORDS = [
    ("NE", r"\bKUZEY ?DOGU|\bNORTH ?-?EAST|\bNE\b"), ("NW", r"\bKUZEY ?BATI|\bNORTH ?-?WEST|\bNW\b"),
    ("SE", r"\bGUNEY ?DOGU|\bSOUTH ?-?EAST|\bSE\b"), ("SW", r"\bGUNEY ?BATI|\bSOUTH ?-?WEST|\bSW\b"),
    ("N", r"\bKUZEY|\bNORTH"), ("S", r"\bGUNEY|\bSOUTH"), ("E", r"\bDOGU|\bEAST"), ("W", r"\bBATI\b|\bBATI ?C|\bWEST"),
    ("front", r"\bON\b|\bFRONT\b|\bANA\b"), ("back", r"\bARKA\b|\bREAR\b|\bBACK\b"),
    ("right", r"\bSAG\b|\bRIGHT\b"), ("left", r"\bSOL\b|\bLEFT\b"), ("side", r"\bYAN\b|\bSIDE\b"),
]
COMPASS = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


def parse_title(text):
    """-> (kind or None, facing or None)"""
    t = norm(text)
    kind = next((k for k, rx in KIND_WORDS if re.search(rx, t)), None)
    facing = next((f for f, rx in FACING_WORDS if re.search(rx, t)), None)
    if kind in ("section", "plan"):
        facing = None
    return kind, facing


def _title_score(view: View, label):
    """Lower is better: titles sit under (or over) their drawing, roughly centered, in larger text."""
    x0, y0, x1, y1 = view.bbox
    w, h = x1 - x0, y1 - y0
    if not (x0 - 0.3 * w <= label.x <= x1 + 0.3 * w):
        return None
    if y0 - 0.6 * h <= label.y <= y0:
        d = (y0 - label.y) / h
    elif y1 <= label.y <= y1 + 0.35 * h:
        d = (label.y - y1) / h + 0.15  # above: slightly less likely
    else:
        return None
    return d - 0.2 * bool(parse_title(label.text)[0])


def guess_kind(view: View):
    """No title: an elevation has a ground line, i.e. a long horizontal line at the very bottom."""
    x0, y0, x1, y1 = view.bbox
    tol = 0.02 * (y1 - y0)
    for s in view.strokes:
        (ax, ay), (bx, by) = s.pts[0], s.pts[-1]
        if abs(ay - y0) < tol and abs(by - y0) < tol and abs(bx - ax) > 0.85 * (x1 - x0):
            return "elevation"
    return "unknown"


def classify_views(sheet, labels):
    used = set()
    for v in sheet.views:
        cands = [(sc, i, lb) for i, lb in enumerate(labels)
                 if i not in used and (sc := _title_score(v, lb)) is not None]
        if cands:
            # prefer labels that name a view; among those the nearest
            named = [c for c in cands if parse_title(c[2].text)[0]] or cands
            sc, i, lb = min(named, key=lambda c: c[0])
            used.add(i)
            v.title = re.sub(r"\s+", " ", lb.text).strip()
            kind, facing = parse_title(lb.text)
            v.kind, v.facing = kind or guess_kind(v), facing
        else:
            v.kind = guess_kind(v)
    return sheet


def absolute_facing(facing, front="S"):
    """Compass bearing (degrees) a facade faces. Relative names need the front's direction:
    the right facade is on your right when you face the front, i.e. front - 90 degrees."""
    if facing in COMPASS:
        return COMPASS[facing]
    base = COMPASS.get(front, 180)
    rel = {"front": 0, "back": 180, "right": -90, "left": 90}.get(facing)
    return None if rel is None else (base + rel) % 360


def display_name(v: View, lang="en"):
    """The title as written on the sheet; untitled views get a generic name in the UI language."""
    if v.title:
        return v.title
    from .i18n import t
    return f"{t('kind.' + v.kind, lang)} {v.id}"
