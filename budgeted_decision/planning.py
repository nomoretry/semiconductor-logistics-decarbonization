"""Actual MILP calls, branch-local caches and complete-candidate interruption."""
from __future__ import annotations

from functools import lru_cache
from scripts.audit_decision_scale import Planner
from notice_benchmark.api_runner import canonical_bytes, sha256

METHODS = ("myopic_index", "myopic_priority", "lookahead_two", "iterative_dp")


def cache_hash(cache):
    return sha256(canonical_bytes([[list(h), cost, plan] for h, (cost, plan) in sorted(cache.items())]))


class Exhausted(Exception):
    """The next cache miss would exceed the current decision's allowance."""


class Decision:
    def __init__(self, context, budget, cache=None, backend=None):
        if type(budget) is not int or budget < 1:
            raise ValueError("positive_integer_budget_required")
        self.model = Planner(context)  # rejects private evaluation state
        self.c = context
        self.budget = budget
        self.cache = dict(cache or {})  # no mutation of a sibling branch
        self.solves = []
        self.backend = backend or self.model._terminal

    def solve(self, history):
        if history in self.cache:
            return self.cache[history]
        if len(self.solves) >= self.budget:
            raise Exhausted()
        cost, plan = self.backend(history)
        self.cache[history] = (cost, plan)
        self.solves.append({"history": list(history), "loss": cost, "plan": plan})
        return cost, plan

    def order(self, history, method):
        legal = self.model.legal(history)
        if method == "myopic_index":
            return legal
        def impact(i):
            p = self.c["prior"][i]
            difference = sum(s["quantity"] * abs(s["late"] * max(0, 4-s["due"])
                                                 - s["holding"] * max(0, s["due"]-2))
                             for s in self.c["known_orders"])
            return p * (1-p) * difference / self.c["query_fees"][i]
        return tuple(sorted(legal, key=lambda i: (-impact(i), i)))

    def choose(self, history, method):
        if method not in METHODS:
            raise ValueError("unknown_method")
        if (len(history) != self.model.k or any(type(x) is not int or x not in (-1, 0, 1) for x in history)
                or sum(x != -1 for x in history) > self.c["max_queries"]
                or sum(f for f, x in zip(self.c["query_fees"], history) if x != -1) > self.c["query_budget"]):
            raise ValueError("invalid_observed_history")
        before = cache_hash(self.cache)
        terminal, plan = self.solve(history)
        best_value, best_action, selected_depth = terminal, -1, 0
        completed = []
        interrupted = False
        root_estimates = {}
        remaining = self.c["max_queries"] - sum(x != -1 for x in history)
        max_depth = min(remaining, 1 if method.startswith("myopic") else 2 if method == "lookahead_two" else remaining)

        @lru_cache(None)
        def value(h, depth):
            best = self.solve(h)[0]
            if depth:
                for i in self.order(h, method):
                    candidate = self.c["query_fees"][i] + sum(
                        weight * value(nxt, depth-1) for weight, nxt in self.model.branch(h, i))
                    best = min(best, candidate)
            return best

        try:
            for depth in range(1, max_depth+1):
                order = self.order(history, method)
                if depth > 1:
                    order = tuple(sorted(order, key=lambda i: (root_estimates[i], i)))
                for i in order:
                    candidate = self.c["query_fees"][i] + sum(
                        weight * value(nxt, depth-1) for weight, nxt in self.model.branch(history, i))
                    # This line is reached only after both complete continuations.
                    completed.append([depth, i, candidate])
                    root_estimates[i] = candidate
                    if candidate < best_value - 1e-8:
                        best_value, best_action, selected_depth = candidate, i, depth
        except Exhausted:
            interrupted = True
        return {"history": list(history), "legal_queries": list(self.model.legal(history)),
                "action": best_action, "selected_depth": selected_depth,
                "predicted_loss": best_value, "terminal_loss": terminal,
                "commit_plan": plan if best_action == -1 else None,
                "completed_candidates": completed, "interrupted": interrupted,
                "milp_calls": len(self.solves), "solves": self.solves,
                "cache_before": before, "cache_after": cache_hash(self.cache)}, self.cache
