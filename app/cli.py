# -*- coding: utf-8 -*-
"""终端版：扫描照片 → 确认设备 → 生成四张海报。不需要 Docker、不开网页。
用法：python cli.py <照片文件夹> [--out 输出文件夹] [--yes]
  --yes   不问问题，设备按建议处理（适合第二次以后直接重跑）
照片只读，不修改、不移动、不上传；扫描结果放在 DATA_DIR（默认 ~/.travel-poster/data）
"""
import argparse, os, shutil, subprocess, sys, threading, time


def main():
    ap = argparse.ArgumentParser(description="旅行海报 · 终端版")
    ap.add_argument("photos", help="照片所在的文件夹（外接硬盘也可以）")
    ap.add_argument("--out", default=os.path.expanduser("~/Desktop/旅行海报"), help="海报输出到哪（默认桌面/旅行海报）")
    ap.add_argument("--data", default=os.path.expanduser("~/.travel-poster/data"), help="扫描结果存哪")
    ap.add_argument("--yes", action="store_true", help="不提问，设备按建议")
    ap.add_argument("--rescan", action="store_true", help="忽略上次结果，全部重新读")
    a = ap.parse_args()
    root = os.path.abspath(os.path.expanduser(a.photos.strip().strip("'\"")))
    if not os.path.isdir(root):
        sys.exit(f"找不到这个文件夹：{root}")
    os.environ["PHOTO_ROOT"] = root
    os.environ["DATA_DIR"] = os.path.join(os.path.abspath(a.data), _slug(root))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import analyze, db, render, scan

    if shutil.which("exiftool") is None:
        sys.exit("缺少 exiftool（读照片拍摄信息用的）。请用一键脚本运行，它会自动装好。")
    if a.rescan and os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)

    # ---------------- 1. 扫描
    print(f"\n① 扫描照片：{root}\n   只读文件头（时间、位置、设备），不会改动任何照片。第一次十几万张大约 20–60 分钟，下次只读新增的。")
    t = threading.Thread(target=scan.scan, kwargs=dict(workers=max(2, min(6, (os.cpu_count() or 4) - 1))), daemon=True)
    t.start(); time.sleep(0.5)
    last = ""
    while t.is_alive():
        s = scan.STATE
        if s["phase"] == "列出文件":
            line = f"   正在列出文件… 已找到 {s['total']:,} 个"
        else:
            done, tot = s["done"], s["total"] or 1
            el = time.time() - s["started"]; new_done = done - (tot - s["new"])
            eta = (s["new"] - new_done) * el / new_done if new_done > 200 else 0
            line = f"   读取拍摄信息 {done:,}/{tot:,}（{100 * done / tot:.0f}%）" + (f"，还要约 {eta / 60:.0f} 分钟" if eta > 60 else "")
        if line != last:
            print("\r" + line.ljust(60), end="", flush=True); last = line
        time.sleep(1)
    print("\r   " + (scan.STATE["msg"] or "完成").ljust(60))
    if scan.STATE["phase"] == "出错":
        sys.exit("扫描出错：" + scan.STATE["msg"])
    con = db.connect()
    n, ng = con.execute("SELECT COUNT(*), SUM(lat IS NOT NULL) FROM files WHERE dt IS NOT NULL").fetchone()
    if not n:
        sys.exit("没找到带拍摄时间的照片。确认选的是放照片的文件夹 / 硬盘。")
    print(f"   有拍摄时间的 {n:,} 个，其中带位置 {ng or 0:,} 个")

    # ---------------- 2. 设备
    rep = analyze.device_report(con)
    rep = [r for r in rep if r["n"] >= 5]
    print("\n② 这些设备是谁的？（别人发来的照片会带着别人的位置，海报上就会多出没去过的地方）\n")
    print(f"   {'编号':<4}{'设备':<24}{'张数':>8}  {'时间':<23}{'建议':<6}说明")
    for i, r in enumerate(rep, 1):
        cur = r["owner"] or r["suggest"]
        tag = "别人" if cur == "other" else "同行" if cur == "companion" else "我的"
        mark = "⚠ " if cur == "other" else "  "
        print(f"   {i:<4}{r['model'][:22]:<24}{r['n']:>8,}  {r['first']}～{r['last']}  {mark}{tag:<4}{r['why'] if not r['owner'] else '（上次的选择）'}")
    owners = {r["model"]: (r["owner"] or r["suggest"]) for r in rep}
    if not a.yes and sys.stdin.isatty():
        print("\n   直接回车 = 按「建议」那一列。")
        print("   要改：输入编号，比如「3 7」= 把 3 号、7 号设为别人的；「+5」= 把 5 号改回我的；改完再回车。")
        while True:
            try:
                s = input("   > ").strip()
            except EOFError:
                s = ""
            if not s:
                break
            for tok in s.replace(",", " ").replace("，", " ").split():
                back = tok.startswith("+"); tok = tok.lstrip("+")
                if tok.isdigit() and 1 <= int(tok) <= len(rep):
                    m = rep[int(tok) - 1]["model"]; owners[m] = "me" if back else "other"
                    print(f"     {tok} 号 {m} → {'我的' if back else '别人'}")
                else:
                    print(f"     看不懂「{tok}」，跳过")
    with db._lock:
        for m, o in owners.items():
            con.execute("INSERT INTO devices(model, owner) VALUES(?,?) ON CONFLICT(model) DO UPDATE SET owner=excluded.owner", (m, o))
        con.commit()
    con.close()

    # ---------------- 3. 分析 + 出图
    print("\n③ 切分旅程、生成海报…")
    res = analyze.run()
    print(f"   {len(res['trips'])} 趟旅程")
    if not res["trips"]:
        sys.exit("没找到离开常住地的旅程（可能照片都没有位置信息）。")
    files = render.png_all(scale=1) + render.png_all(scale=2)
    os.makedirs(a.out, exist_ok=True)
    for f in files:
        shutil.copy2(f, os.path.join(a.out, os.path.basename(f)))
    print(f"\n✅ 完成：{len(files)} 张图在 {a.out}")
    print("   不带 @2x 的是 1206×2622（手机全屏），带 @2x 的是 2412×5244（超高清，适合打印）")
    print("   海报上出现了没去过的地方 → 重新运行一次，在第②步把那台设备设为别人的。")
    if sys.platform == "darwin":
        subprocess.run(["open", a.out])


def _slug(p):
    import hashlib
    return os.path.basename(p.rstrip("/")).replace(" ", "_")[:30] + "-" + hashlib.md5(p.encode()).hexdigest()[:6]


if __name__ == "__main__":
    main()
