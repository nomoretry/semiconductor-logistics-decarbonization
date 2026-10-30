"""Small integer logistics model; all parameters are disclosed synthetic inputs."""
from __future__ import annotations

import itertools
import math

WORLDS = ((0, 0), (0, 2), (2, 0), (2, 2))


def validate(c):
    if c.get("synthetic") is not True or c.get("scope") != "known_orders_announced_uncertainty":
        raise ValueError("Only the synthetic known-order contract is supported")
    if not 2 <= len(c["skus"]) <= 5 or len(c["routes"]) != 3:
        raise ValueError("Unsupported SKU/route count")
    if len(c["prior"]) != 4 or any(not math.isfinite(p) or p <= 0 for p in c["prior"]):
        raise ValueError("Four positive joint probabilities are required")
    if not math.isclose(sum(c["prior"]), 1, abs_tol=1e-12):
        raise ValueError("Joint prior must sum to one")
    def integer(x, minimum=0):
        if type(x) is not int or x < minimum:
            raise ValueError("Expected bounded nonnegative integer")
    def number(x):
        if isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or x < 0:
            raise ValueError("Expected finite nonnegative number")
    for s in c["skus"]:
        integer(s["quantity"], 1); integer(s["mass"], 1); integer(s["due_week"], 1)
        if s["quantity"] > 3 or s["due_week"] > 4 or len(s["eligible"]) != 3:
            raise ValueError("Unsupported order shape")
        if not all(type(x) is bool for x in s["eligible"]) or not any(s["eligible"]):
            raise ValueError("Invalid eligibility")
        number(s["late_penalty"]); number(s["holding"])
    for r in c["routes"]:
        integer(r["capacity_kg"], 1); integer(r["lead_week"], 1)
        number(r["freight_per_kg"]); number(r["co2_per_kg"])
    if [r["lead_week"] for r in c["routes"]] != [1, 2, 2]:
        raise ValueError("Unsupported route lead times")
    integer(c["query_budget"], 1); integer(c["max_queries"])
    integer(c["solve_fee"], 1)
    if c["query_budget"] < c["solve_fee"] or not 0 <= c["max_queries"] <= 3:
        raise ValueError("Insufficient solver reserve or unsupported query horizon")
    if len(c["queries"]) != 3:
        raise ValueError("Exactly three information sources are supported")
    for q in c["queries"]:
        integer(q["fee"], 1)
        if len(q["positive_likelihood"]) != 4 or any(
                not isinstance(x, (int, float)) or isinstance(x, bool)
                or not math.isfinite(x) or not 0 <= x <= 1 for x in q["positive_likelihood"]):
            raise ValueError("Invalid public observation likelihood")
    for k in ("carbon_price", "carbon_budget", "carbon_excess_penalty"):
        number(c[k])


def allocations(c, shared=True):
    """Enumerate every integer SKU/route allocation, respecting shared kg caps."""
    options = []
    for s in c["skus"]:
        n = s["quantity"]
        options.append([x for x in itertools.product(range(n + 1), repeat=3)
                        if sum(x) == n and all(not x[j] or s["eligible"][j] for j in range(3))])
    for plan in itertools.product(*options):
        load = [sum(row[j] * s["mass"] for row, s in zip(plan, c["skus"])) for j in range(3)]
        if not shared or all(load[j] <= c["routes"][j]["capacity_kg"] for j in range(3)):
            yield plan


def physical(c, plan, world, *, shared=True):
    """Replay shipments independently of the planner's objective table."""
    if type(world) is not int or not 0 <= world < 4 or len(plan) != len(c["skus"]):
        raise ValueError("Bad world or plan")
    load, freight, carbon, holding, late_cost, on_time, total = [0, 0, 0], 0., 0., 0., 0., 0, 0
    ledger = []
    for s, row in zip(c["skus"], plan):
        if len(row) != 3 or any(type(n) is not int or n < 0 for n in row) or sum(row) != s["quantity"]:
            raise ValueError("Integer quantity conservation failed")
        arrivals = [0] * 6
        for j, n in enumerate(row):
            if n and not s["eligible"][j]:
                raise ValueError("Ineligible shipment")
            route = c["routes"][j]
            load[j] += n * s["mass"]
            week = route["lead_week"] + (WORLDS[world][j-1] if j else 0)
            arrivals[week] += n
            freight += n * s["mass"] * route["freight_per_kg"]
            carbon += n * s["mass"] * route["co2_per_kg"]
            on_time += n * (week <= s["due_week"])
        inventory, backlog, net = [], [], 0
        for week, arrived in enumerate(arrivals):
            net += arrived - (s["quantity"] if week == s["due_week"] else 0)
            inventory.append(max(0, net)); backlog.append(max(0, -net))
        holding += sum(inventory) * s["holding"]
        late_cost += sum(backlog) * s["late_penalty"]
        total += s["quantity"]
        ledger.append({"sku": s["id"], "dispatch": list(row), "arrivals": arrivals,
                       "inventory": inventory, "backlog": backlog})
    if shared and any(load[j] > c["routes"][j]["capacity_kg"] for j in range(3)):
        raise ValueError("Shared capacity exceeded")
    carbon_cost = carbon * c["carbon_price"] + max(0, carbon - c["carbon_budget"]) * c["carbon_excess_penalty"]
    return {"sku_ledger": ledger, "route_load_kg": load, "freight": freight,
            "holding": holding, "lateness_cost": late_cost, "co2_kg": carbon,
            "carbon_cost": carbon_cost, "shipping_loss": freight + holding + late_cost + carbon_cost,
            "on_time_fill_rate": on_time / total, "all_on_time": on_time == total}
