# -*- coding: utf-8 -*-
"""把分析结果整理成三张海报需要的数字，并画地图 / 时间轴（内嵌 SVG，城市级精度，不画任何国界省界）"""
import collections, datetime as dt, html, math, os, re

import numpy as np

from geo import ALL_PROV, COUNTRY_ZH, DOMESTIC, hav

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_mask = None
CN_NUM = "零一二三四五六七八九十"
BIN_COLORS = [(1, "#7A889B"), (3, "#4c8dd3"), (9, "#38b8a4"), (29, "#a4b06c"), (10 ** 9, "#f5aa42")]
NEW_C, REV_C = "#4c8dd3", "#daac50"


def land():
    global _mask
    if _mask is None:
        _mask = np.unpackbits(np.load(os.path.join(DATA, "landmask_025.npy")), axis=1)[:, :1440].astype(bool)
    return _mask


def cn_num(n):
    if n <= 10:
        return CN_NUM[n]
    if n < 20:
        return "十" + (CN_NUM[n - 10] if n > 10 else "")
    if n < 100:
        return CN_NUM[n // 10] + "十" + (CN_NUM[n % 10] if n % 10 else "")
    return str(n)


def year_color(y, y0, y1):
    t = 0 if y1 == y0 else (y - y0) / (y1 - y0)
    stops = [(0, (84, 124, 230)), (0.5, (56, 184, 164)), (1, (245, 170, 66))]
    for (t0, a), (t1, b) in zip(stops, stops[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * u) for i in range(3))
    return "#f5aa42"


def bin_color(n):
    return next(c for lim, c in BIN_COLORS if n <= lim)


def esc(s):
    return html.escape(str(s))


# ---------------------------------------------------------------- 地图
def fit_extent(points, W, H, pad_lon=8, pad_lat=6, min_span=12):
    los = [p[1] for p in points]; las = [p[0] for p in points]
    lo0, lo1 = min(los) - pad_lon, max(los) + pad_lon
    la0, la1 = min(las) - pad_lat, max(las) + pad_lat
    if lo1 - lo0 < min_span:
        c = (lo0 + lo1) / 2; lo0, lo1 = c - min_span / 2, c + min_span / 2
    if la1 - la0 < min_span * H / W:
        c = (la0 + la1) / 2; h = min_span * H / W; la0, la1 = c - h / 2, c + h / 2
    # 按画布比例补齐（经纬度等比例）
    if (lo1 - lo0) / (la1 - la0) > W / H:
        need = (lo1 - lo0) * H / W; c = (la0 + la1) / 2; la0, la1 = c - need / 2, c + need / 2
    else:
        need = (la1 - la0) * W / H; c = (lo0 + lo1) / 2; lo0, lo1 = c - need / 2, c + need / 2
    if la1 > 82:
        la0 -= la1 - 82; la1 = 82
    if la0 < -60:
        la1 += -60 - la0; la0 = -60
    return lo0, lo1, la0, la1


def map_svg(W, H, ext, dots, labels, cols=170, land_r=None):
    """dots: [(lat, lon, r, color, opacity)]；labels: [(lat, lon, text, size, color)]（贪心避让）"""
    lo0, lo1, la0, la1 = ext
    sx = W / (lo1 - lo0)
    xy = lambda la, lo: ((lo - lo0) * sx, (la1 - la) * sx)
    step = max(0.25, round((lo1 - lo0) / cols / 0.25) * 0.25)
    r = land_r or max(1.3, min(2.2, step * sx * 0.3))
    M = land(); out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="足迹点阵图">']
    lat = la1 - step / 2
    parts = []
    while lat > la0:
        lon = lo0 + step / 2
        row = int((90 - lat) / 0.25)
        while lon < lo1:
            L = ((lon + 180) % 360) - 180
            if 0 <= row < 720 and M[row, int((L + 180) / 0.25) % 1440]:
                x, y = xy(lat, lon); parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}"/>')
            lon += step
        lat -= step
    out.append('<g fill="#2B3646">' + "".join(parts) + "</g>")
    for la, lo, rr, c, op in dots:
        x, y = xy(la, lo)
        if -10 <= x <= W + 10 and -10 <= y <= H + 10:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rr:.1f}" fill="{c}" fill-opacity="{op}" stroke="#10151C" stroke-width="1"/>')
    boxes = []
    for la, lo, text, size, color in labels:
        x, y = xy(la, lo); w = len(text) * size * 0.95 + 4; h = size + 4
        for dx, anchor in ((8, "start"), (-8, "end")):
            bx = x + dx if anchor == "start" else x + dx - w
            box = (bx, y - h / 2, bx + w, y + h / 2)
            if box[0] < 2 or box[2] > W - 2 or box[1] < 2 or box[3] > H - 2:
                continue
            if any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in boxes):
                continue
            boxes.append(box)
            out.append(f'<text x="{x + dx:.1f}" y="{y + size * 0.36:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" '
                       f'font-family="Noto Sans CJK SC, sans-serif">{esc(text)}</text>')
            break
    out.append("</svg>")
    return "".join(out)


def strip_svg(rows, y0, RH, W=400, P=10):
    """年鉴：每年一行，12 个月刻度，每趟一个圆点（蓝=去了新地方，琥珀=都是去过的）"""
    IW = W - 2 * P; H = RH * len(rows)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="每年出行时间分布">']
    for i in range(len(rows)):
        cy = i * RH + RH / 2
        o.append(f'<line x1="{P}" y1="{cy}" x2="{P + IW}" y2="{cy}" stroke="#2B3646" stroke-width="1.2"/>')
        for m in range(13):
            x = P + m / 12 * IW
            o.append(f'<line x1="{x:.1f}" y1="{cy - 5}" x2="{x:.1f}" y2="{cy + 5}" stroke="#2B3646" stroke-width="1.2"/>')
    dots = []
    for i, r in enumerate(rows):
        for t in r["trips"]:
            d = dt.date.fromisoformat(t["start"]); x = P + (d.timetuple().tm_yday - 0.5) / 366 * IW
            dots.append((t["days"], x, i * RH + RH / 2, NEW_C if t["new"] else REV_C))
    rmax = RH / 2 - 4
    for days, x, cy, c in sorted(dots, reverse=True):
        rr = min(rmax, 3 + math.sqrt(days) * 2.8 * RH / 132)
        o.append(f'<circle cx="{x:.1f}" cy="{cy}" r="{rr:.1f}" fill="{c}" fill-opacity="0.75" stroke="#10151C" stroke-width="1.2"/>')
    o.append("</svg>")
    return "".join(o)


# ---------------------------------------------------------------- 数字
def build(res, years_max=20):
    trips = res["trips"]; days = res["days"]
    if not trips:
        return None
    tdays = {d: t["id"] for t in trips for d in t["day_list"]}
    tmap = {t["id"]: t for t in trips}
    aw = [(d, days[d]) for d in sorted(days) if d in tdays and days[d].get("lat") is not None]
    y0, y1 = int(trips[0]["start"][:4]), int(trips[-1]["start"][:4])
    # 城市（区县并入城市）
    city = {}
    for d, i in aw:
        c = city.setdefault(i["city"], dict(first=d[:4], days=0, cc=i["cc"], prov=i["prov"], lat=i["lat"], lon=i["lon"], trips=set(), years=set()))
        c["days"] += 1; c["trips"].add(tdays[d]); c["years"].add(d[:4])
    cc_first, prov_first = {}, {}
    for d, i in aw:
        cc_first.setdefault(i["cc"], d[:7])
        if i["cc"] == "CN" and i["prov"]:
            prov_first.setdefault(i["prov"], d[:4])
        elif i["cc"] in ("HK", "MO", "TW"):
            prov_first.setdefault(COUNTRY_ZH[i["cc"]], d[:4])
    km = 0
    for t in trips:
        pts = [days[d] for d in t["day_list"] if days[d].get("lat") is not None]
        km += sum(hav(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(pts, pts[1:]))
    # 「家」= 最常见的家（只用来算"最远"，不画出来）
    homes = collections.Counter(tuple(h) for h in res.get("homes", {}).values())
    home = homes.most_common(1)[0][0] if homes else (aw[0][1]["lat"], aw[0][1]["lon"])
    north = max(aw, key=lambda x: x[1]["lat"])[1]; south = min(aw, key=lambda x: x[1]["lat"])[1]
    far = max(aw, key=lambda x: hav(home[0], home[1], x[1]["lat"], x[1]["lon"]))[1]
    top_trip = max(trips, key=lambda t: t["n"])
    by_year = collections.defaultdict(list)
    for t in trips:
        by_year[int(t["start"][:4])].append(t)
    years = list(range(y0, y1 + 1))
    # 重访：按旅程顺序，去过以前去过的城市就算
    seen = set(); rev_y = collections.Counter(); n_rev = 0
    for t in trips:
        cs = {c[0] for c in t["cities"]}
        t["new"] = bool(cs - seen)
        if cs & seen:
            rev_y[int(t["start"][:4])] += 1; n_rev += 1
        seen |= cs
    rep = {k: v for k, v in city.items() if len(v["trips"]) >= 2}
    tot_days = sum(v["days"] for v in city.values()) or 1
    rep_days = sum(v["days"] for v in rep.values())
    prov_trips = collections.defaultdict(set); prov_years = collections.defaultdict(set)
    for d, i in aw:
        p = i["prov"] if i["cc"] == "CN" else COUNTRY_ZH.get(i["cc"]) if i["cc"] in ("HK", "MO", "TW") else None
        if p:
            prov_trips[p].add(tdays[d]); prov_years[p].add(d[:4])
    cc_trips = collections.defaultdict(set)
    for d, i in aw:
        cc_trips[i["cc"]].add(tdays[d])
    gaps = []
    for k, v in city.items():
        s = sorted(tmap[t]["start"] for t in v["trips"])
        for a, b in zip(s, s[1:]):
            gaps.append(((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days, k, a[:4], b[:4]))
    gaps.sort(reverse=True)
    best_gaps, used = [], set()                     # 每个城市只取最长的一次，至少隔一年
    for g in gaps:
        if g[0] >= 365 and g[1] not in used:
            used.add(g[1]); best_gaps.append((g[0] // 365, g[1], g[2], g[3]))
        if len(best_gaps) == 6:
            break
    nyears = len(years)
    top_prov = max(prov_years.items(), key=lambda kv: (len(kv[1]), len(prov_trips[kv[0]])), default=(None, set()))
    top_city = max(city.items(), key=lambda kv: (len(kv[1]["trips"]), kv[1]["days"]))
    longest = max(city.items(), key=lambda kv: kv[1]["days"])
    abroad_cc = [(len(v), c) for c, v in cc_trips.items() if c not in DOMESTIC]
    S = dict(
        y0=y0, y1=y1, nyears=nyears, title_years=cn_num(nyears), n_trips=len(trips), n_days=sum(t["days"] for t in trips),
        n_cc=len(cc_first), n_prov=len(prov_first), n_city=len(city), km=km,
        n_photo=res["n_photo"], n_video=res["n_video"], has_cn=bool(prov_first),
        north=north, south=south, far=far, top_trip=top_trip,
        year_trips=[(y, len(by_year[y])) for y in years],
        abroad=sorted(((v[:4], COUNTRY_ZH.get(c, c)) for c, v in cc_first.items() if c not in DOMESTIC)),
        prov_grid=[(p, prov_first.get(p)) for p in sorted(ALL_PROV, key=lambda p: (prov_first.get(p) or "9999", ALL_PROV.index(p)))],
        n_rep=len(rep), n_rev=n_rev, rev_share=round(100 * n_rev / len(trips)), rep_day_share=round(100 * rep_days / tot_days),
        top_city=(top_city[0], len(top_city[1]["trips"]), top_city[1]["days"], len(top_city[1]["years"])),
        top_prov=(top_prov[0], len(top_prov[1])),
        ranking=sorted(((len(v["trips"]), v["days"], k) for k, v in city.items() if len(v["trips"]) >= 2), reverse=True)[:10],
        prov_counts=sorted(((len(prov_trips.get(p, ())), p) for p in ALL_PROV), key=lambda x: (-x[0], ALL_PROV.index(x[1]))),
        rev_years=[(y, rev_y[y], len(by_year[y])) for y in years],
        gaps=best_gaps,
        abroad_top=(COUNTRY_ZH.get(max(abroad_cc)[1], max(abroad_cc)[1]), max(abroad_cc)[0]) if abroad_cc else None,
        longest=(longest[0], longest[1]["days"]),
        best_rev_year=max(rev_y.items(), key=lambda kv: kv[1]) if rev_y else None,
        newest_year=max(((y, n - rev_y[y], n) for y, n in ((y, len(by_year[y])) for y in years[2:]) if n >= 5),
                        key=lambda x: (x[1] / x[2], x[2]), default=None),
    )
    # 年鉴
    yrs = years[-years_max:]
    S["yearly"] = [dict(year=y, n=len(by_year[y]), days=sum(t["days"] for t in by_year[y]), trips=by_year[y],
                        top=[re.sub(r"^\d{4}-\d\d ", "", t["name"]) for t in sorted(by_year[y], key=lambda t: -t["n"])[:3]])
                   for y in yrs]
    S["best_year"] = max(S["yearly"], key=lambda r: (r["n"], r["days"]))
    # 地图
    W1, H1 = 1046, 380
    pts = [(v["lat"], v["lon"]) for v in city.values()]
    ext = fit_extent(pts, W1, H1, min_span=40)
    dots = [(v["lat"], v["lon"], 2.6 + min(5, math.sqrt(v["days"]) * 0.6), year_color(int(v["first"]), y0, y1), 0.9)
            for k, v in sorted(city.items(), key=lambda kv: kv[1]["first"])]
    far_lab = sorted(city.items(), key=lambda kv: -hav(home[0], home[1], kv[1]["lat"], kv[1]["lon"]))
    labs = []
    for k, v in far_lab[:40]:
        if re.search(r"[一-鿿]", k) and all(hav(v["lat"], v["lon"], l[0], l[1]) > 600 for l in labs):
            labs.append((v["lat"], v["lon"], k, 16, "#C5CDD6"))
        if len(labs) >= 8:
            break
    S["map_main"] = map_svg(W1, H1, ext, dots, labs)
    W2, H2 = 900, 540
    rp = [(v["lat"], v["lon"]) for v in rep.values()] or pts
    ext2 = fit_extent(rp, W2, H2, pad_lon=3, pad_lat=2.5, min_span=25)
    dots2 = [(v["lat"], v["lon"], 2.6 if len(v["trips"]) == 1 else 3 + min(10, math.sqrt(v["days"]) * 0.9),
              bin_color(len(v["trips"])), 0.8 if len(v["trips"]) == 1 else 0.9)
             for k, v in sorted(city.items(), key=lambda kv: len(kv[1]["trips"]))]
    labs2 = [(v["lat"], v["lon"], k, 20, "#E9ECEF") for c, d, k in S["ranking"][:8] for v in [city[k]]]
    S["map_rev"] = map_svg(W2, H2, ext2, dots2, labs2, cols=150)
    S["year_colors"] = [(y, year_color(y, y0, y1)) for y in years]
    S["bins"] = [("1", BIN_COLORS[0][1]), ("2–3", BIN_COLORS[1][1]), ("4–9", BIN_COLORS[2][1]), ("10–29", BIN_COLORS[3][1]), ("30+", BIN_COLORS[4][1])]
    S["bin_color"] = bin_color
    RH = min(132, int(1920 / max(1, len(S["yearly"]))))
    S["row_h"] = RH
    S["strip"] = strip_svg(S["yearly"], y0, RH)
    S["year_color"] = lambda y: year_color(y, y0, y1)
    return S
