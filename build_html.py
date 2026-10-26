# -*- coding: utf-8 -*-
"""
浙大城市学院 · 三维校园模型 —— 第 3 步：打包单文件三维网页

把 three.js / OrbitControls / 场景数据全部内联进 out/campus_3d.html，
得到一个离线可用、双击即开的单文件三维校园。

用法：
    py -3.14 build_html.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
TPL = ROOT / "templates" / "campus_3d.html"
VENDOR = ROOT / "tools" / "vendor"
OUT = ROOT / "out"


def main() -> None:
    tpl = TPL.read_text(encoding="utf-8")
    scene = json.loads((OUT / "scene.json").read_text(encoding="utf-8"))

    three = (VENDOR / "three.min.js").read_text(encoding="utf-8")
    orbit = (VENDOR / "OrbitControls.js").read_text(encoding="utf-8")

    html = tpl.replace(
        '<script src="__THREE__"></script>',
        "<script>\n" + three + "\n</script>",
    ).replace(
        '<script src="__ORBIT__"></script>',
        "<script>\n" + orbit + "\n</script>",
    ).replace("__SCENE_JSON__", json.dumps(scene, ensure_ascii=False, separators=(",", ":")))

    dst = OUT / "campus_3d.html"
    dst.write_text(html, encoding="utf-8")
    print(f"  -> {dst.name}  {dst.stat().st_size / 1024:.0f} KB  "
          f"({len(scene['buildings'])} 栋建筑, {len(scene['roads'])} 条道路)")


if __name__ == "__main__":
    main()
