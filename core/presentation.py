"""Presentation sheet: all rendered facades on one A3 landscape page at the same scale, with titles and a
scale bar. Saved as PNG and PDF."""
import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .i18n import t

A3_MM = (420, 297)
DPI = 200
FONTS = [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf", "DejaVuSans.ttf"]
FONTS_BOLD = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf", "DejaVuSans-Bold.ttf"]


def _font(size, bold=False):
    for f in FONTS_BOLD if bold else FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _pack(sizes, width, gap):
    """Shelf-pack (w, h) boxes in order into rows of `width`. Returns ([(x, y)], total height)."""
    pos, x, y, row_h = [], 0, 0, 0
    for w, h in sizes:
        if x > 0 and x + w > width:
            x, y, row_h = 0, y + row_h + gap, 0
        pos.append((x, y))
        x += w + gap
        row_h = max(row_h, h)
    return pos, y + row_h


def make_sheet(items, project_name, out_png, units_per_m, lang="en"):
    """items: [{"image": path, "title": str, "px_per_unit": float}] in display order. All images are
    drawn at one common scale (px per meter on the sheet)."""
    W, H = (round(mm / 25.4 * DPI) for mm in A3_MM)
    margin, header, caption, gap = 90, 150, 70, 60
    area_w, area_h = W - 2 * margin, H - 2 * margin - header - 90
    imgs = [Image.open(it["image"]).convert("RGB") for it in items]
    # meters each image covers -> find the largest sheet scale (px/m) at which everything fits
    meters = [(im.width / it["px_per_unit"] / units_per_m * 1.0, im.height / it["px_per_unit"] / units_per_m)
              for im, it in zip(imgs, items)]
    lo, hi = 1.0, 2000.0
    for _ in range(40):
        s = (lo + hi) / 2
        sizes = [(int(mw * s), int(mh * s) + caption) for mw, mh in meters]
        if max(w for w, _ in sizes) <= area_w and _pack(sizes, area_w, gap)[1] <= area_h:
            lo = s
        else:
            hi = s
    s = lo
    sizes = [(int(mw * s), int(mh * s)) for mw, mh in meters]
    pos, used_h = _pack([(w, h + caption) for w, h in sizes], area_w, gap)

    sheet = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(sheet)
    d.text((margin, margin), project_name, font=_font(64, True), fill=(30, 30, 30))
    date = f"{dt.date.today():%d.%m.%Y}" if lang == "tr" else f"{dt.date.today():%d %B %Y}"
    d.text((margin, margin + 80), f"{t('sheet_subtitle', lang)}  ·  {date}", font=_font(32),
           fill=(110, 110, 110))
    d.line([(margin, margin + header - 20), (W - margin, margin + header - 20)], fill=(200, 200, 200), width=3)
    # center the block of rows horizontally per row and vertically in the area
    top = margin + header + (area_h - used_h) // 2
    rows = {}
    for (x, y), (w, h) in zip(pos, sizes):
        rows.setdefault(y, []).append(x + w)
    for im, it, (x, y), (w, h) in zip(imgs, items, pos, sizes):
        shift = (area_w - max(rows[y])) // 2
        X, Y = margin + shift + x, top + y
        sheet.paste(im.resize((w, h), Image.LANCZOS), (X, Y))
        f = _font(34, True)
        tw = d.textlength(it["title"], font=f)
        d.text((X + (w - tw) / 2, Y + h + 16), it["title"], font=f, fill=(40, 40, 40))
    # scale bar: a round number of meters about 1/8 of the sheet width
    bar_m = next(m for m in (1, 2, 5, 10, 20, 50, 100) if m * s >= W / 16)
    bx, by = W - margin - int(bar_m * s), H - margin - 30
    for i in range(5):
        x0 = bx + int(i * bar_m * s / 5)
        d.rectangle([x0, by, bx + int((i + 1) * bar_m * s / 5), by + 14],
                    fill=(40, 40, 40) if i % 2 == 0 else (250, 250, 248), outline=(40, 40, 40), width=2)
    f = _font(26)
    d.text((bx - 8, by - 40), "0", font=f, fill=(40, 40, 40))
    d.text((bx + int(bar_m * s) - 30, by - 40), f"{bar_m} m", font=f, fill=(40, 40, 40))
    out_png = Path(out_png)
    sheet.save(out_png)
    sheet.save(out_png.with_suffix(".pdf"), resolution=DPI)
    return out_png, out_png.with_suffix(".pdf")
