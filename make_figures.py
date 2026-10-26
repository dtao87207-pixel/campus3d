"""生成建模报告用的静态图（matplotlib + 三维截图拼图）。

输入：out/scene.json、out/shot_*.png
输出：out/fig1_*.png … fig4_*.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

# 中文字体
for cand in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
             "C:/Windows/Fonts/simsun.ttc"]:
    if Path(cand).exists():
        font_manager.fontManager.addfont(cand)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=cand).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

INK = "#22303f"
ACC = "#2f7fd6"
WARM = "#e0763a"
GRID = "#d7dee6"

scene = json.loads((OUT / "scene.json").read_text(encoding="utf-8"))
buildings = scene["buildings"]
named = [b for b in buildings if b.get("name")]
styled = {}


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors="#5b6b7c", labelsize=9)
    ax.grid(axis="y", color=GRID, lw=.8, alpha=.9)
    ax.set_axisbelow(True)


# ---------- 图1：与校方手绘地图的名称核对 ----------
stat = scene["nameAudit"]["stat"]
order = [("一致", "名称一致"), ("写法差异", "用字差异"), ("别名", "编号/俗名"),
         ("待核", "待核对"), ("配准", "按图配准补名"), ("缺失", "图上有的未标注"),
         ("模型独有", "模型独有")]
labels = [o[1] for o in order]
vals = [stat.get(o[0], 0) for o in order]
colors = [ACC, "#5aa9d6", "#8bbf6a", "#e0b23a", WARM, "#8d97a3"]

fig, ax = plt.subplots(figsize=(7.6, 3.6), dpi=200)
bars = ax.barh(labels[::-1], vals[::-1], color=colors[::-1], height=.62)
for r, v in zip(bars, vals[::-1]):
    ax.text(r.get_width() + .6, r.get_y() + r.get_height()/2, str(v),
            va="center", fontsize=10, color=INK)
_loss = sum(vals)
ax.set_title(f"图1  模型楼名与校方手绘地图的对照（共 {_loss} 条标注）",
             fontsize=12, color=INK, loc="left", pad=10)
ax.set_xlabel("条目数", fontsize=9, color="#5b6b7c")
ax.set_xlim(0, max(vals) * 1.18)
_style(ax)
ax.grid(axis="y", visible=False)
ax.grid(axis="x", color=GRID, lw=.8)
fig.tight_layout()
fig.savefig(OUT / "fig1_name_audit.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("  -> fig1_name_audit.png")

# ---------- 图2：建筑规模分布 ----------
areas = sorted((b["area"] for b in named), reverse=True)
levels = [b["levels"] for b in named]

fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.6), dpi=200)

ax = axes[0]
ax.hist(levels, bins=range(1, 14), color=ACC, edgecolor="white", linewidth=.8)
ax.set_title("图2a  建筑层数分布（80 栋）", fontsize=11, color=INK, loc="left")
ax.set_xlabel("层数", fontsize=9, color="#5b6b7c")
ax.set_ylabel("栋数", fontsize=9, color="#5b6b7c")
ax.set_xticks(range(1, 14))
_style(ax)

ax = axes[1]
top = sorted(named, key=lambda b: -b["area"])[:10]
nm = [(b.get("mapName") or b["name"]).replace("浙江大学城市学院", "")[:9] for b in top]
ax.barh(nm[::-1], [b["area"] for b in top][::-1], color=WARM, height=.64)
ax.set_title("图2b  基底面积前十", fontsize=11, color=INK, loc="left")
ax.set_xlabel("基底面积 / m²", fontsize=9, color="#5b6b7c")
_style(ax)
ax.grid(axis="y", visible=False)
ax.grid(axis="x", color=GRID, lw=.8)

fig.tight_layout()
fig.savefig(OUT / "fig2_scale.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("  -> fig2_scale.png")

# ---------- 图3：步行可达性 ----------
dests = scene["keyDests"]
nearest_all, nearest_core = [], []
CORE = ["图书馆", "晨苑食堂", "校医务室", "风雨操场", "第一教学楼"]
for b in named:
    t = b.get("times") or {}
    vals_all = [v for v in t.values() if v is not None]
    vals_core = [t[k] for k in CORE if t.get(k) is not None]
    if vals_all:
        nearest_all.append(min(vals_all))
    if vals_core:
        nearest_core.append(min(vals_core))

fig, ax = plt.subplots(figsize=(7.6, 3.8), dpi=200)
for data, lab, col in [(nearest_all, f"到 {len(dests)} 处设施最近一处", ACC),
                       (nearest_core, f"到 {len(CORE)} 处核心设施最近一处", WARM)]:
    xs = sorted(data)
    ys = [(i + 1) / len(xs) * 100 for i in range(len(xs))]
    ax.plot(xs, ys, lw=2.2, color=col, label=lab)
    ax.axvline(xs[int(len(xs) * .9)], color=col, ls=":", lw=1.1, alpha=.75)
ax.set_title("图3  校内建筑到最近设施的步行时间累计分布", fontsize=12, color=INK, loc="left")
ax.set_xlabel("步行时间 / min", fontsize=9, color="#5b6b7c")
ax.set_ylabel("累计比例 / %", fontsize=9, color="#5b6b7c")
ax.legend(frameon=False, fontsize=9, loc="lower right")
_style(ax)
fig.tight_layout()
fig.savefig(OUT / "fig3_access.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("  -> fig3_access.png")

# ---------- 图4：三维截图拼贴 ----------
try:
    from PIL import Image, ImageDraw

    shots = [("shot_all.png", "总览（北向上）"), ("shot_south.png", "南校区"),
             ("shot_north.png", "北校区"), ("shot_core.png", "教学核心区"),
             ("shot_iso.png", "步行等时圈"), ("shot_levels.png", "层数着色")]
    tiles = []
    for fn, cap in shots:
        p = OUT / fn
        if p.exists():
            tiles.append((Image.open(p).convert("RGB"), cap))
    if tiles:
        w, h = 760, 428
        cols, rows = 2, (len(tiles) + 1) // 2
        sheet = Image.new("RGB", (cols * w, rows * (h + 34)), "white")
        dr = ImageDraw.Draw(sheet)
        try:
            from PIL import ImageFont
            capfont = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
        except Exception:
            capfont = None
        for i, (im, cap) in enumerate(tiles):
            im = im.resize((w, h), Image.LANCZOS)
            x, y = (i % cols) * w, (i // cols) * (h + 34)
            sheet.paste(im, (x, y))
            dr.text((x + 10, y + h + 4), cap, fill="#22303f", font=capfont)
        sheet.save(OUT / "fig4_views.png")
        print("  -> fig4_views.png")
except Exception as exc:  # pragma: no cover
    print("  !! fig4 跳过:", exc)
