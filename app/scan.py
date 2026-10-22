# -*- coding: utf-8 -*-
"""扫描照片文件夹：只读文件头里的拍摄时间 / GPS / 设备型号（exiftool），不修改、不复制任何照片。
支持断点续扫：文件大小和修改时间没变就跳过。"""
import json, os, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor

import db

PHOTO_ROOT = os.environ.get("PHOTO_ROOT", "/photos")
PHOTO_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".dng", ".arw", ".raf", ".cr2", ".cr3", ".nef", ".orf", ".rw2", ".pef", ".srw"}
VIDEO_EXT = {".mov", ".mp4", ".m4v"}
SKIP_DIR = ("@", "#", ".")                     # 群晖/绿联的缩略图、回收站、隐藏目录
SKIP_NAMES = {"$RECYCLE.BIN", "System Volume Information", "lost+found"}
TAGS = ["-DateTimeOriginal", "-CreateDate", "-CreationDate", "-SubSecTimeOriginal", "-GPSLatitude", "-GPSLongitude",
        "-Make", "-Model", "-OffsetTimeOriginal"]

STATE = {"running": False, "phase": "", "total": 0, "done": 0, "new": 0, "errors": 0, "started": 0, "msg": ""}


def walk(root):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    n = e.name
                    if e.is_dir(follow_symlinks=False):
                        if not n.startswith(SKIP_DIR) and n not in SKIP_NAMES:
                            stack.append(e.path)
                    elif e.is_file(follow_symlinks=False) and not n.startswith("._"):
                        ext = os.path.splitext(n)[1].lower()
                        if ext in PHOTO_EXT or ext in VIDEO_EXT:
                            st = e.stat()
                            yield e.path, st.st_size, st.st_mtime, ("video" if ext in VIDEO_EXT else "photo")
        except OSError:
            continue


def folder_of(path):
    """相对照片根目录的前两级文件夹，用来让用户排除"不是自己拍的"文件夹"""
    rel = os.path.relpath(path, PHOTO_ROOT).split(os.sep)[:-1]
    return "/".join(rel[:2]) if rel else "(根目录)"


def _dt(s):
    """'2019:05:01 10:20:30+08:00' → '2019-05-01 10:20:30'（只取当地时钟时间）"""
    if not s or not isinstance(s, str) or len(s) < 19 or s.startswith("0000"):
        return None
    t = s[:19].replace(":", "-", 2)
    try:
        y = int(t[:4])
    except ValueError:
        return None
    if y < 1990 or y > time.localtime().tm_year + 1:
        return None
    return t


def run_exiftool(paths):
    cmd = ["exiftool", "-j", "-n", "-fast2", "-q", "-q", "-charset", "filename=utf8", *TAGS, "-@", "-"]
    try:
        p = subprocess.run(cmd, input="\n".join(paths).encode("utf-8"), capture_output=True, timeout=900)
        data = json.loads(p.stdout.decode("utf-8", "replace") or "[]")
    except Exception:
        data = []
    out = {}
    for r in data:
        src = r.get("SourceFile")
        if not src:
            continue
        kind = "video" if os.path.splitext(src)[1].lower() in VIDEO_EXT else "photo"
        if kind == "video":
            dt = _dt(r.get("CreationDate")) or None        # iPhone 视频：带时区的当地时间；其他视频不取时间
        else:
            dt = _dt(r.get("DateTimeOriginal")) or _dt(r.get("CreateDate"))
        la, lo = r.get("GPSLatitude"), r.get("GPSLongitude")
        if not isinstance(la, (int, float)) or not isinstance(lo, (int, float)) or (abs(la) < 1e-6 and abs(lo) < 1e-6):
            la = lo = None
        out[src] = dict(make=str(r.get("Make") or "").strip(), model=str(r.get("Model") or "").strip(), dt=dt,
                        subsec=str(r.get("SubSecTimeOriginal") or ""), lat=la, lon=lo)
    return out


def scan(workers=3, batch=300):
    if STATE["running"]:
        return
    STATE.update(running=True, phase="列出文件", total=0, done=0, new=0, errors=0, started=time.time(), msg="")
    con = db.connect()
    try:
        known = {p: (s, m) for p, s, m in con.execute("SELECT path, size, mtime FROM files")}
        todo, seen = [], set()
        for path, size, mtime, kind in walk(PHOTO_ROOT):
            seen.add(path)
            STATE["total"] += 1
            if known.get(path) != (size, mtime):
                todo.append((path, size, mtime, kind))
        gone = [p for p in known if p not in seen]
        with db._lock:
            con.executemany("DELETE FROM files WHERE path=?", [(p,) for p in gone]); con.commit()
        STATE.update(phase="读取拍摄信息", done=STATE["total"] - len(todo), new=len(todo))
        chunks = [todo[i:i + batch] for i in range(0, len(todo), batch)]

        def work(chunk):
            return chunk, run_exiftool([c[0] for c in chunk])

        with ThreadPoolExecutor(workers) as ex:
            for chunk, meta in ex.map(work, chunks):
                rows = []
                for path, size, mtime, kind in chunk:
                    m = meta.get(path)
                    if m is None:
                        STATE["errors"] += 1
                        rows.append((path, size, mtime, kind, folder_of(path), "", "", None, "", None, None, "读取失败"))
                    else:
                        rows.append((path, size, mtime, kind, folder_of(path), m["make"], m["model"], m["dt"], m["subsec"],
                                     m["lat"], m["lon"], ""))
                with db._lock:
                    con.executemany("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows); con.commit()
                STATE["done"] += len(chunk)
        with db._lock:
            con.execute("INSERT OR IGNORE INTO folders(folder) SELECT DISTINCT folder FROM files")
            con.execute("INSERT OR IGNORE INTO devices(model) SELECT DISTINCT model FROM files WHERE model!=''")
            con.commit()
        db.kv_set(con, "last_scan", time.strftime("%Y-%m-%d %H:%M"))
        STATE.update(phase="完成", msg=f"共 {STATE['total']:,} 个文件，本次新读 {len(todo):,} 个")
    except Exception as e:  # pragma: no cover
        STATE.update(phase="出错", msg=str(e))
    finally:
        STATE["running"] = False
        con.close()


def start():
    threading.Thread(target=scan, daemon=True).start()
