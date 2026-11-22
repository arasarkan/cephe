"""Record the README demo: drives the running app in Edge and saves docs/demo.gif.

    python tools/record_demo.py <result.json of a finished presentation render> [--lang tr]

The app must be running (Start.bat). The render itself is not re-run: the finished result is shown in the page,
so the GIF stays short. Needs `pip install playwright` (uses the installed Microsoft Edge).
"""
import argparse
import io
import json
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:7860"
W, H = 1280, 800
OUT_W = 960


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result", help="projects/<id>/<run>/result.json")
    ap.add_argument("--lang", default="tr")
    a = ap.parse_args()
    run = Path(a.result).resolve().parent
    meta = json.loads(Path(a.result).read_text(encoding="utf-8"))
    base = f"/api/projects/{run.parent.name}/files/{run.name}"
    result = {
        "images": [{"title": r["title"], "url": f"{base}/{r['image']}", "light": r["light"],
                    "fidelity": r["fidelity"]["score"], "grade": r["fidelity"]["grade"],
                    "drift": f"{base}/{r['fidelity']['drift']}"} for r in meta["results"]],
        "sheet": f"{base}/{meta['sheet'][0]}", "pdf": f"{base}/{meta['sheet'][1]}", "zip": "#"}

    frames = []  # (image, ms)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": W, "height": H})
        page.add_init_script(f"try {{ localStorage.setItem('lang', '{a.lang}') }} catch (e) {{}}")
        page.goto(URL)
        page.wait_for_function("document.getElementById('engine').textContent.length > 0")
        page.wait_for_timeout(800)

        def shot(ms):
            frames.append((Image.open(io.BytesIO(page.screenshot())).convert("RGB"), ms))

        def scroll_to(y, steps=8, ms=60):
            start = page.evaluate("scrollY")
            for i in range(1, steps + 1):
                t = i / steps
                t = t * t * (3 - 2 * t)  # ease in-out
                page.evaluate(f"window.scrollTo(0, {start + (y - start) * t})")
                shot(ms)

        def top_of(sel, offset=60):
            return page.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top + scrollY - {offset}")

        shot(1800)
        page.click("#sample")
        page.wait_for_selector("#s-views:not(.hidden) .view img")
        page.wait_for_timeout(1200)
        shot(500)
        scroll_to(top_of("#s-views"))
        shot(2200)
        scroll_to(top_of("#s-scene"))
        shot(2300)  # left as rendered: the result shown below was made with these settings
        scroll_to(top_of("#mats-wrap"), steps=6)
        shot(1800)
        scroll_to(top_of("#s-render"))
        shot(1600)
        # the finished presentation render
        page.evaluate("(r) => { lastFinal = true; lastResult = r; showResult(r); }", result)
        page.wait_for_function("[...document.querySelectorAll('#s-result img')].every(i => i.complete && i.naturalWidth)")
        scroll_to(top_of("#s-result"), steps=10)
        shot(2600)
        scroll_to(top_of("#gallery", 40), steps=10)
        shot(2200)
        page.click("[data-diff='0']")
        page.wait_for_function("document.getElementById('g0').complete && document.getElementById('g0').naturalWidth")
        page.wait_for_timeout(300)
        shot(2800)
        page.click("[data-diff='0']")
        page.wait_for_timeout(400)
        shot(1600)
        browser.close()

    out = ROOT / "docs" / "demo.gif"
    imgs = [im.resize((OUT_W, int(im.height * OUT_W / im.width)), Image.LANCZOS) for im, _ in frames]
    pal = [im.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG) for im in imgs]
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=[ms for _, ms in frames], loop=0,
                optimize=True, disposal=1)
    print(out, f"{out.stat().st_size / 1e6:.1f} MB", len(frames), "frames")


if __name__ == "__main__":
    main()
