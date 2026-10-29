"""Controlled assumption/aviation-boundary sensitivity, separately from main grid."""
from pathlib import Path
import argparse
import copy
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.experiments import case_config,synthetic_orders,solve_policy,write_json,ROOT,EF,metric_row

def main(projects=("asml","marvell")):
    rows=[]
    for project in projects:
        for variant in ("base","carry10pct","carry30pct","warehouse_zero","warehouse_x5","air_RF_sensitivity"):
            c=case_config(project,"ocean_delay")
            ef=EF.copy()
            if variant=="carry10pct":c["annual_carry_rate"]=.10
            if variant=="carry30pct":c["annual_carry_rate"]=.30
            if variant=="warehouse_zero":c["warehouse_kgco2e_per_unit_period"]=0
            if variant=="warehouse_x5":c["warehouse_kgco2e_per_unit_period"]*=5
            if variant=="air_RF_sensitivity":ef["air"]=1.03455
            demand=synthetic_orders(c,100)
            baseline,_=solve_policy(c,demand,"cost_only",ef=ef)
            for policy in ("cost_only","carbon_minus25"):
                cap=None if policy=="cost_only" else .75*baseline["total_emissions"]
                solution=baseline if policy=="cost_only" else solve_policy(c,demand,policy,carbon_cap=cap,ef=ef)[0]
                row=metric_row(project,"synthetic_weekly",variant,100,policy,solution,cap)
                row["note"]="RF variant includes non-CO2 climate effects; keep separate from base inventory GHG boundary" if variant=="air_RF_sensitivity" else "Assumption sensitivity, not company calibration"
                rows.append(row)
    write_json(ROOT/"reports/sensitivity.json",rows)
    print("Sensitivity solves:",len(rows))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",choices=["asml","marvell","both","auto"],default="auto")
    args=parser.parse_args()
    available=tuple(x for x in ("asml","marvell") if (ROOT/x/"config.json").exists())
    selected=("asml","marvell") if args.project=="both" else available if args.project=="auto" else (args.project,)
    main(selected)
