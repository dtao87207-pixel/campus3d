# 按用户提供的「最新版校方手绘地图」校正显示名（只改 map_name 与 note，model_name 保持以保证匹配不断）
import csv, io, sys
sys.stdout.reconfigure(encoding="utf-8")
P = "data/name_aliases.csv"
rows = list(csv.DictReader(open(P, encoding="utf-8-sig")))
COLS = ["map_name", "model_name", "match_type", "category", "note"]

RENAME = {
    "（仅 OSM）校医务室": ("医务室", "写法差异", "新版校图标注「医务室」"),
    "土木实验用房":       ("土木楼", "写法差异", "新版校图标注「土木楼」"),
    "行政综合楼":         ("行政楼", "写法差异", "新版校图标注「行政楼」"),
    "UW学院大楼（文六）": ("文六", "别名", "新版校图标注「文六」"),
    "科技综合楼":         ("科技楼", "写法差异", "新版校图标注「科技楼」"),
    "勤人坡":             ("情人坡", "写法差异", "新版校图标注「情人坡」"),
    "北大门":             ("北门", "写法差异", "新版校图标注「北门」"),
    "体育馆":             ("体育馆（北）", "写法差异", "北校区体育馆；南校区那座为「老体育馆」"),
}
changed = []
for r in rows:
    mn = r["map_name"]
    if mn in RENAME:
        new, mt, note = RENAME[mn]
        r["map_name"], r["match_type"], r["note"] = new, mt, note
        changed.append((mn, new))

# 新版校图新增、旧表没有的标注
rows.append({"map_name": "老体育馆", "model_name": "老体育馆", "match_type": "一致",
             "category": "建筑", "note": "南校区老体育馆，新版校图单列"})
rows.append({"map_name": "工程师餐厅", "model_name": "", "match_type": "缺失",
             "category": "建筑", "note": "新版校图新增标注，OSM 无对应要素"})
rows.append({"map_name": "校园卡服务中心", "model_name": "", "match_type": "缺失",
             "category": "建筑", "note": "新版校图新增标注，OSM 无对应要素"})

buf = io.StringIO()
w = csv.DictWriter(buf, fieldnames=COLS, lineterminator="\n")
w.writeheader()
for r in rows:
    w.writerow({k: r.get(k, "") for k in COLS})
open(P, "w", encoding="utf-8-sig", newline="").write(buf.getvalue())
print("改名", len(changed), "条；新增 3 条；总行数", len(rows))
for a, b in changed: print("  ", a, "->", b)
