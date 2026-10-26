# -*- coding: utf-8 -*-
"""
浙大城市学院 · 三维校园模型 —— 第 2 步：建模并输出场景数据

模型
  G = (V, E, W)：V 为路网节点 + 每栋建筑的入口锚点；
  W_e = L_e / v(道路类型) + τ(过街惩罚)，L 为 Haversine 长度。

输出
  out/scene.json    三维前端（three.js）直接消费的场景数据
  out/buildings.csv 建筑台账（含层数、面积、到关键设施步行时间）
"""
from __future__ import annotations

import csv
import heapq
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
DATA = ROOT / "data"
OUT = ROOT / "out"
OUT.mkdir(parents=True, exist_ok=True)

# 校园中心（湖州街 51 号一带），局部等距投影原点
LAT0, LON0 = 30.32650, 120.15100
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT0))

# 步行速度模型（m/s）
SPEED = {
    "footway": 1.35, "path": 1.35, "pedestrian": 1.35, "steps": 0.60,
    "cycleway": 1.30, "living_street": 1.30, "residential": 1.30,
    "service": 1.30, "unclassified": 1.30, "track": 1.20,
    "tertiary": 1.10, "tertiary_link": 1.10, "secondary": 1.05,
    "secondary_link": 1.05, "primary": 1.00, "primary_link": 1.00,
    "trunk": 1.00, "trunk_link": 1.00, "construction": 0.90,
    "corridor": 1.20, "elevator": 0.80,
}
DEFAULT_SPEED = 1.25
CROSS_PENALTY_S = {"primary": 12.0, "primary_link": 12.0, "secondary": 8.0,
                   "secondary_link": 8.0, "tertiary": 6.0, "tertiary_link": 6.0}
SNAP_TOL_M = 18.0
ANCHOR_MAX_M = 220.0
FLOOR_H = 3.6

CAT_COLOR = {
    "教学": "#e4572e", "实验": "#f2a541", "图书": "#8e44ad", "行政": "#2e86c1",
    "宿舍": "#1abc9c", "餐饮": "#c0392b", "体育": "#27ae60", "医疗": "#e84393",
    "科研": "#7f8c8d", "其他": "#7c8792",
}
CATEGORY_RULES = [
    ("教学", ["教学楼", "教室", "科技楼", "综合教育楼", "阶梯教室"]),
    ("实验", ["实验", "理工科楼", "工程", "实训"]),
    ("图书", ["图书馆", "图书"]),
    ("行政", ["行政", "办公", "会议室", "新大楼", "城院新大楼"]),
    ("宿舍", ["公寓", "宿舍", "书院", "问源楼", "唯学楼", "尚雅楼", "思睿楼",
              "求真楼", "北秀楼", "慕贤楼", "明德楼", "致远楼", "至善楼", "精诚楼"]),
    ("餐饮", ["食堂", "餐厅", "美食"]),
    ("体育", ["体育馆", "操场", "风雨", "健身", "球场", "射击"]),
    ("医疗", ["医务", "医院", "门诊"]),
]
LAND_LIGHT = {"water": "#7fb6d9", "pitch": "#5f9e72", "park": "#6fa97e",
              "grass": "#6fa97e", "forest": "#64996f", "parking": "#4a5058"}
MAJOR = {"primary", "primary_link", "secondary", "secondary_link",
         "trunk", "trunk_link", "tertiary", "tertiary_link"}
WALK = {"footway", "path", "pedestrian", "steps", "corridor"}

# 关键设施（用于三维卡片里的步行时间）
KEY_NAMES = ["图书馆", "行政楼", "第一教学楼", "第二教学楼", "第三教学楼",
             "第四教学楼", "第五教学楼", "第六教学楼", "第七教学楼", "第八教学楼",
             "理工科楼4号", "科技楼", "风雨操场", "体育馆", "晨苑食堂",
             "校医务室", "问源楼", "尚雅楼", "求真楼", "怀卡托"]


def hav(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    dlat, dlon = (lat2 - lat1) * p, (lon2 - lon1) * p
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def xy(lat, lon):
    return ((lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT)


def classify(name):
    for cat, keys in CATEGORY_RULES:
        if any(k in name for k in keys):
            return cat
    return "其他"


def point_in_poly(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def convex_hull(points):
    pts = sorted(set(map(tuple, points)))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def poly_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def num(v, default=0.0):
    try:
        return float(str(v).split(";")[0])
    except Exception:  # noqa: BLE001
        return default


# ---------------------------------------------------------------- 数据读取
def load(name):
    return json.loads((RAW / name).read_text(encoding="utf-8"))["elements"]


def geom(el):
    if "geometry" in el:
        pts = [(g["lat"], g["lon"]) for g in el["geometry"] if g.get("lat") is not None]
    elif "lat" in el:
        pts = [(el["lat"], el["lon"])]
    elif "center" in el:
        pts = [(el["center"]["lat"], el["center"]["lon"])]
    else:
        pts = []
    return pts


# ---------------------------------------------------------------- 主建模

def ground_image_dataurl(width=2048, quality=80):
    """把正射影像压成 data URL，供前端铺到地面上（ESRI World Imagery，z=18）。"""
    import base64, io
    from PIL import Image
    src = OUT / "imagery_bbox.png"
    if not src.exists():
        return ""
    im = Image.open(src).convert("RGB")
    h = round(im.height * width / im.width)
    im = im.resize((width, h), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def roof_colors_from_imagery(buildings, bbox):
    """按建筑轮廓在正射影像上取屋顶中位色（避开阴影与树冠）。"""
    from PIL import Image, ImageDraw
    import numpy as _np
    src = OUT / "imagery_bbox.png"
    if not src.exists():
        return {}
    im = Image.open(src).convert("RGB")
    W, H = im.size
    w = bbox["maxx"] - bbox["minx"]; h = bbox["maxy"] - bbox["miny"]
    out = {}
    for b in buildings:
        poly = b.get("poly") or []
        if len(poly) < 3:
            continue
        xs = [(x - bbox["minx"]) / w * W for x, y in poly]
        ys = [(bbox["maxy"] - y) / h * H for x, y in poly]
        x0, x1 = int(min(xs)), int(max(xs)); y0, y1 = int(min(ys)), int(max(ys))
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        m = Image.new("L", (x1-x0+1, y1-y0+1), 0)
        ImageDraw.Draw(m).polygon([(x-x0, y-y0) for x, y in zip(xs, ys)], fill=255)
        arr = _np.asarray(im.crop((x0, y0, x1+1, y1+1))).astype(_np.float32)
        msk = _np.asarray(m) > 128
        if msk.sum() < 20:
            continue
        px = arr[msk]
        lum = px.mean(axis=1)
        keep = px[(lum > _np.percentile(lum, 25)) & (lum < _np.percentile(lum, 97))]
        if len(keep) < 10:
            keep = px
        c = _np.median(keep, axis=0)
        # 轻微提亮、压饱和，避免影像里的脏色直接上墙
        c = c + (255 - c) * 0.05
        out[b["id"]] = "#%02x%02x%02x" % tuple(int(v) for v in _np.clip(c, 0, 255))
    return out

def main():
    print("=" * 70)
    print("浙大城市学院 · 三维校园模型 · 建模")
    print("=" * 70)

    # ---- 命名节点
    labels = []
    for el in load("labels.json"):
        if "lat" in el:
            labels.append(((el["lat"], el["lon"]), el["tags"].get("name", "")))

    # ---- 建筑
    raw_b = []
    for el in load("buildings.json"):
        if el.get("type") != "way":
            continue
        t = el.get("tags", {})
        cs = geom(el)
        if len(cs) < 3:
            continue
        lat = sum(p[0] for p in cs) / len(cs)
        lon = sum(p[1] for p in cs) / len(cs)
        raw_b.append({
            "id": el["id"], "name": t.get("name", ""), "tags": t,
            "lat": lat, "lon": lon,
            "poly_ll": cs,
            "poly": [xy(la, lo) for la, lo in cs],
            "levels": num(t.get("building:levels") or t.get("levels") or "", 0.0),
            "area": poly_area([xy(la, lo) for la, lo in cs]),
        })

    # ---- 一对一补名：命名节点 -> 最近的无名建筑（60 m 内）
    pairs = []
    for i, b in enumerate(raw_b):
        if b["name"]:
            continue
        for (nlat, nlon), nname in labels:
            if not any(s in nname for s in ("楼", "馆", "舍", "寓", "堂", "厅", "学院")):
                continue
            d = hav(b["lat"], b["lon"], nlat, nlon)
            if d <= 60.0:
                pairs.append((d, i, nname))
    pairs.sort()
    used = set()
    for d, i, nname in pairs:
        if i in {p[1] for p in pairs if raw_b[p[1]]["name"]} or nname in used:
            continue
        if not raw_b[i]["name"]:
            raw_b[i]["name"] = nname
            used.add(nname)

    # ---- 校园核心区：命名校园建筑凸包外扩 60 m
    seeds = [b for b in raw_b if "城市学院" in b["name"] or "城院" in b["name"]
             or b["name"] in ("图书馆及部分办公室", "休闲餐厅", "体育馆", "晨苑食堂",
                              "风雨操场", "老体育馆", "射击馆及阶梯教室")]
    if len(seeds) < 4:
        seeds = sorted(raw_b, key=lambda b: -b["area"])[:15]
    hull = convex_hull([(b["lat"], b["lon"]) for b in seeds])
    hull_xy = [xy(la, lo) for la, lo in hull]
    cx = sum(p[0] for p in hull_xy) / len(hull_xy)
    cy = sum(p[1] for p in hull_xy) / len(hull_xy)
    campus_hull = []
    for x, y in hull_xy:
        dx, dy = x - cx, y - cy
        n = math.hypot(dx, dy) or 1.0
        campus_hull.append((x + dx / n * 60, y + dy / n * 60))

    buildings = []
    for b in raw_b:
        bx, by = xy(b["lat"], b["lon"])
        if not point_in_poly((bx, by), campus_hull) or b["area"] < 100:
            continue
        b["cat"] = classify(b["name"])
        b["poly"] = [(round(x, 1), round(y, 1)) for x, y in b["poly"]]
        b["c"] = [round(bx, 1), round(by, 1)]
        b["area"] = round(b["area"], 1)
        buildings.append(b)

    # ---- 层数估计：同类中位数；未知且大面积者给 4 层
    med = {}
    for cat, _ in CATEGORY_RULES:
        known = [b["levels"] for b in buildings if b["cat"] == cat and b["levels"] > 1]
        if known:
            known.sort()
            med[cat] = known[len(known) // 2]
    for b in buildings:
        b["levels_est"] = False
        if b["levels"] > 1:
            continue
        if b["cat"] in med:
            b["levels"] = med[b["cat"]]
            b["levels_est"] = True
        elif b["area"] >= 3000:
            b["levels"] = 4.0
            b["levels_est"] = True
        else:
            b["levels"] = max(1.0, b["levels"])
    print(f"  校园内建筑 {len(buildings)} 栋（命名 {sum(1 for b in buildings if b['name'])} 栋）")
    print(f"  层数中位数: {med}")

    # ---- 路网图
    nodes_ll, parent = [], []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    roads = []
    for el in load("roads.json"):
        if el.get("type") != "way":
            continue
        t = el.get("tags", {})
        cs = geom(el)
        if len(cs) < 2:
            continue
        start = len(nodes_ll)
        for p in cs:
            parent.append(len(nodes_ll))
            nodes_ll.append(p)
        roads.append({"k": t.get("highway", ""), "cs": cs,
                      "name": t.get("name", ""), "idx": (start, len(cs))})

    # 网格 union-find 合并近邻顶点
    grid = {}
    for i, (lat, lon) in enumerate(nodes_ll):
        x, y = xy(lat, lon)
        key = (int(x // SNAP_TOL_M), int(y // SNAP_TOL_M))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((key[0] + dx, key[1] + dy), []):
                    x2, y2 = xy(*nodes_ll[j])
                    if (x - x2) ** 2 + (y - y2) ** 2 <= SNAP_TOL_M ** 2:
                        union(i, j)
        grid.setdefault(key, []).append(i)

    rep_idx = {}
    nodes = []          # 平面坐标（米，北向为正）
    node_ll = []
    # 原始节点 -> 图节点
    for i, (lat, lon) in enumerate(nodes_ll):
        r = find(i)
        if r not in rep_idx:
            rep_idx[r] = len(nodes)
            nodes.append(xy(lat, lon))
            node_ll.append((lat, lon))

    adj = [[] for _ in nodes]
    edges = {}
    edge_len = 0.0
    for rd in roads:
        start, n = rd["idx"]
        v = SPEED.get(rd["k"], DEFAULT_SPEED)
        pen = CROSS_PENALTY_S.get(rd["k"], 0.0)
        ids = [rep_idx[find(start + k)] for k in range(n)]
        cs = rd["cs"]
        for k in range(n - 1):
            a, b = ids[k], ids[k + 1]
            if a == b:
                continue
            key = (min(a, b), max(a, b))
            if key in edges:
                continue
            L = hav(cs[k][0], cs[k][1], cs[k + 1][0], cs[k + 1][1])
            if L <= 0:
                continue
            t = L / v + pen
            edges[key] = t
            adj[a].append((b, t))
            adj[b].append((a, t))
            edge_len += L
    print(f"  路网节点 {len(nodes)}，边 {len(edges)}，总长 {edge_len/1000:.2f} km")

    # ---- 图节点空间索引（建筑锚点用）
    ngrid = {}
    for i, (x, y) in enumerate(nodes):
        ngrid.setdefault((int(x // SNAP_TOL_M), int(y // SNAP_TOL_M)), []).append(i)

    def nearest_node(x, y, max_m):
        best, bd = -1, math.inf
        rng = int(max_m // SNAP_TOL_M) + 2
        key = (int(x // SNAP_TOL_M), int(y // SNAP_TOL_M))
        for dx in range(-rng, rng + 1):
            for dy in range(-rng, rng + 1):
                for i in ngrid.get((key[0] + dx, key[1] + dy), []):
                    nx, ny = nodes[i]
                    d = math.hypot(nx - x, ny - y)
                    if d < bd:
                        bd, best = d, i
        return best, bd

    # ---- 建筑锚点（虚拟入口边）
    for b in buildings:
        idx, d = nearest_node(b["c"][0], b["c"][1], ANCHOR_MAX_M)
        if idx < 0:
            b["anchor"] = None
            b["anchorDist"] = None
            continue
        node_id = len(nodes)
        nodes.append((b["c"][0], b["c"][1]))
        adj.append([])
        t = d / 1.35
        adj[node_id].append((idx, t))
        adj[idx].append((node_id, t))
        edges[(min(node_id, idx), max(node_id, idx))] = t
        b["anchor"] = node_id
        b["anchorDist"] = round(d, 1)

    # ---- Dijkstra
    def dijkstra(src):
        dist = [math.inf] * len(nodes)
        dist[src] = 0.0
        pq = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, w in adj[u]:
                nd = d + w
                if nd < dist[v] - 1e-12:
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        return dist

    # ---- 关键设施命中
    dests = {}
    for key in KEY_NAMES:
        for b in buildings:
            if key in b["name"]:
                dests[key] = b
                break
    print(f"  关键设施命中 {len(dests)}/{len(KEY_NAMES)}")

    # ---- 建筑到关键设施步行时间（分钟）
    cache = {}
    for b in buildings:
        times = {}
        for k, d in dests.items():
            if d is b:
                continue
            if d["anchor"] is None or b["anchor"] is None:
                continue
            if d["anchor"] not in cache:
                cache[d["anchor"]] = dijkstra(d["anchor"])
            v = cache[d["anchor"]][b["anchor"]]
            times[k] = round(v / 60.0, 1) if math.isfinite(v) else None
        b["times"] = times

    # ---- p-中位选址（p=4），用于三维场景中的服务点
    # 候选：命名齐全的教学/实验/图书/行政楼（服务点应落在可用楼宇，而非体育场馆或食堂）
    cand = [b for b in buildings if b["cat"] in {"教学", "图书", "行政", "实验"}
            and b["name"] and b["anchor"] is not None]
    dem = [b for b in buildings if b["area"] >= 150 and b["anchor"] is not None]
    weights = [b["area"] * max(b["levels"], 1) for b in dem]
    D = {}
    for c in cand:
        D[c["id"]] = dijkstra(c["anchor"])
    chosen, best = [], [math.inf] * len(dem)
    for _ in range(4):
        bg, bc = -math.inf, None
        for c in cand:
            if c in chosen:
                continue
            dd = D[c["id"]]
            gain = 0.0
            for i, b in enumerate(dem):
                t = dd[b["anchor"]]
                if t < best[i]:
                    gain += weights[i] * ((best[i] - t) if math.isfinite(best[i]) else 900.0)
            if gain > bg:
                bg, bc = gain, c
        if bc is None:
            break
        chosen.append(bc)
        dd = D[bc["id"]]
        for i, b in enumerate(dem):
            t = dd[b["anchor"]]
            if t < best[i]:
                best[i] = t
    fin = [t for t in best if math.isfinite(t)]
    cov5 = 100 * sum(w for t, w in zip(best, weights) if math.isfinite(t) and t <= 300) / sum(weights)
    print(f"  选址 p=4: 平均 {sum(fin)/len(fin)/60:.2f} min，5 min 覆盖 {cov5:.1f}%  "
          f"-> {[c['name'].replace('浙江大学城市学院','') for c in chosen]}")

    # ---- 地表覆盖
    landuse = []
    for el in load("landuse.json"):
        t = el.get("tags", {})
        key = t.get("natural") or t.get("leisure") or t.get("landuse") or t.get("amenity")
        if key not in LAND_LIGHT:
            continue
        cs = geom(el)
        if len(cs) < 3:
            continue
        landuse.append({"t": key,
                        "p": [[round(v, 1) for v in xy(la, lo)] for la, lo in cs]})

    # ---- 道路（地面贴图用）
    road_out = []
    for rd in roads:
        k = rd["k"]
        road_out.append({
            "k": "major" if k in MAJOR else ("walk" if k in WALK else "minor"),
            "p": [[round(v, 1) for v in xy(la, lo)] for la, lo in rd["cs"]],
        })

    # ---- 范围
    xs, ys = [], []
    for b in buildings:
        for x, y in b["poly"]:
            xs.append(x); ys.append(y)
    bbox = {"minx": round(min(xs), 1), "maxx": round(max(xs), 1),
            "miny": round(min(ys), 1), "maxy": round(max(ys), 1)}
    CX, CY = (bbox["minx"] + bbox["maxx"]) / 2, (bbox["miny"] + bbox["maxy"]) / 2

    # ---- 分区（南北校区）：按建筑北向坐标找最大间隙切分
    cys = sorted(b["c"][1] for b in buildings)
    gaps = [(cys[i + 1] - cys[i], i) for i in range(len(cys) - 1)]
    _, gi = max(gaps)
    split_y = (cys[gi] + cys[gi + 1]) / 2
    south = [b for b in buildings if b["c"][1] < split_y]
    north = [b for b in buildings if b["c"][1] >= split_y]

    def sub_box(group):
        if not group:
            return {"minx": bbox["minx"], "maxx": bbox["maxx"],
                    "miny": bbox["miny"], "maxy": bbox["maxy"]}
        gx = [p[0] for b in group for p in b["poly"]]
        gy = [p[1] for b in group for p in b["poly"]]
        return {"minx": min(gx), "maxx": max(gx), "miny": min(gy), "maxy": max(gy)}

    def cam(box_, az_deg, el_deg, k=1.55):
        """由平面范围反推相机（世界坐标：x 东, y 上, z = -北）"""
        bcx, bcy = (box_["minx"] + box_["maxx"]) / 2, (box_["miny"] + box_["maxy"]) / 2
        w = max(box_["maxx"] - box_["minx"], 1.0)
        h = max(box_["maxy"] - box_["miny"], 1.0)
        span = max(w, h)
        dist = span * k
        az, el = math.radians(az_deg), math.radians(el_deg)
        dx = math.sin(az) * math.cos(el) * dist
        dz = -math.cos(az) * math.cos(el) * dist
        dy = math.sin(el) * dist
        tx, tz = bcx - CX, CY - bcy
        return {"pos": [round(tx + dx, 1), round(dy, 1), round(tz + dz, 1)],
                "tgt": [round(tx, 1), 0, round(tz, 1)]}

    views = {
        # 方位角 180° ≈ 相机位于正南看正北，画面北向朝上，符合地图习惯
        "all": cam(bbox, 176, 49, 1.85),
        "south": cam(sub_box(south), 168, 38, 1.28),
        "north": cam(sub_box(north), 194, 38, 1.28),
        "core": cam(sub_box([b for b in buildings if b["cat"] == "教学"] or north), 170, 32, 1.15),
        "top": {"pos": [0, round(max(bbox["maxy"] - bbox["miny"], bbox["maxx"] - bbox["minx"]) * 1.45, 1),
                        round(max(bbox["maxy"] - bbox["miny"], bbox["maxx"] - bbox["minx"]) * 0.30, 1)],
                "tgt": [0, 0, 0]},
    }

    # ---- 与校方手绘地图的名称对照（data/name_aliases.csv 为人工核对表）
    alias_path = DATA / "name_aliases.csv"
    audit_rows = []
    if alias_path.exists():
        with alias_path.open(encoding="utf-8-sig") as fh:
            audit_rows = list(csv.DictReader(fh))
    def _norm_name(n: str) -> str:
        return (n or "").replace("浙江大学城市学院", "").replace(
            "浙江大学工程师学院", "").strip()

    alias_pool = {}   # 归一化名称 -> 待分配的对照条目（同名多栋时按南北顺序依次分配）
    for r in audit_rows:
        mn = _norm_name(r.get("model_name"))
        if mn:
            alias_pool.setdefault(mn, []).append({
                "mapName": r["map_name"].strip(),
                "match": r["match_type"].strip(),
                "note": (r.get("note") or "").strip()})

    def _lookup(bname: str):
        key = _norm_name(bname)
        pool = alias_pool.get(key)
        if pool:
            return pool[0]
        # 前缀匹配：CSV 写「精诚楼」，模型为「精诚楼1」「精诚楼2」
        best = None
        for k, v in alias_pool.items():
            if key.startswith(k) and (best is None or len(k) > len(best[0])):
                best = (k, v)
        return best[1][0] if best else None

    # 同名建筑按纬度从北到南依次取用 CSV 中同名的多个条目
    _seen = {}
    alias_by_id = {}
    for b in sorted(buildings, key=lambda x: -x["c"][1]):
        key = _norm_name(b["name"])
        pool = alias_pool.get(key)
        if pool:
            i = _seen.get(key, 0)
            alias_by_id[b["id"]] = pool[min(i, len(pool) - 1)]
            _seen[key] = i + 1
        elif key:
            hit = _lookup(b["name"])
            if hit:
                alias_by_id[b["id"]] = hit
    match_stat = {}
    for r in audit_rows:
        match_stat[r["match_type"]] = match_stat.get(r["match_type"], 0) + 1

    # ---- 手绘地图配准补名（data/name_from_map.csv，按 OSM id 精确挂接）----
    reg_path = DATA / "name_from_map.csv"
    n_reg = 0
    if reg_path.exists():
        with reg_path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                try:
                    oid = int(r["osm_id"])
                except (KeyError, ValueError):
                    continue
                if oid in alias_by_id:
                    continue
                alias_by_id[oid] = {"mapName": r["map_name"].strip(),
                                    "match": "配准",
                                    "note": (r.get("basis") or "").strip()}
                n_reg += 1
    print(f"  手绘地图配准补名 {n_reg} 栋（data/name_from_map.csv）")

    roofs = roof_colors_from_imagery(buildings, bbox)
    print(f"  屋顶色采样 {len(roofs)} 栋（来自正射影像）")

    scene = {
        "meta": {"campus": "浙大城市学院（湖州街 51 号）",
                 "source": "OpenStreetMap contributors, ODbL 1.0",
                 "imagery": "Esri World Imagery（正射瓦片）",
                 "nodes": len(nodes), "edges": len(edges),
                 "road_km": round(edge_len / 1000, 2),
                 "south_split": round(split_y, 1),
                 "n_south": len(south), "n_north": len(north)},
        "views": views,
        "floorH": FLOOR_H,
        "bbox": bbox,
        "groundImage": ground_image_dataurl(),
        "groundImageRect": [round(bbox["minx"], 1), round(bbox["miny"], 1),
                            round(bbox["maxx"], 1), round(bbox["maxy"], 1)],
        "catColors": CAT_COLOR,
        "landColors": LAND_LIGHT,
        "nodes": [[round(x, 1), round(y, 1)] for x, y in nodes],
        "edges": [[a, b, round(t, 2)] for (a, b), t in edges.items()],
        "buildings": [{
            "id": b["id"], "name": b["name"], "cat": b["cat"],
            "levels": round(b["levels"], 1), "levelsEst": b["levels_est"],
            "area": b["area"], "floor": round(b["area"] * max(b["levels"], 1), 1),
            "c": b["c"], "poly": [list(p) for p in b["poly"]],
            "anchor": b["anchor"], "anchorDist": b["anchorDist"],
            "lat": round(b["lat"], 6), "lon": round(b["lon"], 6),
            "times": b["times"],
            "roof": roofs.get(b["id"], ""),
            "mapName": (alias_by_id.get(b["id"]) or {}).get("mapName", ""),
            "nameMatch": (alias_by_id.get(b["id"]) or {}).get("match", ""),
        } for b in buildings],
        "nameAudit": {"rows": audit_rows, "stat": match_stat},
        "roads": road_out,
        "landuse": landuse,
        "siting": [{"name": c["name"], "xy": c["c"], "levels": c["levels"]} for c in chosen],
        "sitingStats": {"p": len(chosen), "mean_min": round(sum(fin) / len(fin) / 60, 2),
                        "coverage_5min": round(cov5, 1)},
        "keyDests": [k for k in dests],
    }
    (OUT / "scene.json").write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
    print(f"    -> scene.json  {(OUT/'scene.json').stat().st_size/1024:.0f} KB")

    # ---- 建筑台账
    with (OUT / "buildings.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        keys = ["name", "cat", "levels", "levels_est", "area", "floor", "lat", "lon", "anchor_dist"]
        w = csv.writer(fh)
        w.writerow(keys + list(dests))
        for b in sorted(buildings, key=lambda x: (-x["area"])):
            w.writerow([b["name"] or f"未命名#{b['id']}", b["cat"], b["levels"],
                        b["levels_est"], b["area"], round(b["area"] * b["levels"], 1),
                        round(b["lat"], 6), round(b["lon"], 6), b["anchorDist"]]
                       + [b["times"].get(k, "") for k in dests])
    print(f"    -> buildings.csv  ({len(buildings)} 行)")

    total_floor = sum(b["area"] * max(b["levels"], 1) for b in buildings)
    print(f"\n  建筑基底合计 {sum(b['area'] for b in buildings):,.0f} m²；"
          f"建筑面积合计 {total_floor:,.0f} m²（含层数估计）")
    print(f"  校园凸包面积 {poly_area(campus_hull)/1e6:.3f} km²")


if __name__ == "__main__":
    main()


