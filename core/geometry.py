"""Geometry on the sheet: separating drawings, framing a view at a common scale, rasterizing lines and
locating material zones in the raster."""
import math
from collections import deque

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


def split_views(strokes, grid=500, gap=0.012, min_share=0.04):
    """Find separate drawings in model space: rasterize to a coarse grid, close small gaps, label
    connected regions. Returns [(bbox, [strokes])], largest first."""
    x0, y0, x1, y1 = extents(strokes)
    span = max(x1 - x0, y1 - y0) or 1
    cell = span / grid
    nx, ny = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    pad = max(1, int(gap * grid))
    occ = bytearray(nx * ny)

    def mark(px, py):
        for gx in range(max(0, px - pad), min(nx, px + pad + 1)):
            for gy in range(max(0, py - pad), min(ny, py + pad + 1)):
                occ[gy * nx + gx] = 1

    cells_of = []
    for s in strokes:
        cs = set()
        for (ax, ay), (bx, by) in zip(s.pts, s.pts[1:]):
            n = max(1, int(math.hypot(bx - ax, by - ay) / cell))
            for k in range(n + 1):
                cs.add((int((ax + (bx - ax) * k / n - x0) / cell), int((ay + (by - ay) * k / n - y0) / cell)))
        for c in cs:
            mark(*c)
        cells_of.append(next(iter(cs)))

    label = [0] * (nx * ny)
    n_labels = 0
    for start in range(nx * ny):
        if occ[start] and not label[start]:
            n_labels += 1
            label[start] = n_labels
            q = deque([start])
            while q:
                i = q.popleft()
                x = i % nx
                for j in (i - 1 if x > 0 else -1, i + 1 if x < nx - 1 else -1, i - nx, i + nx):
                    if 0 <= j < nx * ny and occ[j] and not label[j]:
                        label[j] = n_labels
                        q.append(j)
    groups = {}
    for s, (cx, cy) in zip(strokes, cells_of):
        groups.setdefault(label[cy * nx + cx], []).append(s)
    views = [(extents(g), g) for g in groups.values()]
    views.sort(key=lambda v: (v[0][2] - v[0][0]) * (v[0][3] - v[0][1]), reverse=True)
    biggest = (views[0][0][2] - views[0][0][0]) * (views[0][0][3] - views[0][0][1]) if views else 1
    return [v for v in views if (v[0][2] - v[0][0]) * (v[0][3] - v[0][1]) >= min_share * biggest]


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
