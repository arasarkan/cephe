"""Geometry on the sheet: separating drawings, framing a view at a common scale, rasterizing lines and
locating material zones in the raster."""
import math

from .sheet import View

# room around a facade, as a fraction of its size: (left, top, right, bottom) - sky above, ground below
MARGIN = (0.08, 0.22, 0.08, 0.14)


def extents(items):
    return (min(s.bbox[0] for s in items), min(s.bbox[1] for s in items),
            max(s.bbox[2] for s in items), max(s.bbox[3] for s in items))


def drop_frames(strokes):
    """Remove title-block frames: single strokes spanning most of the whole sheet."""
    x0, y0, x1, y1 = extents(strokes)
    area = (x1 - x0) * (y1 - y0) or 1
    keep = [s for s in strokes if (s.bbox[2] - s.bbox[0]) * (s.bbox[3] - s.bbox[1]) < 0.35 * area]
    return keep if len(keep) > 0.5 * len(strokes) else strokes


def _components(strokes, grid=4000, pad=2):
    """Group strokes that touch or nearly touch: rasterize onto a grid of `grid` cells across the longest
    side, grow by `pad` cells, label connected regions. Returns [[strokes]]."""
    import numpy as np
    from scipy import ndimage
    x0, y0, x1, y1 = extents(strokes)
    span = max(x1 - x0, y1 - y0) or 1
    cell = span / grid
    nx, ny = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    occ = np.zeros((ny, nx), bool)
    first = []
    for s in strokes:
        p = np.asarray(s.pts, np.float64)
        seg = np.hypot(*np.diff(p, axis=0).T) if len(p) > 1 else np.zeros(0)
        pts = [p[:1]]
        for (a, b), L in zip(zip(p, p[1:]), seg):
            t = np.linspace(0, 1, max(2, int(L / cell) + 2))[:, None]
            pts.append(a + (b - a) * t)
        q = np.concatenate(pts)
        cx = np.clip(((q[:, 0] - x0) / cell).astype(int), 0, nx - 1)
        cy = np.clip(((q[:, 1] - y0) / cell).astype(int), 0, ny - 1)
        occ[cy, cx] = True
        first.append((cy[0], cx[0]))
    grown = ndimage.binary_dilation(occ, np.ones((2 * pad + 1, 2 * pad + 1), bool))
    labels, _ = ndimage.label(grown)
    groups = {}
    for s, (cy, cx) in zip(strokes, first):
        groups.setdefault(labels[cy, cx], []).append(s)
    return list(groups.values())


def _frame_segments(group, box=None):
    """Per stroke: is it a frame line of this box - along an edge, or a divider straight across it?"""
    x0, y0, x1, y1 = box or extents(group)
    w, h = (x1 - x0) or 1, (y1 - y0) or 1
    tol = 0.01 * max(w, h)
    out = []
    for s in group:
        total = edge = 0.0
        for (ax, ay), (bx, by) in zip(s.pts, s.pts[1:]):
            L = math.hypot(bx - ax, by - ay)
            total += L
            on_edge = ((abs(ax - x0) < tol and abs(bx - x0) < tol) or (abs(ax - x1) < tol and abs(bx - x1) < tol)
                       or (abs(ay - y0) < tol and abs(by - y0) < tol) or (abs(ay - y1) < tol and abs(by - y1) < tol))
            across = (abs(ax - bx) < tol and abs(by - ay) > 0.8 * h) or (abs(ay - by) < tol and abs(bx - ax) > 0.8 * w)
            if on_edge or across:
                edge += L
        out.append((s, total, edge))
    return out


def _is_frame(group):
    """A sheet frame, panel dividers or a title-block table: most of its line length runs along the edges
    of its own box or straight across it."""
    segs = _frame_segments(group)
    total = sum(t for _, t, _ in segs)
    return total > 0 and sum(e for _, _, e in segs) / total > 0.5


def _overlap(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _inside(a, b):
    return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


def _peel_frames(groups):
    """A piece whose box holds two or more sizeable drawings is a sheet (frame, dividers, title block, maybe
    drawings touching the frame), not a drawing: strip its long frame lines and split what's left again."""
    for _ in range(4):
        boxes = [extents(g) for g in groups]
        changed = False
        for i, g in enumerate(groups):
            held = [j for j, b in enumerate(boxes) if j != i and _inside(b, boxes[i])
                    and 0 < 0.02 * _area(boxes[i]) <= _area(b) <= 0.3 * _area(boxes[i])]
            if len(held) < 2:
                continue
            x0, y0, x1, y1 = boxes[i]
            long_side = 0.5 * min(x1 - x0, y1 - y0)
            rest = [s for s, total, edge in _frame_segments(g) if not (edge > 0.5 * total and edge >= long_side)]
            groups = groups[:i] + groups[i + 1:] + (_components(rest) if rest else [])
            changed = True
            break
        if not changed:
            break
    return groups


def _area(bb):
    return max(0.0, bb[2] - bb[0]) * max(0.0, bb[3] - bb[1])


def _belongs(small, big):
    """Is `small` a piece of the drawing `big` (furniture inside a plan, a roof part just above a facade)
    rather than a drawing of its own next to it?"""
    if _inside(small, big):  # inner walls inside a plan outline, furniture, panes
        return True
    if _area(small) >= 0.25 * _area(big):  # a drawing of similar size beside it is a neighbor, never a piece
        return False
    ix = min(small[2], big[2]) - max(small[0], big[0])
    iy = min(small[3], big[3]) - max(small[1], big[1])
    if ix > 0 and iy > 0 and ix * iy >= 0.3 * _area(small):
        return True
    gap = max(small[0] - big[2], big[0] - small[2], small[1] - big[3], big[1] - small[3])
    return gap < 0.03 * max(big[2] - big[0], big[3] - big[1])


def split_views(strokes, min_share=0.04):
    """Find separate drawings in model space. Returns [(bbox, [strokes])], largest first.

    Real sheets put many drawings close together inside a frame with a title block, sometimes several sheets
    far apart in one file. So: split finely (per far-apart cluster, so one stray entity doesn't coarsen the
    grid), drop frames and title-block tables, then put each drawing's loose pieces back together."""
    groups = []
    for cluster in _components(strokes, grid=400, pad=4):
        groups += _peel_frames(_components(cluster)) if len(cluster) > 1 else [cluster]
    if len(groups) > 1:
        # Frames: edge-dominated pieces holding two or more drawings that are each much smaller than the frame.
        # (A window outline holds its pane, a plain plan outline its inner walls: one big piece, not a sheet.)
        bxs = [extents(g) for g in groups]
        holds = [sum(1 for j, b in enumerate(bxs) if j != i and _overlap(b, bxs[i]) >= 0.5 * _area(b)
                     and 0 < 0.01 * _area(bxs[i]) <= _area(b) <= 0.3 * _area(bxs[i])) for i in range(len(groups))]
        kept = [g for g, n in zip(groups, holds) if not (n >= 2 and _is_frame(g) and len(g) < 0.5 * len(strokes))]
        groups = kept or groups
    # Merge loose pieces into the drawing they belong to. Pieces are judged against each drawing's original
    # box, not its grown one: otherwise a drawing that takes in a ground line reaches its neighbor and swallows
    # it, and the whole row snowballs into one view.
    cores = [extents(g) for g in groups]
    owner = list(range(len(groups)))
    order = sorted(range(len(groups)), key=lambda i: _area(cores[i]), reverse=True)
    for si in reversed(order):  # smallest pieces first, each to the best (largest) core it belongs to
        for bi in order:
            if bi != si and owner[bi] == bi and _area(cores[si]) <= _area(cores[bi]) and _belongs(cores[si], cores[bi]):
                owner[si] = bi
                break
    merged = {}
    for i, g in enumerate(groups):
        root = i
        while owner[root] != root:
            root = owner[root]
        merged.setdefault(root, []).extend(g)
    views = sorted(((extents(g), g) for g in merged.values()), key=lambda v: _area(v[0]), reverse=True)
    biggest = _area(views[0][0]) if views else 1
    return [v for v in views if _area(v[0]) >= min_share * biggest]


def padded(view: View, margin=MARGIN):
    x0, y0, x1, y1 = view.bbox
    w, h = (x1 - x0) or 1, (y1 - y0) or 1
    l, t, r, b = margin
    return x0 - l * w, y0 - b * h, x1 + r * w, y1 + t * h


def common_scale(views, megapixels=1.0, margin=MARGIN):
    """Pixels per drawing unit shared by all views, so the same window is the same size in every
    render: the largest padded view gets ~`megapixels`."""
    areas = []
    for v in views:
        X0, Y0, X1, Y1 = padded(v, margin)
        areas.append((X1 - X0) * (Y1 - Y0))
    return math.sqrt(megapixels * 1024 * 1024 / max(areas))


def effective_scale(view: View, scale, margin=MARGIN, min_side=512):
    """The px/unit a view is actually drawn at: `scale`, unless the view would be too small to render."""
    X0, Y0, X1, Y1 = padded(view, margin)
    if min((X1 - X0) * scale, (Y1 - Y0) * scale) < min_side:
        return min_side / min(X1 - X0, Y1 - Y0)
    return scale


def frame(view: View, scale, margin=MARGIN, min_side=512):
    """Image size and drawing->pixel mapping for a view at `scale` px/unit. Sizes are multiples of 16
    (the model's patch grid); tiny views are scaled up to `min_side` (they are rare: details)."""
    X0, Y0, X1, Y1 = padded(view, margin)
    s = effective_scale(view, scale, margin, min_side)
    W = max(256, int(round((X1 - X0) * s / 16)) * 16)
    H = max(256, int(round((Y1 - Y0) * s / 16)) * 16)
    ox, oy = (W - (X1 - X0) * s) / 2, (H - (Y1 - Y0) * s) / 2

    def to_px(x, y, k=1):
        return ((ox + (x - X0) * s) * k, (H - (oy + (y - Y0) * s)) * k)
    return W, H, to_px


def rasterize(view: View, scale, margin=MARGIN, heavy_px=2, light_px=1, supersample=2):
    """Draw a view as white lines on black (ControlNet input). Returns (control, preview) PIL images."""
    from PIL import Image, ImageDraw, ImageOps
    W, H, to_px = frame(view, scale, margin)
    ss = supersample
    img = Image.new("L", (W * ss, H * ss), 0)
    d = ImageDraw.Draw(img)
    for st in sorted(view.strokes, key=lambda st: st.heavy):
        d.line([to_px(x, y, ss) for x, y in st.pts], fill=255,
               width=(heavy_px if st.heavy else light_px) * ss, joint="curve")
    img = img.resize((W, H), Image.LANCZOS).point(lambda v: 255 if v > 60 else 0)
    return img.convert("RGB"), ImageOps.invert(img).convert("RGB")


def zones(view: View, control, scale, groups, colors, margin=MARGIN):
    """Where things are in the raster of a view.
    groups: {hatch group id: material key} for the groups to place. colors: {key: rgb} for the preview.
    Returns dict with
      preview  flat-color picture (sky, ground, wall, glass, frames, materials) for the user to check
      masks    {group id: soft mask image} for the regional prompts
      rest     soft mask of everything no group claims (sky, ground, plain wall)
      sky, building  bool arrays (for color harmonizing)"""
    import numpy as np
    from PIL import Image, ImageDraw
    from scipy import ndimage

    W, H, to_px = frame(view, scale, margin)
    lines = np.asarray(control.convert("L")) > 0
    closed = ndimage.binary_dilation(lines, iterations=1)  # close 1 px gaps so rooms stay closed
    labels, n = ndimage.label(~closed)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    exterior = np.isin(labels, list(border))
    ground_y = int(round(to_px(view.bbox[0], view.bbox[1])[1]))  # lowest drawn line = ground
    yy = np.arange(H)[:, None].repeat(W, 1)
    sky = exterior & (yy < ground_y)

    out = np.zeros((H, W, 3), np.float32)
    out[:] = colors["wall"]
    t = (yy / max(1, ground_y))[..., None]  # sky gradient: deeper blue at the top
    out = np.where(sky[..., None], np.array(colors["sky"], np.float32) * (0.85 + 0.15 * t), out)
    out[exterior & (yy >= ground_y)] = colors["ground"]

    # small closed cells inside the building: panes -> glass, thin rings -> frames
    interior_area = max(1, int((~exterior & ~closed).sum()))
    sizes = ndimage.sum(np.ones_like(labels), labels, index=np.arange(n + 1))
    kind = np.zeros(n + 1, np.uint8)  # 0 wall, 1 glass, 2 frame
    min_dim = max(6, W // 150)
    for i, sl in enumerate(ndimage.find_objects(labels), 1):
        if sl is None or i in border or sizes[i] >= 0.015 * interior_area:
            continue
        hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        fill = sizes[i] / (hh * ww)
        if fill < 0.35:
            kind[i] = 2
        elif min(hh, ww) >= min_dim and max(hh, ww) / min(hh, ww) < 6:  # long thin cells: canopies, sills
            kind[i] = 1
    k = kind[labels]
    wall_px = ~exterior & (k == 0)

    areas = {}
    for h in view.hatches:
        if h.group not in groups:
            continue
        mask = Image.new("1", (W, H), 0)
        for poly in h.polys:  # XOR the loops: islands inside a hatch become holes (even-odd)
            m = Image.new("1", (W, H), 0)
            ImageDraw.Draw(m).polygon([to_px(x, y) for x, y in poly], fill=1)
            mask = Image.frombytes("1", (W, H), bytes(a ^ b for a, b in zip(mask.tobytes(), m.tobytes())))
        area = np.asarray(mask, bool) & ~exterior
        if area.any():
            areas[h.group] = areas.get(h.group, np.zeros_like(area)) | area
            out[area & wall_px] = colors.get(groups[h.group], colors["other"])
    out[k == 1] = colors["glass"]
    out[k == 2] = colors["frame"]
    idx = ndimage.distance_transform_edt(closed, return_distances=False, return_indices=True)
    out = out[idx[0], idx[1]]  # lines take the color of the nearest non-line pixel

    sigma = max(1.5, W / 500)
    soft = {g: ndimage.gaussian_filter(a.astype(np.float32), sigma) for g, a in areas.items()}
    rest = np.clip(1 - sum(soft.values()), 0, 1) if soft else np.ones((H, W), np.float32)
    to_img = lambda a: Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))  # noqa: E731
    return {"preview": Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)),
            "masks": {g: to_img(a) for g, a in soft.items()}, "rest": to_img(rest),
            "areas": areas, "sky": sky, "building": ~exterior}
