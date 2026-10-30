"""Same MILP as the frozen scale planner, with scale-aware objective validation."""
from __future__ import annotations

import time
from scripts.audit_decision_scale import Planner as FrozenPlanner


class Planner(FrozenPlanner):
    def _terminal(self, history):
        import numpy as np
        from scipy.optimize import milp
        c = self.c
        objective = []
        for order in c["known_orders"]:
            for route in range(self.r):
                p = 0 if route == 0 else c["prior"][route-1] if history[route-1] == -1 else history[route-1]
                hold = order["due"]-1 if route == 0 else (1-p)*max(0,order["due"]-2)
                late = 0 if route == 0 else p*max(0,4-order["due"])
                objective.append(order["mass"]*(c["route_freight"][route]+c["carbon_price"]*c["route_co2"][route])
                                 + hold*order["holding"]+late*order["late"])
        objective.append(c["carbon_excess_penalty"])
        start = time.perf_counter()
        result = milp(np.array(objective),integrality=self.integrality,bounds=self.bounds,
                      constraints=self.constraints,options={"mip_rel_gap":0.,"time_limit":10.})
        self.solve_seconds += time.perf_counter()-start; self.calls += 1
        if result.status != 0 or result.x is None:
            raise ValueError("MILP_not_proven_optimal")
        values = result.x[:-1]
        if any(abs(v-round(v)) > 1e-6 for v in values):
            raise ValueError("noninteger_solution")
        plan = tuple(tuple(int(round(v)) for v in values[i*self.r:(i+1)*self.r]) for i in range(self.n))
        physical = self.shipping(plan,history)
        # HiGHS can place the continuous carbon slack at its feasibility tolerance.
        # Report the exact physical objective of the integer plan, never its slack.
        if abs(physical["loss"]-result.fun) > 1e-6 + 1e-10*abs(physical["loss"]):
            raise ValueError("objective_replay_mismatch")
        return physical["loss"],plan
