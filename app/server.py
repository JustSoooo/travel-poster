# -*- coding: utf-8 -*-
"""网页界面：扫描 → 确认设备 → 生成海报。只在局域网里用，不要映射到公网。"""
import hashlib, io, os, subprocess, urllib.parse, threading, time, traceback, zipfile

from flask import Flask, jsonify, request, send_file, send_from_directory, abort

import analyze, db, render, scan

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(HERE, "static"), static_url_path="/static")
THUMBS = os.path.join(db.DATA_DIR, "thumbs")
GEN = {"running": False, "phase": "", "msg": "", "files": []}

try:
    from PIL import Image, ImageOps
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    Image = None


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def status():
    con = db.connect()
    n = con.execute("SELECT COUNT(*), SUM(dt IS NOT NULL), SUM(lat IS NOT NULL), SUM(kind='video') FROM files").fetchone()
    roots = []
    try:
        roots = sorted(d for d in os.listdir(scan.PHOTO_ROOT) if not d.startswith((".", "@", "#"))
                       and not os.path.exists(os.path.join(scan.PHOTO_ROOT, d, "data", "poster.db")))
    except OSError:
        pass
    res = analyze.load()
    gen = dict(GEN)
    if not gen["files"] and os.path.isdir(render.OUT):
        gen["files"] = sorted(f for f in os.listdir(render.OUT) if f.endswith(".png"))
    out = dict(scan=scan.STATE, gen=gen, files=n[0] or 0, dated=n[1] or 0, gps=n[2] or 0, videos=n[3] or 0,
               last_scan=db.kv_get(con, "last_scan"), roots=roots, photo_root=scan.PHOTO_ROOT,
               has_result=bool(res), built=res and res.get("built"), n_trips=res and len(res["trips"]))
    con.close()
    return jsonify(out)


@app.post("/api/scan")
def start_scan():
    scan.start()
    return jsonify(ok=True)


@app.get("/api/devices")
def devices():
    con = db.connect()
    rep = analyze.device_report(con)
    folders = con.execute("""SELECT f.folder, f.excluded, COUNT(x.path) FROM folders f LEFT JOIN files x ON x.folder=f.folder
                             GROUP BY f.folder ORDER BY f.folder""").fetchall()
    con.close()
    return jsonify(devices=rep, folders=[dict(folder=a, excluded=bool(b), n=c) for a, b, c in folders])


@app.post("/api/devices")
def save_devices():
    data = request.get_json(force=True)
    con = db.connect()
    with db._lock:
        for m, o in (data.get("owners") or {}).items():
            if o in ("me", "companion", "other", ""):
                con.execute("INSERT INTO devices(model, owner) VALUES(?,?) ON CONFLICT(model) DO UPDATE SET owner=excluded.owner", (m, o))
        for f, ex in (data.get("folders") or {}).items():
            con.execute("INSERT INTO folders(folder, excluded) VALUES(?,?) ON CONFLICT(folder) DO UPDATE SET excluded=excluded.excluded",
                        (f, 1 if ex else 0))
        con.commit()
    con.close()
    return jsonify(ok=True)


def _pid(path):
    return hashlib.md5(path.encode("utf-8")).hexdigest()[:12]


def _thumb(path, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".heic", ".heif") and Image is not None:
        try:
            im = Image.open(path); im.draft("RGB", (480, 480)); im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((360, 360)); im.save(out, "JPEG", quality=78)
            return True
        except Exception:
            pass
    for tag in ("-PreviewImage", "-JpgFromRaw", "-ThumbnailImage"):
        try:
            b = subprocess.run(["exiftool", "-b", tag, path], capture_output=True, timeout=30).stdout
            if len(b) > 1000 and Image is not None:
                im = Image.open(io.BytesIO(b)).convert("RGB"); im.thumbnail((360, 360)); im.save(out, "JPEG", quality=78)
                return True
        except Exception:
            continue
    return False


@app.get("/api/samples")
def samples():
    """某台设备按时间均匀抽 8 张（只取照片），给用户判断是不是自己的"""
    model = request.args.get("model", "")
    con = db.connect()
    rows = con.execute("""SELECT path, dt, lat, lon FROM files WHERE model=? AND kind='photo' AND dt IS NOT NULL
                          ORDER BY dt""", (model,)).fetchall()
    con.close()
    if len(rows) > 8:
        rows = [rows[int(i * len(rows) / 8)] for i in range(8)]
    g = analyze.geo()
    out = []
    for path, d, la, lo in rows:
        place = ""
        if la is not None:
            p = g.place(la, lo); place = p["name"] or p["en"]
        out.append(dict(id=_pid(path), dt=d[:16], place=place, p=path))
    return jsonify([dict(url=f"/api/thumb?p={r['id']}&m={urllib.parse.quote(model)}", dt=r["dt"], place=r["place"]) for r in out])


@app.get("/api/thumb")
def thumb():
    pid, model = request.args.get("p", ""), request.args.get("m", "")
    out = os.path.join(THUMBS, f"{pid}.jpg")
    if not os.path.exists(out):
        con = db.connect()
        rows = con.execute("SELECT path FROM files WHERE model=? AND kind='photo'", (model,)).fetchall()
        con.close()
        path = next((r[0] for r in rows if _pid(r[0]) == pid), None)
        if not path or not _thumb(path, out):
            abort(404)
    return send_file(out, mimetype="image/jpeg", max_age=86400)


def _generate(scale):
    GEN.update(running=True, phase="分析旅程", msg="", files=[])
    try:
        res = analyze.run()
        GEN["phase"] = "生成海报"
        GEN["files"] = [os.path.basename(f) for f in render.png_all(scale=1)]
        if scale == 2:
            GEN["files"] += [os.path.basename(f) for f in render.png_all(scale=2)]
        GEN.update(phase="完成", msg=f"{len(res['trips'])} 趟旅程")
    except Exception as e:
        GEN.update(phase="出错", msg=f"{e}\n{traceback.format_exc()[-800:]}")
    finally:
        GEN["running"] = False


def _auto(scale):
    """一键：扫描（只读新增）→ 用系统建议的设备归属分析 → 出图"""
    GEN.update(running=True, phase="扫描照片", msg="", files=[])
    try:
        scan.scan()
        if scan.STATE.get("phase") == "出错":
            raise RuntimeError("扫描出错：" + scan.STATE.get("msg", ""))
    except Exception as e:
        GEN.update(running=False, phase="出错", msg=str(e))
        return
    _generate(scale)


@app.post("/api/auto")
def auto():
    if not GEN["running"] and not scan.STATE["running"]:
        scale = int((request.get_json(silent=True) or {}).get("scale", 1))
        threading.Thread(target=_auto, args=(scale,), daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/generate")
def generate():
    if not GEN["running"]:
        scale = int((request.get_json(silent=True) or {}).get("scale", 1))
        threading.Thread(target=_generate, args=(scale,), daemon=True).start()
    return jsonify(ok=True)


@app.get("/posters/<path:name>")
def poster_file(name):
    return send_from_directory(render.OUT, name, as_attachment=request.args.get("dl") == "1")


@app.get("/api/posters.zip")
def posters_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted(os.listdir(render.OUT)):
            if f.endswith(".png"):
                z.write(os.path.join(render.OUT, f), f)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="旅行海报.zip")


@app.get("/api/trips")
def trips():
    res = analyze.load() or {"trips": []}
    return jsonify([dict(id=t["id"], start=t["start"], end=t["end"], days=t["days"], n=t["n"], name=t["name"],
                         auto=t["auto_name"]) for t in res["trips"]])


@app.post("/api/trips")
def save_trips():
    data = request.get_json(force=True) or {}
    con = db.connect()
    with db._lock:
        for tid, name in data.items():
            name = (name or "").strip()
            if name:
                con.execute("INSERT INTO trip_names VALUES(?,?) ON CONFLICT(trip_id) DO UPDATE SET name=excluded.name", (tid, name))
            else:
                con.execute("DELETE FROM trip_names WHERE trip_id=?", (tid,))
        con.commit()
    con.close()
    return jsonify(ok=True)


if __name__ == "__main__":
    db.connect().close()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8090)), threaded=True)
