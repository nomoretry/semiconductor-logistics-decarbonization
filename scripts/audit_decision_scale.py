"""Development scaling study: shared-capacity MILP and costly exact queries.

This extends the question, not the frozen coupled_decision artifact format.
Root computation is measured cold per method; quality uses exact expectations.
"""
from __future__ import annotations
import argparse
import json
from functools import lru_cache
from pathlib import Path
import random
import math
import tempfile
import time

from notice_benchmark.api_runner import canonical_bytes as canonical, sha256

ROOT=Path(__file__).resolve().parents[1]
METHODS=("no_query","myopic_voi","lookahead_two","exact_dp")


def generate(skus,bits,seed):
    rng=random.Random(seed+skus*100+bits*10000)
    orders=[{"quantity":rng.choice((2,3,4)),"mass":rng.choice((1,2)),"due":rng.choice((2,3)),
             "late":rng.choice((10,30,80)),"holding":.2} for _ in range(skus)]
    mass=sum(x["quantity"]*x["mass"] for x in orders)
    return {"synthetic":True,"known_orders":orders,"delay_bits":bits,
        "prior":[rng.choice((.1,.25,.5,.75)) for _ in range(bits)],
        "query_fees":[rng.choice((2,3,5)) for _ in range(bits)],"query_budget":8,"max_queries":3,
        "route_freight":[10]+[rng.choice((1,2,3)) for _ in range(bits)],
        "route_co2":[5]+[.25+.05*j for j in range(bits)],
        "route_capacity":[int(.4*mass)+2]+[mass]*bits,
        "shared_ocean_pool_capacity":int(.8*mass)+2,
        "carbon_price":.2,"carbon_budget":2*mass,"carbon_excess_penalty":2}


class Planner:
    def __init__(self,context):
        if "private_evaluation_bits" in context:raise ValueError("private_state_not_policy_input")
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint
        self.c=context;self.n=len(context["known_orders"]);self.k=context["delay_bits"];self.r=self.k+1
        self.calls=0;self.solve_seconds=0.
        total=self.n*self.r;matrix=[];lower=[];upper=[]
        for i,s in enumerate(context["known_orders"]):
            row=np.zeros(total+1);row[i*self.r:(i+1)*self.r]=1
            matrix.append(row);lower.append(s["quantity"]);upper.append(s["quantity"])
        for j,cap in enumerate(context["route_capacity"]):
            row=np.zeros(total+1)
            for i,s in enumerate(context["known_orders"]):row[i*self.r+j]=s["mass"]
            matrix.append(row);lower.append(-np.inf);upper.append(cap)
        # Ocean routes 1 and 2 additionally share one origin handling pool.
        row=np.zeros(total+1)
        for i,s in enumerate(context["known_orders"]):
            for j in (1,2):row[i*self.r+j]=s["mass"]
        matrix.append(row);lower.append(-np.inf);upper.append(context["shared_ocean_pool_capacity"])
        row=np.zeros(total+1)
        for i,s in enumerate(context["known_orders"]):
            for j in range(self.r):row[i*self.r+j]=s["mass"]*context["route_co2"][j]
        row[-1]=-1
        matrix.append(row);lower.append(-np.inf);upper.append(context["carbon_budget"])
        self.constraints=LinearConstraint(np.array(matrix),lower,upper)
        self.bounds=Bounds(np.zeros(total+1),np.array([s["quantity"] for s in context["known_orders"] for _ in range(self.r)]+[np.inf]))
        self.integrality=np.array([1]*total+[0])
        self.terminal=lru_cache(None)(self._terminal)
        self.value=lru_cache(None)(self._value)
        self.expected=lru_cache(None)(self._expected)

    def legal(self,h):
        spent=sum(f for f,x in zip(self.c["query_fees"],h) if x!=-1)
        return tuple(i for i,x in enumerate(h) if x==-1 and sum(a!=-1 for a in h)<self.c["max_queries"]
                     and spent+self.c["query_fees"][i]<=self.c["query_budget"])

    def branch(self,h,i):
        for answer,p in ((0,1-self.c["prior"][i]),(1,self.c["prior"][i])):
            nxt=list(h);nxt[i]=answer
            yield p,tuple(nxt)

    def shipping(self,plan,h):
        """Direct physical expected loss, used to check the solver objective."""
        c=self.c;freight=holding=late=co2=0.
        if len(plan)!=self.n:raise ValueError("sku_coverage")
        loads=[0]*self.r
        for s,row in zip(c["known_orders"],plan):
            if len(row)!=self.r or any(type(v) is not int or v<0 for v in row) or sum(row)!=s["quantity"]:raise ValueError("quantity_conservation")
            for j,q in enumerate(row):
                loads[j]+=q*s["mass"]
                freight+=q*s["mass"]*c["route_freight"][j]
                co2+=q*s["mass"]*c["route_co2"][j]
                if j==0:hold=s["due"]-1;backlog=0
                else:
                    p=c["prior"][j-1] if h[j-1]==-1 else h[j-1]
                    hold=(1-p)*max(0,s["due"]-2);backlog=p*max(0,4-s["due"])
                holding+=q*hold*s["holding"];late+=q*backlog*s["late"]
        if any(x>cap for x,cap in zip(loads,c["route_capacity"])) or loads[1]+loads[2]>c["shared_ocean_pool_capacity"]:raise ValueError("capacity_violation")
        carbon=co2*c["carbon_price"]+max(0,co2-c["carbon_budget"])*c["carbon_excess_penalty"]
        return {"freight":freight,"holding":holding,"lateness":late,"co2":co2,"carbon":carbon,"loss":freight+holding+late+carbon,"loads":loads}

    def _terminal(self,h):
        import numpy as np
        from scipy.optimize import milp
        c=self.c;objective=[]
        for s in c["known_orders"]:
            for j in range(self.r):
                p=0 if j==0 else (c["prior"][j-1] if h[j-1]==-1 else h[j-1])
                hold=(s["due"]-1) if j==0 else (1-p)*max(0,s["due"]-2)
                late=0 if j==0 else p*max(0,4-s["due"])
                objective.append(s["mass"]*(c["route_freight"][j]+c["carbon_price"]*c["route_co2"][j])+hold*s["holding"]+late*s["late"])
        objective.append(c["carbon_excess_penalty"])
        start=time.perf_counter();res=milp(np.array(objective),integrality=self.integrality,bounds=self.bounds,constraints=self.constraints,options={"mip_rel_gap":0.0,"time_limit":10.})
        self.solve_seconds+=time.perf_counter()-start;self.calls+=1
        if res.status!=0 or res.x is None:raise ValueError("MILP_not_proven_optimal")
        xs=res.x[:-1]
        if any(abs(v-round(v))>1e-6 for v in xs):raise ValueError("noninteger_solution")
        plan=tuple(tuple(int(round(v)) for v in xs[i*self.r:(i+1)*self.r]) for i in range(self.n))
        physical=self.shipping(plan,h)
        if abs(physical["loss"]-res.fun)>1e-6:raise ValueError("objective_replay_mismatch")
        return physical["loss"],plan

    def _value(self,h,depth):
        best=(self.terminal(h)[0],-1)
        if depth:
            for i in self.legal(h):
                candidate=self.c["query_fees"][i]+sum(p*self.value(nxt,depth-1)[0] for p,nxt in self.branch(h,i))
                if candidate<best[0]-1e-8:best=(candidate,i)
        return best

    def action(self,h,method):
        return self.value(h,{"no_query":0,"myopic_voi":1,"lookahead_two":2,"exact_dp":self.k}[method])[1]

    def _expected(self,h,method):
        i=self.action(h,method)
        return self.terminal(h)[0] if i==-1 else self.c["query_fees"][i]+sum(p*self.expected(nxt,method) for p,nxt in self.branch(h,i))


def audit(output,smoke=False):
    import platform
    import scipy
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    # A cold dummy solve avoids charging only the first method for HiGHS startup.
    warm=generate(4,2,1);Planner(warm).terminal((-1,-1))
    rows=[];tasks=[];runtime=[]
    grid=[(4,2,31)] if smoke else [(n,k,s) for n in (4,8,12) for k in (2,4,6) for s in (31,47)]
    for n,k,seed in grid:
        task=generate(n,k,seed);task_id=f"scale-{n}-{k}-{seed}"
        # Truth is drawn from each disclosed prior, not a separate hidden distribution.
        rng=random.Random(seed+n*17+k*31)
        truth=[int(rng.random()<p) for p in task["prior"]]
        task["private_evaluation_bits"]=truth;tasks.append({"id":task_id,"context":task})
        public={key:value for key,value in task.items() if key!="private_evaluation_bits"}
        initial=(-1,)*k
        values={}
        for method in METHODS:
            p=Planner(public);start=time.perf_counter();p.action(initial,method)
            runtime.append({"id":task_id,"method":method,"root_wall_seconds":time.perf_counter()-start,"root_milp_calls":p.calls,
                            "root_solver_seconds":p.solve_seconds,"python":platform.python_version(),"scipy":scipy.__version__})
            expected=p.expected(initial,method);values[method]=expected
            h=initial;trace=[];fees=0
            while True:
                i=p.action(h,method)
                trace.append({"history":list(h),"legal_queries":list(p.legal(h)),"action":"commit" if i==-1 else f"query_{i}"})
                if i==-1:break
                fees+=public["query_fees"][i];h=list(h);h[i]=truth[i];h=tuple(h)
            _,plan=p.terminal(h);physical=p.shipping(plan,tuple(truth))
            rows.append({"id":task_id,"method":method,"skus":n,"delay_bits":k,"expected_loss":expected,
                         "plan":plan,"trace":trace,"query_fees":fees,"physical":physical,"realized_loss":physical["loss"]+fees})
        for r in rows[-len(METHODS):]:
            r["optimal_expected_loss"]=values["exact_dp"];r["normalized_regret"]=(r["expected_loss"]-values["exact_dp"])/max(1,values["exact_dp"])
            if r["normalized_regret"] < -1e-8:raise ValueError("policy_better_than_oracle")
    summary={"scope":"development_scaling_not_final_test","tasks":len(tasks),"runs":len(rows),"trained":False,
        "methods":{m:{"mean_normalized_regret":sum(r["normalized_regret"] for r in rows if r["method"]==m)/len(tasks),
                      "max_normalized_regret":max(r["normalized_regret"] for r in rows if r["method"]==m)} for m in METHODS},
        "limits":"Known orders, independent disclosed binary route priors, at most three exact queries. Root effort only, no equal wall-time cap or learned policy comparison."}
    for name,value in (("tasks.json",tasks),("outcomes.json",rows),("summary.json",summary),("runtime.json",runtime)):
        (output/name).write_bytes(canonical(value)+b"\n")
    manifest={"smoke":smoke,"source_sha256":sha256(Path(__file__).read_bytes()),
              "files":{n:sha256((output/n).read_bytes()) for n in ("tasks.json","outcomes.json","summary.json")},
              "runtime_note":"Machine-dependent diagnostic; exact plans may tie across solver versions. Verification compares objective values and physical feasibility, not wall-time or tied plans."}
    (output/"manifest.json").write_bytes(canonical(manifest)+b"\n")
    return summary


def verify(output):
    output=Path(output);m=json.loads((output/"manifest.json").read_text())
    if m["source_sha256"]!=sha256(Path(__file__).read_bytes()):raise ValueError("source_mismatch")
    if set(m["files"])!={"tasks.json","outcomes.json","summary.json"}:raise ValueError("manifest_coverage")
    if type(m["smoke"]) is not bool:raise ValueError("invalid_run_scope")
    for name,h in m["files"].items():
        if name not in ("tasks.json","outcomes.json","summary.json") or sha256((output/name).read_bytes())!=h:raise ValueError("artifact_mismatch")
    with tempfile.TemporaryDirectory() as tmp:
        fresh=audit(tmp,m["smoke"])
        if json.loads((output/"tasks.json").read_text())!=json.loads((Path(tmp)/"tasks.json").read_text()):raise ValueError("task_regeneration_mismatch")
        a=json.loads((output/"outcomes.json").read_text());b=json.loads((Path(tmp)/"outcomes.json").read_text())
        if len(a)!=len(b):raise ValueError("coverage_mismatch")
        tasks={t["id"]:t["context"] for t in json.loads((output/"tasks.json").read_text())}
        for x,y in zip(a,b):
            for name in ("id","method","skus","delay_bits"):
                if x[name]!=y[name]:raise ValueError("case_identity_mismatch")
            for name in ("expected_loss","optimal_expected_loss","normalized_regret"):
                if not math.isfinite(x[name]) or abs(x[name]-y[name])>1e-6:raise ValueError("expected_value_mismatch")
            task=tasks[x["id"]];truth=task["private_evaluation_bits"];public={k:v for k,v in task.items() if k!="private_evaluation_bits"}
            p=Planner(public);h=(-1,)*p.k;fees=0
            if not 1<=len(x["trace"])<=public["max_queries"]+1:raise ValueError("trace_length")
            for index,step in enumerate(x["trace"]):
                q=p.action(h,x["method"]);action="commit" if q==-1 else f"query_{q}"
                if step!={"history":list(h),"legal_queries":list(p.legal(h)),"action":action}:raise ValueError("trace_mismatch")
                if q==-1 and index!=len(x["trace"])-1:raise ValueError("action_after_commit")
                if q!=-1:fees+=public["query_fees"][q];nxt=list(h);nxt[q]=truth[q];h=tuple(nxt)
            if x["trace"][-1]["action"]!="commit":raise ValueError("uncommitted_trace")
            ph=p.shipping(x["plan"],tuple(truth))
            if ph!=x["physical"] or abs(ph["loss"]+fees-x["realized_loss"])>1e-6 or fees!=x["query_fees"]:raise ValueError("physical_replay_mismatch")
            if abs(p.shipping(x["plan"],h)["loss"]-p.terminal(h)[0])>1e-6:raise ValueError("nonoptimal_dispatch")
        old=json.loads((output/"summary.json").read_text())
        for name in ("scope","tasks","runs","trained","limits"):
            if old.get(name)!=fresh[name]:raise ValueError("summary_mismatch")
        if set(old["methods"])!=set(METHODS):raise ValueError("summary_coverage")
        for method in METHODS:
            for name,value in fresh["methods"][method].items():
                actual=old["methods"][method][name]
                if not math.isfinite(actual) or abs(actual-value)>1e-8:raise ValueError("summary_mismatch")
    return {"verified":True,"tasks":fresh["tasks"]}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,default=Path("artifacts/decision_scale"));p.add_argument("--smoke",action="store_true");p.add_argument("--verify",action="store_true");a=p.parse_args()
    print(json.dumps(verify(a.output) if a.verify else audit(a.output,a.smoke),sort_keys=True))


if __name__=="__main__":main()
