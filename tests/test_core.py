"""Core behavior without a GPU: reading, titles, facing, scale, materials, sun, presentation sheet."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import geometry, materials  # noqa: E402
from core.classify import absolute_facing, parse_title  # noqa: E402
from core.scene import Scene, light_on, storeys, view_prompt  # noqa: E402

SAMPLE_DXF = ROOT / "tests" / "_sample.dxf"


@pytest.fixture(scope="session")
def sheet():
    if not SAMPLE_DXF.exists():  # DXF: no ODA needed for the tests
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample.py"), str(SAMPLE_DXF)], check=True)
    from core.inputs import dwg
    return dwg.read(SAMPLE_DXF)


@pytest.mark.parametrize("text,kind,facing", [
    ("ÖN CEPHE 1/100", "elevation", "front"),
    ("Güney Cephesi", "elevation", "S"),
    ("KUZEYDOĞU CEPHESİ", "elevation", "NE"),
    ("BATI GÖRÜNÜŞ", "elevation", "W"),
    ("SAĞ YAN CEPHE", "elevation", "right"),
    ("YAN CEPHE", "elevation", "side"),
    ("NORTH ELEVATION", "elevation", "N"),
    ("A-A KESİTİ", "section", None),
    ("ZEMİN KAT PLANI", "plan", None),
    ("VAZİYET PLANI", "plan", None),
    ("ÖNERİLEN DETAY", None, None),  # 'ÖN' inside a word is not 'front'
])
def test_parse_title(text, kind, facing):
    assert parse_title(text) == (kind, facing)


def test_sample_views(sheet):
    got = {(v.kind, v.facing) for v in sheet.views}
    assert got == {("elevation", "front"), ("elevation", "back"), ("elevation", "right"),
                   ("elevation", "left"), ("section", None), ("plan", None)}
    assert sheet.units_per_m == 100.0  # cm


def test_relative_facing():
    assert absolute_facing("front", "S") == 180
    assert absolute_facing("back", "S") == 0
    assert absolute_facing("right", "S") == 90   # facing the south front, your right hand is east
    assert absolute_facing("left", "S") == 270
    assert absolute_facing("N", "S") == 0
    assert absolute_facing("side", "S") is None


def test_one_sun():
    assert light_on(180, "noon")[0] == "lit"         # south facade at noon
    assert light_on(0, "noon")[0] == "shade"         # north facade at noon
    assert light_on(90, "morning")[0] == "lit"         # east facade in the morning
    assert light_on(270, "sunset")[0] == "lit"    # west facade at sunset
    # morning sun (ESE) on the south facade comes from the viewer's left... standing south looking
    # north, east is on your right
    assert light_on(180, "morning")[0] == "right"
    assert light_on(180, "overcast")[0] == "overcast"


def test_common_scale_same_window_size(sheet):
    """The same 140 cm window must be the same number of pixels wide on every facade."""
    elevs = sheet.elevations()
    scale = geometry.common_scale(elevs, 1.0)
    widths = {round(geometry.effective_scale(v, scale) * 140, 1) for v in elevs}
    assert len(widths) == 1
    sizes = [geometry.frame(v, scale)[:2] for v in elevs]
    assert all(w % 16 == 0 and h % 16 == 0 for w, h in sizes)
    assert max(w * h for w, h in sizes) <= 1.1 * 1024 * 1024


def test_materials(sheet):
    groups = materials.groups_of(sheet)
    assert groups["TARAMA|BRICK"]["material"] == "brick"           # from the pattern name
    assert groups["TAS_KAPLAMA|ANSI31"]["material"] == "stone"     # from the layer name
    assert groups["TARAMA|BRICK"]["count"] == 4                    # one per elevation
    assert materials.words("brick", "yellow") == "buff yellow brick cladding"
    assert materials.words(materials.IGNORE, None) is None


def test_zones_cover_hatches(sheet):
    v = next(v for v in sheet.views if v.facing == "front")
    scale = geometry.common_scale([v], 1.0)
    control, _ = geometry.rasterize(v, scale)
    groups = {g: d["material"] for g, d in materials.groups_of(sheet).items()}
    z = geometry.zones(v, control, scale, groups, materials.preview_colors(materials.groups_of(sheet)))
    assert set(z["masks"]) == {"TARAMA|BRICK", "TAS_KAPLAMA|ANSI31"}
    assert z["sky"].mean() > 0.1 and z["building"].mean() > 0.2


def test_prompts(sheet):
    scene = Scene(time="noon", front="S")
    front = next(v for v in sheet.views if v.facing == "front")
    back = next(v for v in sheet.views if v.facing == "back")
    pf, lf = view_prompt(scene, front, sheet.units_per_m)
    pb, lb = view_prompt(scene, back, sheet.units_per_m)
    assert (lf, lb) == ("lit", "shade")
    assert storeys(front, sheet.units_per_m) == "four-storey"
    assert pf["subject"] == pb["subject"] and pf["wall"] == pb["wall"]
    assert pf["context"].split(", ")[:3] == pb["context"].split(", ")[:3]  # setting, season, sky
    assert "plaster" not in pf["subject"] + pf["context"]  # wall material stays in its own slot


def test_presentation_sheet(tmp_path):
    from PIL import Image
    from core.presentation import make_sheet
    items = []
    for i, (w, h) in enumerate([(800, 500), (500, 500), (800, 500), (500, 500)]):
        p = tmp_path / f"{i}.png"
        Image.new("RGB", (w, h), (200, 100, 80)).save(p)
        items.append({"image": p, "title": f"CEPHE {i}", "px_per_unit": 0.5})
    png, pdf = make_sheet(items, "Test Projesi", tmp_path / "pafta.png", 100.0)
    assert png.exists() and pdf.exists()


def test_i18n():
    from core.i18n import UserError, t
    from core.scene import options_for_ui
    assert t("done") == "Done" and t("done", "tr") == "Bitti" and t("done", "xx") == "Done"
    e = UserError("unsupported_type", ext=".pdf")
    assert ".pdf" in str(e) and "supported" in str(e) and "desteklenmiyor" in e.message("tr")
    assert options_for_ui("en")["time"]["sunset"] == "Sunset"
    assert options_for_ui("tr")["time"]["sunset"] == "Gün batımı"
    assert materials.catalog_for_ui("tr")["brick"]["name"] == "Tuğla"
    assert materials.catalog_for_ui()["brick"]["options"]["yellow"] == "Buff yellow"


def test_turkish_drawings_still_read_in_english_ui(sheet):
    """UI language is English, but Turkish titles and layer names are still understood."""
    from core.classify import display_name
    names = {display_name(v, "en") for v in sheet.views}
    assert "ÖN CEPHE 1/100" in names


def test_people_and_turkish_notes(sheet):
    """'çocuklar oyun oynasın' reached the model in Turkish and was ignored; it must become English words."""
    from core.scene import note_to_english
    assert note_to_english("evin ön cephesinde çocuklar oyun oynasın insanlar olsun") == \
        ["children playing", "people walking"]
    assert note_to_english("İNSANLAR ve ARABALAR") == ["people walking", "cars parked along the street"]
    assert note_to_english("") == []
    front = next(v for v in sheet.views if v.facing == "front")
    quiet, _ = view_prompt(Scene(people="none"), front, sheet.units_per_m)
    busy, _ = view_prompt(Scene(people="families", vehicles="parked"), front, sheet.units_per_m)
    assert "quiet city street" in quiet["context"] and "children" not in quiet["context"]
    assert "quiet" not in busy["context"] and "children playing" in busy["context"] and "cars" in busy["context"]
    noted, _ = view_prompt(Scene(people="none", note="çocuklar oynasın"), front, sheet.units_per_m)
    assert "quiet" not in noted["context"] and "children playing" in noted["context"]


def test_tiles_cover_and_blend_without_seams():
    """2K detail is done in ~1 MP tiles (one 4 MP pass smears); tiles must cover the image and blend
    back to the exact original where they agree."""
    import numpy as np
    from PIL import Image
    from core import tiles
    W, H = 2592, 1632
    boxes = tiles.grid(W, H)
    assert all((x1 - x0) == 1024 and (y1 - y0) == 1024 and x0 % 16 == 0 for x0, y0, x1, y1 in boxes)
    cover = np.zeros((H, W), bool)
    for x0, y0, x1, y1 in boxes:
        cover[y0:y1, x0:x1] = True
    assert cover.all() and len(boxes) == 6
    rng = np.random.default_rng(0)
    src = Image.fromarray(rng.integers(0, 255, (H, W, 3), dtype=np.uint8))
    out = tiles.blend((W, H), [(b, src.crop(b)) for b in boxes])
    assert np.abs(np.asarray(out, int) - np.asarray(src, int)).max() <= 1
    assert tiles.grid(800, 600) == [(0, 0, 800, 600)]


def test_fidelity_follows_drawing(sheet, tmp_path):
    """A render that is the drawing scores ~1; blurred or moved ones score low, and the misses show where."""
    from PIL import Image, ImageFilter, ImageOps
    from core import fidelity
    v = next(v for v in sheet.views if v.kind == "elevation")
    scale = geometry.common_scale([v], 1.0)
    control, _ = geometry.rasterize(v, scale)
    # a "photo" of the drawing: mid-grey surfaces, dark lines, plus texture noise everywhere
    import numpy as np
    rng = np.random.default_rng(0)
    base = np.asarray(ImageOps.invert(control.convert("L")), np.float32) * 0.6 + 60
    noisy = Image.fromarray(np.clip(base + rng.normal(0, 6, base.shape), 0, 255).astype(np.uint8))
    good = fidelity.check(v, scale, noisy)
    assert good["score"] > 0.95 and fidelity.grade(good["score"]) == "good"
    assert fidelity.check(v, scale, noisy.filter(ImageFilter.GaussianBlur(6)))["score"] < 0.3
    moved = noisy.transform(noisy.size, Image.AFFINE, (1, 0, 10, 0, 1, 10))  # 10 px off in x and y
    bad = fidelity.check(v, scale, moved)
    assert bad["score"] < fidelity.FAIR and len(bad["misses"]) > len(good["misses"])
    # works at 2K too (final renders are compared at the first-pass size)
    big = noisy.resize((noisy.width * 2, noisy.height * 2), Image.LANCZOS)
    assert fidelity.check(v, scale, big)["score"] > 0.9
    out = fidelity.drift_map(big, bad["misses"], control.size, tmp_path / "drift.png")
    assert Image.open(out).size == big.size


def test_harmonize_leaves_other_colors_in_a_material_zone(tmp_path):
    """A beige band crossing a brick zone stays beige; only the brick moves toward the hero's brick."""
    import numpy as np
    from PIL import Image
    from core.harmonize import _srgb_to_lab, harmonize
    img = np.zeros((200, 200, 3), np.uint8)
    img[:] = (190, 75, 45)          # brick
    img[95:105] = (225, 210, 180)   # beige band inside the brick zone
    hero = np.zeros_like(img)
    hero[:] = (175, 85, 60)         # the hero's brick: a bit browner
    Image.fromarray(img).save(tmp_path / "v.png")
    Image.fromarray(hero).save(tmp_path / "h.png")
    zone = np.ones((200, 200), bool)
    harmonize(tmp_path / "v.png", {"mat:B": zone}, tmp_path / "h.png", {"mat:B": zone}, tmp_path / "o.png")
    out = np.asarray(Image.open(tmp_path / "o.png").convert("RGB"), np.float64)
    lab = lambda a: _srgb_to_lab(np.asarray(a, np.float64)[None, None])[0, 0]  # noqa: E731
    band_before, band_after = lab(img[100, 100]), lab(out[100, 100])
    assert np.hypot(*(band_after[1:] - band_before[1:])) < 3
    brick_before, brick_after, target = lab(img[20, 20]), lab(out[20, 20]), lab(hero[20, 20])
    assert np.hypot(*(brick_after[1:] - target[1:])) < 0.5 * np.hypot(*(brick_before[1:] - target[1:]))


def test_shade_grade_darkens_the_building_not_the_surroundings(tmp_path):
    import numpy as np
    from PIL import Image
    from core.harmonize import shade_grade
    img = np.full((300, 400, 3), 200, np.uint8)
    Image.fromarray(img).save(tmp_path / "f.png")
    building = np.zeros((300, 400), bool)
    building[60:220, 120:280] = True
    shade_grade(tmp_path / "f.png", building, tmp_path / "f.png")
    out = np.asarray(Image.open(tmp_path / "f.png").convert("L"), np.float64)
    assert out[140, 200] < 0.8 * 200          # the facade is in shade
    assert out[230, 200] < out[290, 200]      # its shadow on the ground fades away from it
    assert abs(out[30, 30] - 200) < 2 and abs(out[150, 20] - 200) < 2  # sky and sunlit surroundings untouched
