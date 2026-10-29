"""Public-belief planning; never accepts an actual hidden world or evaluation ID."""
from __future__ import annotations

from functools import lru_cache
import math

from .model import allocations, physical, validate

METHODS = ("no_query_bayes", "no_query_robust", "entropy_per_cost", "myopic_voi", "lookahead_two", "exact_dp")
INITIAL = (-1, -1, -1)


class Planner:
    def __init__(self, context, *, shared=True):
        import copy
        self.c = copy.deepcopy(context)
        validate(self.c)
        self.plans = tuple(allocations(self.c, shared=shared))
        if not self.plans:
            raise ValueError("No feasible dispatch")
        self.table = tuple(tuple(physical(self.c, p, w, shared=shared)["shipping_loss"]
                                 for w in range(4)) for p in self.plans)
        # Instance-local caches avoid retaining every completed task's model.
        self.belief = lru_cache(None)(self._belief)
        self.terminal = lru_cache(None)(self._terminal)
        self.lookahead = lru_cache(None)(self._lookahead)
        self.expected = lru_cache(None)(self._expected)

    def spent(self, history):
        return sum(q["fee"] for q, answer in zip(self.c["queries"], history) if answer != -1)

    def _belief(self, history):
        if len(history) != 3 or any(type(a) is not int or a not in (-1, 0, 1) for a in history):
            raise ValueError("Invalid query history")
        weights = list(self.c["prior"])
        for q, answer in zip(self.c["queries"], history):
            if answer != -1:
                weights = [p * (l if answer else 1-l) for p, l in zip(weights, q["positive_likelihood"])]
        if sum(weights) <= 0:
            raise ValueError("Impossible observation")
        return tuple(p / sum(weights) for p in weights)

    def legal_queries(self, history):
        if sum(a != -1 for a in history) >= self.c["max_queries"]:
            return ()
        return tuple(i for i, q in enumerate(self.c["queries"]) if history[i] == -1
                     and self.spent(history) + q["fee"] + self.c["solve_fee"] <= self.c["query_budget"])

    def branches(self, history, i):
        p = sum(w*l for w, l in zip(self.belief(history), self.c["queries"][i]["positive_likelihood"]))
        for answer, probability in ((0, 1-p), (1, p)):
            if probability > 1e-14:
                nxt = list(history); nxt[i] = answer
                yield probability, tuple(nxt)

    def _terminal(self, history, robust=False):
        b = self.belief(history)
        values = [max(v for v, p in zip(row, b) if p > 0) if robust else sum(v*p for v, p in zip(row, b))
                  for row in self.table]
        idx = min(range(len(values)), key=lambda i: (values[i], self.plans[i]))
        # Evaluation always uses expected loss, even when selection is robust.
        return self.c["solve_fee"] + sum(v*p for v, p in zip(self.table[idx], b)), idx

    def _lookahead(self, history, depth):
        best = (self.terminal(history)[0], -1)
        if depth:
            for i in self.legal_queries(history):
                value = self.c["queries"][i]["fee"] + sum(
                    p*self.lookahead(nxt, depth-1)[0] for p, nxt in self.branches(history, i))
                if value < best[0] - 1e-10:
                    best = (value, i)
        return best

    def action(self, history, method):
        if method not in METHODS:
            raise ValueError("Unknown policy")
        if method.startswith("no_query"):
            return -1
        if method == "entropy_per_cost":
            def entropy(b):
                return -sum(p*math.log(p) for p in b if p > 0)
            base = entropy(self.belief(history))
            gains = [( (base - sum(p*entropy(self.belief(nxt)) for p, nxt in self.branches(history, i)))
                       / self.c["queries"][i]["fee"], i) for i in self.legal_queries(history)]
            return max(gains, key=lambda x: (x[0], -x[1]))[1] if gains and max(x[0] for x in gains) > 1e-10 else -1
        depth = {"myopic_voi": 1, "lookahead_two": 2, "exact_dp": 3}[method]
        return self.lookahead(history, depth)[1]

    def _expected(self, history, method):
        i = self.action(history, method)
        if i == -1:
            return self.terminal(history, method == "no_query_robust")[0]
        return self.c["queries"][i]["fee"] + sum(p*self.expected(nxt, method) for p, nxt in self.branches(history, i))
