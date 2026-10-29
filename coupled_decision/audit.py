"""Generate, run and deterministically replay the coupled development audit."""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
import random
import tempfile
import time

from decision_benchmark.model import canonical, digest
from .env import Environment, run
from .planning import Planner, INITIAL, METHODS

ROOT = Path(__file__).resolve().parents[1]


def generate(count, seed):
    rng = random.Random(seed)
    tasks = []
    for index in range(count):
        family = ("three_sku", "four_sku", "route_eligibility", "carbon_tradeoff")[index % 4]
        for attempt in range(100):
            n = 4 if family == "four_sku" else 3
            skus = [{"id": f"sku-{i}", "quantity": rng.choice((1, 2)), "mass": rng.choice((1, 2)),
                     "due_week": rng.choice((2, 3)), "late_penalty": rng.choice((3, 10, 30, 80)),
                     "holding": rng.choice((0.1, 0.5)),
                     "eligible": [True, True, True]} for i in range(n)]
            if family == "route_eligibility":
                skus[0]["eligible"][1] = False
                skus[1]["eligible"][2] = False
            mass = sum(s["quantity"] * s["mass"] for s in skus)
            routes = [{"name": name, "capacity_kg": max(2, int(mass*rng.choice((.35, .5, .7)))),
                       "lead_week": 1 if j == 0 else 2,
                       "freight_per_kg": rng.choice((7, 10, 15)) if j == 0 else rng.choice((1, 2, 3)),
                       "co2_per_kg": 5 if j == 0 else (0.25 if j == 1 else 0.35)}
                      for j, name in enumerate(("air", "ocean_a", "ocean_b"))]
            prior = rng.choice(((.55, .1, .1, .25), (.1, .4, .4, .1), (.25, .25, .25, .25), (.7, .1, .1, .1)))
            c = {"synthetic": True, "scope": "known_orders_announced_uncertainty", "skus": skus,
                 "routes": routes, "prior": list(prior), "solve_fee": 1,
                 "query_budget": rng.choice((3, 6, 10, 18, 30)), "max_queries": rng.choice((1, 2, 3)),
                 "carbon_price": 8 if family == "carbon_tradeoff" else .1,
                 "carbon_budget": mass * 2, "carbon_excess_penalty": 4 if family == "carbon_tradeoff" else 0,
                 "queries": [
                    {"name": "confirm_ocean_a", "fee": rng.choice((2, 5, 12)), "positive_likelihood": [0, 0, 1, 1]},
                    {"name": "confirm_ocean_b", "fee": rng.choice((2, 5, 12)), "positive_likelihood": [0, 1, 0, 1]},
                    {"name": "network_screen", "fee": rng.choice((1, 3, 8)), "positive_likelihood": [.15, .8, .8, .9]}]}
            try:
                Planner(c)
            except ValueError as exc:
                if str(exc) != "No feasible dispatch":
                    raise
                continue
            break
        else:
            raise RuntimeError("Could not generate feasible context")
        world = rng.choices(range(4), weights=prior)[0]
        answers = [int(rng.random() < q["positive_likelihood"][world]) for q in c["queries"]]
        tasks.append({"id": f"coupled-dev-{index:04d}", "family": family,
                      "rejected_infeasible_draws": attempt, "context": c,
                      "private_evaluation": {"world": world, "answers": answers}})
    return tasks


def _realized_expectation(planner, method):
    """Independent traversal of world/answer outcomes, without Bellman values."""
    result = 0.
    for w, prior in enumerate(planner.c["prior"]):
        for answers in itertools.product((0, 1), repeat=3):
            prob = prior
            for answer, q in zip(answers, planner.c["queries"]):
                p = q["positive_likelihood"][w]
                prob *= p if answer else 1-p
            if not prob:
                continue
            history = INITIAL
            while True:
                i = planner.action(history, method)
                if i == -1:
                    _, plan = planner.terminal(history, method == "no_query_robust")
                    result += prob * (planner.table[plan][w] + planner.spent(history) + planner.c["solve_fee"])
                    break
                nxt = list(history); nxt[i] = answers[i]; history = tuple(nxt)
    return result


def _counterfactual(c, p):
    initial = p.expected(INITIAL, "exact_dp")
    unlimited = Planner(c, shared=False)
    free_capacity_value = unlimited.expected(INITIAL, "exact_dp")
    relaxed = copy.deepcopy(c)
    relaxed["query_budget"] = sum(q["fee"] for q in c["queries"]) + c["solve_fee"]
    relaxed["max_queries"] = 3
    relaxed_value = Planner(relaxed).expected(INITIAL, "exact_dp")
    expensive = copy.deepcopy(c)
    for q in expensive["queries"]:
        q["fee"] = 1000
    expensive_action = Planner(expensive).action(INITIAL, "exact_dp")
    if free_capacity_value > initial + 1e-8 or relaxed_value > initial + 1e-8:
        raise AssertionError("Relaxing constraints made the exact optimum worse")
    return {"capacity_relaxation_gain": max(0, initial-free_capacity_value),
            "query_budget_relaxation_gain": max(0, initial-relaxed_value),
            "query_price_changes_first_action": expensive_action != p.action(INITIAL, "exact_dp"),
            "independent_sku_optimum_infeasible": _independent_infeasible(c)}


def _independent_infeasible(c):
    # This diagnostic removes shared capacity and allocates each SKU alone.
    # The pooled carbon penalty is also removed, so it is not a fair main baseline.
    plan = []
    for s in c["skus"]:
        one = copy.deepcopy(c)
        # Planner validates >=2 SKUs; direct per-SKU candidates below need no dummy SKU.
        from .model import allocations, physical
        one["skus"] = [s]; one["carbon_excess_penalty"] = 0
        candidates = list(allocations(one, shared=False))
        best = min(candidates, key=lambda x: (sum(p*physical(one, x, w, shared=False)["shipping_loss"]
                      for w,p in enumerate(c["prior"])), x))
        plan.extend(best)
    return any(sum(row[j]*s["mass"] for row,s in zip(plan,c["skus"])) > c["routes"][j]["capacity_kg"] for j in range(3))


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(obj) + b"\n")


def run_audit(output, count=120, seed=61803):
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("contexts must be between 1 and 1000")
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    tasks, rows, traces, checks, runtime = generate(count, seed), [], [], [], []
    residual = 0.
    for task in tasks:
        c, private = task["context"], task["private_evaluation"]
        start = time.perf_counter()
        p = Planner(c)
        optimum = p.expected(INITIAL, "exact_dp")
        runtime.append({"task_id": task["id"], "root_planning_seconds": time.perf_counter()-start,
                        "feasible_integer_plans": len(p.plans), "cached_lookahead_states": p.lookahead.cache_info().currsize})
        checks.append({"task_id": task["id"], **_counterfactual(c,p)})
        # Every possible world has the identical initial policy input and legal tools.
        initial_observations = [Environment(c, w, [int(q["positive_likelihood"][w] == 1) for q in c["queries"]]).observation() for w in range(4)]
        if any(x != initial_observations[0] for x in initial_observations):
            raise AssertionError("Private world leaked through public observation")
        for method in METHODS:
            expected = p.expected(INITIAL, method)
            residual = max(residual, abs(expected-_realized_expectation(p, method)))
            if expected < optimum - 1e-8:
                raise AssertionError("Baseline beat exact public oracle")
            result = run(c, private["world"], private["answers"], method)
            trace = result.pop("trace")
            for step in trace:
                for side in ("before", "after"):
                    step[side]["context_sha256"] = digest(step[side].pop("context"))
            tr = {"task_id": task["id"], "method": method, "steps": trace}
            traces.append(tr)
            rows.append({"task_id": task["id"], "family": task["family"], "method": method,
                         "expected_loss": expected, "optimal_expected_loss": optimum,
                         "normalized_regret": max(0, expected-optimum)/max(1, optimum),
                         "trace_sha256": digest(tr), **result})
    aggregate = {}
    for method in METHODS:
        r = [x for x in rows if x["method"] == method]
        aggregate[method] = {"mean_expected_loss": sum(x["expected_loss"] for x in r)/count,
            "mean_normalized_regret": sum(x["normalized_regret"] for x in r)/count,
            "realized_all_on_time_rate": sum(x["evaluation"]["physical"]["all_on_time"] for x in r)/count,
            "mean_realized_co2_kg": sum(x["evaluation"]["physical"]["co2_kg"] for x in r)/count,
            "mean_realized_tool_fees": sum(x["evaluation"]["tool_fees"] for x in r)/count}
    adaptive = min(("myopic_voi", "lookahead_two"), key=lambda m: aggregate[m]["mean_normalized_regret"])
    protocol = json.loads((ROOT/"coupled_decision/protocol.json").read_text())
    capacity = sum(x["capacity_relaxation_gain"] > 1e-7 for x in checks)/count
    budget = sum(x["query_budget_relaxation_gain"] > 1e-7 for x in checks)/count
    gate = (capacity >= protocol["minimum_capacity_and_budget_effect_fraction"] and
            budget >= protocol["minimum_capacity_and_budget_effect_fraction"] and
            aggregate[adaptive]["mean_normalized_regret"] >= protocol["minimum_best_adaptive_mean_normalized_regret_for_further_learning_study"])
    summary = {"schema_version": "coupled-development-audit-v1", "split": "development_only",
        "contexts": count, "method_runs": len(rows), "seed": seed, "methods": aggregate,
        "counterfactuals": {"capacity_affects_optimum_fraction": capacity,
            "query_budget_affects_optimum_fraction": budget,
            "query_price_changes_first_action_fraction": sum(x["query_price_changes_first_action"] for x in checks)/count,
            "independent_sku_plan_infeasible_fraction": sum(x["independent_sku_optimum_infeasible"] for x in checks)/count},
        "world_enumeration_max_residual": residual, "best_adaptive_baseline": adaptive,
        "further_learning_study_gate": gate, "bc_ppo_trained": False, "canonical_final": False,
        "interpretation": "Gate is a development diagnostic, not evidence that RL will help. Exact planning remains a required baseline; measure computational value at larger scale before training."}
    if residual > 1e-8:
        raise AssertionError("Expected values do not match explicit world enumeration")
    for filename, obj in (("tasks.json",tasks), ("outcomes.json",rows), ("counterfactuals.json",checks), ("summary.json",summary), ("runtime.json",runtime)):
        write(output/filename,obj)
    (output/"traces.jsonl").write_bytes(b"".join(canonical(x)+b"\n" for x in traces))
    names = ("tasks.json", "outcomes.json", "counterfactuals.json", "summary.json", "traces.jsonl")
    source_names = [str(p.relative_to(ROOT)) for p in sorted((ROOT/"coupled_decision").glob("*.py"))] + ["coupled_decision/protocol.json", "decision_benchmark/model.py"]
    write(output/"manifest.json", {"schema_version":"coupled-audit-manifest-v1", "count":count, "seed":seed,
         "files":{n:hashlib.sha256((output/n).read_bytes()).hexdigest() for n in names},
         "source":{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in source_names},
         "runtime_note":"Non-deterministic local diagnostic; excluded from evidence identity and simulated costs."})
    return summary


def verify(output):
    output = Path(output)
    m = json.loads((output/"manifest.json").read_text())
    for base, hashes in ((ROOT,m["source"]),(output,m["files"])):
        for name,h in hashes.items():
            p=base/name
            if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:
                raise ValueError("Evidence identity mismatch: "+name)
    with tempfile.TemporaryDirectory() as tmp:
        run_audit(Path(tmp),m["count"],m["seed"])
        regenerated=json.loads((Path(tmp)/"manifest.json").read_text())
        if regenerated != m:
            raise ValueError("Regenerated manifest mismatch")
        for name in m["files"]:
            if (Path(tmp)/name).read_bytes() != (output/name).read_bytes():
                raise ValueError("Replay mismatch: "+name)
    return {"verified":True,"contexts":m["count"]}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,default=Path("artifacts/coupled_decision"))
    p.add_argument("--contexts",type=int,default=120)
    p.add_argument("--seed",type=int,default=61803)
    p.add_argument("--verify",action="store_true")
    args=p.parse_args(argv)
    print(json.dumps(verify(args.output) if args.verify else run_audit(args.output,args.contexts,args.seed),sort_keys=True))


if __name__ == "__main__":
    main()
