"""Costly simulated information tools with a hidden physical terminal replay."""

from __future__ import annotations

from .model import (QUERIES, SOLVERS, TOOLS, candidate_for_solver, clone,
                    digest, physical_outcome, score_outcome,
                    updated_posterior, validate_context)


class DecisionEnv:
    """Policies receive only JSON observations; world access is evaluation-only.

    Hidden state is the unresolved *announced delay*, not unknown future
    demand. Clarification is an offline simulator response; no message is sent.
    This Python object is an API boundary, not a hostile-code security sandbox.
    """

    def __init__(self, context: dict, *, theta: int, screen_positive: bool):
        validate_context(context)
        if type(theta) is not int or theta not in (0, 2) or type(screen_positive) is not bool:
            raise ValueError("Invalid private physical world")
        self._context = clone(context)
        self._theta = theta
        self._screen_positive = screen_positive
        self.reset()

    def reset(self):
        self._posterior = self._context["prior_severe_delay"]
        self._screen_used = False
        self._clarification_used = False
        self._queries = 0
        self._solver_calls = 0
        self._steps = 0
        self._fees = 0
        self._candidates = []
        self._committed = None
        self._done = False
        self._reason = None
        self._responses = []
        self._trace = []
        return self.observation()

    @property
    def terminated(self):
        return self._done

    def action_mask(self):
        if self._done:
            return {tool: False for tool in TOOLS}
        budgets, fees = self._context["budgets"], self._context["tool_fees_usd"]
        cash = budgets["tool_budget_usd"] - self._fees
        queries_left = self._queries < budgets["max_queries"]
        return {
            "query_status": queries_left and not self._screen_used and cash >= fees["query_status"],
            "request_clarification": queries_left and not self._clarification_used
            and cash >= fees["request_clarification"],
            **{solver: self._solver_calls < budgets["max_solver_calls"] and cash >= fees[solver]
               for solver in SOLVERS},
            "commit_plan": bool(self._candidates), "handoff": True,
        }

    def observation(self):
        budgets = self._context["budgets"]
        return {
            "context": clone(self._context), "posterior_severe_delay": self._posterior,
            "screen_used": self._screen_used, "clarification_used": self._clarification_used,
            "queries_used": self._queries, "solver_calls_used": self._solver_calls,
            "steps_used": self._steps, "fees_paid_usd": self._fees,
            "steps_remaining": max(0, budgets["max_steps"] - self._steps),
            "tool_budget_remaining_usd": budgets["tool_budget_usd"] - self._fees,
            "candidates": clone(self._candidates), "responses": clone(self._responses),
            "action_mask": self.action_mask(), "terminated": self._done,
        }

    def _execute(self, tool, action):
        if tool in QUERIES:
            self._queries += 1
            if tool == "query_status":
                self._screen_used = True
                self._posterior = updated_posterior(self._context, self._posterior, self._screen_positive)
                response = {"signal": "delay_indicated" if self._screen_positive else "delay_not_indicated",
                            "posterior_severe_delay": self._posterior}
            else:
                self._clarification_used = True
                self._posterior = float(self._theta == 2)
                response = {"mode": "offline_simulation_no_message_sent",
                            "confirmed_ocean_delay_weeks": self._theta,
                            "posterior_severe_delay": self._posterior}
            self._responses.append({"tool": tool, **response})
            return response
        if tool in SOLVERS:
            self._solver_calls += 1
            q = candidate_for_solver(self._context, self._posterior, tool)
            # IDs depend only on public call order, never the hidden world.
            candidate = {"candidate_id": f"candidate_{len(self._candidates)}",
                         "ocean_units": q, "air_units": self._context["committed_order"]["quantity"] - q,
                         "solver": tool, "belief_at_solve": self._posterior}
            self._candidates.append(candidate)
            return clone(candidate)
        if tool == "commit_plan":
            self._committed = next(clone(item) for item in self._candidates
                                   if item["candidate_id"] == action["candidate_id"])
            self._done, self._reason = True, "plan_committed"
            return {"committed": True, "candidate_id": self._committed["candidate_id"]}
        self._done, self._reason = True, "handoff"
        return {"handed_off": True, "mode": "offline_simulation_no_message_sent"}

    def step(self, action):
        if self._done:
            raise RuntimeError("Episode already terminated")
        before = self.observation()
        tool = action if isinstance(action, str) else action.get("tool") if isinstance(action, dict) else None
        payload = {"tool": action} if isinstance(action, str) else action
        valid_shape = isinstance(payload, dict) and (
            set(payload) == {"tool", "candidate_id"} if tool == "commit_plan" else set(payload) == {"tool"})
        valid = valid_shape and isinstance(tool, str) and before["action_mask"].get(tool, False)
        if valid and tool == "commit_plan":
            valid = any(item["candidate_id"] == payload.get("candidate_id") for item in self._candidates)
        self._steps += 1
        fee = self._context["tool_fees_usd"].get(tool, 0) if isinstance(tool, str) else 0
        if valid:
            self._fees += fee
            response = self._execute(tool, payload)
        else:
            fee = min(self._context["invalid_action_fee_usd"], before["tool_budget_remaining_usd"])
            self._fees += fee
            response = {"error": "unknown_malformed_or_unavailable_action"}
        if not self._done and self._steps >= self._context["budgets"]["max_steps"]:
            self._done, self._reason = True, "step_budget_exhausted"
        reward = -float(fee)
        evaluation = None
        if self._done:
            evaluation = self.terminal_evaluation()
            reward -= evaluation["shipping_loss_usd"]
        after = self.observation()
        trace_row = {"step": self._steps, "action": clone(payload) if isinstance(payload, dict) else "<malformed>",
                     "valid_action": bool(valid), "fee_usd": fee, "response": response,
                     "observation_before_sha256": digest(before), "observation_after_sha256": digest(after),
                     "reward": reward, "terminated": self._done}
        self._trace.append(trace_row)
        info = {"valid_action": bool(valid), "response": clone(response)}
        if evaluation is not None:
            info["evaluation"] = evaluation
        return {"observation": after, "reward": reward, "terminated": self._done, "info": info}

    def terminal_evaluation(self):
        if not self._done:
            raise RuntimeError("Hidden evaluation is unavailable before termination")
        physical = scoring = None
        shipping_loss = self._context["unshipped_order_loss_usd"]
        success = False
        if self._committed is not None:
            physical = physical_outcome(self._context, self._committed["ocean_units"], self._theta)
            scoring = score_outcome(self._context, physical)
            shipping_loss = scoring["shipping_loss_usd"]
            success = (physical["quantity_conservation"] and physical["all_committed_orders_delivered"]
                       and scoring["service_success"] and scoring["carbon_budget_met"])
        return {"task_success": bool(success), "shipment_committed": self._committed is not None,
                "terminal_reason": self._reason, "actual_delay_weeks": self._theta,
                "shipping_loss_usd": float(shipping_loss), "tool_fees_usd": float(self._fees),
                "all_in_loss_usd": float(shipping_loss + self._fees),
                "physical_outcome": physical, "goal_scoring": scoring,
                "steps": self._steps, "solver_calls": self._solver_calls, "queries": self._queries}

    def trace(self):
        return clone(self._trace)
