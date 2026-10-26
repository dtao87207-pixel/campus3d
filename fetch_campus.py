# -*- coding: utf-8 -*-
"""
浙大城市学院 · 三维校园模型 —— 第 1 步：抓取真实地理数据

数据源：OpenStreetMap / Overpass API（ODbL）
范围：30.3170,120.1420,30.3360,120.1600（南校区 + 北校区）
缓存：data/raw/*.json（重复运行自动跳过，--refetch 强制重抓）

用法：
    py -3.14 fetch_campus.py
    py -3.14 fetch_campus.py --refetch
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

BBOX = (30.3170, 120.1420, 30.3360, 120.1600)   # S, W, N, E
B = ",".join(f"{v:.4f}" for v in BBOX)

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
UA = {"User-Agent": "campus3d-model/1.0 (education; OSM ODbL)"}

QUERIES = {
    # 建筑轮廓 + 层数 + 名称
    "buildings.json": f"""
[out:json][timeout:180];
way["building"]({B});
out geom tags;
""",
    # 道路 / 步道（含台阶、室内走廊）
    "roads.json": f"""
[out:json][timeout:180];
way["highway"]({B});
out geom tags;
""",
    # 地表覆盖：水体、绿地、球场、停车场
    "landuse.json": f"""
[out:json][timeout:180];
(
  way["natural"]({B});
  way["landuse"]({B});
  way["leisure"~"^(pitch|track|park|garden|sports_centre|playground)$"]({B});
  way["amenity"="parking"]({B});
);
out geom tags;
""",
    # 设施点（食堂、医务室、校门、停车、球场等）
    "poi.json": f"""
[out:json][timeout:180];
(
  node["amenity"]({B});
  way["amenity"]({B});
  node["leisure"]({B});
  node["shop"]({B});
  node["tourism"]({B});
  node["barrier"~"^(gate|entrance|toll_booth)$"]({B});
  node["highway"="bus_stop"]({B});
  node["railway"]({B});
);
out center tags;
""",
    # 带名称节点：为 OSM 中仅有节点标注的教学楼/宿舍楼补名
    "labels.json": f"""
[out:json][timeout:120];
node["name"]({B});
out;
""",
}


def overpass(query: str, timeout: int = 240) -> dict:
    last = None
    for attempt in range(3):
        for ep in ENDPOINTS:
            try:
                url = ep + "?data=" + urllib.parse.quote(query)
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                n = len(data.get("elements", []))
                print(f"    [OK] {ep.split('/')[2]} -> {n} elements")
                return data
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
                print(f"    [--] {ep.split('/')[2]} 失败: {last}")
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Overpass 全部镜像失败: {last}")


def cached(name: str, query: str, refetch: bool = False) -> dict:
    p = RAW / name
    if not refetch and p.exists() and p.stat().st_size > 200:
        print(f"  缓存命中 {name} ({p.stat().st_size/1e6:.2f} MB)")
        return json.loads(p.read_text(encoding="utf-8"))
    print(f"  抓取 {name} ...")
    d = overpass(query)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def main() -> None:
    refetch = "--refetch" in sys.argv
    print("=" * 70)
    print("浙大城市学院 · 三维校园模型 · 数据抓取")
    print(f"范围 bbox = {BBOX}")
    print("=" * 70)
    for name, q in QUERIES.items():
        cached(name, q, refetch)
    print("\n原始数据已缓存到 data/raw/")


if __name__ == "__main__":
    main()
