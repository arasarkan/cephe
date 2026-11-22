"""Local web app: drop a drawing, pick options, get consistent facade renders and a presentation sheet.

  python app/server.py            (Start.bat does this and opens the browser)

Starts ComfyUI in the background (no window) when it is not already running, runs one render job at a
time on the GPU, and serves the single-page UI from app/static.
"""
import atexit
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
import zipfile
from dataclasses import fields
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import materials  # noqa: E402
from core.comfy import Comfy, ComfyError  # noqa: E402
from core.i18n import UserError, lang_of, t  # noqa: E402
from core.project import SECONDS, Project, read_input  # noqa: E402
from core.scene import Scene, options_for_ui  # noqa: E402

CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8")) if (ROOT / "config.json").exists() else {}
PROJECTS = ROOT / "projects"
PORT = int(os.environ.get("PORT") or CONFIG.get("app_port", 7860))
ACCEPT = {".dwg", ".dxf"}

app = Flask(__name__, static_folder=str(ROOT / "app" / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
app.json.sort_keys = False  # option lists keep their order (morning, noon, sunset...)
comfy = Comfy(CONFIG.get("server", "http://127.0.0.1:8188"))
projects, jobs = {}, {}
gpu_lock = threading.Lock()
comfy_state = {"state": "unknown", "message": ""}  # message: i18n key


# ---- ComfyUI in the background ------------------------------------------------------------------------
# Exactly one ComfyUI: every start goes through one lock, a ComfyUI that is still loading is waited for
# instead of started again, and one left over from an earlier session is adopted. (Two copies each load the
# 12 GB model into RAM; that starved the machine and made renders fail.)
comfy_lock = threading.Lock()
comfy_proc = None  # the ComfyUI we started, so it can be shut down with the app


def comfy_pids():
    """PIDs of ComfyUI processes for our port (Windows), including ones a previous app session left."""
    if sys.platform != "win32":
        return []
    port = CONFIG.get("server", "http://127.0.0.1:8188").rsplit(":", 1)[-1].strip("/")
    ps = (f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {{ $_.CommandLine -match 'main\\.py' -and "
          f"$_.CommandLine -match '--port {port}\\b' }} | ForEach-Object {{ $_.ProcessId }}")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=30, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(x) for x in out.split() if x.isdigit()]


def wait_alive(seconds):
    for _ in range(seconds):
        if comfy.alive():
            comfy_state.update(state="ready", message="")
            return True
        time.sleep(1)
    return False


def start_comfy():
    """Start ComfyUI headless unless one is running or starting. Uses the command from config.json."""
    global comfy_proc
    with comfy_lock:
        if comfy.alive():
            comfy_state.update(state="ready", message="")
            return
        cmd = CONFIG.get("comfy_cmd")
        if not cmd:
            comfy_state.update(state="missing", message="engine_missing")
            return
        comfy_state.update(state="starting", message="engine_starting")
        if comfy_pids():  # one is already loading (ours, or left by an earlier session): wait for it
            if wait_alive(240):
                return
            stop_comfy(comfy_pids())  # hung: replace it
        log = open(ROOT / "comfyui.log", "a", encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        comfy_proc = subprocess.Popen(cmd, cwd=CONFIG.get("comfy_cwd"), stdout=log, stderr=subprocess.STDOUT,
                                      creationflags=flags)
        if not wait_alive(240):
            comfy_state.update(state="error", message="engine_failed")


def stop_comfy(pids):
    """Kill whole process trees: on Windows a venv's python.exe is a launcher with the real Python as its
    child, so killing only the launcher leaves ComfyUI running."""
    for pid in pids:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)


def shutdown_comfy():
    if comfy_proc is not None and comfy_proc.poll() is None:
        stop_comfy([comfy_proc.pid])


def ensure_comfy():
    if not comfy.alive():
        start_comfy()  # waits if another thread is already starting it
    if not comfy.alive():
        raise ComfyError(comfy_state["message"] or "engine_not_running")
    comfy_state["state"] = "ready"


# ---- projects ---------------------------------------------------------------------------------------------
def get_project(pid):
    if pid not in projects:
        folder = PROJECTS / pid
        src = next(folder.glob("input.*"), None) if folder.is_dir() else None
        if src is None:
            abort(404)
        p = Project(folder, read_input(src))
        meta = folder / "project.json"
        info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        p.name, p.name_key = info.get("name", pid), info.get("name_key")
        projects[pid] = p
    return projects[pid]


def lang():
    """UI language of this request: ?lang=, a JSON/form field, or the configured default."""
    data = request.get_json(silent=True) or {}
    return lang_of(request.args.get("lang") or data.get("lang") or request.form.get("lang") or CONFIG.get("lang"))


def scene_from(data):
    names = {f.name for f in fields(Scene)}
    s = Scene(**{k: v for k, v in data.items() if k in names})
    if isinstance(s.wall, list):
        s.wall = tuple(s.wall)
    return s


@app.get("/")
def index():
    return send_from_directory(ROOT / "app" / "static", "index.html")


@app.get("/api/status")
def status():
    alive = comfy.alive()
    if alive:
        comfy_state.update(state="ready", message="")
    gpu = comfy.gpu()[0] if alive else ""
    m = re.search(r"cuda:\d+\s+(.*?)\s*(?::|$)", gpu)  # "cuda:0 NVIDIA GeForce RTX 4050 Laptop GPU : cudaMallocAsync"
    gpu = (m.group(1) if m else gpu).replace("NVIDIA GeForce ", "")
    msg = t(comfy_state["message"], lang()) if comfy_state["message"] else ""
    return jsonify({"comfy": comfy_state["state"] if not alive else "ready", "message": msg,
                    "gpu": gpu, "busy": gpu_lock.locked()})


@app.get("/api/options")
def options():
    return jsonify({"scene": options_for_ui(lang()), "catalog": materials.catalog_for_ui(lang()),
                    "wall_default": list(materials.WALL_DEFAULT), "seconds": SECONDS})


@app.post("/api/projects")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": t("no_file", lang())}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ACCEPT:
        return jsonify({"error": t("unsupported_type", lang(), ext=ext)}), 400
    tmp = PROJECTS / "_uploads" / f"{uuid.uuid4().hex}{ext}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    f.save(tmp)
    try:
        return open_project(tmp, Path(f.filename).stem)
    finally:
        tmp.unlink(missing_ok=True)


@app.post("/api/projects/sample")
def sample():
    src = next((ROOT / "examples").glob("ornek_proje.*"), None)
    if src is None:
        return jsonify({"error": t("sample_missing", lang())}), 404
    return open_project(src, t("sample_name", lang()), key="sample_name")


def open_project(src, name, key=None):
    """key: an i18n key for the name (the sample), so the sheet shows it in the render's language."""
    try:
        p = Project.create(src, PROJECTS)
    except UserError as e:
        return jsonify({"error": e.message(lang())}), 400
    p.name, p.name_key = name, key
    (p.folder / "project.json").write_text(json.dumps({"name": name, "name_key": key}, ensure_ascii=False),
                                           encoding="utf-8")
    projects[p.folder.name] = p
    s = p.summary(lang())
    if not any(v["renderable"] for v in s["views"]):
        s["warnings"].append(t("no_facades_warning", lang()))
    return jsonify(s)


@app.get("/api/projects/<pid>/thumb/<int:vid>.png")
def thumb(pid, vid):
    return send_from_directory(PROJECTS / pid / "thumbs", f"{vid}.png")


@app.get("/api/projects/<pid>/files/<path:rel>")
def project_file(pid, rel):
    return send_from_directory(PROJECTS / pid, rel)


@app.get("/api/projects/<pid>/download/<run>.zip")
def download(pid, run):
    folder = (PROJECTS / pid / run).resolve()
    if not folder.is_dir() or PROJECTS.resolve() not in folder.parents:
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in folder.iterdir():
            if f.is_file():
                z.write(f, f.name)
    buf.seek(0)
    name = get_project(pid).name
    return send_file(buf, as_attachment=True, download_name=f"{name}_{run}.zip", mimetype="application/zip")


# ---- render jobs ------------------------------------------------------------------------------------------
def run_job(job, p, scene, views, final):
    try:
        with gpu_lock:
            job.update(state="running", message=t("engine_preparing", scene.lang))
            ensure_comfy()
            comfy.check()

            def progress(frac, msg):
                job.update(progress=frac, message=msg)
            out, meta = p.render(comfy, scene, views, final, progress, stop=lambda: job["cancel"])
        base = f"/api/projects/{p.folder.name}/files/{out.name}"
        job.update(state="done", progress=1.0, message=t("done", scene.lang), result={
            "images": [{"title": r["title"], "url": f"{base}/{r['image']}", "light": r["light"],
                        "fidelity": r["fidelity"]["score"], "grade": r["fidelity"]["grade"],
                        "drift": f"{base}/{r['fidelity']['drift']}"}
                       for r in meta["results"]],
            "sheet": f"{base}/{meta['sheet'][0]}", "pdf": f"{base}/{meta['sheet'][1]}",
            "zip": f"/api/projects/{p.folder.name}/download/{out.name}.zip"})
    except InterruptedError:
        job.update(state="cancelled", message=t("cancelled", scene.lang))
    except UserError as e:
        job.update(state="error", message=e.message(scene.lang) if not job["cancel"] else t("cancelled", scene.lang))
    except Exception as e:  # unexpected: keep the trace for support
        (ROOT / "error.log").open("a", encoding="utf-8").write(traceback.format_exc())
        job.update(state="error", message=t("unexpected", scene.lang, error=e))


@app.post("/api/projects/<pid>/render")
def render(pid):
    p = get_project(pid)
    data = request.get_json(force=True)
    scene = scene_from(data.get("scene", {}))
    scene.lang = lang()
    views = [int(v) for v in data.get("views", [])]
    final = bool(data.get("final"))
    jid = uuid.uuid4().hex[:10]
    job = jobs[jid] = {"id": jid, "state": "queued", "progress": 0.0, "message": t("queued", scene.lang), "cancel": False,
                       "estimate": SECONDS["final" if final else "preview"] * max(1, len(views)),
                       "started": time.time()}
    threading.Thread(target=run_job, args=(job, p, scene, views, final), daemon=True).start()
    return jsonify({"job": jid})


@app.get("/api/jobs/<jid>")
def job_status(jid):
    job = jobs.get(jid) or abort(404)
    return jsonify({k: v for k, v in job.items() if k != "cancel"} | {"elapsed": time.time() - job["started"]})


@app.post("/api/jobs/<jid>/cancel")
def cancel(jid):
    job = jobs.get(jid) or abort(404)
    job["cancel"] = True
    return jsonify({"ok": True})


def main():
    for stream in (sys.stdout, sys.stderr):  # non-ASCII text on a cp1252/cp857 console must not crash us
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    PROJECTS.mkdir(exist_ok=True)
    atexit.register(shutdown_comfy)
    threading.Thread(target=start_comfy, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}"
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"Cephe: {url}  (close this window to quit)")
    app.run(host="127.0.0.1", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
