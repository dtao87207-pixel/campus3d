# -*- coding: utf-8 -*-
"""阶段1（改）：用 OSM 已知屋顶当训练样本，训练一个「像不像屋顶」的判别器

原来的固定阈值把施工土方、路面也算进来了。改成数据驱动：
  正样本 = OSM 建筑多边形内部（腐蚀 3px）的像素
  负样本 = 道路 / 绿地水系 / 操场 / 停车场 内部像素
  特征   = HSV + 8x8 邻域标准差（纹理）
  分类器 = 每类高斯 + 马氏距离（等价于二次判别分析，numpy 就能算）
"""
import json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import ndimage as ndi
from shapely.geometry import Polygon, MultiPoint
from shapely.ops import unary_union

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
LAT0, LON0 = 30.32650, 120.15100
M_LON = 111320.0 * math.cos(math.radians(LAT0))
M_LAT = 110540.0
Z = 18; TX0, TY0 = 218556, 107871; WORLD = 256 * 2**Z
PX_M = 40075016.686 * math.cos(math.radians(LAT0)) / WORLD
print(f"分辨率 {PX_M:.3f} m/px")

def ll_to_px(lat, lon):
    X = (lon+180.0)/360.0*WORLD
    Y = (1-math.log(math.tan(math.radians(lat))+1/math.cos(math.radians(lat)))/math.pi)/2*WORLD
    return X-TX0*256, Y-TY0*256
def xy_to_px(x, y):
    return ll_to_px(y/M_LAT+LAT0, x/M_LON+LON0)

img = Image.open(OUT/"imagery_bbox.png").convert("RGB")
W, H = img.size
hsv = np.asarray(img.convert("HSV")).astype(np.float32)/255.0
Hc = hsv[...,0]*2*np.pi
S, V = hsv[...,1], hsv[...,2]
gray = np.asarray(img.convert("L")).astype(np.float32)/255.0
std8 = ndi.uniform_filter(gray**2, 9) - ndi.uniform_filter(gray, 9)**2
std8 = np.sqrt(np.maximum(std8, 0))

def polys_mask(polys, buf=0.0, dilate=0):
    m = Image.new("L", (W,H), 0); d = ImageDraw.Draw(m)
    if not polys: return np.zeros((H,W), bool)
    g = unary_union(polys)
    if buf: g = g.buffer(buf)
    parts = list(g.geoms) if hasattr(g,"geoms") else [g]
    for p in parts:
        if p.is_empty: continue
        d.polygon([xy_to_px(x,y) for x,y in p.exterior.coords], fill=255)
        for h in p.interiors: d.polygon([xy_to_px(x,y) for x,y in h.coords], fill=0)
    a = np.array(m) > 0
    return ndi.binary_dilation(a, iterations=dilate) if dilate else a

def load_polys(fn):
    raw = json.load(open(ROOT/"data"/"raw"/fn, encoding="utf-8"))
    out = []
    for e in raw["elements"]:
        g = e.get("geometry")
        if not g or len(g) < 3: continue
        try:
            p = Polygon([((q["lon"]-LON0)*M_LON, (q["lat"]-LAT0)*M_LAT) for q in g])
        except Exception: continue
        if not p.is_valid: p = p.buffer(0)
        if p.is_empty: continue
        out.append(p)
    return out

scene = json.load(open(OUT/"scene.json", encoding="utf-8"))
B = scene["buildings"]; split = scene["meta"]["south_split"]
existing = [Polygon([tuple(pp) for pp in b["poly"]]) for b in B]
roads = load_polys("roads.json"); landuse = load_polys("landuse.json")

north = [b for b in B if b["c"][1] > split]; south = [b for b in B if b["c"][1] <= split]
def hull_of(bs, pad):
    pts = [tuple(pp) for b in bs for pp in b["poly"]]
    return MultiPoint(pts).convex_hull.buffer(pad)
roi = unary_union([hull_of(north,95), hull_of(south,95)])
roi_m = polys_mask([roi])

pos_m = polys_mask(existing, buf=-2.0)
neg_m = polys_mask(roads, buf=3.0, dilate=2) | polys_mask(landuse, dilate=1)

feat = np.stack([np.cos(Hc), np.sin(Hc), S, V, std8], -1).astype(np.float32)

rng = np.random.default_rng(7)
def sample(mask, n):
    ys, xs = np.nonzero(mask)
    if len(ys) == 0: return np.zeros((0,5), np.float32)
    idx = rng.choice(len(ys), size=min(n, len(ys)), replace=False)
    return feat[ys[idx], xs[idx]]

Xp = sample(pos_m & roi_m, 60000)
Xn = sample(neg_m & roi_m, 60000)
print("正样本", len(Xp), "负样本", len(Xn))
from scipy.cluster.vq import kmeans2
def mixture(X, k, seed):
    """用 k 个高斯拟合，取最小马氏距离（屋顶有亮灰和深灰两种，单高斯抓不住）"""
    cent, _ = kmeans2(X, k, minit="++", seed=seed)
    comps = []
    for c in cent:
        d = np.linalg.norm(X - c, axis=1)
        sub = X[d < np.quantile(d, 0.35)]
        if len(sub) < 200: sub = X
        mu = sub.mean(0)
        cov = np.cov(sub.T) + np.eye(5)*1e-4
        comps.append((mu, np.linalg.inv(cov), np.linalg.slogdet(cov)[1], np.linalg.norm(c)))
    return comps

P = mixture(Xp, 3, 11)
N = mixture(Xn, 2, 12)
print("屋顶簇中心:", [np.round(c[0],2).tolist() for c in P])
print("非屋顶簇中心:", [np.round(c[0],2).tolist() for c in N])

F = feat.reshape(-1,5)
def mindist(comps):
    out = None
    for mu, inv, ld, _ in comps:
        d = np.einsum("ij,jk,ik->i", F-mu, inv, F-mu) + ld
        out = d if out is None else np.minimum(out, d)
    return out
dp, dn = mindist(P), mindist(N)
prob = (dn - dp).reshape(H, W)   # >0 更像屋顶

roof = (prob > 0) & roi_m
roof = ndi.binary_opening(roof, np.ones((3,3)))
roof = ndi.binary_closing(roof, np.ones((7,7)))
roof = ndi.binary_fill_holes(roof)
cand = roof & ~polys_mask(existing, buf=1.5, dilate=2)
cand = ndi.binary_opening(cand, np.ones((5,5)))
print("候选像素", int(cand.sum()), " 占比 %.1f%%" % (100*cand.mean()))

lab, n = ndi.label(cand)
objs = ndi.find_objects(lab)
px2 = PX_M**2
kept = []
for i in range(1, n+1):
    sl = objs[i-1]
    if sl is None: continue
    sub = lab[sl] == i
    area = sub.sum()*px2
    if area < 60 or area > 40000: continue
    fill = sub.sum()/max(1,(sl[0].stop-sl[0].start)*(sl[1].stop-sl[1].start))
    if fill < 0.5: continue
    kept.append((i, area, fill, sl))
print("过滤后候选", len(kept))

ov = img.copy(); dd = ImageDraw.Draw(ov, "RGBA")
for i, area, fill, sl in kept:
    sub = (lab[sl]==i).astype(float)
    if sub.sum()==0: continue
    cs = plt.contour(sub, levels=[0.5])
    for seg in cs.allsegs[0]:
        pts = [(sl[1].start+p[0], sl[0].start+p[1]) for p in seg]
        if len(pts)>2: dd.polygon(pts, outline=(255,60,60,255))
    plt.close()
ov.save(OUT/"step1_candidates_full.jpg", quality=86)
for name,(lat,lon) in {"north":(30.3330,120.1510), "south":(30.3205,120.1495)}.items():
    cx,cy = ll_to_px(lat,lon); r=420
    ov.crop((int(cx-r),int(cy-r),int(cx+r),int(cy+r))).resize((r*3,r*3), Image.LANCZOS)\
      .save(OUT/f"step1_zoom_{name}.jpg", quality=90)
print("-> step1_candidates_full.jpg / step1_zoom_north.jpg / step1_zoom_south.jpg")
