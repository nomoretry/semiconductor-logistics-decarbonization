"""Transactional query -> solve -> commit environment with public observations."""
from __future__ import annotations

import copy
from .planning import Planner, INITIAL
from .model import physical


class Environment:
    def __init__(self, context, world, answers):
        self.planner = Planner(context)
        if type(world) is not int or not 0 <= world < 4 or len(answers) != 3 or any(type(x) is not int or x not in (0,1) for x in answers):
            raise ValueError("Invalid private evaluation world")
        for q, answer in zip(context["queries"], answers):
            p = q["positive_likelihood"][world]
            if (answer == 1 and p == 0) or (answer == 0 and p == 1):
                raise ValueError("Impossible private answer")
        self._world, self._answers = world, tuple(answers)
        self.history, self.candidate, self.done = INITIAL, None, False

    def observation(self):
        tools = [] if self.done else (["commit"] if self.candidate is not None else
                 ["solve_bayes", "solve_robust"] + [f"query_{i}" for i in self.planner.legal_queries(self.history)])
        return copy.deepcopy({"context": self.planner.c, "history": list(self.history),
                "posterior": list(self.planner.belief(self.history)), "legal_tools": tools,
                "spent": self.planner.spent(self.history) + (self.planner.c["solve_fee"] if self.candidate is not None else 0),
                "candidate": None if self.candidate is None else self.planner.plans[self.candidate], "done": self.done})

    def step(self, tool):
        # Validate first; rejection cannot spend money or partially change state.
        if tool not in self.observation()["legal_tools"]:
            raise ValueError("Illegal tool call")
        if tool.startswith("query_"):
            i = int(tool[6:]); history = list(self.history); history[i] = self._answers[i]
            self.history = tuple(history)
        elif tool.startswith("solve_"):
            self.candidate = self.planner.terminal(self.history, tool == "solve_robust")[1]
        else:
            self.done = True
        return self.observation()

    def evaluation(self):
        if not self.done:
            raise ValueError("Plan is not committed")
        outcome = physical(self.planner.c, self.planner.plans[self.candidate], self._world)
        fees = self.planner.spent(self.history) + self.planner.c["solve_fee"]
        return {"physical": outcome, "tool_fees": fees, "all_in_loss": outcome["shipping_loss"] + fees}


def run(context, world, answers, method):
    env = Environment(context, world, answers)
    policy = Planner(context)  # Receives only the public context.
    trace = []
    while not env.done:
        before = env.observation()
        if before["candidate"] is not None:
            action = "commit"
        else:
            q = policy.action(tuple(before["history"]), method)
            action = f"query_{q}" if q >= 0 else ("solve_robust" if method == "no_query_robust" else "solve_bayes")
        after = env.step(action)
        trace.append({"before": before, "action": action, "after": after})
    return {"trace": trace, "evaluation": env.evaluation()}
