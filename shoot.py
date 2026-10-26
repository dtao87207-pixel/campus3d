"""用无头 Edge 批量截取三维场景图（不需要人工交互）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

SHOTS = [
    ("shot_all.png", "view=all", 1920, 1080),
    ("shot_south.png", "view=south", 1920, 1080),
    ("shot_north.png", "view=north", 1920, 1080),
    ("shot_core.png", "view=core", 1920, 1080),
    ("shot_top.png", "view=top", 1600, 1600),
    ("shot_iso.png", "view=south&iso=1&label=0", 1920, 1080),
    ("shot_levels.png", "view=all&mode=levels", 1920, 1080),
    ("shot_white.png", "view=all&mode=white", 1920, 1080),
    ("shot_dusk.png", "view=all&az=250&el=14", 1920, 1080),
]


def main() -> None:
    if not EDGE.exists():
        raise SystemExit(f"找不到 Edge：{EDGE}")
    html = OUT / "campus_3d.html"
    if not html.exists():
        raise SystemExit("请先运行 build_html.py")
    url = "file:///" + str(html).replace("\\", "/")
    for name, query, w, h in SHOTS:
        dst = OUT / name
        cmd = [str(EDGE), "--headless=new", "--disable-gpu-sandbox",
               "--enable-unsafe-swiftshader", "--use-gl=angle",
               "--use-angle=swiftshader", "--hide-scrollbars",
               f"--window-size={w},{h}", "--virtual-time-budget=22000",
               f"--screenshot={str(dst).replace(chr(92), '/')}",
               f"{url}?{query}"]
        subprocess.run(cmd, capture_output=True, timeout=180)
        print(f"  -> {name:18s} {dst.stat().st_size/1024:6.0f} KB")


if __name__ == "__main__":
    main()
