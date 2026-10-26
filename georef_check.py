# -*- coding: utf-8 -*-
"""阶段0：影像地理配准 + 用 OSM 轮廓叠加校验对齐"""
import json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

# ---- 与 build_scene.py 完全一致的局部投影 ----
LAT0, LON0 = 30.32650, 120.15100
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT0))
M_PER_DEG_LAT = 110540.0

def to_xy(lat, lon):
    return ((lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT)

# ---- 影像瓦片参数（下载时的常量）----
Z = 18
TX0, TY0 = 218556, 107871
WORLD = 256 * 2**Z

def px_to_ll(px, py):
    X = TX0 * 256 + px
    Y = TY0 * 256 + py
    lon = X / WORLD * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * Y / WORLD))))
    return lat, lon

def ll_to_px(lat, lon):
    X = (lon + 180.0) / 360.0 * WORLD
    Y = (1 - math.log(math.tan(math.radians(lat)) + 1/math.cos(math.radians(lat))) / math.pi) / 2 * WORLD
    return X - TX0 * 256, Y - TY0 * 256

img = Image.open(OUT / "imagery_bbox.png").convert("RGB")
W, H = img.size
print(f"影像 {W}x{H}  px")

# 交叉校验：两条路径算同一像素的地理坐标是否一致
for px, py in [(0,0), (W-1, H-1), (W//2, H//2)]:
    lat, lon = px_to_ll(px, py)
    bx, by = ll_to_px(lat, lon)
    x, y = to_xy(lat, lon)
    print(f"  px({px:4d},{py:4d}) -> ({lat:.6f},{lon:.6f}) -> 平面({x:8.1f},{y:8.1f})  回算 px({bx:.2f},{by:.2f})")

# ---- 把 OSM 80 栋轮廓画到影像上 ----
scene = json.load(open(OUT / "scene.json", encoding="utf-8"))
ov = img.copy()
d = ImageDraw.Draw(ov, "RGBA")
for b in scene["buildings"]:
    pts = []
    for (x, y) in b["poly"]:
        lat = y / M_PER_DEG_LAT + LAT0
        lon = x / M_PER_DEG_LON + LON0
        px, py = ll_to_px(lat, lon)
        pts.append((px, py))
    d.polygon(pts, fill=(0, 200, 255, 70), outline=(0, 255, 255, 220))
ov.save(OUT / "step0_overlay_full.jpg", quality=86)

# 局部放大：图书馆一带（北校区核心）
cx, cy = ll_to_px(30.3300, 120.1515)
r = 300
box = (int(cx-r), int(cy-r), int(cx+r), int(cy+r))
ov.crop(box).resize((r*4, r*4), Image.LANCZOS).save(OUT / "step0_overlay_lib.jpg", quality=90)
print("-> out/step0_overlay_full.jpg, out/step0_overlay_lib.jpg")
