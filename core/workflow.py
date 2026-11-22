"""The ComfyUI graphs.

1. `build`: Z-Image-Turbo + Fun Union ControlNet following the line drawing at ~1 MP, one regional prompt per
   facade material for the first half of the steps, then a shared prompt. For a final render it also saves
   a 2x upscale (RealESRGAN x4 -> half) for the detail pass.
2. `build_tile`: the 2K detail pass, run tile by tile (~1 MP each, see tiles.py): img2img at low denoise
   with the 2K line drawing as control, so lines stay exactly where the drawing has them.

Lessons baked in (see the earlier cad-render-ai experiments and this project):
- thin CAD lines need ControlNet strength ~1.3 in the first pass (0.85 ignores them, 1.5 ghosts);
- start from noise: starting from a flat color picture makes results look drawn;
- regional prompts only matter early; after half the steps one shared prompt is enough and cheaper;
- fp8 compute ("fp8_e4m3fn_fast") is ~15% faster but at 100% it leaves a speckled, grid-like texture on
  walls and mushy backgrounds: bf16 only;
- one 4 MP detail pass is outside what the model was trained on: it smears edges and invents streaks.
  ~1 MP tiles stay sharp;
- "soft", haze or mist words in the prompt give a foggy, out-of-focus background: ask for deep focus.
"""
from .comfy import MODELS

STYLE = ("straight-on frontal view of the facade, orthographic architectural elevation photograph, "
         "shot at f/11 with deep depth of field, everything in crisp sharp focus from foreground to background, "
         "clear air, no haze, no fog, no bokeh, realistic materials and textures, highly detailed")


def _base(m, control, strength):
    return {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["clip"], "type": "lumina2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "patch": {"class_type": "ModelPatchLoader", "inputs": {"name": m["control"]}},
        "ctrl": {"class_type": "LoadImage", "inputs": {"image": control}},
        "cn": {"class_type": "QwenImageDiffsynthControlnet", "inputs": {
            "model": ["unet", 0], "model_patch": ["patch", 0], "vae": ["vae", 0], "image": ["ctrl", 0],
            "strength": strength, "end_percent": 1.0}},
        "shift": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["cn", 0], "shift": 3.0}},
    }


def shared_prompt(prompt, materials):
    """One prompt for the whole facade (used after the regional phase and in the detail pass)."""
    mats = f" with {', '.join(materials)}" if materials else ""
    return f"{prompt['subject']}, {prompt['wall']} facade{mats}, {prompt['context']}, {STYLE}"


def build(*, control, zones, rest, prompt, width, height, seed, prefix, final,
          strength=1.3, regional_until=0.5, steps=8):
    """First pass. prompt: {"subject", "wall", "context"} (scene.view_prompt).
    zones: [(material words, uploaded mask)]; rest: uploaded mask for everything no material claims.
    Each region's prompt names only its own material."""
    m = {k: v[1] for k, v in MODELS.items()}
    subj, ctx = prompt["subject"], prompt["context"]
    texts = {"pos_rest": f"{subj}, {prompt['wall']} facade, {ctx}, {STYLE}"}
    for i, (word, _) in enumerate(zones):
        texts[f"pos_z{i}"] = f"{subj}, facade clad in {word}, {ctx}, {STYLE}"
    wf = _base(m, control, strength)
    wf["neg"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos_rest", 0]}}
    wf["latent"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
    for key, text in texts.items():
        wf[key] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": text}}
    positive = ["pos_rest", 0]
    if zones:
        for key, file in [("pos_rest", rest)] + [(f"pos_z{i}", f) for i, (_, f) in enumerate(zones)]:
            wf[f"{key}_img"] = {"class_type": "LoadImage", "inputs": {"image": file}}
            wf[f"{key}_mask"] = {"class_type": "ImageToMask", "inputs": {"image": [f"{key}_img", 0], "channel": "red"}}
            wf[f"{key}_set"] = {"class_type": "ConditioningSetMask", "inputs": {
                "conditioning": [key, 0], "mask": [f"{key}_mask", 0], "strength": 1.0, "set_cond_area": "default"}}
            if key == "pos_rest":
                positive = [f"{key}_set", 0]
            else:
                wf[f"{key}_comb"] = {"class_type": "ConditioningCombine", "inputs": {
                    "conditioning_1": positive, "conditioning_2": [f"{key}_set", 0]}}
                positive = [f"{key}_comb", 0]
        wf["pos_all"] = {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["clip", 0], "text": shared_prompt(prompt, [w for w, _ in zones])}}
        wf["reg_range"] = {"class_type": "ConditioningSetTimestepRange", "inputs": {
            "conditioning": positive, "start": 0.0, "end": regional_until}}
        wf["all_range"] = {"class_type": "ConditioningSetTimestepRange", "inputs": {
            "conditioning": ["pos_all", 0], "start": regional_until, "end": 1.0}}
        wf["pos_split"] = {"class_type": "ConditioningCombine", "inputs": {
            "conditioning_1": ["reg_range", 0], "conditioning_2": ["all_range", 0]}}
        positive = ["pos_split", 0]
    wf.update({
        "sample": {"class_type": "KSampler", "inputs": {
            "model": ["shift", 0], "positive": positive, "negative": ["neg", 0], "latent_image": ["latent", 0],
            "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "res_multistep",
            "scheduler": "simple", "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "save1k": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": f"{prefix}_1k"}},
    })
    if final:
        wf.update({
            "up_model": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": m["upscale"]}},
            "up": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["up_model", 0], "image": ["decode", 0]}},
            "half": {"class_type": "ImageScaleBy", "inputs": {"image": ["up", 0], "upscale_method": "lanczos", "scale_by": 0.5}},
            "save_up": {"class_type": "SaveImage", "inputs": {"images": ["half", 0], "filename_prefix": f"{prefix}_up"}},
        })
    return wf


def build_tile(*, image, control, text, seed, prefix, strength=0.9, denoise=0.33, steps=5):
    """Detail pass for one ~1 MP tile of the 2x upscale: low-denoise img2img that keeps following the
    lines of the drawing (at 2x), so edges stay exactly on the drawing and crisp."""
    m = {k: v[1] for k, v in MODELS.items()}
    wf = _base(m, control, strength)
    wf.update({
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": text}},
        "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos", 0]}},
        "enc": {"class_type": "VAEEncode", "inputs": {"pixels": ["img", 0], "vae": ["vae", 0]}},
        "sample": {"class_type": "KSampler", "inputs": {
            "model": ["shift", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["enc", 0],
            "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "dpmpp_2m_sde", "scheduler": "beta",
            "denoise": denoise}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": prefix}},
    })
    return wf
