import json, sys, urllib.parse, urllib.request, collections, time
sys.stdout.reconfigure(encoding="utf-8")
scene = json.load(open("out/scene.json", encoding="utf-8"))
ids = [b["id"] for b in scene["buildings"]]
Q = "[out:json][timeout:60];way(id:%s);out meta;" % ",".join(str(i) for i in ids)
MIRRORS = ["https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter",
           "https://overpass-api.de/api/interpreter"]
data = None
for u in MIRRORS:
    for attempt in range(2):
        try:
            req = urllib.request.Request(u, data=urllib.parse.urlencode({"data": Q}).encode(),
                                         headers={"User-Agent": "campus3d/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            print("镜像:", u); break
        except Exception as e:
            print("失败", u, type(e).__name__); time.sleep(3)
    if data: break
if not data: sys.exit(1)
meta = {e["id"]: e for e in data["elements"]}
json.dump({str(k): {"ts": v.get("timestamp"), "ver": v.get("version")} for k, v in meta.items()},
          open("out/osm_edit_meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
hit = [(i, meta[i]["timestamp"], meta[i].get("version")) for i in ids if i in meta and meta[i].get("timestamp")]
print(f"80 栋有 meta: {len(hit)}")
print("按最后编辑年份:", dict(sorted(collections.Counter(t[:4] for _, t, _ in hit).items())))
ts = sorted(t for _, t, _ in hit)
print("最早:", ts[0], "最新:", ts[-1])
print("2025 年以来编辑过:", sum(1 for _, t, _ in hit if t >= "2025-01-01"), "/", len(hit))
print("2026 年以来编辑过:", sum(1 for _, t, _ in hit if t >= "2026-01-01"), "/", len(hit))
