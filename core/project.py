"""A project: one input file, its views, and the renders made from it."""
import json
import shutil
import time
import uuid
from pathlib import Path

from PIL import Image

from . import fidelity, geometry, materials, tiles, workflow
from .classify import absolute_facing, display_name
from .comfy import saved_files
from .harmonize import harmonize, material_ok, regions, shade_grade
from .presentation import make_sheet
from .scene import Scene, light_on, view_prompt
from .i18n import UserError, t

RENDERABLE = ("elevation",)
SECONDS = {"preview": 65, "final": 215}  # per facade with two materials, RTX 4050 6 GB (bf16, tiled 2K)
ORDER = {"front": 0, "S": 0, "right": 1, "E": 1, "back": 2, "N": 2, "left": 3, "W": 3}


def read_input(path):
    ext = Path(path).suffix.lower()
    if ext in (".dwg", ".dxf"):
        from .inputs import dwg
        return dwg.read(path)
    raise UserError("unsupported_type", ext=ext)


class Project:
    def __init__(self, folder, sheet):
        self.folder = Path(folder)
        self.sheet = sheet
        self.groups = materials.groups_of(sheet)
        self.views = {v.id: v for v in sheet.views}

    @classmethod
    def create(cls, src, root):
        pid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        folder = Path(root) / pid
        folder.mkdir(parents=True)
        dst = folder / ("input" + Path(src).suffix.lower())
        shutil.copy(src, dst)
        p = cls(folder, read_input(dst))
        p.name = Path(src).stem
        p.make_thumbnails()
        return p

    # ---- what the UI shows -------------------------------------------------------------------------
    def make_thumbnails(self):
        (self.folder / "thumbs").mkdir(exist_ok=True)
        for v in self.sheet.views:
            scale = geometry.common_scale([v], 0.12)
            _, preview = geometry.rasterize(v, scale, margin=(0.04, 0.04, 0.04, 0.04), supersample=1)
            preview.save(self.folder / "thumbs" / f"{v.id}.png")

    def summary(self, lang="en"):
        upm = self.sheet.units_per_m
        views = []
        for v in self.sheet.views:
            views.append({
                "id": v.id, "name": display_name(v, lang), "kind": v.kind, "kind_label": t("kind." + v.kind, lang),
                "facing": v.facing, "facing_label": t("facing." + v.facing, lang) if v.facing else None,
                "renderable": v.kind in RENDERABLE,
                "size_m": [round(v.width / upm, 1), round(v.height / upm, 1)],
                "needs_facing": v.kind in RENDERABLE and v.facing in (None, "side"),
            })
        groups = [{"id": g, "layer": d["layer"], "pattern": d["pattern"], "count": d["count"],
                   "material": d["material"], "option": d["option"]} for g, d in self.groups.items()]
        return {"id": self.folder.name, "name": getattr(self, "name", self.folder.name), "views": views,
                "materials": groups, "units_per_m": upm, "warnings": self.sheet.warnings,
                "has_relative": any(v.facing in ("front", "back", "left", "right") for v in self.sheet.views)}

    # ---- rendering ---------------------------------------------------------------------------------
    def _material_map(self, scene):
        out = {}
        for g, d in self.groups.items():
            ov = scene.materials.get(g, {})
            mat, opt = ov.get("material", d["material"]), ov.get("option", d["option"])
            if mat in materials.CATALOG:
                out[g] = (mat, opt)
        return out

    def _order(self, scene, ids):
        """Hero first (the sunlit front, else the sunniest, else the largest), then the rest in a
        natural walk around the building."""
        vs = [self.views[i] for i in ids]
        def key(v):
            kind, _ = light_on(absolute_facing(scene.facing_of(v), scene.front), scene.time)
            return ({"lit": 0, "left": 1, "right": 1, "overcast": 1, "shade": 2}[kind],
                    ORDER.get(scene.facing_of(v), 9), -v.width * v.height)
        return sorted(vs, key=key)

    def _detail_pass(self, comfy, v, scale, w, out, text, seed, dest, stop, progress):
        """2K detail, tile by tile: each ~1 MP tile of the 2x upscale is redrawn at low strength while
        following the drawing's lines at 2x. (One 4 MP pass smears edges and invents streaks.)"""
        from PIL import Image
        img = Image.open(w / f"{v.id}_up.png").convert("RGB")
        control, _ = geometry.rasterize(v, scale * 2)
        control = control.resize(img.size, Image.NEAREST)
        boxes = tiles.grid(*img.size)
        pieces = []
        for i, box in enumerate(boxes):
            if stop():
                raise InterruptedError
            progress(i, len(boxes))
            ti, tc = w / f"{v.id}_tile{i}.png", w / f"{v.id}_tile{i}_ctrl.png"
            img.crop(box).save(ti)
            control.crop(box).save(tc)
            name = lambda p: f"cephe_{self.folder.name}_{out.name}_{p.name}"  # noqa: E731
            wf = workflow.build_tile(image=comfy.upload(ti, name(ti)), control=comfy.upload(tc, name(tc)), text=text,
                                     seed=seed + i, prefix=f"cephe/{self.folder.name}_{v.id}_t{i}")
            outputs = comfy.run(wf, should_stop=stop)
            for item in saved_files(outputs, "save"):
                comfy.download(item, w / f"{v.id}_tile{i}_out.png")
            pieces.append((box, Image.open(w / f"{v.id}_tile{i}_out.png")))
        tiles.blend(img.size, pieces).save(dest)

    def render(self, comfy, scene: Scene, view_ids, final, progress=lambda f, m: None, stop=lambda: False):
        mode = "final" if final else "preview"
        out = self.folder / f"{mode}_{time.strftime('%H%M%S')}"
        (out / "work").mkdir(parents=True)
        ids = [i for i in view_ids if self.views[i].kind in RENDERABLE] or \
            [v.id for v in self.sheet.views if v.kind in RENDERABLE]
        if not ids:
            raise UserError("no_facades")
        views = self._order(scene, ids)
        mats = self._material_map(scene)
        colors = materials.preview_colors({g: {"material": m} for g, (m, _) in mats.items()})
        groups = {g: m for g, (m, _) in mats.items()}
        scale = geometry.common_scale(views, 1.0)
        name, gb = comfy.gpu()
        results, hero = [], None
        for n, v in enumerate(views):
            if stop():
                raise InterruptedError
            title = display_name(v, scene.lang)
            progress(n / len(views), t("preparing_view", scene.lang, title=title, n=n + 1, total=len(views)))
            control, _ = geometry.rasterize(v, scale)
            z = geometry.zones(v, control, scale, groups, colors)
            w = out / "work"
            control.save(w / f"{v.id}_control.png")
            z["preview"].save(w / f"{v.id}_materials.png")
            z["rest"].save(w / f"{v.id}_rest.png")
            up = lambda p: comfy.upload(p, f"cephe_{self.folder.name}_{out.name}_{p.name}")  # noqa: E731
            zone_files = []
            for g, mask in z["masks"].items():
                mask.save(w / f"{v.id}_zone_{len(zone_files)}.png")
                zone_files.append((materials.words(*mats[g]), up(w / f"{v.id}_zone_{len(zone_files)}.png")))
            prompt, light = view_prompt(scene, v, self.sheet.units_per_m)
            ctrl_name = up(w / f"{v.id}_control.png")
            rest_name = up(w / f"{v.id}_rest.png") if zone_files else None

            def first_pass(k, seed):
                """One try of the ~1 MP pass; returns (seed, fidelity check, files)."""
                wf = workflow.build(control=ctrl_name, zones=zone_files, rest=rest_name, prompt=prompt,
                                    width=control.width, height=control.height, seed=seed,
                                    prefix=f"cephe/{self.folder.name}_{v.id}", final=final)
                outputs = comfy.run(wf, should_stop=stop)
                files = {"1k": w / f"{v.id}_try{k}_1k.png", "up": w / f"{v.id}_try{k}_up.png"}
                for item in saved_files(outputs, "save1k"):
                    comfy.download(item, files["1k"])
                if final:
                    for item in saved_files(outputs, "save_up"):
                        comfy.download(item, files["up"])
                return seed, fidelity.check(v, scale, Image.open(files["1k"])), files

            progress((n + 0.1) / len(views), t("rendering_view", scene.lang, title=title, n=n + 1, total=len(views)))
            tries = [first_pass(0, scene.seed)]
            if tries[0][1]["score"] < fidelity.FAIR:
                # drifted from the drawing: one more try with another seed, keep whichever follows it better.
                # Checked on the cheap first pass, before the expensive 2K detail.
                if stop():
                    raise InterruptedError
                progress((n + 0.2) / len(views), t("redrawing_view", scene.lang, title=title))
                tries.append(first_pass(1, scene.seed + 7919))
            seed, check, files = max(tries, key=lambda r: r[1]["score"])
            raw = w / f"{v.id}_raw.png"
            if not final:
                shutil.copy(files["1k"], raw)
            else:
                shutil.copy(files["up"], w / f"{v.id}_up.png")
                text = workflow.shared_prompt(prompt, [wd for wd, _ in zone_files])
                self._detail_pass(comfy, v, scale, w, out, text, seed, raw, stop,
                                  lambda i, k: progress((n + 0.3 + 0.65 * i / k) / len(views),
                                                        t("detailing_view", scene.lang, title=title, i=i + 1, k=k)))
            regs = regions(z)
            final_png = out / f"{v.id}.png"
            if hero is None:
                # materials the model missed on the hero must not drag the other facades toward it
                missed = {f"mat:{g}" for g, area in z["areas"].items()
                          if not material_ok(raw, area, materials.CATALOG[mats[g][0]][1])}
                hero = (raw, regs, missed)
                shutil.copy(raw, final_png)
            else:
                harmonize(raw, regs, hero[0], hero[1], final_png, skip=hero[2])
            if light == "shade":
                shade_grade(final_png, z["sky"], final_png)
            if final:  # the 2K detail could still move lines: judge what the user gets
                check = fidelity.check(v, scale, Image.open(raw))
            fidelity.drift_map(Image.open(final_png), check["misses"], control.size, out / f"{v.id}_drift.png")
            px_per_unit = geometry.effective_scale(v, scale) * (2 if final else 1)  # 2K pass doubles
            results.append({"view": v.id, "title": title, "image": final_png.name, "light": light,
                            "prompt": prompt, "px_per_unit": px_per_unit, "seed": seed,
                            "fidelity": {"score": round(check["score"], 3), "grade": fidelity.grade(check["score"]),
                                         "drift": f"{v.id}_drift.png", "tries": len(tries)}})
        progress(0.97, t("making_sheet", scene.lang))
        # the sheet reads front, right, back, left (render order is about light, not reading)
        results.sort(key=lambda r: (ORDER.get(scene.facing_of(self.views[r["view"]]), 9), r["view"]))
        items = [{"image": out / r["image"], "title": r["title"], "px_per_unit": r["px_per_unit"]} for r in results]
        png, pdf = make_sheet(items, getattr(self, "name", "Project"), out / "sheet.png", self.sheet.units_per_m,
                              scene.lang)
        meta = {"mode": mode, "scene": scene.__dict__, "results": results, "sheet": [png.name, pdf.name],
                "gpu": name}
        (out / "result.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        progress(1.0, t("done", scene.lang))
        return out, meta
