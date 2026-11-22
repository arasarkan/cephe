"""Second half of the installer (install.ps1 runs it with ComfyUI's own Python; standard library only).

Creates the app's Python environment, installs its packages, downloads the missing models (resumable,
SHA256-checked) and writes config.json. Safe to run again: everything that is already there is skipped.
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# (models subfolder, Hugging Face repo, path in repo): Comfy-Org repackages + Alibaba's ControlNet
MODELS = [
    ("diffusion_models", "Comfy-Org/z_image_turbo", "split_files/diffusion_models/z_image_turbo_bf16.safetensors"),
    ("text_encoders", "Comfy-Org/z_image_turbo", "split_files/text_encoders/qwen_3_4b.safetensors"),
    ("vae", "Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors"),
    ("model_patches", "alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union", "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"),
    ("upscale_models", "Comfy-Org/Real-ESRGAN_repackaged", "RealESRGAN_x4plus.safetensors"),
]
USER_AGENT = "cephe-setup"


def say(msg=""):
    print(msg, flush=True)


def fail(msg):
    say(f"\nERROR: {msg}")
    sys.exit(1)


def yes(question, assume):
    if assume:
        return True
    try:
        a = input(f"{question} (Y/n) ").strip().lower()
    except EOFError:
        a = ""
    return a in ("", "y", "yes")


# ---- app environment ------------------------------------------------------------------------------------
def app_python(comfy_python, portable):
    """The portable build's embedded Python has no venv module: install into it. Otherwise make our own
    venv from ComfyUI's Python, so ComfyUI's environment is never touched."""
    if portable:
        return Path(comfy_python)
    env = ROOT / "runtime" / "appenv"
    py = env / "Scripts" / "python.exe"
    if not py.exists():
        say("  Creating the app environment ...")
        r = subprocess.run([str(comfy_python), "-m", "venv", str(env)])
        if r.returncode or not py.exists():
            fail("Could not create the Python environment.")
    return py


def install_packages(py):
    say("  Installing packages (ezdxf, scipy, flask ...) ...")
    r = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                        "-r", str(ROOT / "requirements.txt")])
    if r.returncode:
        fail("Packages could not be installed. Check the internet connection and run setup again.")


# ---- models ---------------------------------------------------------------------------------------------
def hf_get(url, headers=None, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}),
                                  timeout=timeout)


def remote_info(repo, path):
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    with hf_get(f"https://huggingface.co/api/models/{repo}/tree/main/{folder}") as r:
        for entry in json.load(r):
            if entry["path"] == path:
                return entry["size"], entry.get("lfs", {}).get("oid")
    fail(f"{path} not found in {repo}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(16 * 2**20):
            h.update(chunk)
    return h.hexdigest()


def download(repo, path, dest, size, digest):
    part = dest.with_name(dest.name + ".part")
    url = f"https://huggingface.co/{repo}/resolve/main/{path}"
    for attempt in range(1, 6):
        done = part.stat().st_size if part.exists() else 0
        if done >= size:
            break
        try:
            with hf_get(url, {"Range": f"bytes={done}-"}, timeout=120) as r, open(part, "ab") as f:
                if done and r.status != 206:
                    f.truncate(0)
                    done = 0
                start, start_bytes, last = time.time(), done, 0
                while chunk := r.read(4 * 2**20):
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 1:
                        last = time.time()
                        speed = (done - start_bytes) / max(0.001, last - start) / 1e6
                        print(f"\r    {done / 1e9:6.2f} / {size / 1e9:.2f} GB  {speed:5.1f} MB/s", end="", flush=True)
            print(f"\r    {done / 1e9:6.2f} / {size / 1e9:.2f} GB          ", flush=True)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            say(f"\n    connection problem ({e}); retrying {attempt}/5 ...")
            time.sleep(3 * attempt)
    if not part.exists() or part.stat().st_size != size:
        fail(f"{dest.name} is incomplete. Run setup again; it resumes where it stopped.")
    if digest:
        say("    verifying (SHA256) ...")
        if sha256(part) != digest:
            part.unlink()
            fail(f"{dest.name} failed verification and was deleted. Run setup again.")
    part.replace(dest)


def ensure_models(models_dir, assume):
    if not Path(models_dir).is_absolute() or not Path(models_dir).is_dir():
        fail(f"ComfyUI model folder not found ({models_dir}). Nothing was downloaded.")
    todo = []
    for folder, repo, path in MODELS:
        dest = Path(models_dir) / folder / Path(path).name
        if dest.exists():
            say(f"  ✓ {dest.name}")
            continue
        size, digest = remote_info(repo, path)
        todo.append((folder, repo, path, dest, size, digest))
    if not todo:
        return
    total = sum(t[4] for t in todo)
    free = __import__("shutil").disk_usage(models_dir).free
    say(f"\n  Models to download: {total / 1e9:.1f} GB (huggingface.co). Free space: {free / 1e9:.0f} GB")
    if free < total * 1.05:
        fail("Not enough free disk space.")
    if not yes("  Start the download?", assume):
        fail("Rendering needs the models. Run setup again when you are ready.")
    for folder, repo, path, dest, size, digest in todo:
        dest.parent.mkdir(parents=True, exist_ok=True)
        say(f"  ↓ {dest.name}")
        download(repo, path, dest, size, digest)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--comfy-python", required=True)
    p.add_argument("--comfy-cwd", required=True)
    p.add_argument("--comfy-cmd-file", required=True, help="JSON list of the ComfyUI start command")
    p.add_argument("--models-dir", required=True)
    p.add_argument("--portable", action="store_true")
    p.add_argument("--yes", action="store_true")
    a = p.parse_args()

    say("\n[3/5] App environment")
    py = app_python(a.comfy_python, a.portable)
    install_packages(py)
    say("\n[4/5] Models")
    ensure_models(a.models_dir, a.yes)

    oda = sorted(glob.glob(r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe"), reverse=True)
    cfg = {"server": "http://127.0.0.1:8188", "python": str(py), "comfy_cwd": a.comfy_cwd,
           "lang": "en", "comfy_cmd": json.loads(Path(a.comfy_cmd_file).read_text(encoding="utf-8-sig")), "models_dir": a.models_dir, "app_port": 7860}
    if oda:
        cfg["oda"] = oda[0]
    (ROOT / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    if not (ROOT / "examples" / "ornek_proje.dwg").exists() and not (ROOT / "examples" / "ornek_proje.dxf").exists():
        subprocess.run([str(py), str(ROOT / "tools" / "make_sample.py"), str(ROOT / "examples" / "ornek_proje.dxf")])
    say("  Settings saved.")


if __name__ == "__main__":
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    main()
