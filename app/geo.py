# -*- coding: utf-8 -*-
"""离线地名：GeoNames cities5000（人口 ≥5000 的城镇）+ 一级行政区名 + 中文国名"""
import collections, io, math, os, re, zipfile

try:
    import opencc
    _cc = opencc.OpenCC("t2s")
    T2S = lambda s: _cc.convert(s).replace("徳", "德")
except Exception:  # pragma: no cover
    T2S = lambda s: s

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DOMESTIC = {"CN", "HK", "MO", "TW"}

CN_PROV = [("anhui", "安徽"), ("zhejiang", "浙江"), ("jiangxi", "江西"), ("jiangsu", "江苏"), ("jilin", "吉林"), ("qinghai", "青海"),
           ("fujian", "福建"), ("heilongjiang", "黑龙江"), ("henan", "河南"), ("hebei", "河北"), ("hunan", "湖南"), ("hubei", "湖北"),
           ("xinjiang", "新疆"), ("tibet", "西藏"), ("xizang", "西藏"), ("gansu", "甘肃"), ("guangxi", "广西"), ("guizhou", "贵州"),
           ("liaoning", "辽宁"), ("inner mongolia", "内蒙古"), ("nei mongol", "内蒙古"), ("ningxia", "宁夏"), ("beijing", "北京"),
           ("shanghai", "上海"), ("shaanxi", "陕西"), ("shanxi", "山西"), ("shandong", "山东"), ("tianjin", "天津"), ("yunnan", "云南"),
           ("guangdong", "广东"), ("hainan", "海南"), ("sichuan", "四川"), ("chongqing", "重庆")]
ALL_PROV = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏", "浙江", "安徽", "福建", "江西",
            "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃",
            "青海", "宁夏", "新疆", "香港", "澳门", "台湾"]

COUNTRY_ZH = {
    "CN": "中国", "HK": "香港", "MO": "澳门", "TW": "台湾", "JP": "日本", "KR": "韩国", "KP": "朝鲜", "MN": "蒙古", "RU": "俄罗斯",
    "TH": "泰国", "VN": "越南", "LA": "老挝", "KH": "柬埔寨", "MM": "缅甸", "MY": "马来西亚", "SG": "新加坡", "ID": "印度尼西亚",
    "PH": "菲律宾", "BN": "文莱", "TL": "东帝汶", "IN": "印度", "LK": "斯里兰卡", "MV": "马尔代夫", "NP": "尼泊尔", "BT": "不丹",
    "BD": "孟加拉国", "PK": "巴基斯坦", "AF": "阿富汗", "KZ": "哈萨克斯坦", "KG": "吉尔吉斯斯坦", "UZ": "乌兹别克斯坦",
    "TJ": "塔吉克斯坦", "TM": "土库曼斯坦", "IR": "伊朗", "IQ": "伊拉克", "TR": "土耳其", "GE": "格鲁吉亚", "AM": "亚美尼亚",
    "AZ": "阿塞拜疆", "AE": "阿联酋", "QA": "卡塔尔", "SA": "沙特阿拉伯", "OM": "阿曼", "JO": "约旦", "IL": "以色列",
    "LB": "黎巴嫩", "EG": "埃及", "MA": "摩洛哥", "TN": "突尼斯", "KE": "肯尼亚", "TZ": "坦桑尼亚", "ZA": "南非",
    "MU": "毛里求斯", "SC": "塞舌尔", "MG": "马达加斯加", "ET": "埃塞俄比亚", "NA": "纳米比亚",
    "GB": "英国", "IE": "爱尔兰", "FR": "法国", "DE": "德国", "IT": "意大利", "ES": "西班牙", "PT": "葡萄牙", "NL": "荷兰",
    "BE": "比利时", "LU": "卢森堡", "CH": "瑞士", "AT": "奥地利", "CZ": "捷克", "SK": "斯洛伐克", "PL": "波兰", "HU": "匈牙利",
    "DK": "丹麦", "NO": "挪威", "SE": "瑞典", "FI": "芬兰", "IS": "冰岛", "EE": "爱沙尼亚", "LV": "拉脱维亚", "LT": "立陶宛",
    "GR": "希腊", "HR": "克罗地亚", "SI": "斯洛文尼亚", "RS": "塞尔维亚", "ME": "黑山", "BA": "波黑", "AL": "阿尔巴尼亚",
    "RO": "罗马尼亚", "BG": "保加利亚", "UA": "乌克兰", "MT": "马耳他", "CY": "塞浦路斯", "MC": "摩纳哥", "VA": "梵蒂冈",
    "US": "美国", "CA": "加拿大", "MX": "墨西哥", "CU": "古巴", "BR": "巴西", "AR": "阿根廷", "CL": "智利", "PE": "秘鲁",
    "BO": "玻利维亚", "EC": "厄瓜多尔", "CO": "哥伦比亚", "CR": "哥斯达黎加", "PA": "巴拿马", "AU": "澳大利亚", "NZ": "新西兰",
    "FJ": "斐济", "PF": "法属波利尼西亚", "PW": "帕劳", "GU": "关岛", "MP": "北马里亚纳群岛",
}


try:
    from pypinyin import lazy_pinyin
except Exception:  # pragma: no cover
    lazy_pinyin = None
_SUFFIX = re.compile(r"(shi|xian|qu|zhen|district|city|county|prefecture|-)$")


def _norm(s):
    s = re.sub(r"[^a-z]", "", s.lower())
    for _ in range(2):
        s = _SUFFIX.sub("", s)
    return s


def pick_zh(alts, ascii_name, cc):
    """GeoNames 的别名里混着繁体、日文汉字、旧称：选一个简体、读音和英文名对得上的"""
    cands = []
    for n in alts.split(","):
        if not re.search(r"[一-鿿]", n) or re.search(r"[぀-ヿ]", n):
            continue
        s = T2S(n)
        try:
            s.encode("gb2312")
        except UnicodeEncodeError:
            continue                                   # 日文新字体（如「営」）等
        cands.append(s)
    if not cands:
        return ""
    if lazy_pinyin and cc in ("CN", "TW", "HK", "MO"):
        target = _norm(ascii_name)
        for s in cands:
            py = _norm("".join(lazy_pinyin(re.sub(r"(市|县|区|镇)$", "", s))))
            if py and target and (py == target or target.startswith(py) or py.startswith(target)):
                return s
    return cands[0]


def hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1, x)))


class Geo:
    """place(lat, lon) → 最近的城镇；city(lat, lon) → 所属城市（50 公里内人口 ≥50 万的大城市，区县并进城市）"""

    def __init__(self):
        self.grid = collections.defaultdict(list)
        self.big = collections.defaultdict(list)
        with zipfile.ZipFile(os.path.join(DATA, "cities5000.zip")) as z:
            name = [n for n in z.namelist() if n.endswith(".txt")][0]
            for line in io.TextIOWrapper(z.open(name), encoding="utf-8"):
                f = line.rstrip("\n").split("\t")
                if len(f) < 18:
                    continue
                zh = pick_zh(f[3], f[2], f[8])
                rec = (float(f[4]), float(f[5]), f[2], zh, f[8], int(f[14] or 0), f[10])
                key = (int(float(f[4]) // 1), int(float(f[5]) // 1))
                self.grid[key].append(rec)
                if rec[5] >= 500_000:
                    self.big[key].append(rec)
        self.admin1 = {}
        for line in open(os.path.join(DATA, "admin1CodesASCII.txt"), encoding="utf-8"):
            f = line.rstrip("\n").split("\t")
            if len(f) >= 3:
                self.admin1[f[0]] = f[2]
        self.cache, self.ccache = {}, {}

    def _nearest(self, grid, la, lo, maxr=3):
        best = None
        for r in range(maxr):
            for i in range(-r, r + 1):
                for j in range(-r, r + 1):
                    for c in grid.get((int(la // 1) + i, int(lo // 1) + j), ()):
                        d = (c[0] - la) ** 2 + ((c[1] - lo) * math.cos(la * math.pi / 180)) ** 2
                        d -= min(c[5], 2_000_000) / 2e10          # 同等距离优先大城市
                        if best is None or d < best[0]:
                            best = (d, c)
            if best:
                break
        return best[1] if best else None

    def _fmt(self, c):
        cla, clo, asc, zh, cc, pop, a1 = c
        name = re.sub(r"(?<=..)市$", "", re.sub(r"[（(].*?[）)]", "", zh)) if zh else ""
        prov = self.admin1.get(f"{cc}.{a1}", "")
        if cc == "CN":
            low = prov.lower()
            prov = next((z for en, z in CN_PROV if en in low), prov)
        elif cc in ("HK", "MO", "TW"):
            prov = COUNTRY_ZH[cc]
        return dict(name=name, en=asc, cc=cc, prov=prov, lat=cla, lon=clo, pop=pop)

    def place(self, la, lo):
        k = (round(la, 2), round(lo, 2))
        if k not in self.cache:
            c = self._nearest(self.grid, la, lo)
            self.cache[k] = self._fmt(c) if c else dict(name="", en="", cc="", prov="", lat=la, lon=lo, pop=0)
        return self.cache[k]

    def city(self, la, lo):
        """区县并进所属大城市；周围 50 公里没有大城市就用最近的城镇"""
        k = (round(la, 2), round(lo, 2))
        if k not in self.ccache:
            p = self.place(la, lo)
            if p["cc"] == "CN" and p["prov"] in ("北京", "上海", "天津", "重庆"):      # 直辖市：整个市算一个城市
                self.ccache[k] = dict(p, name=p["prov"])
            elif p["cc"] in ("HK", "MO"):
                self.ccache[k] = dict(p, name=COUNTRY_ZH[p["cc"]])
            else:
                best = None
                for i in (-1, 0, 1):
                    for j in (-1, 0, 1):
                        for c in self.big.get((int(la // 1) + i, int(lo // 1) + j), ()):
                            d = hav(la, lo, c[0], c[1])
                            if d <= 45 and c[4] == p["cc"] and (best is None or c[5] > best[1][5]):
                                best = (d, c)
                # 自己就是大城市、离那个更大的城市又不近（如昆山之于上海）：保留自己
                if best and p["pop"] >= 500_000 and best[0] > 30:
                    best = None
                c = self._fmt(best[1]) if best else p
                if not c["name"] and c["cc"] in DOMESTIC:          # 没有中文名的小地方：借 40 公里内最近的有中文名的城镇
                    near = None
                    for i in (-1, 0, 1):
                        for j in (-1, 0, 1):
                            for r in self.grid.get((int(la // 1) + i, int(lo // 1) + j), ()):
                                if r[3] and r[4] == c["cc"]:
                                    d = hav(la, lo, r[0], r[1]) - min(r[5], 1_000_000) / 100_000
                                    if hav(la, lo, r[0], r[1]) <= 40 and (near is None or d < near[0]):
                                        near = (d, r)
                    c = self._fmt(near[1]) if near else dict(c, name=c["prov"])
                self.ccache[k] = c
        return self.ccache[k]


def short_name(p):
    """海报上用的短名：中文名优先，没有就用英文名"""
    return p["name"] or p["en"]
