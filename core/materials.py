"""Facade materials: recognizing them from hatches (Turkish and English names), and the choices
offered to the user.

A material *group* is all hatches with the same layer + pattern across the whole sheet, so a choice
("brick: yellow") applies to every facade at once."""
import re

# key -> ({lang: name}, preview color, {option: ({lang: label}, prompt words)}, default option)
CATALOG = {
    "brick": ({"en": "Brick", "tr": "Tuğla"}, (156, 74, 52), {
        "red": ({"en": "Red", "tr": "Kırmızı"}, "red clay brick cladding"),
        "yellow": ({"en": "Buff yellow", "tr": "Sarı"}, "buff yellow brick cladding"),
        "white": ({"en": "White painted", "tr": "Beyaz boyalı"}, "white painted brick"),
        "dark": ({"en": "Dark brown", "tr": "Koyu kahve"}, "dark brown brick cladding"),
    }, "red"),
    "stone": ({"en": "Natural stone", "tr": "Doğal taş"}, (184, 174, 156), {
        "travertine": ({"en": "Travertine", "tr": "Traverten"}, "beige travertine stone cladding"),
        "granite": ({"en": "Grey granite", "tr": "Gri granit"}, "grey granite stone cladding"),
        "sandstone": ({"en": "Sandstone", "tr": "Kumtaşı"}, "warm sandstone cladding"),
        "slate": ({"en": "Slate", "tr": "Kayrak"}, "dark slate stone cladding"),
    }, "travertine"),
    "concrete": ({"en": "Concrete", "tr": "Beton"}, (160, 160, 155), {
        "board": ({"en": "Board-formed", "tr": "Brüt beton"}, "exposed board-formed concrete"),
        "smooth": ({"en": "Smooth", "tr": "Pürüzsüz beton"}, "smooth fair-faced concrete"),
    }, "smooth"),
    "wood": ({"en": "Wood", "tr": "Ahşap"}, (148, 101, 62), {
        "light": ({"en": "Light wood", "tr": "Açık ahşap"}, "light larch wood cladding"),
        "dark": ({"en": "Dark wood", "tr": "Koyu ahşap"}, "dark thermowood cladding"),
    }, "light"),
    "metal": ({"en": "Metal / composite", "tr": "Metal / kompozit"}, (125, 130, 136), {
        "anthracite": ({"en": "Anthracite", "tr": "Antrasit"}, "anthracite metal composite panels"),
        "white": ({"en": "White", "tr": "Beyaz"}, "white aluminium composite panels"),
        "corten": ({"en": "Corten", "tr": "Corten"}, "rusty corten steel panels"),
    }, "anthracite"),
    "glass": ({"en": "Glass", "tr": "Cam"}, (60, 78, 96), {
        "clear": ({"en": "Clear glass", "tr": "Şeffaf cam"}, "clear glass curtain wall"),
        "reflective": ({"en": "Reflective glass", "tr": "Reflekte cam"}, "reflective blue-grey glass curtain wall"),
    }, "clear"),
    "roof": ({"en": "Roof tiles", "tr": "Kiremit"}, (152, 66, 46), {
        "clay": ({"en": "Clay tiles", "tr": "Kil kiremit"}, "terracotta clay roof tiles"),
    }, "clay"),
    "plaster": ({"en": "Plaster", "tr": "Sıva"}, (222, 208, 180), {
        "cream": ({"en": "Cream", "tr": "Krem"}, "smooth cream stucco plaster"),
        "white": ({"en": "White", "tr": "Beyaz"}, "smooth white stucco plaster"),
        "grey": ({"en": "Light grey", "tr": "Açık gri"}, "smooth light grey stucco plaster"),
        "terracotta": ({"en": "Terracotta", "tr": "Kiremit rengi"}, "smooth terracotta-colored stucco plaster"),
    }, "cream"),
}
WALL_DEFAULT = ("plaster", "cream")  # the unhatched wall
IGNORE = "ignore"                   # user: "this hatch is not a material"

# Hatch pattern / layer name -> material. The layer name is checked first: offices name layers by
# material (TUGLA, TAS...) while patterns are often generic (ANSI31).
RULES = [
    ("glass", r"glass|\bcam\b|cam_|cam-|_cam|glaz|curtain"),
    ("brick", r"brick|tu[gğ]la|ar-b8|ar-brstd|ar-bs|klinker|clinker"),
    ("stone", r"stone|ta[sş]\b|ta[sş]_|ta[sş]-|granit|traverten|travertine|mermer|marble|ar-rs|ar-hbone|"
              r"andezit|bazalt|kayrak|kumta"),
    ("concrete", r"conc|beton|brut|exposed"),
    ("wood", r"wood|ah[sş]ap|timber|lambiri"),
    ("metal", r"metal|alu|kompozit|composite|panel|[çc]elik|steel|zinc|corten"),
    ("roof", r"roof|[çc]at[ıi]|kiremit|tile"),
    ("plaster", r"s[ıi]va|plaster|render|stucco|ar-sand|mantolama"),
]
# hatches that are drafting conventions, not materials
NOT_MATERIAL = r"^solid$|^ansi3[1-8]$|insul|yal[ıi]t|earth|toprak|zemin|ground|gravel|cak[ıi]l"
PREVIEW = {"sky": (150, 186, 222), "ground": (104, 104, 100), "wall": (222, 212, 192), "glass": (58, 74, 92),
           "frame": (236, 236, 232), "other": (196, 188, 172)}


def guess(pattern, layer):
    """Material key for a hatch group, or None when neither name says anything."""
    for text in (layer, pattern):
        for key, rx in RULES:
            if text and re.search(rx, text, re.I):
                return key
    return None


def groups_of(sheet, kinds=("elevation",)):
    """{group id: {"layer", "pattern", "count", "material", "option"}} over the given view kinds."""
    out = {}
    for v in sheet.views:
        if v.kind not in kinds:
            continue
        for h in v.hatches:
            g = out.setdefault(h.group, {"layer": h.layer, "pattern": h.pattern, "count": 0})
            g["count"] += 1
    for g in out.values():
        key = guess(g["pattern"], g["layer"])
        if key is None and re.search(NOT_MATERIAL, g["pattern"] or "", re.I) is None:
            key = None  # unknown but may be a material: the user can assign one
        g["material"] = key or IGNORE
        g["option"] = CATALOG[key][3] if key else None
    return out


def words(material, option):
    if material in (None, IGNORE) or material not in CATALOG:
        return None
    opts = CATALOG[material][2]
    return opts.get(option, opts[CATALOG[material][3]])[1]


def preview_colors(groups):
    colors = dict(PREVIEW)
    for gid, g in groups.items():
        if g["material"] in CATALOG:
            colors[g["material"]] = CATALOG[g["material"]][1]
    return colors


def catalog_for_ui(lang="en"):
    from .i18n import label
    return {k: {"name": label(n, lang), "options": {o: label(lbl, lang) for o, (lbl, _) in opts.items()}, "default": d}
            for k, (n, _, opts, d) in CATALOG.items()}
