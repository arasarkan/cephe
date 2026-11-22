"""Does the render follow the drawing? A check per facade, done with the drawing's own lines.

For every line of the drawing we look across it in the render: a line the render follows shows up as an
edge right on the line (within a couple of pixels), clearly stronger than the texture just beside it.
Brick, stone or noise beside a line give edges in every direction, so they don't count as following it.

    score   share of the drawing's line length the render follows (0..1)
    misses  stretches of drawn lines the render lost or moved, in image pixels, for the drift map

Measured at the first-pass resolution (~1 MP): this is about geometry, not fine texture.
"""
import warnings

import numpy as np

from . import geometry

STEP = 2.0          # px between samples along a line
ON = 2              # px either side of the line still counted as "on" it
OFF = (5, 6, 7, 8)  # px either side where the texture beside the line is measured
PARTNER = 7         # px: a parallel drawn line this close makes the two one band (see check)
RATIO = 1.6         # an edge on the line must be this much stronger than beside it ...
FLOOR = 0.035       # ... and at least this strong (luminance 0..1, Sobel / 8)
WINDOW = 7          # samples smoothed along a line (~14 px), so single noisy samples don't decide
GOOD, FAIR = 0.90, 0.84  # from ~50 past renders (close double lines as bands): drifted or blurry 0.78-0.88, sharp 0.90-0.98


def _gradients(img, size):
    from PIL import Image
    from scipy import ndimage
    im = img.convert("RGB")
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    a = np.asarray(im, np.float32) / 255
    lum = ndimage.gaussian_filter(a @ np.array([0.299, 0.587, 0.114], np.float32), 0.8)
    return ndimage.sobel(lum, 1) / 8, ndimage.sobel(lum, 0) / 8  # d/dx, d/dy


def _samples(view, scale):
    """Points along every drawn line, with the line's normal: arrays x, y, nx, ny, line id."""
    W, H, to_px = geometry.frame(view, scale)
    xs, ys, nxs, nys, ids = [], [], [], [], []
    for k, st in enumerate(view.strokes):
        pts = np.array([to_px(x, y) for x, y in st.pts], np.float64)
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            L = np.hypot(bx - ax, by - ay)
            if L < 2 * STEP:
                continue
            t = np.arange(STEP / 2, L, STEP) / L
            xs.append(ax + (bx - ax) * t)
            ys.append(ay + (by - ay) * t)
            nxs.append(np.full(t.size, -(by - ay) / L))
            nys.append(np.full(t.size, (bx - ax) / L))
            ids.append(np.full(t.size, k))
    if not xs:
        return (W, H), *(np.zeros(0) for _ in range(5))
    return (W, H), *(np.concatenate(v) for v in (xs, ys, nxs, nys, ids))


def check(view, scale, render):
    """render: PIL image of the facade (any resolution, same framing as the control image)."""
    from scipy import ndimage
    size, x, y, nx, ny, ids = _samples(view, scale)
    W, H = size
    inside = (x > OFF[-1]) & (x < W - OFF[-1]) & (y > OFF[-1]) & (y < H - OFF[-1])
    x, y, nx, ny, ids = x[inside], y[inside], nx[inside], ny[inside], ids[inside]
    if x.size == 0:
        return {"score": 1.0, "misses": [], "samples": 0}
    gx, gy = _gradients(render, size)

    def across(d):
        px, py = x + nx * d, y + ny * d
        c = [py, px]
        return np.abs(ndimage.map_coordinates(gx, c, order=1) * nx + ndimage.map_coordinates(gy, c, order=1) * ny)

    on = np.max([across(d) for d in range(-ON, ON + 1)], axis=0)
    control, _ = geometry.rasterize(view, scale)
    lines = np.asarray(control.convert("L")) > 0
    near_line = ndimage.distance_transform_edt(~lines)
    # Two drawn lines a few px apart (a band, a frame, a sill) often come out as one band with one strong
    # edge: an edge anywhere between this line and its close neighbor counts for both.
    reach = np.arange(-PARTNER, PARTNER + 1)
    for s in (-1, 1):
        partner = np.zeros(x.size)
        for d in range(PARTNER, ON, -1):  # nearest partner wins
            hitp = ndimage.map_coordinates(lines.astype(np.float32), [y + ny * d * s, x + nx * d * s], order=0) > 0
            partner = np.where(hitp, d, partner)
        if partner.any():
            band = np.max([np.where((partner >= abs(d)) & (np.sign(d) == s), across(d), 0)
                           for d in reach if d * s > ON], axis=0)
            on = np.maximum(on, band)
    # beside the line, but not where another drawn line runs (double frame lines, mullions)
    off_vals = []
    for d in OFF:
        for s in (-1, 1):
            px, py = x + nx * d * s, y + ny * d * s
            v = across(d * s)
            clear = ndimage.map_coordinates(near_line, [py, px], order=0) > ON
            off_vals.append(np.where(clear, v, np.nan))
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN where lines crowd: no texture to compare
        off = np.nanmedian(np.array(off_vals), axis=0)
    off = np.where(np.isnan(off), 0, off)
    hit = (on > FLOOR) & (on > RATIO * off)

    # smooth along each line, then join consecutive misses into stretches
    ok = np.zeros(hit.size, bool)
    misses = []
    for k in np.unique(ids):
        idx = np.flatnonzero(ids == k)
        h = hit[idx].astype(np.float32)
        sm = ndimage.uniform_filter1d(h, min(WINDOW, h.size), mode="nearest") >= 0.5
        ok[idx] = sm
        run = []
        for i, good in zip(idx, sm):
            if not good:
                run.append(i)
            elif run:
                misses.append(run)
                run = []
        if run:
            misses.append(run)
    stretches = [[(float(x[i]), float(y[i])) for i in r] for r in misses if len(r) * STEP >= 10]
    return {"score": float(ok.mean()), "misses": stretches, "samples": int(x.size)}


def grade(score):
    return "good" if score >= GOOD else "fair" if score >= FAIR else "poor"


def drift_map(render, misses, size, out):
    """The render, dimmed, with the stretches of drawing it didn't follow in red."""
    from PIL import ImageDraw, ImageEnhance
    im = render.convert("RGB")
    k = im.width / size[0]
    im = ImageEnhance.Brightness(ImageEnhance.Color(im).enhance(0.35)).enhance(0.75)
    d = ImageDraw.Draw(im)
    w = max(3, int(round(3 * k)))
    for run in misses:
        pts = [(px * k, py * k) for px, py in run]
        if len(pts) == 1:
            pts = pts * 2
        d.line(pts, fill=(255, 40, 40), width=w, joint="curve")
    im.save(out)
    return out
