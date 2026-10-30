"""Public-only, solver-free, shared candidate features and budget masks."""
from __future__ import annotations

import numpy as np

PUBLIC_KEYS = frozenset(("synthetic", "known_orders", "delay_bits", "prior", "query_fees",
    "query_budget", "max_queries", "route_freight", "route_co2", "route_capacity",
    "shared_ocean_pool_capacity", "carbon_price", "carbon_budget", "carbon_excess_penalty"))
ORDER_KEYS = frozenset(("quantity", "mass", "due", "late", "holding"))
FEATURE_VERSION = "public-candidate-37-v1"


def encode(context, history):
    """Return [commit, query_0, ...] rows; no case identity or teacher inputs."""
    if set(context) != PUBLIC_KEYS or any(set(x) != ORDER_KEYS for x in context["known_orders"]):
        raise ValueError("public_context_fields")
    c, h = context, tuple(history)
    k = c["delay_bits"]
    if len(h) != k or any(type(x) is not int or x not in (-1, 0, 1) for x in h):
        raise ValueError("invalid_history")
    spent = sum(f for f, a in zip(c["query_fees"], h) if a != -1)
    count = sum(a != -1 for a in h)
    if spent > c["query_budget"] or count > c["max_queries"]:
        raise ValueError("history_budget")
    orders = c["known_orders"]
    mass = sum(s["quantity"] * s["mass"] for s in orders)
    quantity = sum(s["quantity"] for s in orders)
    lateness = sum(s["quantity"] * s["late"] * (4-s["due"]) for s in orders)
    holding = sum(s["quantity"] * s["holding"] * (s["due"]-2) for s in orders)
    ps = [c["prior"][i] if a == -1 else a for i, a in enumerate(h)]
    expected = [mass*c["route_freight"][i+1] + p*lateness + (1-p)*holding
                for i, p in enumerate(ps)]
    remaining = c["query_budget"] - spent
    legal = [a == -1 and count < c["max_queries"] and c["query_fees"][i] <= remaining
             for i, a in enumerate(h)]
    state = [len(orders)/12, k/6, quantity/48, mass/96, lateness/7680, holding/10,
             remaining/8, (c["max_queries"]-count)/3, sum(legal)/6,
             min(ps), max(ps), sum(ps)/k, min(expected)/7680,
             sum(a == 0 for a in h)/6, sum(a == 1 for a in h)/6,
             c["route_capacity"][0]/mass, c["shared_ocean_pool_capacity"]/mass,
             c["carbon_budget"]/(5*mass), c["carbon_price"], c["carbon_excess_penalty"]/2]
    rows = [state + [1.] + [0.]*16]
    for i in range(k):
        p, fee = ps[i], c["query_fees"][i]
        rows.append(state + [0., p, p*(1-p), fee/8, fee/max(1,remaining),
            c["route_freight"][i+1]/10, c["route_co2"][i+1]/5,
            c["route_capacity"][i+1]/mass, float(i < 2), float(h[i] != -1),
            p*lateness/7680, expected[i]/7680, (expected[i]-min(expected))/7680,
            p*(1-p)*lateness/(7680*fee), (remaining-fee)/8,
            sum(legal[j] and j != i and c["query_fees"][j]+fee <= remaining for j in range(k))/6,
            float(h[i] == 0)])
    result = np.asarray(rows, dtype=np.float64)
    if result.shape != (k+1, 37) or not np.isfinite(result).all():
        raise ValueError("feature_shape_or_finiteness")
    return result, np.asarray([True, *legal], dtype=bool)
