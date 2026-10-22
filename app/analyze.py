# -*- coding: utf-8 -*-
"""从扫描结果算出：每天在哪、家在哪、哪些天在外面、切成一趟趟旅程、给旅程起名。
时间一律用照片里的「当地时钟时间」（不做时区换算），足够判断哪天在哪。"""
import bisect, collections, datetime as dt, json, os, re, statistics, time

import db
from geo import Geo, hav, COUNTRY_ZH, DOMESTIC

try:
    from lunardate import LunarDate
except Exception:  # pragma: no cover
    LunarDate = None

CAMERA_MAKES = ("sony", "fujifilm", "canon", "nikon", "panasonic", "olympus", "om digital", "leica", "ricoh", "pentax",
                "hasselblad", "sigma", "gopro", "dji", "insta360", "kodak", "casio", "samsung techwin")
RESULT = os.path.join(db.DATA_DIR, "result.json")
_geo = None


def geo():
    global _geo
    if _geo is None:
        _geo = Geo()
    return _geo


def P(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def is_camera(make, model):
    m = (make or "").lower()
    return any(m.startswith(c) for c in CAMERA_MAKES) and "iphone" not in (model or "").lower()


# ---------------------------------------------------------------- 设备
def device_report(con):
    """每台设备：数量、时间范围、有 GPS 的比例、和当天主力设备"打架"的天数 → 给出建议归属"""
    rows = con.execute("""SELECT model, make, dt, lat, lon, folder FROM files
                          WHERE model!='' AND dt IS NOT NULL""").fetchall()
    excl = {f for f, in con.execute("SELECT folder FROM folders WHERE excluded=1")}
    owners = dict(con.execute("SELECT model, owner FROM devices"))
    per = collections.defaultdict(lambda: dict(n=0, gps=0, first="9999", last="0000", make="", days=set(), folders=collections.Counter()))
    day_pts = collections.defaultdict(lambda: collections.defaultdict(list))
    for model, make, d, la, lo, folder in rows:
        if folder in excl:
            continue
        x = per[model]; x["n"] += 1; x["make"] = make or x["make"]
        x["first"] = min(x["first"], d); x["last"] = max(x["last"], d); x["days"].add(d[:10]); x["folders"][folder] += 1
        if la is not None:
            x["gps"] += 1; day_pts[d[:10]][model].append((la, lo))
    conflict = collections.Counter()
    for day, ms in day_pts.items():
        if len(ms) < 2:
            continue
        top = max(ms, key=lambda m: len(ms[m]))
        tla = statistics.median(p[0] for p in ms[top]); tlo = statistics.median(p[1] for p in ms[top])
        for m, pts in ms.items():
            if m == top:
                continue
            if hav(tla, tlo, statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts)) > 300:
                conflict[m] += 1
    total = sum(x["n"] for x in per.values()) or 1
    out = []
    for model, x in per.items():
        cam = is_camera(x["make"], model)
        nd = len(x["days"])
        if cam:
            sug, why = "me", "相机"
        elif conflict[model] >= 3 and conflict[model] >= 0.2 * nd:
            sug, why = "other", f"有 {conflict[model]} 天和你的主力手机相距 300 公里以上"
        elif x["n"] < 60 and x["n"] < total * 0.005:
            sug, why = "other", "照片很少，常见于别人发来的"
        else:
            sug, why = "me", "照片多、时间连续"
        out.append(dict(model=model, make=x["make"], n=x["n"], gps=x["gps"], first=x["first"][:10], last=x["last"][:10],
                        days=nd, conflict=conflict[model], suggest=sug, why=why, owner=owners.get(model) or "",
                        camera=cam, folders=x["folders"].most_common(3)))
    out.sort(key=lambda r: r["first"])
    return out


# ---------------------------------------------------------------- 节假日 + 起名
def holidays(year):
    h = [("元旦", dt.date(year, 1, 1), dt.date(year, 1, 1)), ("清明", dt.date(year, 4, 4), dt.date(year, 4, 6)),
         ("五一", dt.date(year, 5, 1), dt.date(year, 5, 5)), ("国庆", dt.date(year, 10, 1), dt.date(year, 10, 7))]
    if LunarDate:
        try:
            cny = LunarDate(year, 1, 1).toSolarDate()
            h.append(("春节", cny - dt.timedelta(days=1), cny + dt.timedelta(days=6)))
            dw = LunarDate(year, 5, 5).toSolarDate(); h.append(("端午", dw - dt.timedelta(days=1), dw + dt.timedelta(days=1)))
            zq = LunarDate(year, 8, 15).toSolarDate(); h.append(("中秋", zq - dt.timedelta(days=1), zq + dt.timedelta(days=1)))
        except Exception:
            pass
    return h


def trip_name(t):
    a, b = dt.date.fromisoformat(t["start"]), dt.date.fromisoformat(t["end"])
    mid = a + (b - a) / 2
    hol = ""
    cands = []
    for y in {a.year, b.year}:
        for n, s, e in holidays(y):
            ov = (min(b, e) - max(a, s)).days + 1
            if ov > 0:
                cands.append((n == "国庆", ov, n))
    if cands:
        hol = max(cands)[2]
    if a.month == 12 and b.month == 1 and not hol:
        hol = "跨年"
    # 地点：海外写国家/城市，国内写城市；城市太多就写省
    cities = t["cities"]                   # [(城市名, 国家码, 省, 天数)] 按天数降序
    abroad = [c for c in cities if c[1] not in DOMESTIC]
    ab_days = sum(c[3] for c in abroad)
    if abroad and ab_days >= 0.3 * sum(c[3] for c in cities):
        cd = collections.Counter()
        for c in abroad:
            cd[c[1]] += c[3]
        ccs = [c for c, k in cd.most_common() if k >= 0.2 * ab_days]
        zh = lambda s: bool(re.search(r"[一-鿿]", s))
        if len(ccs) >= 2:
            place = "·".join(COUNTRY_ZH.get(c, c) for c in ccs[:3])
        else:
            names = [c[0] for c in abroad if c[1] == ccs[0] and zh(c[0])][:2]
            place = "·".join(names) if names else COUNTRY_ZH.get(ccs[0], ccs[0])
            if len(abroad) >= 4 and names:
                place = f"{COUNTRY_ZH.get(ccs[0], ccs[0])}·{names[0]}"
    else:
        cities = [c for c in cities if c[1] in DOMESTIC] or cities
        main = [c for c in cities if c[3] >= max(1, 0.15 * t["days"])] or cities[:1]
        provs = list(dict.fromkeys(c[2] for c in cities if c[2]))
        if len(main) > 3 and len(provs) >= 2:
            place = "·".join(provs[:3])
        elif len(main) > 3:
            place = f"{provs[0]}·{main[0][0]}" if provs else "·".join(c[0] for c in main[:3])
        else:
            place = "·".join(c[0] for c in main[:3])
    return f"{mid.strftime('%Y-%m')}{' ' + hol if hol else ''} {place}".strip()


# ---------------------------------------------------------------- 主流程
def run(progress=None):
    t0 = time.time()
    con = db.connect()
    G = geo()
    excl = {f for f, in con.execute("SELECT folder FROM folders WHERE excluded=1")}
    rep = {r["model"]: r for r in device_report(con)}
    owner = {m: (r["owner"] or r["suggest"]) for m, r in rep.items()}
    rows = con.execute("""SELECT path, kind, make, model, dt, subsec, lat, lon, folder, size FROM files
                          WHERE dt IS NOT NULL""").fetchall()
    # 去重：同一台机器同一时刻（RAW+JPG、导出副本）只算一张
    shots = {}
    for path, kind, make, model, d, sub, la, lo, folder, size in rows:
        if folder in excl:
            continue
        own = owner.get(model, "me") if model else "me"
        if own == "other":
            continue
        key = (model, d, sub) if model else (d, size)
        old = shots.get(key)
        if old is None or (old["lat"] is None and la is not None):
            shots[key] = dict(kind=kind, model=model, make=make, dt=d, lat=la, lon=lo, own=own, native=la is not None)
    media = list(shots.values())
    # 定位参照点：自己和同行的设备、自带 GPS
    ref = sorted(((m["dt"], m["lat"], m["lon"]) for m in media if m["native"]), key=lambda r: r[0])
    rt = [r[0] for r in ref]
    for m in media:
        m["conf"] = "自带" if m["native"] else ""
        if m["native"]:
            continue
        i = bisect.bisect_left(rt, m["dt"]); best = None
        for j in (i - 1, i):
            if 0 <= j < len(ref):
                gap = abs((P(ref[j][0]) - P(m["dt"])).total_seconds()) / 60
                if best is None or gap < best[0]:
                    best = (gap, ref[j])
        if best and best[0] <= 60:
            m["lat"], m["lon"] = best[1][1], best[1][2]; m["conf"] = "近" if best[0] <= 10 else "远"
    mine = [m for m in media if m["own"] != "companion"]
    days = collections.defaultdict(list)
    for m in media:
        days[m["dt"][:10]].append(m)
    # 每天在哪：可信点的中位数
    day_info = {}
    for d, ms in days.items():
        pts = [(m["lat"], m["lon"]) for m in ms if m["lat"] is not None and m["conf"] in ("自带", "近")] or \
              [(m["lat"], m["lon"]) for m in ms if m["lat"] is not None]
        n_mine = sum(1 for m in ms if m["own"] != "companion")
        if pts:
            la = sorted(p[0] for p in pts)[len(pts) // 2]; lo = sorted(p[1] for p in pts)[len(pts) // 2]
            day_info[d] = dict(lat=la, lon=lo, n=n_mine, pts=pts)
        else:
            day_info[d] = dict(lat=None, lon=None, n=n_mine, pts=[])
    # 家：每季度照片最多的 0.5° 格子
    cell = lambda la, lo: (round(la * 2) / 2, round(lo * 2) / 2)
    qc = collections.defaultdict(collections.Counter); yc = collections.defaultdict(collections.Counter)
    for d, inf in day_info.items():
        if inf["lat"] is None:
            continue
        c = cell(inf["lat"], inf["lon"]); q = f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"
        qc[q][c] += 1; yc[d[:4]][c] += 1
    allc = collections.Counter()
    for c in yc.values():
        allc.update(c)

    def home_of(d):
        q = f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"
        if qc[q] and qc[q].most_common(1)[0][1] >= 15:
            return qc[q].most_common(1)[0][0]
        if yc[d[:4]]:
            return yc[d[:4]].most_common(1)[0][0]
        return allc.most_common(1)[0][0] if allc else None

    for d, inf in day_info.items():
        h = home_of(d); inf["home"] = h
        if h is None or not inf["pts"]:
            inf["away"] = None; continue
        far = sum(1 for la, lo in inf["pts"] if hav(la, lo, h[0], h[1]) > 80)
        inf["away"] = far / len(inf["pts"]) >= 0.5
        p = G.place(inf["lat"], inf["lon"]); c = G.city(inf["lat"], inf["lon"])
        inf.update(place=p["name"] or p["en"], city=c["name"] or c["en"], cc=p["cc"], prov=p["prov"])
    cell_days = collections.Counter(cell(i["lat"], i["lon"]) for i in day_info.values() if i["lat"] is not None)
    frequent = {c for c, n in cell_days.items() if n >= 45}

    def near_frequent(inf):
        if inf["lat"] is None:
            return None
        for c in frequent:
            if hav(inf["lat"], inf["lon"], c[0], c[1]) < 60:
                return c
        return None

    # 切旅程（规则同主项目）
    trips, cur, last = [], [], None
    for d in sorted(day_info):
        inf = day_info[d]; a = inf["away"]; dd = dt.date.fromisoformat(d)
        if a:
            if cur:
                prev = day_info[cur[-1]]; gap = (dd - last).days
                km = hav(prev["lat"], prev["lon"], inf["lat"], inf["lon"])
                f1, f2 = near_frequent(prev), near_frequent(inf)
                if gap > 3 or (gap >= 2 and km > 300) or (km > 300 and f1 != f2 and (f1 or f2)):
                    trips.append(cur); cur = []
            cur.append(d); last = dd
        elif a is False and cur:
            trips.append(cur); cur = []
    if cur:
        trips.append(cur)
    names = dict(con.execute("SELECT trip_id, name FROM trip_names"))
    out = []
    for t in trips:
        n = sum(day_info[d]["n"] for d in t)
        if n < 20 and len(t) < 2:
            continue
        tid = "T" + t[0].replace("-", "")
        cdays = collections.Counter(); cinfo = {}
        for d in t:
            i = day_info[d]; cdays[i["city"]] += 1; cinfo[i["city"]] = (i["cc"], i["prov"])
            i["trip"] = tid
        cities = [(c, cinfo[c][0], cinfo[c][1], k) for c, k in cdays.most_common()]
        tr = dict(id=tid, start=t[0], end=t[-1], days=(dt.date.fromisoformat(t[-1]) - dt.date.fromisoformat(t[0])).days + 1,
                  n=n, cities=cities, day_list=t)
        tr["auto_name"] = trip_name(tr); tr["name"] = names.get(tid) or tr["auto_name"]
        out.append(tr)
    # 每趟按时间排好的轨迹点（画路线用；只用自己的、带可信位置的点，抽稀到 ≥2 公里一个）
    trip_of_day = {d: tr["id"] for tr in out for d in tr["day_list"]}
    tracks = collections.defaultdict(list)
    for m in sorted(mine, key=lambda m: m["dt"]):
        tid = trip_of_day.get(m["dt"][:10])
        if tid and m["lat"] is not None and m["conf"] in ("自带", "近"):
            tr = tracks[tid]
            if not tr or hav(tr[-1][0], tr[-1][1], m["lat"], m["lon"]) >= 2:
                tr.append((round(m["lat"], 4), round(m["lon"], 4), m["dt"]))
    res = dict(
        built=time.strftime("%Y-%m-%d %H:%M"), seconds=round(time.time() - t0, 1),
        n_photo=sum(1 for m in mine if m["kind"] == "photo"), n_video=sum(1 for m in mine if m["kind"] == "video"),
        days={d: {k: v for k, v in i.items() if k != "pts" and k != "home"} for d, i in day_info.items()},
        homes={d[:7]: i["home"] for d, i in day_info.items() if i.get("home")},
        trips=[{k: v for k, v in t.items()} for t in out],
        tracks=tracks,
    )
    with open(RESULT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    os.replace(RESULT + ".tmp", RESULT)
    con.close()
    return res


def load():
    if os.path.exists(RESULT):
        with open(RESULT, encoding="utf-8") as f:
            return json.load(f)
    return None
