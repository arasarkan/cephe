"""Small ComfyUI API client (library version: raises ComfyError instead of exiting)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .i18n import UserError

MODELS = {
    "unet": ("diffusion_models", "z_image_turbo_bf16.safetensors"),
    "clip": ("text_encoders", "qwen_3_4b.safetensors"),
    "vae": ("vae", "ae.safetensors"),
    "control": ("model_patches", "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"),
    "upscale": ("upscale_models", "RealESRGAN_x4plus.safetensors"),
}
NODES = ["QwenImageDiffsynthControlnet", "ModelPatchLoader", "ModelSamplingAuraFlow", "ConditioningSetMask",
         "ConditioningSetTimestepRange", "ConditioningCombine", "ImageToMask", "VAEDecodeTiled",
         "UpscaleModelLoader", "EmptySD3LatentImage"]


class ComfyError(UserError):
    pass


class Comfy:
    def __init__(self, server="http://127.0.0.1:8188"):
        self.server = server.rstrip("/")

    def request(self, path, data=None, headers=None, raw=False, timeout=60):
        req = urllib.request.Request(self.server + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            raise ComfyError("render_failed", detail=f"ComfyUI {path}: HTTP {e.code} "
                                                    f"{e.read().decode(errors='replace')[:2000]}") from e
        except (urllib.error.URLError, OSError) as e:
            raise ComfyError("comfy_unreachable", server=self.server) from e
        return body if raw else json.loads(body)

    def alive(self):
        try:
            self.request("/system_stats", timeout=3)
            return True
        except ComfyError:
            return False

    def gpu(self):
        dev = (self.request("/system_stats").get("devices") or [{}])[0]
        return dev.get("name", ""), dev.get("vram_total", 0) / 2**30

    def check(self):
        info = self.request("/object_info")
        missing = [n for n in NODES if n not in info]
        if missing:
            raise ComfyError("comfy_old", missing=", ".join(missing))
        for folder, filename in MODELS.values():
            if filename not in self.request(f"/models/{folder}"):
                raise ComfyError("model_missing", name=f"{folder}/{filename}")

    def upload(self, file_path, name):
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'.encode(),
            (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
             "Content-Type: image/png\r\n\r\n").encode(),
            Path(file_path).read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        res = self.request("/upload/image", b"".join(parts),
                           {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return f"{res['subfolder']}/{res['name']}" if res.get("subfolder") else res["name"]

    def run(self, workflow, should_stop=lambda: False):
        body = json.dumps({"prompt": workflow, "client_id": uuid.uuid4().hex}).encode()
        prompt_id = self.request("/prompt", body, {"Content-Type": "application/json"})["prompt_id"]
        while True:
            if should_stop():
                self.request("/interrupt", b"")
                raise ComfyError("cancelled")
            hist = self.request(f"/history/{prompt_id}").get(prompt_id)
            if hist and hist.get("status", {}).get("completed") is not None:
                break
            time.sleep(1)
        status = hist["status"]
        if status.get("status_str") != "success":
            msgs = [m for kind, m in status.get("messages", []) if kind == "execution_error"]
            detail = msgs[0].get("exception_message", "")[:500] if msgs else status.get("status_str")
            raise ComfyError("render_failed", detail=detail)
        return hist["outputs"]

    def download(self, item, dest):
        q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                    "type": item.get("type", "output")})
        Path(dest).write_bytes(self.request(f"/view?{q}", raw=True, timeout=300))


def saved_files(outputs, node_id):
    items = []
    for value in outputs.get(node_id, {}).values():
        if isinstance(value, list):
            items += [i for i in value if isinstance(i, dict) and "filename" in i]
    return items
