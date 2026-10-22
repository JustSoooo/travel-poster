# -*- coding: utf-8 -*-
"""海报 HTML（Jinja 模板）→ PNG（无头 Chromium 截图）"""
import os, threading

from jinja2 import Environment, FileSystemLoader, select_autoescape

import analyze, db, poster

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(db.DATA_DIR, "posters")
POSTERS = [("main", "总海报"), ("revisit", "重访篇"), ("yearly", "年鉴篇")]
env = Environment(loader=FileSystemLoader(os.path.join(HERE, "templates")), autoescape=select_autoescape(["html"]))
_lock = threading.Lock()


def html_all():
    res = analyze.load()
    if not res:
        return None
    S = poster.build(res)
    if not S:
        return {}
    return {k: env.get_template(f"{k}.html").render(S=S) for k, _ in POSTERS}


def png_all(scale=1):
    """生成三张 PNG（1206×2622，iPhone 17 Pro 全屏；scale=2 时为 2412×5244）"""
    pages = html_all()
    if not pages:
        return []
    os.makedirs(OUT, exist_ok=True)
    from playwright.sync_api import sync_playwright
    exe = os.environ.get("CHROMIUM_PATH") or None
    files = []
    with _lock, sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = b.new_page(viewport={"width": 1206, "height": 2622}, device_scale_factor=scale)
        for k, label in POSTERS:
            pg.set_content(pages[k], wait_until="load")
            pg.wait_for_timeout(300)
            f = os.path.join(OUT, f"{label}{'@2x' if scale == 2 else ''}.png")
            pg.screenshot(path=f, full_page=False)
            files.append(f)
        b.close()
    return files
