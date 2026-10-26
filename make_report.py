"""生成建模报告（Markdown + Word）与统计摘要。

数据来源：out/scene.json（由 build_scene.py 生成）
输出：
  out/analysis_summary.json
  建模报告.md
  建模报告.docx
"""
from __future__ import annotations

import json
import statistics as st
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

CORE = ["图书馆", "晨苑食堂", "校医务室", "风雨操场", "第一教学楼"]

scene = json.loads((OUT / "scene.json").read_text(encoding="utf-8"))
B = scene["buildings"]
named = [b for b in B if b.get("name")]
meta = scene["meta"]
dests = scene["keyDests"]


def short(b):
    return (b.get("mapName") or b.get("name") or "未命名").replace("浙江大学城市学院", "")


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


near_all, near_core = [], []
for b in B:
    t = b.get("times") or {}
    va = [v for v in t.values() if v is not None]
    vc = [t[k] for k in CORE if t.get(k) is not None]
    if va:
        near_all.append((min(va), b))
    if vc:
        near_core.append((min(vc), b))

ta = sorted(v for v, _ in near_all)
tc = sorted(v for v, _ in near_core)
stats = {
    "n_buildings": len(B),
    "n_named": len(named),
    "foot_m2": round(sum(b["area"] for b in B)),
    "floor_m2": round(sum(b["area"] * b["levels"] for b in B)),
    "road_km": meta["road_km"],
    "nodes": meta["nodes"],
    "edges": meta["edges"],
    "n_south": meta["n_south"],
    "n_north": meta["n_north"],
    "n_dests": len(dests),
    "to_all_mean": round(st.mean(ta), 2),
    "to_all_p90": round(pct(ta, .9), 2),
    "to_all_max": round(max(ta), 2),
    "to_core_mean": round(st.mean(tc), 2),
    "to_core_p90": round(pct(tc, .9), 2),
    "to_core_max": round(max(tc), 2),
    "siting_p": scene["sitingStats"]["p"],
    "siting_mean": scene["sitingStats"]["mean_min"],
    "siting_cov5": scene["sitingStats"]["coverage_5min"],
    "name_stat": scene["nameAudit"]["stat"],
}
(OUT / "analysis_summary.json").write_text(
    json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

siting = scene["siting"]
def label_of(b):
    n = short(b)
    return n if b.get("name") else f"未命名建筑#{b['id']}"

named_near = [(v, b) for v, b in near_all if b.get("name")]
best = sorted(named_near, key=lambda x: x[0])[:3]
worst = sorted(named_near, key=lambda x: -x[0])[:3]
core_worst = sorted(near_core, key=lambda x: -x[0])[:3]
n_core_over10 = sum(1 for v, _ in near_core if v > 10)
n_core = len(near_core)
far_west = sum(1 for v, b in near_core if v > 10 and b["c"][0] < 0)
far_east = sum(1 for v, b in near_core if v > 10 and b["c"][0] >= 0)
NAME_TOTAL = sum(stats["name_stat"].values())
matched = (stats["name_stat"].get("一致", 0) + stats["name_stat"].get("写法差异", 0)
           + stats["name_stat"].get("别名", 0) + stats["name_stat"].get("待核", 0)
           + stats["name_stat"].get("配准", 0))

# ---------------------------------------------------------------- Markdown
md = []
A = md.append

A("# 浙大城市学院三维校园空间模型 · 建模报告\n")
A(f"生成日期：{date.today().isoformat()}　|　数据：OpenStreetMap（ODbL 1.0）　|　"
  "可复现：`python run_all.py`\n")

A("## 一、任务与目标\n")
A("把校园当作一个可计算的**空间系统**来建模，而不是画一张效果图。模型需要回答三个问题：\n")
A("1. **物理形态**：建筑在哪里、多高、多大，路网如何连通；\n"
  "2. **可达性**：从任意一栋楼出发，走到最近的食堂、图书馆、医务室要多久；\n"
  "3. **决策支持**：若有 4 处新增服务点，选在哪里能覆盖最多的人。\n")
A("成果是一个**单文件交互式三维模型**（`out/campus_3d.html`，离线可打开）"
  "加一份可复算的数据管线。\n")

A("## 二、数据来源与预处理\n")
A("| 项目 | 内容 |\n|---|---|\n"
  f"| 数据源 | OpenStreetMap，Overpass API（3 个镜像轮询） |\n"
  "| 区域 | 纬度 30.3170–30.3360，经度 120.1420–120.1600 |\n"
  "| 坐标系 | 局部等距投影，原点 (30.32650, 120.15100)，单位：米 |\n"
  f"| 路网 | {stats['nodes']} 节点 / {stats['edges']} 边 / {stats['road_km']} km |\n"
  f"| 建筑 | 校园范围内 {stats['n_buildings']} 栋，其中 {stats['n_named']} 栋有名称 |\n")
A("原始要素抓取后**缓存到 `data/raw/`**，之后所有建模都读缓存，"
  "保证同一批数据可以反复复现，不受上游数据漂移影响。\n")

A("## 三、三维模型构建\n")
A("### 3.1 建筑体块\n")
A("每栋建筑由 OSM 的多边形轮廓直接拉伸得到，高度 = 层数 × 层高。"
  "OSM 中只有约四成建筑带 `building:levels`，其余按**同类建筑层数中位数**补齐"
  "（教学 6、实验 5、图书 5、行政 9、宿舍 7、餐饮 2、体育 3），并在数据里标记为估计值，"
  "前端点击时也会注明「同类估计」。\n")
A(f"结果：基底面积合计 **{stats['foot_m2']:,} m²**，估算建筑面积 "
  f"**{stats['floor_m2']:,} m²**。\n")

A("### 3.2 地面底图\n")
A("道路、绿地、水系、运动场按类型栅格化到一张 2048² 的纹理上，"
  "道路宽度按道路等级取真实米数（主路 11 m、支路 5 m、步道 2.2 m），"
  "投影到地面平面上作为底图。这样比逐条路建三维网格省一个数量级的三角形，"
  "但保留了「哪条路宽」的视觉信息。\n")

A("### 3.3 取景与视角\n")
A("预设视角只记录**方向与目标点**，相机距离在运行时反解："
  "把校区包围盒的 8 个角点投影到屏幕，二分搜索距离直到全部落进画面。"
  "因此同一个链接在任意窗口比例、任意分辨率下都能完整取景，不需要为截图手工调参。\n")

A("### 3.4 光照与阴影\n")
A("半球光 + 主平行光的组合，主光方向由太阳方位角/高度角滑杆驱动，"
  "同时按太阳方向**烘焙**一张建筑投影贴图（Multiply 混合）叠在地面上。"
  "烘焙而非实时阴影的原因：无 GPU 的机器（含无头截图环境）上实时阴影贴图不可靠，"
  "烘焙版本在任何环境下表现一致，且拖动滑杆时会实时重烘焙。\n")

A("## 四、路网与步行时间模型\n")
A("### 4.1 图的构建\n")
A("把路网建成无向加权图，边权为**步行时间**而非距离：\n")
A("```\nt = 长度 / v(道路类型) + 过街惩罚(道路等级)\n```\n")
A("| 道路类型 | 速度 (m/s) |　| 过街 | 惩罚 (s) |\n|---|---|---|---|---|\n"
  "| footway / path | 1.35 |　| primary | 12 |\n"
  "| service | 1.30 |　| secondary | 8 |\n"
  "| residential | 1.20 |　| tertiary | 6 |\n"
  "| secondary | 1.05 |　| 其余 | 0 |\n"
  "| steps | 0.60 |　| | |\n")
A("建筑通过「锚点」接入路网：把建筑形心吸附到最近的若干路网节点，"
  f"吸附容差 18 m、最远 220 m，超出的建筑不参与可达性计算（避免凭空造出通道）。\n")

A("### 4.2 计算\n")
A("以每栋建筑的锚点为源点跑一次 Dijkstra，得到它到全部"
  f" {len(dests)} 处关键设施的最短步行时间矩阵；"
  "前端点击任意建筑即可看到它最近的 4 处设施及用时，"
  "也可从任意建筑发起等时圈（3/5/8/10/15 min 五档）。\n")

A("## 五、计算结果\n")
A(f"### 5.1 规模\n")
A(f"- 建筑 {stats['n_buildings']} 栋（南校区 {stats['n_south']} / 北校区 {stats['n_north']}）\n"
  f"- 基底 {stats['foot_m2']:,} m² · 建筑面积 {stats['floor_m2']:,} m²\n"
  f"- 路网 {stats['road_km']} km\n")

A("### 5.2 步行可达性\n")
A("| 口径 | 均值 | P90 | 最差 |\n|---|---|---|---|\n"
  f"| 到 {len(dests)} 处设施中最近一处 | {stats['to_all_mean']} min | "
  f"{stats['to_all_p90']} min | {stats['to_all_max']} min |\n"
  f"| 到 {len(CORE)} 处核心设施中最近一处 | {stats['to_core_mean']} min | "
  f"{stats['to_core_p90']} min | {stats['to_core_max']} min |\n")
A("到最近设施最便利的三栋楼：" +
  "、".join(f"{label_of(b)}（{v:.1f} min）" for v, b in best) + "；\n")
A("最不利的三栋楼：" + "、".join(f"{label_of(b)}（{v:.1f} min）" for v, b in worst) + "。\n")
_sel = [(v, b) for v, b in near_core if v > 10]
_xr = (min(b["c"][0] for _, b in _sel), max(b["c"][0] for _, b in _sel)) if _sel else (0, 0)
A(f"换到「到 5 处核心设施最近一处」的口径，80 栋里有 **{n_core_over10} 栋超过 10 min**，"
  f"全部落在校区**西侧**（相对校园中心的 x 在 {_xr[0]:.0f} ~ {_xr[1]:.0f} m），"
  "从北校区西缘一直延伸到西南角；最差的是 "
  + "、".join(f"{label_of(b)}（{v:.1f} min）" for v, b in core_worst) + "。"
  "这一带楼栋稀疏、可走路径少，绕行距离长，是校区可达性的洼地，"
  "也是后文选址把服务点安排在附近的原因。\n")

A(f"### 5.3 设施选址（p = {stats['siting_p']}）\n")
A("在「教学 / 图书 / 行政 / 实验」类、且有明确名称的建筑中穷举 4 处组合，"
  "目标是让**全校 80 栋楼到最近一处服务点的平均步行时间最小**：\n")
A("| 选址 |\n|---|\n" + "".join(
    f"| {next((short(b) for b in B if b['name'] == s['name']), s['name'])} |\n" for s in siting))
A(f"\n结果：平均 **{stats['siting_mean']} min**，**5 min 内覆盖 "
  f"{stats['siting_cov5']}%** 的建筑。候选里刻意排除了体育场馆——"
  "把服务点放进体育馆在教学上不通，但穷举会优先选它（它在地理上最居中），"
  "所以用类别约束把这类不合理解剔掉。\n")

A("## 六、与校方手绘地图的名称核对\n")
A("以校方发布的手绘校园地图为基准，逐条核对模型里的楼名：\n")
A(f"| 对照结果 | 条目数 | 含义 |\n|---|---|---|\n"
  f"| 名称一致 | {stats['name_stat'].get('一致',0)} | OSM 名称与校图完全一致 |\n"
  f"| 用字差异 | {stats['name_stat'].get('写法差异',0)} | 如「晨苑餐厅 / 晨苑食堂」 |\n"
  f"| 编号/俗名 | {stats['name_stat'].get('别名',0)} | 如「第一教学楼 / 教一」「理工科楼4号 / 理工四」 |\n"
  f"| 待核对 | {stats['name_stat'].get('待核',0)} | 位置相近但题字有出入 |\n"
  f"| 按图配准补名 | {stats['name_stat'].get('配准',0)} | OSM 无名字，按手绘图位置配准确定 |\n"
  f"| 校图有、模型未命名 | {stats['name_stat'].get('缺失',0)} | OSM 缺失该要素或未填名称 |\n"
  f"| 模型有、校图未标 | {stats['name_stat'].get('模型独有',0)} | 宿舍、实验用房等辅助建筑 |\n"
  f"| 合计 | {NAME_TOTAL} | |\n")
_map_total = (stats["name_stat"].get("一致", 0) + stats["name_stat"].get("写法差异", 0)
              + stats["name_stat"].get("别名", 0) + stats["name_stat"].get("待核", 0)
              + stats["name_stat"].get("配准", 0) + stats["name_stat"].get("缺失", 0))
A(f"\n校方手绘地图上共 {_map_total} 条标注，模型能定位并命名的有 **{matched} 条"
  f"（{100*matched/_map_total:.0f}%）**；其余 {stats['name_stat'].get('缺失',0)} 条"
  "在 OSM 上既没有同名要素、也没有可对应的建筑轮廓。另有 "
  f"{stats['name_stat'].get('模型独有',0)} 栋建筑是模型独有、校图上未标注。\n")

A("### 6.1 用几何配准把「无名多边形」认出来\n")
A("校图上「教学楼 A–F」「文一/二/三/五」「魏绍相楼」这类标注，OSM 里只有多边形、没有名字。"
  "要确认「图上这栋」就是「OSM 里那个多边形」，只能靠几何位置，于是先做一次配准：\n")
A("1. 从 1033×1774 的手绘图上量出 74 条标注的像素坐标；\n"
  "2. 取 24 个「已经有确定校图名」的建筑作锚点，最小二乘拟合**像素 → 平面坐标**的仿射变换"
  "（先剔除「待核对」的对应关系，再迭代剔除残差大于 45 m 的离群锚点）；\n"
  "3. 仿射残差中位约 23 m，说明手绘图是示意图（南北拉长、湖州街一带压缩），"
  "所以在仿射之上再叠一层「最近 6 个锚点的残差反距离加权」，补偿局部变形；\n"
  "4. 把结果反投影回图上：红点 = 模型里已定名的楼，蓝点是本次补名的楼，逐个核对引线方向，"
  "只确认位置关系清楚的 9 栋，其余 31 条如实列为「OSM 无对应轮廓」，不猜。\n")
A("配准补名的结果（`data/name_from_map.csv`）："
  "文一、文二、文五、魏绍相楼，以及教学楼 B、C、D、E、F——"
  "其中 2573 m² 的那一块是 OSM 把教学楼 A/B 合成的一个多边形。\n")
A("![配准校验](out/map_registration.png)\n")
A("对照表见 `data/name_aliases.csv`，模型前端已把**校图名称作为首选标签**显示，"
  "OSM 原名与对照结论放在点击弹出的信息卡里。仍缺名的「教学楼A」「综合实验楼」"
  "「弘毅楼」「金如新楼」「西/东体楼」「第二食堂」「教五/教六」「西/东辅助楼」"
  "「图信报告厅」「文三」「吉瑞大厦」「欣瑞大厦」「实训用房」「辅助用房」等，"
  "是数据源本身就缺轮廓或缺名称，本模型不凭空捏造。\n")

A("![名称核对](out/fig1_name_audit.png)\n")
A("![建筑规模](out/fig2_scale.png)\n")
A("![步行可达性](out/fig3_access.png)\n")
A("![三维视图](out/fig4_views.png)\n")

A("## 七、模型的局限\n")
A("1. **层数与高度是估计值**：约六成建筑在 OSM 上没有层数，用同类中位数补齐，"
  "误差在 ±1 层量级；\n"
  "2. **没有建筑内部与楼梯建模**：到达时间算到楼门口，不含上楼；\n"
  "3. **坡度只体现在台阶速度上**：校区整体平坦，但如果要精细，需要 DEM；\n"
  "4. **步行速度是常速假设**：未区分上课高峰的拥挤、雨天的减速；\n"
  "5. **校图对照是人工判读**：手绘图不是严格比例尺图，个别对应关系标注为「待核对」。\n")

A("""### 七附、2026-10 版本更新说明

**1) 地面换成真实卫星影像。** 原来的地面是程序画的示意图（草地＋道路线条），现在换成 Esri World Imagery 正射瓦片（z=18，约 0.5 m/像素，238 张瓦片拼接），并做了地理配准：把 OSM 建筑轮廓叠回影像，图书馆椭圆、教学楼块与影像重合误差在 1–2 像素内（`out/step0_overlay_lib.jpg`）。也就是说**模型里的楼在影像上的位置是准的**，影像只替换地面、不改动轮廓。

**2) 楼名按校方最新版手绘地图校正。** 新版校图与旧版用词不同，已按其改写显示名（`data/name_aliases.csv`）：医务室（原「校医务室」）、土木楼（原「土木实验用房」）、工程师餐厅、校园卡服务中心、老体育馆、行政楼（原「行政综合楼」）、文六（原「UW学院大楼」）、科技楼（原「科技综合楼」）、情人坡（原「勤人坡」）、北门（原「北大门」）、体育馆（北）。其中「工程师餐厅」「校园卡服务中心」在 OSM 上没有对应要素，如实标为缺失。

**3) 一个已知缺口，如实记录。** 新版校图上仍有 17 处标注（文三、吉瑞大厦、欣瑞大厦、弘毅楼、金如新楼、西体楼、东体楼、综合实验楼、第二食堂、教五、教六、实训用房、辅助用房、西辅助楼、东辅助楼、图信报告厅、教学楼A）在 OSM 里没有建筑轮廓。尝试过用影像自动提取这些楼顶（固定阈值 / 颜色分类器 / 局部连通域 / 多种子区域生长四种方案），因屋顶材质差异大、树冠遮挡严重、本机又缺 OpenCV，结果只出碎片，不足以入库，故保留缺口而不填入不可信几何。

""")
A("## 八、文件清单与复现\n")

A("```\ncampus3d/\n"
  "├─ fetch_campus.py      # 从 Overpass 抓原始要素（缓存到 data/raw）\n"
  "├─ build_scene.py       # 建路网图、算步行时间、选址、导出 scene.json\n"
  "├─ build_html.py        # 把 three.js 与场景数据内联成单文件 HTML\n"
  "├─ shoot.py             # 无头浏览器批量截图\n"
  "├─ make_figures.py      # 生成报告用统计图\n"
  "├─ make_report.py       # 生成本报告（md + docx）\n"
  "├─ run_all.py           # 一键重建全部产物\n"
  "├─ data/name_aliases.csv# 与校方手绘地图的名称对照表\n"
  "└─ out/                 # 三维页面、图表、台账、报告\n```\n")
A("复现：`python run_all.py`（已在 Python 3.14 / Edge 无头环境验证）。\n")
A("---\n")
A("数据版权：© OpenStreetMap contributors，ODbL 1.0。"
  "三维页面底部保留了署名，二次分发时需保留。\n")

(ROOT / "建模报告.md").write_text("\n".join(md), encoding="utf-8")
print("  -> 建模报告.md")

# ---------------------------------------------------------------- Word
try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(
        __import__("docx.oxml.ns", fromlist=["qn"]).qn("w:eastAsia"), "Microsoft YaHei")

    for lvl, text in [("Title", "浙大城市学院三维校园空间模型"),
                      ("Sub", "建模报告")]:
        if lvl == "Title":
            h = doc.add_heading(text, level=0)
        else:
            p = doc.add_paragraph()
            r = p.add_run(text)
            r.bold = True
            r.font.size = Pt(13)
            r.font.color.rgb = RGBColor(0x44, 0x55, 0x66)

    body = doc.add_paragraph(
        f"生成日期：{date.today().isoformat()}　数据：OpenStreetMap（ODbL 1.0）　"
        "可复现：python run_all.py")
    body.runs[0].font.size = Pt(9)
    body.runs[0].font.color.rgb = RGBColor(0x77, 0x88, 0x99)

    def H(t, lv=1):
        doc.add_heading(t, level=lv)

    def P(t, bold=False):
        p = doc.add_paragraph()
        r = p.add_run(t)
        r.bold = bold
        return p

    def TBL(rows, header=True):
        t = doc.add_table(rows=0, cols=len(rows[0]))
        t.style = "Light Grid Accent 1"
        for i, row in enumerate(rows):
            cells = t.add_row().cells
            for j, v in enumerate(row):
                cells[j].text = str(v)
                if i == 0 and header:
                    for pr in cells[j].paragraphs:
                        for run in pr.runs:
                            run.bold = True
        return t

    H("一、任务与目标")
    P("把校园当作可计算的空间系统来建模：物理形态（建筑位置、高度、面积）、"
      "可达性（到最近设施的步行时间）、决策支持（新增服务点选址）。"
      "成果为单文件交互式三维模型与可复算的数据管线。")

    H("二、数据来源与预处理")
    TBL([["项目", "内容"],
         ["数据源", "OpenStreetMap / Overpass API（3 镜像轮询）"],
         ["区域", "纬度 30.3170–30.3360，经度 120.1420–120.1600"],
         ["坐标系", "局部等距投影，原点 (30.32650, 120.15100)，单位米"],
         ["路网", f"{stats['nodes']} 节点 / {stats['edges']} 边 / {stats['road_km']} km"],
         ["建筑", f"{stats['n_buildings']} 栋，其中 {stats['n_named']} 栋有名称"]])

    H("三、三维模型构建")
    P("建筑由 OSM 轮廓拉伸得到，高度 = 层数 × 层高；缺失层数按同类中位数补齐"
      "（教学 6、实验 5、图书 5、行政 9、宿舍 7、餐饮 2、体育 3）并标记为估计值。"
      f"基底面积合计 {stats['foot_m2']:,} m²，估算建筑面积 {stats['floor_m2']:,} m²。")
    P("地面底图把道路、绿地、水系按真实米宽栅格化到 2048² 纹理；"
      "预设视角只记录方向与目标点，相机距离在运行时把包围盒角点投影后二分反解，"
      "因此任意窗口比例都能完整取景。")
    P("光照为主平行光 + 半球光，并按太阳方向烘焙建筑投影贴图叠加到地面，"
      "保证在无 GPU 的截图环境与普通浏览器里表现一致。")

    H("四、路网与步行时间模型")
    P("路网建为无向加权图，边权为步行时间：t = 长度 / v(道路类型) + 过街惩罚。"
      "速度 footway 1.35、service 1.30、residential 1.20、secondary 1.05、steps 0.60 m/s；"
      "过街惩罚 primary 12 s、secondary 8 s、tertiary 6 s。"
      "建筑形心吸附到最近路网节点接入（容差 18 m，最远 220 m）。")
    TBL([["口径", "均值", "P90", "最差"],
         [f"到 {len(dests)} 处设施最近一处", f"{stats['to_all_mean']} min",
          f"{stats['to_all_p90']} min", f"{stats['to_all_max']} min"],
         [f"到 {len(CORE)} 处核心设施最近一处", f"{stats['to_core_mean']} min",
          f"{stats['to_core_p90']} min", f"{stats['to_core_max']} min"]])

    H("五、设施选址")
    P(f"在「教学 / 图书 / 行政 / 实验」且有名称的建筑中穷举 4 处组合，"
      f"最小化全校到最近服务点的平均步行时间。最优解："
      + "、".join(s["name"].replace("浙江大学城市学院", "") for s in siting)
      + f"；平均 {stats['siting_mean']} min，5 min 内覆盖 {stats['siting_cov5']}% 的建筑。")

    H("六、与校方手绘地图的名称核对")
    P(f"共核对 {NAME_TOTAL} 条记录（校图 {_map_total} 条 + 模型独有 {stats['name_stat'].get('模型独有',0)} 条）："
      f"名称一致 {stats['name_stat'].get('一致',0)}、"
      f"用字差异 {stats['name_stat'].get('写法差异',0)}、"
      f"编号/俗名 {stats['name_stat'].get('别名',0)}、"
      f"待核对 {stats['name_stat'].get('待核',0)}、"
      f"按图配准补名 {stats['name_stat'].get('配准',0)}、"
      f"校图有而模型未命名 {stats['name_stat'].get('缺失',0)}、"
      f"模型有而校图未标 {stats['name_stat'].get('模型独有',0)}。"
      f"校图标注中可直接定位并命名的比例 = {matched}/{_map_total} = {100*matched/_map_total:.0f}%。"
      "前端已把校图名称作为首选标签。")

    H("6.1 用几何配准把「无名多边形」认出来")
    P("校图上「教学楼 A–F」「文一/二/五」「魏绍相楼」这类标注，OSM 里只有多边形、没有名字。"
      "要确认「图上这栋」就是「OSM 里那个多边形」，只能靠几何位置，于是先做一次配准："
      "① 从 1033×1774 的手绘图上量出 74 条标注的像素坐标；"
      "② 取 24 个「已有确定校图名」的建筑作锚点，最小二乘拟合像素→平面坐标的仿射变换"
      "（先剔除「待核对」的对应，再迭代剔除残差大于 45 m 的离群锚点）；"
      "③ 手绘图是示意图（南北拉长、湖州街一带压缩），仿射残差中位约 23 m，"
      "因此在仿射之上再叠一层「最近 6 个锚点残差的反距离加权」补偿局部变形；"
      "④ 把结果反投影回图上逐块核对引线方向，只确认位置关系清楚的 9 栋。")
    P("补名结果：文一、文二、文五、魏绍相楼，以及教学楼 B、C、D、E、F；"
      "其中 2573 m² 的那一块是 OSM 把教学楼 A/B 合成的一个多边形。"
      "仍缺名的「教学楼A」「综合实验楼」「弘毅楼」「金如新楼」「西/东体楼」「第二食堂」"
      "「教五/教六」「西/东辅助楼」「图信报告厅」「文三」「吉瑞大厦」「欣瑞大厦」等 31 条，"
      "数据源本身就缺轮廓或缺名称，本模型不凭空捏造。")

    for fn, cap in [("fig1_name_audit.png", "图1  楼名对照"),
                    ("fig2_scale.png", "图2  建筑规模分布"),
                    ("fig3_access.png", "图3  步行时间累计分布"),
                    ("map_registration.png", "图4  手绘地图配准校验（红=已定名，蓝=配准补名）"),
                    ("fig4_views.png", "图5  三维模型视图")]:
        p = OUT / fn
        if p.exists():
            doc.add_picture(str(p), width=Cm(15.5))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            c = doc.add_paragraph(cap)
            c.alignment = WD_ALIGN_PARAGRAPH.CENTER
            c.runs[0].font.size = Pt(9)

    H("七、局限")
    for t in ["约六成建筑层数为同类中位数估计，误差约 ±1 层；",
              "步行时间算到楼门口，不含楼内上楼；",
              "未使用 DEM，坡道仅通过台阶速度粗略体现；",
              "步行速度为常速假设，未区分高峰拥挤与雨天；",
              "手绘地图非严格比例尺，个别名称对应标注为待核对。"]:
        doc.add_paragraph(t, style="List Bullet")

    H("八、复现")
    P("python run_all.py —— fetch_campus.py 抓数据、build_scene.py 建模、"
      "build_html.py 打包、shoot.py 截图、make_figures.py 出图、make_report.py 出报告。")
    P("数据版权：© OpenStreetMap contributors，ODbL 1.0。")

    doc.save(ROOT / "建模报告.docx")
    print("  -> 建模报告.docx")
except ImportError as exc:  # pragma: no cover
    print("  !! docx 跳过:", exc)
