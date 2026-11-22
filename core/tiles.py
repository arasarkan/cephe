"""Splitting a 2K image into overlapping ~1 MP tiles and blending them back without visible seams."""
import numpy as np
from PIL import Image


def grid(width, height, tile=1024, overlap=160):
    """Boxes (x0, y0, x1, y1) covering the image; tiles are `tile` px (multiples of 16), the last row/column
    is shifted inward so every tile is full size."""
    def starts(total):
        if total <= tile:
            return [0]
        n = int(np.ceil((total - overlap) / (tile - overlap)))
        step = (total - tile) / (n - 1)
        return [int(round(i * step / 16)) * 16 for i in range(n - 1)] + [total - tile]
    tw, th = min(tile, width), min(tile, height)
    xs = starts(width) if width > tile else [0]
    ys = starts(height) if height > tile else [0]
    return [(x, y, x + tw, y + th) for y in ys for x in xs]


def blend(size, pieces, overlap=160):
    """pieces: [(box, PIL image)] -> one image. Each tile fades out linearly over the overlap on sides that
    have a neighbor, so seams don't show."""
    W, H = size
    acc = np.zeros((H, W, 3), np.float64)
    wsum = np.zeros((H, W, 1), np.float64)
    for (x0, y0, x1, y1), im in pieces:
        a = np.asarray(im.convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS), np.float64)
        h, w = a.shape[:2]
        wx = np.ones(w)
        wy = np.ones(h)
        ramp = np.linspace(0, 1, overlap + 2)[1:-1]
        if x0 > 0:
            wx[:overlap] = np.minimum(wx[:overlap], ramp)
        if x1 < W:
            wx[-overlap:] = np.minimum(wx[-overlap:], ramp[::-1])
        if y0 > 0:
            wy[:overlap] = np.minimum(wy[:overlap], ramp)
        if y1 < H:
            wy[-overlap:] = np.minimum(wy[-overlap:], ramp[::-1])
        wgt = (wy[:, None] * wx[None, :])[..., None]
        acc[y0:y1, x0:x1] += a * wgt
        wsum[y0:y1, x0:x1] += wgt
    return Image.fromarray(np.clip(acc / np.maximum(wsum, 1e-6), 0, 255).astype(np.uint8))
