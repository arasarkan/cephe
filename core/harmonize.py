"""Make separately rendered facades look like one building: match each material's color (and the sky)
to the hero facade.

Only hue/chroma (Lab a, b) of materials is matched, not lightness: a facade in shade must stay darker
than the sunlit one. The sky is matched fully, there is one sky."""
import numpy as np
from PIL import Image


def _srgb_to_lab(rgb):
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def _lab_to_srgb(lab):
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f > 0.2069, f ** 3, (f - 16 / 116) / 7.787) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])
    c = xyz @ m.T
    c = np.where(c > 0.0031308, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(c * 255, 0, 255)


def _resize_mask(mask, size):
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.NEAREST)) > 127


MATERIAL_SPREAD = 14.0  # Lab a/b distance at which a pixel stops counting as "the material"


def _stats(lab, mask):
    px = lab[mask]
    return (px.mean(0), px.std(0) + 1e-3) if len(px) > 200 else None


def _dominant_ab(lab, mask):
    """The material's own a/b color in a zone: median of the pixels near the zone's median, so bands,
    sills and windows inside the zone don't pull it. Returns ((a, b), count) or None."""
    px = lab[mask][:, 1:]
    if len(px) < 200:
        return None
    center = np.median(px, 0)
    near = px[np.hypot(*(px - center).T) < MATERIAL_SPREAD]
    if len(near) < 100:
        return None
    return np.median(near, 0), len(near)


def regions(z):
    """Comparable regions of a view from geometry.zones(): sky, each material group, plain wall."""
    building = z["building"]
    claimed = np.zeros_like(building)
    out = {"sky": z["sky"]}
    for g, area in z["areas"].items():
        out[f"mat:{g}"] = area
        claimed |= area
    out["wall"] = building & ~claimed
    return out


def material_ok(image_path, area, expected_rgb, tol=40):
    """Did a material come out roughly in its expected color (hue/chroma)? Used to skip harmonizing
    toward a hero facade where the model missed the material."""
    img = np.asarray(Image.open(image_path).convert("RGB"), np.float64)
    m = _resize_mask(area, (img.shape[1], img.shape[0]))
    if m.sum() < 200:
        return False
    got = _srgb_to_lab(img[m].mean(0)[None, None, :])[0, 0]
    want = _srgb_to_lab(np.array(expected_rgb, np.float64)[None, None, :])[0, 0]
    return float(np.hypot(got[1] - want[1], got[2] - want[2])) < tol


def shade_grade(image_path, building_mask, out_path, darken=0.64, cool=8.0, chroma=0.8, ground=0.18):
    """A facade on the shadow side gets only skylight: the building clearly darker, cooler and less
    saturated, and the ground just in front of it in its shadow (soft-edged), while the sky and the sunlit
    surroundings stay as they are. The model tends to light every facade evenly; this makes the one-sun
    logic read across the set."""
    from scipy import ndimage
    img = np.asarray(Image.open(image_path).convert("RGB"), np.float64)
    H, W = img.shape[:2]
    b = _resize_mask(building_mask, (W, H))
    shade = ndimage.gaussian_filter(b.astype(np.float64), max(1.5, W / 800))
    rows = np.flatnonzero(b.any(1))
    cols = np.flatnonzero(b.any(0))
    if rows.size:  # the building's own shadow on the ground in front: fades with distance, soft at the sides
        y0, depth = rows[-1], max(1, int(ground * (rows[-1] - rows[0])))
        ys = np.arange(y0, min(H, y0 + depth))
        g = np.zeros((H, W))
        g[ys[:, None], cols[None, :]] = (1 - (ys - y0) / depth)[:, None] * 0.75
        shade = np.maximum(shade, ndimage.gaussian_filter(g, W / 120))
    lab = _srgb_to_lab(img)
    lab[..., 0] *= 1 - (1 - darken) * shade
    lab[..., 1:] *= (1 - (1 - chroma) * shade)[..., None]
    lab[..., 2] -= cool * shade
    Image.fromarray(np.clip(_lab_to_srgb(lab), 0, 255).astype(np.uint8)).save(out_path)


def harmonize(image_path, view_regions, hero_image_path, hero_regions, out_path, strength=0.8, skip=()):
    img = np.asarray(Image.open(image_path).convert("RGB"), np.float64)
    hero = np.asarray(Image.open(hero_image_path).convert("RGB"), np.float64)
    lab, hlab = _srgb_to_lab(img), _srgb_to_lab(hero)
    H, W = lab.shape[:2]
    result = lab.copy()
    for name, mask in view_regions.items():
        if name not in hero_regions or name in skip:
            continue
        m = _resize_mask(mask, (W, H))
        hm = _resize_mask(hero_regions[name], (hero.shape[1], hero.shape[0]))
        if name == "sky":
            s, hs = _stats(lab, m), _stats(hlab, hm)
            if s is None or hs is None:
                continue
            for c in (0, 1, 2):
                target = (lab[..., c] - s[0][c]) * (hs[1][c] / s[1][c]) + hs[0][c]
                result[..., c] = np.where(m, lab[..., c] + strength * (target - lab[..., c]), result[..., c])
            continue
        # A material zone also holds things that aren't the material (a band crossing brick, sills, frames).
        # Match only the material itself: its dominant color, shifted (not stretched) toward the hero's, and
        # applied only to pixels near that color, so a beige band in a brick zone stays beige.
        own, ref = _dominant_ab(lab, m), _dominant_ab(hlab, hm)
        if own is None or ref is None:
            continue
        center, _ = own
        dist = np.hypot(lab[..., 1] - center[0], lab[..., 2] - center[1])
        weight = np.where(m, np.exp(-(dist / MATERIAL_SPREAD) ** 2), 0.0)
        for c, (a, b) in zip((1, 2), zip(center, ref[0])):
            result[..., c] += strength * weight * (b - a)
    # feather the edits a little so region borders don't show
    from scipy import ndimage
    blended = _lab_to_srgb(result)
    diff = ndimage.gaussian_filter(blended - img, sigma=(1.5, 1.5, 0))
    Image.fromarray(np.clip(img + diff, 0, 255).astype(np.uint8)).save(out_path)
