"""Project-wide scene settings (picked in the UI, any language) -> English prompts, and one sun for all facades."""
import re
from dataclasses import dataclass, field

from .classify import absolute_facing
from .i18n import label
from .materials import WALL_DEFAULT, words

BUILDING = {
    "residential": ({"en": "Apartment building", "tr": "Apartman / konut"}, "residential apartment building"),
    "house": ({"en": "House / villa", "tr": "Müstakil ev / villa"}, "detached family house"),
    "office": ({"en": "Office", "tr": "Ofis"}, "office building"),
    "commercial": ({"en": "Commercial / retail", "tr": "Ticari / AVM"}, "commercial building"),
    "public": ({"en": "Public / school", "tr": "Kamu / okul"}, "public building"),
    "hotel": ({"en": "Hotel", "tr": "Otel"}, "hotel building"),
}
SETTING = {
    # "{quiet}" becomes "quiet " only when no people are wanted: "quiet street" keeps people away
    "city": ({"en": "City street", "tr": "Şehir sokağı"}, "on a {quiet}city street, clean sidewalk, a few street trees"),
    "garden": ({"en": "Garden", "tr": "Bahçe"}, "in a landscaped garden with a green lawn, shrubs and trees"),
    "rural": ({"en": "Countryside", "tr": "Kırsal"}, "in open countryside with grass and distant hills"),
    "coast": ({"en": "Seaside", "tr": "Sahil"}, "near the seaside, mediterranean vegetation, olive trees"),
}
SEASON = {
    "summer": ({"en": "Summer", "tr": "Yaz"}, "lush green summer trees"),
    "spring": ({"en": "Spring", "tr": "İlkbahar"}, "fresh green spring trees with some blossoms"),
    "autumn": ({"en": "Autumn", "tr": "Sonbahar"}, "autumn trees with orange and yellow leaves"),
    "winter": ({"en": "Winter", "tr": "Kış"}, "bare winter trees, a little snow on the ground"),
}
# time -> (labels, sky words, sun azimuth deg or None (overcast), sun altitude deg, light words)
# No "soft", "haze", "mist" style words anywhere: they turn into a foggy, out-of-focus background.
TIME = {
    "morning": ({"en": "Morning", "tr": "Sabah"}, "clear fresh morning sky", 110, 30, "low morning sunlight"),
    "noon": ({"en": "Noon", "tr": "Öğle"}, "clear blue sky", 180, 60, "bright midday sunlight"),
    "sunset": ({"en": "Sunset", "tr": "Gün batımı"}, "clear golden hour sky", 255, 12, "warm golden sunset light"),
    "overcast": ({"en": "Overcast", "tr": "Bulutlu"}, "bright overcast sky", None, None, "even overcast daylight"),
}
FRONT = {"N": {"en": "North", "tr": "Kuzey"}, "E": {"en": "East", "tr": "Doğu"},
         "S": {"en": "South", "tr": "Güney"}, "W": {"en": "West", "tr": "Batı"}}
# People at true scale are small on an elevation; they mostly appear on the sidewalk and beside the building.
PEOPLE = {
    "none": ({"en": "None", "tr": "Yok"}, ""),
    "few": ({"en": "A few people", "tr": "Birkaç kişi"}, "a few people walking on the sidewalk"),
    "families": ({"en": "Families and children", "tr": "Aileler ve çocuklar"},
                 "families with children playing in front of the building, people walking on the sidewalk"),
    "busy": ({"en": "Busy street", "tr": "Kalabalık"}, "many people walking on the sidewalk, lively street life"),
}
VEHICLES = {
    "none": ({"en": "None", "tr": "Yok"}, ""),
    "parked": ({"en": "Parked cars", "tr": "Park etmiş araçlar"}, "a few cars parked along the street"),
}
# The image model follows English descriptions; an instruction in Turkish ("çocuklar oynasın") reaches it
# but is not understood. Common things people ask for are turned into English words next to the note.
NOTE_WORDS = [
    (r"çocuk|cocuk", "children playing"),
    (r"insan|kişi|kisi|yaya|aile|halk", "people walking"),
    (r"kalabal", "a lively crowd of people"),
    (r"araba|araç|arac|otomobil|taksi", "cars parked along the street"),
    (r"bisiklet", "people riding bicycles"),
    (r"köpek|kopek", "a person walking a dog"),
    (r"saksı|saksi|çiçek|cicek", "flower pots with flowers"),
    (r"bank\b|banklar", "street benches"),
    (r"ağaç|agac", "more trees"),
    (r"lamba|aydınlatma|aydinlatma", "street lamps"),
    (r"yağmur|yagmur", "rain, wet pavement"),
    (r"gece", "night, warm lights in the windows"),
]


@dataclass
class Scene:
    building: str = "residential"
    setting: str = "city"
    season: str = "summer"
    time: str = "noon"
    front: str = "S"                 # which way the front facade faces
    wall: tuple = WALL_DEFAULT       # unhatched wall (material, option)
    note: str = ""                   # free text from the user, any language
    seed: int = 42
    materials: dict = field(default_factory=dict)  # group id -> {"material", "option"} overrides
    facings: dict = field(default_factory=dict)    # view id (str) -> facing, where the title didn't say
    lang: str = "en"                 # UI language: progress messages, sheet text
    people: str = "few"
    vehicles: str = "none"

    def facing_of(self, view):
        return self.facings.get(str(view.id)) or view.facing


def light_on(facing_deg, time):
    """How the one sun lights a facade facing `facing_deg`: ('lit'|'left'|'right'|'shade'|'overcast', words).
    Standing in front of a facade you look the opposite way, so the sun is on your right when it sits
    90 degrees clockwise... i.e. at facing - 90."""
    _, _, az, alt, light = TIME[time]
    if az is None:
        return "overcast", f"{light}, no hard shadows"
    if facing_deg is None:
        return "lit", f"{light} on the facade"
    d = (az - facing_deg + 180) % 360 - 180  # sun relative to the facade normal, -180..180
    if abs(d) < 55:
        return "lit", f"facade in direct {light}, crisp shadows under balconies and in window reveals"
    if abs(d) < 100:
        side = "right" if d < 0 else "left"
        return side, f"{light} raking across the facade from the {side}, long sideways shadows"
    return "shade", ("facade in open shade on the shadow side of the building, diffuse light, "
                     "sunlit surroundings")


def storeys(view, units_per_m):
    h = view.height / units_per_m
    n = max(1, round(h / 3.1))
    names = {1: "single-storey", 2: "two-storey", 3: "three-storey", 4: "four-storey", 5: "five-storey",
             6: "six-storey", 7: "seven-storey", 8: "eight-storey"}
    return names.get(n, f"{n}-storey")


def view_prompt(scene: Scene, view, units_per_m):
    """({"subject", "wall", "context"}, light kind). The wall material is kept apart: a region clad in
    brick must not also be told the facade is plaster (the two fight and the plaster wins).
    Same words for every facade except the light."""
    facing = absolute_facing(scene.facing_of(view), scene.front)
    kind, light = light_on(facing, scene.time)
    note_words = note_to_english(scene.note)
    people = PEOPLE.get(scene.people, PEOPLE["none"])[1]
    wants_people = bool(people) or any("people" in w or "children" in w or "crowd" in w for w in note_words)
    setting = SETTING[scene.setting][1].replace("{quiet}", "" if wants_people else "quiet ")
    # entourage right after the setting: words late in a long prompt carry little weight
    context = [setting] + [w for w in (people, VEHICLES.get(scene.vehicles, VEHICLES["none"])[1]) if w]
    context += note_words + [SEASON[scene.season][1], TIME[scene.time][1], light]
    if scene.note.strip():
        context.append(scene.note.strip())
    return {"subject": f"{storeys(view, units_per_m)} {BUILDING[scene.building][1]}",
            "wall": words(*scene.wall) or words(*WALL_DEFAULT), "context": ", ".join(context)}, kind


def note_to_english(note):
    """English words for things a note asks for in Turkish (see NOTE_WORDS)."""
    text = note.replace("İ", "i").replace("I", "ı").lower()  # Turkish dotted/dotless i before lower()
    out = []
    for rx, phrase in NOTE_WORDS:
        if re.search(rx, text) and phrase not in out:
            out.append(phrase)
    return out


def options_for_ui(lang="en"):
    pick = lambda d: {k: label(v[0], lang) for k, v in d.items()}  # noqa: E731
    return {"building": pick(BUILDING), "setting": pick(SETTING), "season": pick(SEASON),
            "time": pick(TIME), "front": {k: label(v, lang) for k, v in FRONT.items()},
            "people": pick(PEOPLE), "vehicles": pick(VEHICLES)}
