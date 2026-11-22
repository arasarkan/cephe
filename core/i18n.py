"""User-facing text in English (default) and Turkish.

Only what people read is translated here. Reading drawings stays bilingual regardless of the UI language:
Turkish and English view titles and layer names are always recognized (see classify.py, materials.py).
"""
LANGS = ("en", "tr")
DEFAULT = "en"

STRINGS = {
    # ---- errors the user can act on
    "oda_missing": {
        "en": "Reading DWG files needs ODA File Converter. Run the installer again, or save the drawing as DXF "
              "in AutoCAD and upload that.",
        "tr": "DWG dosyalarını okumak için ODA File Converter gerekiyor. Kurulumu tekrar çalıştırın ya da çizimi "
              "AutoCAD'de DXF olarak kaydedip onu yükleyin."},
    "read_failed": {
        "en": "The drawing could not be read ({kind}). The file may be damaged; try opening and saving it again "
              "in AutoCAD.",
        "tr": "Çizim okunamadı ({kind}). Dosya bozuk olabilir; AutoCAD'de açıp tekrar kaydetmeyi deneyin."},
    "no_lines": {
        "en": "No lines found in the drawing. Model space may be empty, or the drawing may only be in a layout; "
              "move it to model space and try again.",
        "tr": "Çizimde çizgi bulunamadı. Model alanı boş olabilir ya da çizim bir pafta düzeninde (layout) "
              "olabilir; model alanına taşıyıp tekrar deneyin."},
    "unsupported_type": {
        "en": "'{ext}' files are not supported yet. Upload a DWG or DXF file.",
        "tr": "'{ext}' dosyaları henüz desteklenmiyor. DWG ya da DXF yükleyin."},
    "no_facades": {
        "en": "No facades to render. This file may only contain plans or sections.",
        "tr": "Render edilecek cephe yok. Bu dosyada sadece plan/kesit bulunuyor olabilir."},
    "no_facades_warning": {
        "en": "No facades found in this file. For now only elevations can be rendered; plans and sections "
              "come in a later version.",
        "tr": "Bu dosyada cephe bulunamadı. Şimdilik sadece cephe görünüşleri render edilebiliyor; plan ve "
              "kesit desteği sonraki sürümde."},
    "no_file": {"en": "No file selected.", "tr": "Dosya seçilmedi."},
    "sample_missing": {"en": "Sample project not found.", "tr": "Örnek proje bulunamadı."},
    "comfy_unreachable": {"en": "Cannot reach the render engine ({server}).",
                          "tr": "Render motoruna ulaşılamıyor ({server})."},
    "comfy_old": {"en": "The render engine (ComfyUI) is too old (missing: {missing}). Update ComfyUI.",
                  "tr": "Render motorunun (ComfyUI) sürümü eski (eksik: {missing}). ComfyUI'ı güncelleyin."},
    "model_missing": {"en": "Model missing: {name}. Run the installer again.",
                      "tr": "Model eksik: {name}. Kurulumu tekrar çalıştırın."},
    "render_failed": {"en": "Render failed: {detail}", "tr": "Render başarısız: {detail}"},
    "engine_missing": {"en": "Render engine (ComfyUI) not found. Run Install.bat.",
                       "tr": "Render motoru (ComfyUI) bulunamadı. Install.bat'i çalıştırın."},
    "engine_starting": {"en": "Starting the render engine (the first start can take 1-2 minutes)",
                        "tr": "Render motoru başlatılıyor (ilk açılış 1-2 dakika sürebilir)"},
    "engine_failed": {"en": "The render engine did not start. Details: comfyui.log",
                      "tr": "Render motoru başlamadı. Ayrıntı: comfyui.log"},
    "engine_not_running": {"en": "The render engine is not running.", "tr": "Render motoru çalışmıyor."},
    "unexpected": {"en": "Unexpected error: {error}. Details are in error.log.",
                   "tr": "Beklenmeyen hata: {error}. Ayrıntı error.log dosyasında."},
    # ---- progress
    "queued": {"en": "Queued", "tr": "Sırada"},
    "engine_preparing": {"en": "Preparing the render engine", "tr": "Render motoru hazırlanıyor"},
    "preparing_view": {"en": "Preparing {title} ({n}/{total})", "tr": "{title} hazırlanıyor ({n}/{total})"},
    "rendering_view": {"en": "Rendering {title} ({n}/{total})", "tr": "{title} render ediliyor ({n}/{total})"},
    "redrawing_view": {"en": "{title} drifted from the drawing, drawing it again",
                       "tr": "{title} çizimden saptı, yeniden çiziliyor"},
    "detailing_view": {"en": "Adding detail to {title} (part {i}/{k})", "tr": "{title} detaylandırılıyor (parça {i}/{k})"},
    "making_sheet": {"en": "Making the presentation sheet", "tr": "Sunum paftası hazırlanıyor"},
    "done": {"en": "Done", "tr": "Bitti"},
    "cancelled": {"en": "Cancelled", "tr": "İptal edildi"},
    # ---- presentation sheet
    "sheet_subtitle": {"en": "Elevations", "tr": "Cephe görünüşleri"},
    "sample_name": {"en": "Sample House", "tr": "Örnek Konut"},
    # ---- view kinds and directions
    "kind.elevation": {"en": "Elevation", "tr": "Cephe"},
    "kind.section": {"en": "Section", "tr": "Kesit"},
    "kind.plan": {"en": "Plan", "tr": "Plan"},
    "kind.unknown": {"en": "Unknown", "tr": "Bilinmiyor"},
    "facing.N": {"en": "North", "tr": "Kuzey"}, "facing.NE": {"en": "North-east", "tr": "Kuzeydoğu"},
    "facing.E": {"en": "East", "tr": "Doğu"}, "facing.SE": {"en": "South-east", "tr": "Güneydoğu"},
    "facing.S": {"en": "South", "tr": "Güney"}, "facing.SW": {"en": "South-west", "tr": "Güneybatı"},
    "facing.W": {"en": "West", "tr": "Batı"}, "facing.NW": {"en": "North-west", "tr": "Kuzeybatı"},
    "facing.front": {"en": "Front", "tr": "Ön"}, "facing.back": {"en": "Back", "tr": "Arka"},
    "facing.right": {"en": "Right", "tr": "Sağ"}, "facing.left": {"en": "Left", "tr": "Sol"},
    "facing.side": {"en": "Side", "tr": "Yan"},
}


def lang_of(value):
    return value if value in LANGS else DEFAULT


def t(key, lang=DEFAULT, **kw):
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(lang_of(lang)) or entry[DEFAULT]
    return text.format(**kw) if kw else text


def label(labels, lang=DEFAULT):
    """Pick from a {"en": ..., "tr": ...} label."""
    return labels.get(lang_of(lang)) or labels[DEFAULT]


class UserError(Exception):
    """A problem the user can act on. Carries a message key, so it can be shown in the user's language;
    str() gives English (for logs)."""

    def __init__(self, key, **kw):
        self.key, self.kw = key, kw
        super().__init__(t(key, DEFAULT, **kw))

    def message(self, lang=DEFAULT):
        return t(self.key, lang, **self.kw)
