"""Answer every question in questions.jsonl from its own text.

Method: exact dynamic programme in integer arithmetic (no floating point, no
heuristic).  The plan is ordered by ARRIVAL offset.  The state after the
arrivals of one offset is (cumulative planned receipts of each SKU, emissions
used so far); the expected inventory cost of an offset depends only on the
cumulative receipts, the route capacity limits one dispatch at a time, and the
window emission limit is the last coordinate of the state.

All money amounts are exact fractions read from the decimal text and are
multiplied by one common integer, so that equal costs are recognised exactly.

Run:  python solver.py             (reads questions.jsonl, writes answers.jsonl
                                     and, for checking, solutions.jsonl)
      python solver.py --no-cache  (solves every text again, even when two texts
                                     state the same planning problem)
"""
import itertools
import json
import re
import sys
import time
from fractions import Fraction
from math import lcm

import numpy as np

LABELS = {
    "Decision period (t)": "t",
    "Public parameters (public)": "public",
    "Available stock (stock)": "stock",
    "Outstanding backlog (backlog)": "backlog",
    "Current arrivals (arrivals)": "arrivals",
    "Old backlog served (served_old)": "served_old",
    "Pipeline arrivals by absolute period (pipeline)": "pipeline",
    "Remaining emissions budget (carbon_remaining)": "carbon_remaining",
    "Past demand (history)": "history",
    "Mean forecast from now (forecast)": "forecast",
    "Demand scenarios (scenario, offset, SKU)": "demand",
}

Q_MATRIX = "What is an optimal current dispatch matrix (SKU × route, units)?"
Q_EMISSIONS = "What are current dispatch emissions in an optimal plan?"
RE_SKU = re.compile(r"^Does an optimal plan dispatch SKU (\d+) now\?$")
RE_KG = re.compile(r"^How many kg use route (\d+) now in an optimal plan\?$")

INF = np.int64(1) << 60


# --------------------------------------------------------------------------
# reading one text
# --------------------------------------------------------------------------
def parse(text):
    """Return (data, question).  Decimal numbers become exact fractions."""
    data = {}
    lines = text.rstrip().split("\n")
    for line in lines:
        for label, name in LABELS.items():
            if line.startswith(label + " = "):
                if name in data:
                    raise ValueError("field given twice: " + name)
                data[name] = json.loads(line[len(label) + 3:], parse_float=Fraction)
    missing = set(LABELS.values()) - set(data)
    if missing:
        raise ValueError("missing fields: %s" % sorted(missing))
    return data, lines[-1]


def parse_question(q):
    if q == Q_MATRIX:
        return ("matrix", None)
    if q == Q_EMISSIONS:
        return ("emissions", None)
    m = RE_SKU.match(q)
    if m:
        return ("sku", int(m.group(1)))
    m = RE_KG.match(q)
    if m:
        return ("kg", int(m.group(1)))
    raise ValueError("unknown question: " + q)


# --------------------------------------------------------------------------
# the planning problem defined by the text
# --------------------------------------------------------------------------
class Problem:
    """The quantities that enter the cost and the constraints."""

    def __init__(self, data):
        p = data["public"]
        self.t = data["t"]
        self.periods = p["periods"]
        self.h = h = min(p["horizon"], self.periods - self.t)
        self.mass = p["mass"]
        self.cap = p["capacity"]
        self.lead = p["lead"]
        self.emis = [Fraction(e) for e in p["emissions"]]
        self.freight = [Fraction(f) for f in p["freight"]]
        self.price = Fraction(p["carbon_price"])
        self.hold = [Fraction(v) for v in p["holding"]]
        self.back = [Fraction(v) for v in p["backlog"]]
        self.term = [Fraction(v) for v in p["terminal_backlog"]]
        self.M = len(self.mass)
        self.J = len(self.cap)
        self.demand = data["demand"]
        self.S = len(self.demand)
        # net inventory at the start of the window (receipts of offset 0 are
        # already counted in stock and backlog)
        self.start = [data["stock"][i] - data["backlog"][i] for i in range(self.M)]
        self.pipe = [[0] * self.M] + [list(data["pipeline"][self.t + u]) for u in range(1, h)]
        self.limit = Fraction(data["carbon_remaining"]) * h / (self.periods - self.t)

        # shape checks of the text
        assert all(len(s) == h for s in self.demand)
        assert all(len(o) == self.M for s in self.demand for o in s)
        assert all(isinstance(v, int) and v >= 0 for s in self.demand for o in s for v in o)

        # common integer multiplier for all money amounts
        den = [x.denominator for x in self.hold + self.back + self.term]
        den += [(self.mass[i] * self.unit_cost_per_kg(j)).denominator
                for i in range(self.M) for j in range(self.J)]
        self.scale = lcm(*den) * self.S

    def unit_cost_per_kg(self, j):
        return self.freight[j] + self.price * self.emis[j]

    def last_episode_offset(self, u):
        return self.t + u == self.periods - 1

    def unit_backlog(self, u, i):
        b = self.back[i]
        if self.last_episode_offset(u):
            b = b + self.term[i]
        return b

    # net inventory without any planned receipt, scenario s, after demand of u
    def base_net(self, s, u, i):
        return (self.start[i] + sum(self.pipe[w][i] for w in range(u + 1))
                - sum(self.demand[s][w][i] for w in range(u + 1)))

    # ---------- plain evaluation straight from the rules (Fractions) ----------
    def evaluate(self, x):
        """Cost of plan x[u][i][j] (exact fraction)."""
        h, M, J = self.h, self.M, self.J
        dispatch = sum(x[u][i][j] * self.mass[i] * self.unit_cost_per_kg(j)
                       for u in range(h) for i in range(M) for j in range(J))
        total = Fraction(0)
        for s in range(self.S):
            net = list(self.start)
            for u in range(h):
                for i in range(M):
                    net[i] += self.pipe[u][i]
                    for j in range(J):
                        v = u - self.lead[j]
                        if v >= 0:
                            net[i] += x[v][i][j]
                for i in range(M):
                    net[i] -= self.demand[s][u][i]
                    total += self.hold[i] * max(net[i], 0) + self.unit_backlog(u, i) * max(-net[i], 0)
        return dispatch + total / self.S

    def violations(self, x):
        h, M, J = self.h, self.M, self.J
        out = []
        emitted = Fraction(0)
        for u in range(h):
            for j in range(J):
                kg = 0
                for i in range(M):
                    v = x[u][i][j]
                    if not isinstance(v, int) or v < 0:
                        out.append(("integer", u, i, j))
                    if v and u + self.lead[j] >= h:
                        out.append(("late", u, i, j))
                    kg += self.mass[i] * v
                    emitted += self.mass[i] * self.emis[j] * v
                if kg > self.cap[j]:
                    out.append(("capacity", u, j, kg))
        if emitted > self.limit:
            out.append(("emissions", emitted, self.limit))
        return out

    # ---------- one dispatch x[0] ----------
    def kg_on_route(self, x0, j):
        return sum(self.mass[i] * x0[i][j] for i in range(self.M))

    def emissions_of(self, x0):
        e = sum(self.mass[i] * self.emis[j] * x0[i][j]
                for i in range(self.M) for j in range(self.J))
        return e


def load_vectors(mass, cap, upper):
    """All nonnegative integer vectors y with sum mass*y <= cap and y <= upper."""
    rng = [range(min(upper[i], cap // mass[i]) + 1) for i in range(len(mass))]
    return [y for y in itertools.product(*rng)
            if sum(m * v for m, v in zip(mass, y)) <= cap]


class ExactDP:
    """Backward dynamic programme over arrival offsets 1..h-1."""

    def __init__(self, pb):
        self.pb = pb
        h, M, J = pb.h, pb.M, pb.J
        assert M == 3
        assert all(l >= 1 for l in pb.lead)
        # Every x[0] move must come before any other move in arrival order.
        # True when the leads differ by at most one offset.
        assert max(pb.lead) - min(pb.lead) <= 1

        # ---- an upper bound on the cumulative receipts of each SKU that holds
        #      in EVERY optimal plan: if after the last receipt of SKU i the net
        #      inventory stays >= 1 in all scenarios and later offsets, dropping
        #      one unit of that receipt is feasible and strictly cheaper.
        self.U = [max([0] + [-pb.base_net(s, u, i) for s in range(pb.S) for u in range(1, h)])
                  for i in range(M)]
        # ---- emission coordinate (emissions are whole numbers)
        e_kg = []
        for j in range(J):
            for i in range(M):
                assert (pb.mass[i] * pb.emis[j]).denominator == 1
            e_kg.append(pb.emis[j])
        floor_limit = pb.limit.numerator // pb.limit.denominator
        self.vec = [load_vectors(pb.mass, pb.cap[j], self.U) for j in range(J)]
        self.vec_e = [[int(sum(m * v for m, v in zip(pb.mass, y)) * e_kg[j]) for y in self.vec[j]]
                      for j in range(J)]
        self.vec_c = [[int(sum(m * v for m, v in zip(pb.mass, y)) * pb.unit_cost_per_kg(j) * pb.scale)
                       for y in self.vec[j]] for j in range(J)]
        max_e = sum(max(self.vec_e[j]) for j in range(J) for u in range(h) if u + pb.lead[j] < h)
        self.E = int(min(max(floor_limit, -1), max_e))     # -1: nothing is feasible
        # ---- expected inventory cost of an offset for each cumulative receipt
        k = pb.scale // pb.S
        assert pb.scale % pb.S == 0
        self.inv = []
        for u in range(h):
            parts = []
            for i in range(M):
                hc = pb.hold[i] * k
                bc = pb.unit_backlog(u, i) * k
                assert hc.denominator == 1 and bc.denominator == 1
                hc, bc = int(hc), int(bc)
                base = [pb.base_net(s, u, i) for s in range(pb.S)]
                parts.append(np.array(
                    [sum(hc * max(b + c, 0) + bc * max(-(b + c), 0) for b in base)
                     for c in range(self.U[i] + 1)], dtype=np.int64))
            self.inv.append(parts)
        self._solve()

    # value arrays have shape (U0+1, U1+1, U2+1, E+1)
    def _inv_array(self, u):
        a, b, c = self.inv[u]
        return (a[:, None, None] + b[None, :, None] + c[None, None, :])[:, :, :, None]

    def _apply(self, W, j):
        """best over y of cost(y) + W(C + y, E + e(y))."""
        out = np.full_like(W, INF)
        n0, n1, n2, ne = W.shape
        for y, e, c in zip(self.vec[j], self.vec_e[j], self.vec_c[j]):
            if e >= ne or y[0] >= n0 or y[1] >= n1 or y[2] >= n2:
                continue
            tgt = out[:n0 - y[0], :n1 - y[1], :n2 - y[2], :ne - e]
            src = W[y[0]:, y[1]:, y[2]:, e:]
            np.minimum(tgt, src + c, out=tgt)
        np.minimum(out, INF, out=out)
        return out

    def _solve(self):
        pb = self.pb
        h, J = pb.h, pb.J
        if self.E < 0:
            raise ValueError("no plan satisfies the emission limit")
        shape = tuple(u + 1 for u in self.U) + (self.E + 1,)
        V = np.zeros(shape, dtype=np.int64)
        # moves[a]: the dispatches (u, j) that arrive at offset a, x[0] first.
        # value[(a, n)]: cost still to come just AFTER the n-th of these moves
        # (inventory cost of offsets a..h-1 and later moves), for every state.
        self.moves = {}
        self.value = {}
        for a in range(h - 1, 0, -1):
            mv = [(a - pb.lead[j], j) for j in range(J) if a - pb.lead[j] >= 0]
            mv.sort()                                   # offset 0 first
            self.moves[a] = mv
            W = V + self._inv_array(a)
            for n in range(len(mv) - 1, -1, -1):
                self.value[(a, n)] = W
                W = self._apply(W, mv[n][1])
            V = W
        self.const0 = int(sum(int(self.inv[0][i][0]) for i in range(pb.M)))
        self.opt = int(V[(0,) * (pb.M + 1)]) + self.const0

    # ------------------------------------------------------------------
    def first_dispatch_values(self):
        """{x0: best scaled cost of any feasible plan with x[0] = x0}.

        x0 is a tuple of route vectors (one tuple of SKU units per route).
        Only vectors within the bound U are listed (others are never optimal).
        """
        pb = self.pb
        h, M, J = pb.h, pb.M, pb.J
        first = [j for j in range(J) if pb.lead[j] <= h - 1]
        first.sort(key=lambda j: pb.lead[j])
        zero = (0,) * M
        res = {}
        if not first:
            res[tuple(zero for _ in range(J))] = self.opt
            return res
        # the moves (0, j) are the first moves in arrival order; between them
        # only the inventory cost of the offsets in between is added
        for combo in itertools.product(*[range(len(self.vec[j])) for j in first]):
            C = [0] * M
            E = 0
            cost = self.const0
            prev_a = None
            ok = True
            W = None
            for j, idx in zip(first, combo):
                a = pb.lead[j]
                if prev_a is not None and a != prev_a:
                    # close stage prev_a (all its moves are x[0] moves)
                    assert all(v == 0 for v, _ in self.moves[prev_a])
                    for b in range(prev_a, a):
                        cost += sum(int(self.inv[b][i][C[i]]) for i in range(M))
                y = self.vec[j][idx]
                C = [c + d for c, d in zip(C, y)]
                E += self.vec_e[j][idx]
                cost += self.vec_c[j][idx]
                if E > self.E or any(c > u for c, u in zip(C, self.U)):
                    ok = False
                    break
                n = self.moves[a].index((0, j))
                W = self.value[(a, n)]
                prev_a = a
            if not ok:
                continue
            # stages before the first arrival offset carry no moves
            a0 = pb.lead[first[0]]
            for b in range(1, a0):
                cost += sum(int(self.inv[b][i][0]) for i in range(M))
            total = cost + int(W[tuple(C) + (E,)])
            if total >= int(INF) // 2:
                continue
            x0 = [zero] * J
            for j, idx in zip(first, combo):
                x0[j] = self.vec[j][idx]
            res[tuple(x0)] = total
        return res

    def complete_plan(self, x0):
        """One optimal completion of x[0]; returns x[u][i][j]."""
        pb = self.pb
        h, M, J = pb.h, pb.M, pb.J
        x = [[[0] * J for _ in range(M)] for _ in range(h)]
        C, E = (0,) * M, 0
        for a in range(1, h):
            for n, (u, j) in enumerate(self.moves[a]):
                W = self.value[(a, n)]
                if u == 0:
                    y = x0[j]
                    k = self.vec[j].index(y)
                    best_k = k
                else:
                    best, best_k = None, None
                    for k, y in enumerate(self.vec[j]):
                        D = tuple(c + d for c, d in zip(C, y))
                        F = E + self.vec_e[j][k]
                        if F > self.E or any(c > b for c, b in zip(D, self.U)):
                            continue
                        val = int(W[D + (F,)]) + self.vec_c[j][k]
                        if best is None or val < best:
                            best, best_k = val, k
                y = self.vec[j][best_k]
                C = tuple(c + d for c, d in zip(C, y))
                E += self.vec_e[j][best_k]
                for i in range(M):
                    x[u][i][j] = y[i]
        return x


def as_matrix(x0, M, J):
    return [[int(x0[j][i]) for j in range(J)] for i in range(M)]


def solve_problem(pb):
    """Exact optimum, every optimal current dispatch, one full plan for each."""
    dp = ExactDP(pb)
    q = dp.first_dispatch_values()
    best = min(q.values())
    assert best == dp.opt
    optimal = sorted(x0 for x0, v in q.items() if v == best)
    matrices = [as_matrix(x0, pb.M, pb.J) for x0 in optimal]
    plans = [dp.complete_plan(x0) for x0 in optimal]
    for plan, m in zip(plans, matrices):
        assert pb.evaluate(plan) * pb.scale == best
        assert not pb.violations(plan)
        assert plan[0] == m
    return {"cost": Fraction(best, pb.scale), "scaled": best, "scale": pb.scale,
            "matrices": matrices, "plans": plans, "values": q}


def to_json_number(v):
    v = Fraction(v)
    return int(v) if v.denominator == 1 else float(v)


def possible_answers(pb, sol, kind, arg):
    """All answers given by the optimal plans of the text (list of JSON values)."""
    out = []
    for m in sol["matrices"]:
        a = answer_from(pb, m, kind, arg)
        if a not in out:
            out.append(a)
    return out


def choose(kind, arg, matrices):
    """Index of the optimal current dispatch that the answer is taken from.

    Any optimal plan may be used.  The one taken here is the first optimal
    current dispatch (in list order) that dispatches the most SKUs.  If a
    yes-or-no question asks about a SKU which that dispatch leaves out although
    another optimal dispatch has it, the other one is used (this never happens
    in these texts).  So "true" is written exactly when at least one optimal
    plan dispatches the SKU, and all questions about one situation are answered
    from one and the same optimal plan.
    """
    size = [sum(any(v > 0 for v in row) for row in m) for m in matrices]
    pick = size.index(max(size))
    if kind == "sku" and not any(v > 0 for v in matrices[pick][arg]):
        for n, m in enumerate(matrices):
            if any(v > 0 for v in m[arg]):
                return n
    return pick


def answer_from(pb, matrix, kind, arg):
    if kind == "matrix":
        return matrix
    if kind == "sku":
        return any(v > 0 for v in matrix[arg])
    if kind == "kg":
        return to_json_number(pb.kg_on_route(matrix, arg))
    return to_json_number(pb.emissions_of(matrix))


def cache_key(data):
    return json.dumps({k: data[k] for k in
                       ("t", "public", "stock", "backlog", "arrivals", "pipeline",
                        "carbon_remaining", "demand")},
                      sort_keys=True, default=str)


def main(use_cache=True):
    start = time.time()
    rows = [json.loads(l) for l in open("questions.jsonl", encoding="utf-8")]
    cache = {}
    n = solved = 0
    with open("answers.jsonl", "w", encoding="utf-8", newline="\n") as fh, \
            open("solutions.jsonl", "w", encoding="utf-8", newline="\n") as gh:
        for row in rows:
            data, question = parse(row["text"])
            kind, arg = parse_question(question)
            key = cache_key(data)
            if not use_cache or key not in cache:
                pb = Problem(data)
                cache[key] = (pb, solve_problem(pb))
                solved += 1
            pb, sol = cache[key]
            pick = choose(kind, arg, sol["matrices"])
            answer = answer_from(pb, sol["matrices"][pick], kind, arg)
            fh.write(json.dumps({"key": row["key"], "answer": answer}, ensure_ascii=False) + "\n")
            gh.write(json.dumps({
                "key": row["key"], "question": question, "answer": answer,
                "all_answers_of_optimal_plans": possible_answers(pb, sol, kind, arg),
                "optimal_cost": str(sol["cost"]),
                "plan_x_u_i_j": sol["plans"][pick],
                "optimal_current_dispatches": sol["matrices"],
            }, ensure_ascii=False) + "\n")
            n += 1
    print("answered", n, "questions;", solved, "planning problems solved;",
          "%.1f s" % (time.time() - start))


if __name__ == "__main__":
    main(use_cache="--no-cache" not in sys.argv)
