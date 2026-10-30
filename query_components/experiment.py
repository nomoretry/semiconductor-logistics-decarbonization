"""Run and replay a fixed development factorial without reading final tasks."""
from __future__ import annotations

from pathlib import Path
import time
import numpy as np

from query_study.common import ROOT, read, write, write_lines, read_lines, canonical, sha256, empty_output
from query_study.development import datasets, prepare_teachers
from query_study.statistics import paired_interval
from query_policy.experiment import close, rollout, verify_trace
from query_policy.model import deserialize, serialize
from query_policy.solver import Planner
from query_ppo.experiment import config as ppo_config
from scripts.verify_training_portable import BoundComparison
from .potential import fit
from .environment import tree, step
from .training import train

PREVIOUS = ROOT / "benchmark_results/query_study_development"
DEFAULT = ROOT / "benchmark_results/query_components_development"
LEARNED = ("bc_masked", "bc_unmasked", "masked_cost", "unmasked_cost",
           "masked_potential", "unmasked_potential", "masked_cost_inference_off")
BASELINES = ("lookahead_two_13", "iterative_dp_65")


def config(smoke=False):
    cfg = read(ROOT / "query_components/config.json")
    if smoke: cfg.update(training_seeds=[17], bootstrap_replicates=40)
    return cfg


def source_identity():
    from query_study.common import source_identity as previous
    result = previous()
    files = list((ROOT / "query_components").glob("*.py"))
    files += [ROOT / "query_components/config.json", ROOT / "docs/query_components_protocol.md",
              PREVIOUS / "manifest.json", ROOT / "scripts/verify_training_portable.py"]
    result.update({str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in files})
    return result


def previous_bc(seed):
    from query_study.common import check_bundle
    check_bundle(PREVIOUS, "query-study-development-v1")
    return read(PREVIOUS / f"models/{seed}-bc.json")["selected"]


def pack(episodes):
    fields = ("action", "answer", "base_reward", "phi_before", "phi_after", "old_logp", "old_value")
    return [[e["iteration"], e["id"], e["repeat"], [[s[k] for k in fields] for s in e["steps"]]] for e in episodes]


def expand(rows, tasks, cfg, fitted):
    from query_ppo.algorithm import gae
    models = {t["id"]: Planner(t["public"]) for t in tasks if t["split"] == "train"}
    episodes = []
    for iteration, identity, repeat, records in rows:
        model = models[identity]; h = (-1,) * model.k; steps = []
        if not records or len(records) > model.c["max_queries"] + 1:
            raise ValueError("episode_length")
        for index, (action, answer, base, before, after, logp, value) in enumerate(records):
            transition = step(model, h, action, answer, cfg, fitted)
            close([base, before, after], [transition[k] for k in ("base_reward", "phi_before", "phi_after")])
            if transition["done"] != (index == len(records) - 1):
                raise ValueError("terminal_boundary")
            record = {"history": list(h), "action": action, "answer": answer,
                      "old_logp": logp, "old_value": value, **transition}
            steps.append(record); h = tuple(transition["next_history"])
        adv, ret = gae([s["reward"] for s in steps], [s["old_value"] for s in steps],
                       np.array([s["done"] for s in steps]), cfg["gamma"], cfg["gae_lambda"])
        for s, a, r in zip(steps, adv, ret): s.update(advantage=float(a), value_target=float(r))
        episodes.append({"iteration": iteration, "id": identity, "repeat": repeat, "steps": steps})
    return episodes


def coefficient_map(payload):
    result = {}
    for item in payload["checkpoints"]:
        for obj in (item, item["actor"]): result[sha256(canonical(obj))] = obj
    return result


def compare_training(saved, fresh):
    compare = BoundComparison(coefficient_map(saved), coefficient_map(fresh))
    compare({k: v for k, v in saved.items() if k != "checkpoints"},
            {k: v for k, v in fresh.items() if k != "checkpoints"})
    close(saved["checkpoints"], fresh["checkpoints"])


def train_one(seed, variant, tasks, cfg, potential, smoke):
    settings = ppo_config(smoke)
    settings.update(training_seed=seed, invalid_action_penalty=cfg["invalid_action_penalty"], **cfg["variants"][variant])
    bc = previous_bc(seed); fitted = potential if settings["shaping"] else None
    initial, selected, last, log, episodes, checkpoints = train(tasks, deserialize(bc, 32), settings, fitted)
    if initial["actor"] != bc: raise ValueError("shared_bc_start")
    if log["total_updates"] <= 0 or log["last_actor_l2_from_bc"] <= 0: raise ValueError("missing_training_updates")
    payload = {"seed": seed, "variant": variant, "config": settings, "bc_start_sha256": sha256(canonical(bc)),
               "potential_sha256": sha256(canonical(potential)) if fitted else None,
               "initial": initial, "selected": selected, "last": last, "training": log, "checkpoints": checkpoints}
    if variant == "masked_cost" and not smoke:
        old = read(PREVIOUS / f"models/{seed}-ppo.json")
        companion = read(ROOT / "benchmark_results/training_replay_checkpoints.json")["coefficients"]
        comparison = BoundComparison(companion, coefficient_map(payload))
        for name in ("initial", "selected", "last", "training"):
            comparison(old[name], payload[name])
        from query_study.common import expand_episodes
        old_episodes = expand_episodes(read_lines(PREVIOUS / f"episodes/{seed}-ppo.jsonl"), tasks, old["config"])
        stripped = [{**e, "steps": [{k: s[k] for k in old_episodes[0]["steps"][0]} for s in e["steps"]]} for e in episodes]
        close(old_episodes, stripped)
    return payload, episodes


def policies(path, cfg):
    result = []
    for seed in cfg["training_seeds"]:
        bc = previous_bc(seed)
        for method, mask in (("bc_masked", True), ("bc_unmasked", False)):
            result.append((method, seed, bc, mask))
        for variant, settings in cfg["variants"].items():
            payload = read(path / f"models/{seed}-{variant}.json")
            if payload["initial"]["actor"] != bc or payload["bc_start_sha256"] != sha256(canonical(bc)):
                raise ValueError("model_start_binding")
            actor = payload["selected"]["actor"]
            result.append((variant, seed, actor, settings["action_mask"]))
            if variant == "masked_cost": result.append(("masked_cost_inference_off", seed, actor, False))
    return result


def evaluate(path, audit, cfg):
    rows, traces, references = [], [], []
    models = policies(path, cfg)
    for task in audit:
        public = task["public"]; planner = Planner(public)
        reference = planner.value((-1,) * planner.k, planner.k)[0]
        references.append({"id": task["id"], "optimal_expected_loss": reference})
        for method, seed, actor, mask in models:
            result = tree(public, deserialize(actor, 32), mask, cfg["invalid_action_penalty"])
            row = {k: v for k, v in result.items() if k != "nodes"}
            row.update(id=task["id"], method=method, seed=seed, model_sha256=sha256(canonical(actor)),
                       regret=(result["expected_loss"] - reference) / max(1., reference))
            if row["regret"] < -1e-7: raise ValueError("better_than_exact_reference")
            rows.append(row); traces.append({"id": task["id"], "method": method, "seed": seed, "result": result})
        for method in BASELINES:
            result = rollout(public, method, None)
            row = {k: result[k] for k in ("expected_loss", "expected_queries", "expected_milp_calls")}
            row.update(id=task["id"], method=method, seed=None, model_sha256=None,
                       expected_economic_cost=result["expected_loss"], rejection_probability=0.,
                       expected_decisions=result["expected_queries"] + 1.,
                       regret=(result["expected_loss"] - reference) / max(1., reference))
            rows.append(row); traces.append({"id": task["id"], "method": method, "seed": None, "result": result})
    return rows, traces, references


def summarize(rows, audit, cfg):
    ids = [t["id"] for t in audit]; seeds = cfg["training_seeds"]
    lookup = {(r["method"], r["seed"], r["id"]): r for r in rows}
    expected = {(m, s, i) for m in LEARNED for s in seeds for i in ids}
    expected |= {(m, None, i) for m in BASELINES for i in ids}
    if len(lookup) != len(rows) or set(lookup) != expected: raise ValueError("paired_coverage")
    arrays = {m: np.array([[lookup[(m, s, i)]["regret"] for i in ids] for s in seeds]) for m in LEARNED}
    strata = [f"{len(t['public']['known_orders']):02d}-{t['public']['delay_bits']}" for t in audit]
    metrics = ("regret", "expected_loss", "expected_economic_cost", "rejection_probability",
               "expected_queries", "expected_decisions", "expected_milp_calls")
    methods = {}
    for m in (*LEARNED, *BASELINES):
        group = [r for r in rows if r["method"] == m]
        methods[m] = {"mean_" + k: float(np.mean([r[k] for r in group])) for k in metrics}
        methods[m]["max_regret"] = max(r["regret"] for r in group)
        if m in arrays: methods[m]["per_seed_regret"] = arrays[m].mean(axis=1).tolist()
    differences = {"remove_mask": arrays["unmasked_cost"] - arrays["masked_cost"],
                   "potential_masked": arrays["masked_potential"] - arrays["masked_cost"],
                   "potential_unmasked": arrays["unmasked_potential"] - arrays["unmasked_cost"],
                   "inference_only_remove_mask": arrays["masked_cost_inference_off"] - arrays["masked_cost"]}
    differences["interaction"] = differences["potential_unmasked"] - differences["potential_masked"]
    contrasts = {k: paired_interval(v, strata, cfg["bootstrap_replicates"], cfg["bootstrap_seed"]) for k, v in differences.items()}
    return {"scope": cfg["scope"], "distinct_development_contexts": len(ids), "training_seeds": seeds,
            "ppo_training_runs": 4 * len(seeds), "policy_evaluations": len(rows), "methods": methods,
            "exploratory_contrasts": contrasts, "new_final_test": False, "old_final_unchanged": True}


def seal(path, smoke):
    files = {str(p.relative_to(path)): sha256(p.read_bytes()) for p in sorted(path.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    write(path / "manifest.json", {"schema": "query-components-bundle-v1", "smoke": smoke,
                                   "source": source_identity(), "files": files})


def check(path):
    m = read(path / "manifest.json")
    if m["schema"] != "query-components-bundle-v1" or type(m["smoke"]) is not bool or m["source"] != source_identity():
        raise ValueError("component_source_identity")
    files = {str(p.relative_to(path)) for p in path.rglob("*") if p.is_file() and p.name != "manifest.json"}
    if files != set(m["files"]): raise ValueError("component_file_coverage")
    for name, identity in m["files"].items():
        p = Path(name)
        if p.is_absolute() or ".." in p.parts or (path / p).is_symlink(): raise ValueError("unsafe_path")
        if sha256((path / p).read_bytes()) != identity: raise ValueError("component_file_hash")
    return m


def run(output, smoke=False):
    path = empty_output(output); cfg = config(smoke); tasks, audit = datasets(smoke)
    for name in ("models", "episodes"): (path / name).mkdir()
    teachers = prepare_teachers(tasks)
    potential = fit([t for t in tasks if t["split"] == "train"], teachers, cfg, ppo_config()["reward_scale"])
    for name, value in (("config", cfg), ("training_tasks", tasks), ("audit_tasks", audit), ("potential", potential)):
        write(path / f"{name}.json", value)
    start = time.perf_counter()
    for seed in cfg["training_seeds"]:
        for variant in cfg["variants"]:
            payload, episodes = train_one(seed, variant, tasks, cfg, potential, smoke)
            write(path / f"models/{seed}-{variant}.json", payload)
            write_lines(path / f"episodes/{seed}-{variant}.jsonl", pack(episodes))
            print(f"trained seed {seed}, {variant}", flush=True)
    training_seconds = time.perf_counter() - start; start = time.perf_counter()
    rows, traces, refs = evaluate(path, audit, cfg)
    summary = summarize(rows, audit, cfg)
    for name, value in (("outcomes", rows), ("traces", traces), ("references", refs)):
        write_lines(path / f"{name}.jsonl", value)
    write(path / "summary.json", summary)
    write(path / "runtime.json", {"training_seconds": training_seconds, "evaluation_seconds": time.perf_counter() - start})
    seal(path, smoke)
    return summary


def compare_traces(saved, fresh, audit):
    public = {t["id"]: t["public"] for t in audit}
    if len(saved) != len(fresh): raise ValueError("trace_coverage")
    for old, new in zip(saved, fresh):
        close({k: v for k, v in old.items() if k != "result"}, {k: v for k, v in new.items() if k != "result"})
        if new["method"] in BASELINES:
            verify_trace(public[new["id"]], old["result"], new["result"])
            continue
        a, b = old["result"], new["result"]
        close({k: v for k, v in a.items() if k != "nodes"}, {k: v for k, v in b.items() if k != "nodes"})
        if len(a["nodes"]) != len(b["nodes"]): raise ValueError("node_coverage")
        model = Planner(public[new["id"]])
        for left, right in zip(a["nodes"], b["nodes"]):
            x, y = dict(left), dict(right); plan = x.pop("commit_plan"); y.pop("commit_plan")
            close(x, y)
            if right["action"] == 0 or right["invalid"]:
                close(model.shipping(plan, tuple(left["history"]))["loss"], right["terminal_cost"])
            elif plan is not None: raise ValueError("plan_before_commit")


def verify(output):
    path = Path(output); m = check(path); cfg = config(m["smoke"]); tasks, audit = datasets(m["smoke"])
    for name, expected in (("config", cfg), ("training_tasks", tasks), ("audit_tasks", audit)):
        if read(path / f"{name}.json") != expected: raise ValueError("component_configuration")
    teachers = prepare_teachers(tasks)
    potential = fit([t for t in tasks if t["split"] == "train"], teachers, cfg, ppo_config()["reward_scale"])
    close(read(path / "potential.json"), potential)
    for seed in cfg["training_seeds"]:
        for variant in cfg["variants"]:
            fresh, episodes = train_one(seed, variant, tasks, cfg, potential, m["smoke"])
            saved = read(path / f"models/{seed}-{variant}.json")
            # Bind the saved potential SHA to the saved full, numerically replayed predictor.
            expected_phi = sha256(canonical(read(path / "potential.json"))) if saved["config"]["shaping"] else None
            if saved["potential_sha256"] != expected_phi: raise ValueError("potential_binding")
            fresh["potential_sha256"] = expected_phi
            compare_training(saved, fresh)
            restored = expand(read_lines(path / f"episodes/{seed}-{variant}.jsonl"), tasks,
                              saved["config"], potential if saved["config"]["shaping"] else None)
            close(restored, episodes)
        print(f"verified four component variants for seed {seed}", flush=True)
    rows, traces, refs = evaluate(path, audit, cfg)
    close(read_lines(path / "outcomes.jsonl"), rows)
    compare_traces(read_lines(path / "traces.jsonl"), traces, audit)
    close(read_lines(path / "references.jsonl"), refs)
    close(read(path / "summary.json"), summarize(rows, audit, cfg))
    return {"verified": True, "ppo_training_runs": 4 * len(cfg["training_seeds"]),
            "policy_evaluations": len(rows), "distinct_development_contexts": len(audit),
            "potential_refitted_on_train_only": True, "frozen_final_evaluated": False}
