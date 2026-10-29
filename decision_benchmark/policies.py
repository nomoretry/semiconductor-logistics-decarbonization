"""Strong public-information policies and a finite Bayes decision oracle.

Every policy accepts an observation dictionary, never an environment. The
oracle enumerates both possible public-model states; it cannot see which one
was sampled. Its value includes query/solver fees and all tool budgets.
"""

from __future__ import annotations

from functools import lru_cache

from .env import DecisionEnv
from .model import QUERIES, SOLVERS, canonical, loss_table, screen_branches


def state_from_observation(obs):
    return (obs["posterior_severe_delay"], obs["screen_used"], obs["clarification_used"],
            obs["queries_used"], obs["solver_calls_used"], obs["steps_remaining"],
            obs["tool_budget_remaining_usd"],
            tuple(sorted({item["ocean_units"] for item in obs["candidates"]})))


def action_from_abstract(obs, action):
    tool, q = action
    if tool != "commit_plan":
        return {"tool": tool}
    candidate = next(item for item in obs["candidates"] if item["ocean_units"] == q)
    return {"tool": tool, "candidate_id": candidate["candidate_id"]}


class PublicPlanner:
    """Exact finite-horizon DP for this explicit public simulator model."""

    def __init__(self, context):
        self.context = context
        self.table = loss_table(context)
        self.fees = context["tool_fees_usd"]
        self.budgets = context["budgets"]
        self.failure = context["unshipped_order_loss_usd"]
        self._solve = lru_cache(maxsize=None)(self._solve_uncached)
        self.candidate = lru_cache(maxsize=None)(self._candidate)

    def _candidate(self, p, solver):
        if solver == "solve_nominal":
            objective = lambda q: self.table[q][0]
        elif solver == "solve_robust":
            objective = lambda q: max(self.table[q])
        else:
            objective = lambda q: self.expected_shipping_loss(p, q)
        return min(range(len(self.table)), key=lambda q: (objective(q), q))

    def expected_shipping_loss(self, p, q):
        return (1 - p) * self.table[q][0] + p * self.table[q][1]

    def legal_queries(self, state):
        p, screen, clarified, queries, solves, steps, cash, candidates = state
        if queries >= self.budgets["max_queries"]:
            return []
        return [tool for tool, used in (("query_status", screen), ("request_clarification", clarified))
                if not used and self.fees[tool] <= cash]

    def legal_solvers(self, state):
        p, screen, clarified, queries, solves, steps, cash, candidates = state
        if solves >= self.budgets["max_solver_calls"]:
            return []
        return [tool for tool in SOLVERS if self.fees[tool] <= cash]

    def after_solver(self, state, solver):
        p, screen, clarified, queries, solves, steps, cash, candidates = state
        q = self.candidate(p, solver)
        return (p, screen, clarified, queries, solves + 1, steps - 1,
                cash - self.fees[solver], tuple(sorted(set(candidates) | {q})))

    def query_outcomes(self, state, tool):
        p, screen, clarified, queries, solves, steps, cash, candidates = state
        if tool == "query_status":
            branches = [(prob, new_p) for prob, new_p, signal in screen_branches(self.context, p)]
        else:
            branches = [(1 - p, 0.0), (p, 1.0)]
        return [(prob, (new_p, screen or tool == "query_status",
                         clarified or tool == "request_clarification", queries + 1, solves,
                         steps - 1, cash - self.fees[tool], candidates))
                for prob, new_p in branches if prob > 0]

    def best_direct(self, state):
        p, screen, clarified, queries, solves, steps, cash, candidates = state
        if steps <= 0:
            return self.failure, ("handoff", None)
        choices = [(self.failure, ("handoff", None))]
        choices += [(self.expected_shipping_loss(p, q), ("commit_plan", q)) for q in candidates]
        if steps >= 2:
            choices += [(self.fees[solver] + self.expected_shipping_loss(p, self.candidate(p, solver)),
                         (solver, None)) for solver in self.legal_solvers(state)]
        return self._best(choices)

    @staticmethod
    def _best(choices):
        # Prefer completion over an equally good extra call, using no hidden data.
        rank = {"commit_plan": 0, "solve_nominal": 1, "solve_robust": 2,
                "solve_bayes": 3, "query_status": 4, "request_clarification": 5, "handoff": 6}
        return min(choices, key=lambda item: (round(item[0], 10), rank[item[1][0]], item[1][1] or 0))

    def _solve_uncached(self, state):
        p, screen, clarified, queries, solves, steps, cash, candidates = state
        if steps <= 0:
            return self.failure, ("handoff", None)
        choices = [(self.failure, ("handoff", None))]
        choices += [(self.expected_shipping_loss(p, q), ("commit_plan", q)) for q in candidates]
        if steps >= 2:
            for solver in self.legal_solvers(state):
                next_state = self.after_solver(state, solver)
                # Paying again for an identical candidate cannot improve the state.
                if self.candidate(p, solver) in candidates:
                    continue
                value = self.fees[solver] + self._solve(next_state)[0]
                choices.append((value, (solver, None)))
        if steps >= 3:
            for tool in self.legal_queries(state):
                value = self.fees[tool] + sum(prob * self._solve(next_state)[0]
                                              for prob, next_state in self.query_outcomes(state, tool))
                choices.append((value, (tool, None)))
        return self._best(choices)

    def optimal(self, state):
        return self._solve(state)

    def myopic(self, state):
        choices = [self.best_direct(state)]
        if state[5] >= 3:
            for tool in self.legal_queries(state):
                value = self.fees[tool] + sum(prob * self.best_direct(next_state)[0]
                                              for prob, next_state in self.query_outcomes(state, tool))
                choices.append((value, (tool, None)))
        return self._best(choices)


class AdaptivePolicy:
    def __init__(self, mode="bayes_dp"):
        if mode not in ("bayes_dp", "myopic_voi"):
            raise ValueError("Unknown adaptive policy")
        self.mode, self._planners = mode, {}

    def planner(self, context):
        key = canonical(context)
        if key not in self._planners:
            self._planners[key] = PublicPlanner(context)
        return self._planners[key]

    def __call__(self, obs):
        planner, state = self.planner(obs["context"]), state_from_observation(obs)
        value, action = planner.optimal(state) if self.mode == "bayes_dp" else planner.myopic(state)
        return action_from_abstract(obs, action)


class FixedPolicy:
    """Competent workflows with explicit fallback when fees or budgets bind."""

    def __init__(self, mode):
        if mode not in ("cheapest_freight", "risk_robust", "always_clarify", "screen_then_solve"):
            raise ValueError("Unknown fixed workflow")
        self.mode = mode

    def __call__(self, obs):
        mask = obs["action_mask"]
        if obs["candidates"]:
            planner = PublicPlanner(obs["context"])
            p = obs["posterior_severe_delay"]
            candidate = min(obs["candidates"], key=lambda item: planner.expected_shipping_loss(p, item["ocean_units"]))
            return {"tool": "commit_plan", "candidate_id": candidate["candidate_id"]}
        if obs["steps_remaining"] >= 3:
            fees = obs["context"]["tool_fees_usd"]
            reserve = min(fees[solver] for solver in SOLVERS)
            can_query_and_solve = lambda tool: (mask[tool] and obs["tool_budget_remaining_usd"] >= fees[tool] + reserve)
            if (self.mode == "always_clarify" and not obs["clarification_used"]
                    and can_query_and_solve("request_clarification")):
                return {"tool": "request_clarification"}
            if self.mode == "screen_then_solve" and not obs["screen_used"] and can_query_and_solve("query_status"):
                return {"tool": "query_status"}
        solver = {"cheapest_freight": "solve_nominal", "risk_robust": "solve_robust"}.get(self.mode, "solve_bayes")
        if mask[solver] and obs["steps_remaining"] >= 2:
            return {"tool": solver}
        planner = PublicPlanner(obs["context"])
        return action_from_abstract(obs, planner.best_direct(state_from_observation(obs))[1])


def policies():
    return {
        "fixed_cheapest_freight": FixedPolicy("cheapest_freight"),
        "fixed_risk_robust": FixedPolicy("risk_robust"),
        "fixed_always_clarify": FixedPolicy("always_clarify"),
        "fixed_screen_then_solve": FixedPolicy("screen_then_solve"),
        "adaptive_myopic_voi": AdaptivePolicy("myopic_voi"),
        "public_bayes_dp": AdaptivePolicy("bayes_dp"),
    }


def run_policy(env, policy):
    while not env.terminated:
        env.step(policy(env.observation()))
    return {"evaluation": env.terminal_evaluation(), "trace": env.trace()}


def expected_policy_loss(context, policy):
    """Exact public-model expectation over delay and screen outcomes, not a sample."""
    prior, query = context["prior_severe_delay"], context["query_model"]
    expected = 0.0
    for theta, probability in ((0, 1 - prior), (2, prior)):
        positive = query["sensitivity"] if theta == 2 else 1 - query["specificity"]
        for signal, conditional in ((False, 1 - positive), (True, positive)):
            if probability * conditional <= 0:
                continue
            result = run_policy(DecisionEnv(context, theta=theta, screen_positive=signal), policy)
            expected += probability * conditional * result["evaluation"]["all_in_loss_usd"]
    return expected
