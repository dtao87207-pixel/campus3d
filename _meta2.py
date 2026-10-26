import json, sys, urllib.request, collections, statistics
sys.stdout.reconfigure(encoding="utf-8")
scene = json.load(open("out/scene.json", encoding="utf-8"))
ids = [b["id"] for b in scene["buildings"]]
url = "https://api.openstreetmap.org/api/0.6/ways?ways=" + ",".join(map(str, ids))
req = urllib.request.Request(url, headers={"User-Agent": "campus3d-model/1.0 (education)"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        xml = r.read().decode("utf-8")
except Exception as e:
    print("OSM API 失败:", type(e).__name__, e); sys.exit(1)

import re
rec = {}
for m in re.finditer(r'<way id="(\d+)"[^>]*version="(\d+)"[^>]*timestamp="([^"]+)"[^>]*>', xml):
    rec[int(m.group(1))] = (int(m.group(2)), m.group(3))
print("拿到 80 栋中", len(rec), "栋的编辑元数据")
yrs = collections.Counter(t[:4] for _, t in rec.values())
print("最后编辑年份分布:", dict(sorted(yrs.items())))
ts = sorted(t for _, t in rec.values())
print("最早:", ts[0][:10], " 中位:", ts[len(ts)//2][:10], " 最新:", ts[-1][:10])
print("2024 年以后编辑过:", sum(1 for _, t in rec.values() if t >= "2024"), "/", len(rec))
names = {b["id"]: (b.get("mapName") or b.get("name") or "(无名)") for b in scene["buildings"]}
old = sorted(rec.items(), key=lambda kv: kv[1][1])[:8]
print("\n最老的 8 栋:")
for i, (ver, t) in old:
    print(f"  {t[:10]}  v{ver:<3} {names[i]}  (id {i})")
json.dump({str(k): {"v": v, "ts": t} for k, (v, t) in rec.items()},
          open("out/osm_edit_meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
