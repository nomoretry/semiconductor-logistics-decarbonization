"""Run the two independent company-inspired benchmark grids."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.experiments import run_grid

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--project",choices=["asml","marvell","both","auto"],default="auto")
    p.add_argument("--smoke",action="store_true")
    a=p.parse_args()
    available=tuple(x for x in ("asml","marvell") if (Path(__file__).resolve().parents[1]/x/"config.json").exists())
    projects=("asml","marvell") if a.project=="both" else available if a.project=="auto" else (a.project,)
    run_grid(projects,seeds=(100,) if a.smoke else tuple(range(100,110)),include_analogue=not a.smoke)
