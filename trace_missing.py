# -*- coding: utf-8 -*-
"""阶段1b：对配准预测位置上的 17 处「OSM 无轮廓」建筑，在影像局部窗口里自动描出屋顶

全局分割在密集校园里很难调；但局部窗口里干扰少，而且我们知道建筑大致在哪，
所以改成「小窗口 + 最近邻 blob + 最小外接旋转矩形」。
"""
import json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi
from shapely.geometry import Polygon, MultiPoint
from shapely.ops import unary_union
import register_map as R

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
LAT0, LON0 = 30.32650, 120.15100
M_LON = 111320.0 * math.cos(math.radians(LAT0))
M_LAT = 110540.0
Z = 18; TX0, TY0 = 218556, 107871; WORLD = 256 * 2**Z
PX_M = 40075016.686 * math.cos(math.radians(LAT0)) / WORLD

def xy_to_px(x, y):
    lat = y / M_LAT + LAT0; lon = x / M_LON + LON0
    X = (lon+180.0)/360.0*WORLD
    Y = (1-math.log(math.tan(math.radians(lat))+1/math.cos(math.radians(lat)))/math.pi)/2*WORLD
    return X-TX0*256, Y-TY0*256

img = Image.open(OUT/"imagery_bbox.png").convert("RGB")
W, H = img.size
hsv = np.asarray(img.convert("HSV")).astype(np.float32)/255.0
Hh, S, V = hsv[...,0], hsv[...,1], hsv[...,2]
gray = np.asarray(img.convert("L")).astype(np.float32)/255.0
std8 = np.sqrt(np.maximum(ndi.uniform_filter(gray**2, 9) - ndi.uniform_filter(gray,9)**2, 0))
green = (Hh > 0.20) & (Hh < 0.46) & (S > 0.28)
# 屋顶候选：低饱和、非过曝、非植被、纹理较平
roofish = (S < 0.34) & (V > 0.16) & (V < 0.92) & (~green) & (std8 < 0.095)

def load_mask(fn, buf=0.0):
    raw = json.load(open(ROOT/"data"/"raw"/fn, encoding="utf-8"))
    polys = []
    for e in raw["elements"]:
        g = e.get("geometry")
        if not g or len(g) < 3: continue
        try:
            p = Polygon([((q["lon"]-LON0)*M_LON, (q["lat"]-LAT0)*M_LAT) for q in g])
        except Exception: continue
        if not p.is_valid: p = p.buffer(0)
        if not p.is_empty: polys.append(p)
    m = Image.new("L", (W,H), 0); d = ImageDraw.Draw(m)
    g = unary_union(polys).buffer(buf) if polys else None
    if g is None: return np.zeros((H,W), bool)
    for p in (list(g.geoms) if hasattr(g,"geoms") else [g]):
        if p.is_empty: continue
        d.polygon([xy_to_px(x,y) for x,y in p.exterior.coords], fill=255)
    return np.array(m) > 0

# 注意：不要把 roads.json / landuse.json 多边形整体抠掉——它们是「线」被当成多边形，
# 抠出来会连整片校区一起抹掉（曾导致 17 处建筑全部检不出）。
# 道路靠「长条形状」在下游的 fill/长宽比过滤里自然排除。
ok = roofish

# ---------- 用 register_map 的锚点重新拟合，拿到 17 处的预测坐标 ----------
scene = json.load(open(OUT/"scene.json", encoding="utf-8"))
by_id = {b["id"]: b for b in scene["buildings"]}
keys = [k for k in R.MANUAL if k in by_id]
pts, anchors = {}, []
for k in keys:
    nm = R.MANUAL[k][0]
    if nm not in R.MAP_PX: continue
    px, py = R.MAP_PX[nm]
    c = by_id[k]["c"]
    pts[nm] = (px, py, c[0], c[1])
    anchors.append((px, py, c[0], c[1]))
M, resid = R.fit(list(pts), pts)
print("锚点 %d 个，仿射残差 中位 %.1f m 最大 %.1f m" % (
    len(pts), np.median(list(resid.values())), max(resid.values())))

def idw4(u, v, ans, k=6, power=2.0):
    """残差内插：ans 是 (px, py, x, y) 四元组（register_map.idw 用的是另一种结构，故自带一份）"""
    ds = sorted((math.hypot(u - a[0], v - a[1]), i) for i, a in enumerate(ans))[:k]
    ws = dx = dy = 0.0
    for d, i in ds:
        w = 1.0 / max(d, 1.0) ** power
        dx += w * (ans[i][2] - (M[0,0]*ans[i][0] + M[1,0]*ans[i][1] + M[2,0]))
        dy += w * (ans[i][3] - (M[0,1]*ans[i][0] + M[1,1]*ans[i][1] + M[2,1]))
        ws += w
    return (dx / ws, dy / ws) if ws else (0.0, 0.0)

def predict(px, py):
    x = M[0,0]*px + M[1,0]*py + M[2,0]
    y = M[0,1]*px + M[1,1]*py + M[2,1]
    dx, dy = idw4(px, py, anchors)
    return x + dx, y + dy

font = None
for cand in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
    try:
        font = ImageFont.truetype(cand, 20); break
    except Exception: pass

tiles, results = [], []
for name in R.UNMATCHED:
    if name not in R.MAP_PX: continue
    px, py = R.MAP_PX[name]
    ex, ey = predict(px, py)
    cx, cy = xy_to_px(ex, ey)
    r = int(85 / PX_M)                       # ±85 m 窗口
    x0, x1 = max(0,int(cx-r)), min(W,int(cx+r))
    y0, y1 = max(0,int(cy-r)), min(H,int(cy+r))
    rgb = np.asarray(img.crop((x0,y0,x1,y1))).astype(np.float32)
    hh, ww = rgb.shape[:2]
    # 多种子区域生长：从预测点及其邻域播种，按颜色相近扩张，取「最大且最像矩形」的一块
    best, bestscore = None, -1e9
    for dxs in (-10, 0, 10):
        for dys in (-10, 0, 10):
            sx, sy = int(ww/2 + dxs/PX_M), int(hh/2 + dys/PX_M)
            if not (2 <= sx < ww-2 and 2 <= sy < hh-2): continue
            seed = rgb[sy, sx]
            tol = 26.0
            mask = np.zeros((hh, ww), bool)
            stack = [(sy, sx)]; mask[sy, sx] = True; cnt = 1
            while stack and cnt < 60000:
                cy2, cx2 = stack.pop()
                for ny, nx in ((cy2-1,cx2),(cy2+1,cx2),(cy2,cx2-1),(cy2,cx2+1)):
                    if 0 <= ny < hh and 0 <= nx < ww and not mask[ny, nx]:
                        if abs(rgb[ny,nx,0]-seed[0]) + abs(rgb[ny,nx,1]-seed[1]) + abs(rgb[ny,nx,2]-seed[2]) < tol:
                            mask[ny, nx] = True; stack.append((ny, nx)); cnt += 1
            m = ndi.binary_closing(mask, np.ones((3,3)))
            m = ndi.binary_fill_holes(m)
            if m.sum() < 80: continue
            area = m.sum()*PX_M**2
            if area < 150 or area > 15000: continue
            yy, xx = np.nonzero(m)
            bh, bw = yy.max()-yy.min()+1, xx.max()-xx.min()+1
            fill = m.sum()/(bh*bw)
            if fill < 0.55 or bw > 6*bh or bh > 6*bw: continue
            d = math.hypot(xx.mean()+x0-cx, yy.mean()+y0-cy)*PX_M
            if d > 40: continue
            score = area**0.5*min(1.0, fill) - 2.0*d
            if score > bestscore: bestscore, best = score, (m, area, d, xx.mean()+x0, yy.mean()+y0)
    crop = img.crop((x0, y0, x1, y1)).convert("RGB").resize((340,340), Image.LANCZOS)
    d = ImageDraw.Draw(crop, "RGBA")
    sc = 340/(x1-x0)
    outline = None
    d.line([(170-14,170),(170+14,170)], fill=(255,220,0,255), width=2)
    d.line([(170,170-14),(170,170+14)], fill=(255,220,0,255), width=2)
    d.ellipse([170-46,170-46,170+46,170+46], outline=(255,220,0,120), width=2)
    if best and best[1] >= 600 and best[2] <= 22:
        m, area, dist, mx, my = best
        ptsxy = [((xx+x0-cx)*PX_M+ex, -(yy+y0-cy)*PX_M+ey)
                 for yy, xx in zip(*np.nonzero(ndi.binary_dilation(m, iterations=1)))]
        if len(ptsxy) > 50:
            rect = MultiPoint(ptsxy).convex_hull.minimum_rotated_rectangle
            outline = list(rect.exterior.coords)
            d.polygon([((X-ex)/PX_M+ (cx-x0), (ey-Y)/PX_M + (cy-y0)) for X,Y in outline],
                      outline=(255,50,50,255), fill=(255,50,50,55))
        d.text((6,6), f"{name}  {area:.0f}m²  d={dist:.0f}m", fill=(255,255,0), font=font)
        results.append({"map_name": name, "area": round(area), "dist_m": round(dist),
                        "pred": [round(ex,1), round(ey,1)],
                        "poly": [[round(X,1), round(Y,1)] for X,Y in outline] if outline else None})
    else:
        d.text((6,6), f"{name}  (未检出)", fill=(255,80,80), font=font)
        results.append({"map_name": name, "area": None, "dist_m": None,
                        "pred": [round(ex,1), round(ey,1)], "poly": None})
    tiles.append(crop)

json.dump(results, open(OUT/"step1b_traced.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
cols = 4; rows = math.ceil(len(tiles)/cols)
sheet = Image.new("RGB", (cols*340, rows*340), "white")
for i,t in enumerate(tiles): sheet.paste(t, ((i%cols)*340, (i//cols)*340))
sheet.save(OUT/"step1b_traced.jpg", quality=88)
hit = sum(1 for r in results if r["poly"])
print(f"17 处中描出 {hit} 处 -> out/step1b_traced.jpg")
