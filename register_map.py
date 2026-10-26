# -*- coding: utf-8 -*-
"""
把校方手绘校园地图「配准」到 OSM 平面坐标，据此给 OSM 缺名的楼补名字。

为什么需要配准，而不是直接按名字对
----------------------------------
手绘图上 74 条标注里有 40 条在 OSM 里没有同名要素。要判断「图上这栋」是不是
「OSM 里那个无名多边形」，只能靠几何位置，所以先把图配准到平面坐标。

配准怎么做
----------
1) 用 24 个「已有确定校图名」的建筑作锚点，最小二乘拟合像素 → 平面坐标的仿射变换
   （先剔除「待核」对应关系，再迭代剔除残差 > 45 m 的离群锚点）；
2) 仿射残差中位约 23 m，说明手绘图是示意图（南北拉长、中段压缩），
   因此再叠一层「最近 k 个锚点的残差反距离加权」，补偿局部变形；
3) 把配准结果反投影回图上（红点 = 模型里的楼，蓝十字 = OSM 无名楼），
   生成 out/map_registration.png 供人工核验；
4) 据此**人工判定**哪些校图标注能对应到具体的 OSM 多边形。只有北校区东侧「文」字楼
   群和西北侧「教学楼 A–F」群的位置关系足够清楚，才给出确定对应；其余如实列为
   「OSM 无对应轮廓」，不猜。

输出：data/name_from_map.csv（osm_id → 校图名）、data/map_register_report.txt、
      out/map_registration.png

运行：py -3.14 register_map.py
"""
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "out"

# 手绘图像素坐标（1033×1774，左上角为原点），值为标注文字中心
MAP_PX = {
    "辅助用房": (247, 62), "风雨操场(北)": (325, 85), "工4": (513, 72),
    "北大门": (588, 80), "工1-3": (845, 70), "北秀食堂": (712, 128),
    "土木实验用房": (390, 143), "实训用房": (500, 145), "教育超市": (728, 158),
    "工程师学院食堂": (392, 196), "至善楼": (478, 208), "惟学楼": (648, 202),
    "求真楼": (790, 182), "思睿楼": (808, 265), "操场(北)": (285, 240),
    "教学楼A": (270, 340), "教学楼B": (352, 342), "图书馆": (582, 358),
    "图信报告厅": (500, 380), "尚雅楼": (766, 358), "教学楼E": (238, 405),
    "教学楼F": (335, 410), "教学楼C": (240, 450), "教学楼D": (345, 455),
    "问源楼": (735, 455), "陈家桥河": (555, 550), "勤人坡": (555, 597),
    "理工一": (272, 578), "理工二": (272, 610), "理工三": (272, 665),
    "理工四": (345, 615), "理工五": (350, 712), "文一": (752, 570),
    "文二": (722, 617), "文三": (888, 568), "魏绍相楼": (830, 638),
    "吉瑞大厦": (855, 685), "文五": (770, 700), "行政综合楼": (648, 708),
    "正门": (528, 715), "UW学院大楼（文六）": (770, 760), "湖州街": (432, 795),
    "综合实验楼": (295, 800), "教六": (395, 889), "教五": (330, 892),
    "欣瑞大厦": (940, 919), "风雨操场(南)": (720, 944), "教四": (345, 952),
    "教七": (270, 959), "第二食堂": (700, 984), "教三": (315, 1017),
    "医学实验中心": (253, 1104), "致远楼": (668, 1146), "教师公寓": (735, 1146),
    "金如新楼": (405, 1181), "西体楼": (480, 1182), "东体楼": (545, 1180),
    "学生公寓": (210, 1209), "菜鸟驿站": (322, 1209), "晨苑餐厅": (400, 1209),
    "体育馆": (628, 1214), "创业街": (425, 1264), "嘉贤楼": (645, 1269),
    "操场(南)": (525, 1289), "弘毅楼": (735, 1309), "明德楼": (262, 1319),
    "精诚楼": (350, 1319), "科技综合楼": (430, 1419), "小舟东美食城": (600, 1424),
    "教二": (520, 1539), "教一": (325, 1544), "西辅助楼": (245, 1619),
    "东辅助楼": (525, 1619), "南门": (420, 1664),
}

# 人工判定的配准结果：osm_id -> (校图名, 依据)
# 判据：配准后在图上反投影叠加（out/map_registration.png），逐个确认标注引线与楼块的一一对应。
MANUAL = {
    544691361: ("文一", "北校区东侧最北的一栋，图上「文一」引线所指"),
    544691362: ("文二", "「文一」正南一栋，图上「文二」引线所指"),
    544691363: ("魏绍相楼", "「文二」东南，图上「魏绍相楼」引线所指"),
    544691359: ("文五", "东侧组最南一栋，图上「文五」引线所指"),
    547574292: ("教学楼B", "西北组最北的大楼块（2573 m²，OSM 把 A/B 合成一个多边形）"),
    547574293: ("教学楼E", "西北组左列中间，图上「教学楼E」引线所指"),
    547574294: ("教学楼C", "西北组左列最南，图上「教学楼C」引线所指"),
    547574295: ("教学楼D", "西北组右列最南，图上「教学楼D」引线所指"),
    547574296: ("教学楼F", "西北组右列中间，图上「教学楼F」引线所指"),
}

# 校图上仍无法在 OSM 找到对应轮廓的标注（如实记录，不猜）
UNMATCHED = ["教学楼A", "文三", "吉瑞大厦", "欣瑞大厦", "弘毅楼", "金如新楼",
             "西体楼", "东体楼", "综合实验楼", "第二食堂", "教五", "教六",
             "实训用房", "辅助用房", "西辅助楼", "东辅助楼", "图信报告厅"]


def norm(s):
    for pre in ("浙江大学城市学院", "浙江大学工程师学院", "城市学院"):
        s = s.replace(pre, "")
    return s.strip()


def fit(keys, pts):
    A = np.array([[pts[k][0], pts[k][1], 1.0] for k in keys])
    B = np.array([[pts[k][2], pts[k][3]] for k in keys])
    M, *_ = np.linalg.lstsq(A, B, rcond=None)
    return M, dict(zip(keys, np.hypot(*(A @ M - B).T)))


def idw(u, v, anchors, k=6, power=2.0):
    ds = sorted((math.hypot(u - a[0], v - a[1]), i) for i, a in enumerate(anchors))[:k]
    wsum = dx = dy = 0.0
    for d, i in ds:
        w = 1.0 / max(d, 1.0) ** power
        dx += w * (anchors[i][3][0] - anchors[i][2][0])
        dy += w * (anchors[i][3][1] - anchors[i][2][1])
        wsum += w
    return (dx / wsum, dy / wsum) if wsum else (0.0, 0.0)


def main():
    scene = json.loads((OUT / "scene.json").read_text(encoding="utf-8"))
    blds = scene["buildings"]
    by_id = {b["id"]: b for b in blds}

    # ---- 1) 锚点 ----
    unsure = set()
    own = set()
    for r in csv.DictReader((DATA / "name_aliases.csv").open(encoding="utf-8-sig")):
        if r["match_type"] == "待核":
            unsure.add(r["map_name"])
        if r["match_type"] == "模型独有":
            own.add(norm(r["model_name"]))

    grouped = {}
    for b in blds:
        mn = (b.get("mapName") or "").strip()
        if mn and not mn.startswith("（仅 OSM）") and mn in MAP_PX and mn not in unsure:
            grouped.setdefault(mn, []).append((b["c"][0], b["c"][1]))
    pts = {mn: (MAP_PX[mn][0], MAP_PX[mn][1],
                sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps))
           for mn, ps in grouped.items()}

    keys = list(pts)
    M, res = fit(keys, pts)
    dropped = []
    while len(keys) > 8:
        worst = max(res, key=res.get)
        if res[worst] <= 45.0:
            break
        dropped.append((worst, res[worst]))
        keys.remove(worst)
        M, res = fit(keys, pts)

    anchors = []
    for k in keys:
        u, v, x, y = pts[k]
        pred = tuple((np.array([[u, v, 1.0]]) @ M)[0])
        anchors.append((u, v, pred, (x, y)))

    lines = []

    def P(s=""):
        print(s)
        lines.append(s)

    P("=" * 68)
    P("手绘地图 → 平面坐标 配准报告")
    P("=" * 68)
    P(f"锚点 {len(keys)} 个（模型里已确定校图名、且非「待核」的建筑）")
    rv = list(res.values())
    P(f"仿射残差：中位 {np.median(rv):.1f} m · 均值 {np.mean(rv):.1f} m · 最大 {max(rv):.1f} m")
    sx, sy = math.hypot(M[0, 0], M[1, 0]), math.hypot(M[0, 1], M[1, 1])
    P(f"比例尺 {sx:.3f} m/px（横）· {sy:.3f} m/px（纵）→ 手绘图覆盖约 "
      f"{sx*1033:.0f} m × {sy*1774:.0f} m")
    if dropped:
        P("剔除离群锚点：" + "、".join(f"{k}({r:.0f} m)" for k, r in dropped))
    P("")

    # ---- 2) 人工配准结果 ----
    rows = []
    for oid, (nm, why) in MANUAL.items():
        b = by_id.get(oid)
        if not b:
            P(f"  ! 场景里没有 id={oid}")
            continue
        u, v = MAP_PX[nm]
        base = tuple((np.array([[u, v, 1.0]]) @ M)[0])
        dx, dy = idw(u, v, anchors)
        px, py = base[0] + dx, base[1] + dy
        rows.append({"osm_id": oid, "map_name": nm,
                     "dist_m": round(math.hypot(b["c"][0] - px, b["c"][1] - py), 1),
                     "pred_x": round(px, 1), "pred_y": round(py, 1),
                     "osm_name": b["name"], "basis": why})

    # 工1-3 是「一标多楼」，按 OSM 已有名字直接挂
    for nm in ("工1", "工2", "工3"):
        for b in blds:
            if norm(b["name"] or "") == nm:
                rows.append({"osm_id": b["id"], "map_name": "工1-3",
                             "dist_m": 0.0, "pred_x": "", "pred_y": "",
                             "osm_name": b["name"],
                             "basis": "校图以「工1-3」统称三栋，按 OSM 名称直接挂"})

    rows.sort(key=lambda r: r["map_name"])
    out_csv = DATA / "name_from_map.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["osm_id", "map_name", "osm_name",
                                          "dist_m", "pred_x", "pred_y", "basis"])
        w.writeheader()
        w.writerows(rows)

    P(f"{'校图名':<10}{'OSM id':>14}{'残差':>8}  说明")
    P("-" * 68)
    for r in rows:
        P(f"{r['map_name']:<10}{r['osm_id']:>14}{r['dist_m']:8.1f}  {r['basis'][:34]}")
    P("")
    P(f"共补 {len(rows)} 栋（其中 {sum(1 for r in rows if r['map_name']=='工1-3')} 栋为「工1-3」组）")
    P("仍无 OSM 对应轮廓的校图标注（%d 条）：" % len(UNMATCHED))
    P("  " + "、".join(UNMATCHED))

    # ---- 3) 配准校验图 ----
    try:
        from PIL import Image, ImageDraw, ImageFont
        SRC = DATA / "map_source.jpg"
        if not SRC.exists():
            raise FileNotFoundError(
                f"缺少配准基准图 {SRC}，请把校方手绘地图放到该路径后再跑配准校验")
        im = Image.open(SRC).convert("RGB")
        d = ImageDraw.Draw(im, "RGBA")
        f14 = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        Aff = np.array([[M[0, 0], M[1, 0], M[2, 0]],
                        [M[0, 1], M[1, 1], M[2, 1]], [0, 0, 1.0]])
        Minv = np.linalg.inv(Aff)

        def to_px(x, y):
            p = Minv @ np.array([x, y, 1.0])
            return float(p[0]), float(p[1])

        for k in keys:      # 红点：已定名的楼
            u, v = to_px(pts[k][2], pts[k][3])
            d.ellipse([u - 5, v - 5, u + 5, v + 5], fill=(220, 30, 30, 210),
                      outline=(255, 255, 255, 220), width=1)
        for r in rows:      # 蓝点：本次补名的楼
            b = by_id[r["osm_id"]]
            u, v = to_px(b["c"][0], b["c"][1])
            d.ellipse([u - 6, v - 6, u + 6, v + 6], fill=(30, 110, 220, 225),
                      outline=(255, 255, 255, 230), width=2)
            d.text((u + 8, v - 8), r["map_name"], font=f14, fill=(15, 60, 160, 255))
        im.thumbnail((900, 1600))
        im.save(OUT / "map_registration.png")
        P("")
        P("-> out/map_registration.png（红点=已定名楼，蓝点=本次补名楼）")
    except Exception as e:      # 原图不在本机时跳过，不影响主流程
        P(f"（跳过校验图：{e}）")

    (DATA / "map_register_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    P(f"-> data/name_from_map.csv  {len(rows)} 条")


if __name__ == "__main__":
    main()
