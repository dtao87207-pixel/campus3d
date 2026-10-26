"""一键重建：抓数据 -> 建模 -> 打包三维页面 -> 截图 -> 出图 -> 出报告。

用法：python run_all.py            （用已有 data/raw 缓存）
      python run_all.py --refetch  （强制重新抓 OSM 数据）
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def run(script: str, *args: str) -> None:
    t0 = time.time()
    print(f"\n=== {script} {' '.join(args)}")
    r = subprocess.run([PY, script, *args], cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"{script} 失败（{r.returncode}）")
    print(f"    {time.time()-t0:.1f}s")


def main() -> None:
    refetch = "--refetch" in sys.argv
    run("fetch_campus.py", *("--refetch",) if refetch else ())
    run("build_scene.py")
    run("build_html.py")
    run("shoot.py")
    run("make_figures.py")
    run("make_report.py")
    print("\n完成。产物在 out/ 下：campus_3d.html、fig*.png、buildings.csv、"
          "analysis_summary.json；报告在项目根：建模报告.md / 建模报告.docx")


if __name__ == "__main__":
    main()
