"""Common data model. Every input adapter (DWG/DXF now, PDF/image later) produces a Sheet."""
from dataclasses import dataclass, field

KINDS = ("elevation", "section", "plan", "unknown")


@dataclass
class Stroke:
    pts: list            # [(x, y), ...] polyline in drawing units
    heavy: bool = False  # thick line (lineweight >= 0.4 mm)
    bbox: tuple = None

    def __post_init__(self):
        if self.bbox is None:
            xs, ys = [p[0] for p in self.pts], [p[1] for p in self.pts]
            self.bbox = (min(xs), min(ys), max(xs), max(ys))


@dataclass
class Hatch:
    polys: list          # boundary loops [[(x, y), ...], ...] (even-odd)
    pattern: str
    layer: str
    group: str = ""      # material group id, shared by all hatches with the same layer + pattern
    bbox: tuple = None

    def __post_init__(self):
        if self.bbox is None:
            xs = [x for p in self.polys for x, _ in p]
            ys = [y for p in self.polys for _, y in p]
            self.bbox = (min(xs), min(ys), max(xs), max(ys))


@dataclass
class Label:
    text: str
    x: float
    y: float
    height: float = 0.0


@dataclass
class View:
    id: int
    bbox: tuple
    strokes: list
    hatches: list = field(default_factory=list)
    title: str = ""          # as written on the sheet, e.g. "KUZEY CEPHESİ 1/100"
    kind: str = "unknown"    # one of KINDS
    facing: str = None       # "N", "NE", ... absolute, or "front"/"back"/"left"/"right"/"side"

    @property
    def width(self):
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self):
        return self.bbox[3] - self.bbox[1]


@dataclass
class Sheet:
    source: str
    units_per_m: float       # drawing units in one meter (1000 for mm, 100 for cm, 1 for m)
    views: list
    warnings: list = field(default_factory=list)

    def elevations(self):
        return [v for v in self.views if v.kind == "elevation"]
