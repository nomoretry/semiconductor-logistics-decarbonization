"""Offline, known-order tool workflow with a hidden terminal evaluator.

This environment is an engineering baseline, not evidence that reinforcement
learning is needed. A fixed workflow can perform its sequencing. There is no
external messaging, API call, unknown-demand stream or rolling controller.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from typing import Any, Callable

import numpy as np

from shared.experiments import compile_notice, planning_inputs, solve_policy
from .metrics import normalize_output


TOOLS = (
    "inspect_notice", "extract_notice", "validate_update", "read_state",
    "solve_plan", "audit_plan", "commit_plan", "request_clarification",
    "safe_handoff",
)


def _plain(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite value cannot enter a public tool record")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def audit_plan_feasibility(
    config: dict[str, Any], committed_orders: Any, plan: dict[str, Any], *,
    initial_inventory: Any = None, carbon_cap: float | None = None,
    tolerance: float = 1e-5,
) -> dict[str, Any]:
    """Reconstruct physical outcomes from dispatches without calling the solver.

    For visible auditing supply the extracted configuration. For independent
    terminal evaluation supply the reference configuration. Claimed feasibility
    and claimed objective values are never accepted as physical evidence.
    """
    demand = np.asarray(committed_orders, dtype=float)
    args, _ = planning_inputs(config, demand, initial=initial_inventory)
    T, K = demand.shape
    J = len(config["routes"])
    violations: list[str] = []
    if not isinstance(plan, dict) or plan.get("orders") is None:
        return {"valid": False, "violations": ["no_dispatch_plan"],
                "actual_total_cost": None, "actual_total_emissions": None}
    try:
        quantities = np.asarray(plan["orders"], dtype=float)
    except (TypeError, ValueError):
        quantities = np.array([])
    if quantities.shape != (T, J, K) or not np.isfinite(quantities).all():
        return {"valid": False, "violations": ["invalid_dispatch_shape_or_number"],
                "actual_total_cost": None, "actual_total_emissions": None}
    if np.any(quantities < -tolerance):
        violations.append("negative_dispatch")
    if np.any(np.abs(quantities - np.rint(quantities)) > tolerance):
        violations.append("noninteger_dispatch")
    if np.any(quantities.sum(axis=2) > np.asarray(args["route_capacity"]) + tolerance):
        violations.append("route_capacity")
    eligibility = np.broadcast_to(np.asarray(args["eligibility"], dtype=bool), quantities.shape)
    if np.any(quantities[~eligibility] > tolerance):
        violations.append("route_qualification")
    origins = list(dict.fromkeys(args["route_origin"]))
    origin_capacity = np.asarray(args["origin_capacity"])
    for index, origin in enumerate(origins):
        routes = [j for j, name in enumerate(args["route_origin"]) if name == origin]
        if np.any(quantities[:, routes].sum(axis=(1, 2)) > origin_capacity[:, index] + tolerance):
            violations.append("origin_capacity")
            break
    arrivals = np.asarray(args["pipeline_arrivals"], dtype=float).copy()
    leads = np.asarray(args["lead_times"], dtype=int)
    for period in range(T):
        for route in range(J):
            arrival = period + leads[period, route]
            if arrival < T:
                arrivals[arrival] += quantities[period, route]
            elif np.any(np.abs(quantities[period, route]) > tolerance):
                violations.append("receipt_beyond_horizon")
    net = np.asarray(args["initial_inventory"]) + np.cumsum(arrivals - demand, axis=0)
    inventory, backlog = np.maximum(net, 0.0), np.maximum(-net, 0.0)
    if np.any(backlog > tolerance):
        violations.append("hard_period_service")
    if np.any(inventory[-1] + tolerance < np.asarray(args["terminal_inventory"])):
        violations.append("terminal_inventory")
    for name, physical in (("inventory", inventory), ("backlog", backlog)):
        try:
            reported = np.asarray(plan[name], dtype=float)
        except (KeyError, TypeError, ValueError):
            reported = np.array([])
        if reported.shape != physical.shape or not np.isfinite(reported).all() or not np.allclose(
            reported, physical, atol=tolerance, rtol=0,
        ):
            violations.append(f"reported_{name}_inconsistent")
    transport_cost = float((quantities * np.asarray(args["unit_costs"])).sum())
    holding = float((inventory * np.asarray(args["holding_cost"])).sum())
    backlog_cost = float((backlog * np.asarray(args["backlog_cost"])).sum())
    emissions = float((quantities * np.asarray(args["unit_emissions"])).sum()
                      + (inventory * np.asarray(args["warehouse_emissions"])).sum())
    if carbon_cap is not None and emissions > carbon_cap + tolerance:
        violations.append("carbon_budget")
    return {
        "valid": not violations, "violations": sorted(set(violations)),
        "actual_total_cost": transport_cost + holding + backlog_cost,
        "actual_total_emissions": emissions,
        "actual_mean_inventory": float(inventory.sum(axis=1).mean()),
        "actual_mean_backlog": float(backlog.sum(axis=1).mean()),
        "actual_max_backlog": float(backlog.max()),
    }


class ToolWorkflowEnv:
    """One synthetic notice, one known order book, one simulated workflow.

    Policy access is restricted to ``observation``/``action_mask`` and tool
    results. The hidden reference is consulted only after a terminal action or
    budget exhaustion. Python object introspection is not a security boundary.
    """

    def __init__(
        self, case: dict[str, Any], base_config: dict[str, Any],
        committed_orders: Any, extractor: Callable[..., dict[str, Any]], *,
        extractor_name: str = "rules", carbon_cap: float | None = None,
        max_steps: int = 20, max_solver_calls: int = 2,
        initial_inventory: Any = None, step_cost: float = 0.01,
    ) -> None:
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        if type(max_solver_calls) is not int or max_solver_calls < 1:
            raise ValueError("max_solver_calls must be a positive integer")
        if not math.isfinite(step_cost) or step_cost < 0:
            raise ValueError("step_cost must be finite and nonnegative")
        if carbon_cap is not None and (not math.isfinite(carbon_cap) or carbon_cap < 0):
            raise ValueError("carbon_cap must be finite and nonnegative")
        if case.get("synthetic") is not True:
            raise ValueError("This public offline simulator accepts synthetic cases only")
        model_input = case["model_input"]
        if set(model_input) != {"text", "context"} or not isinstance(model_input["text"], str):
            raise ValueError("Only the public text/context inference payload is accepted")
        self._notice = copy.deepcopy(model_input)
        self._reference = normalize_output(case["reference"])
        self._base = copy.deepcopy(base_config)
        self._orders = np.asarray(committed_orders, dtype=float).copy()
        args, _ = planning_inputs(self._base, self._orders, initial=initial_inventory)
        if self._orders.shape[0] != self._base["horizon"]:
            raise ValueError("Known orders must match the planning horizon")
        if not np.isfinite(self._orders).all() or np.any(self._orders < 0):
            raise ValueError("Known orders must be finite and nonnegative")
        self._initial = np.asarray(args["initial_inventory"], dtype=float).copy()
        self._true_config = (
            compile_notice(self._base, self._reference)
            if self._reference["status"] == "ready" else None
        )
        self._extractor = extractor
        self.extractor_name = str(extractor_name)
        self._carbon_cap = carbon_cap
        self.max_steps = max_steps
        self.max_solver_calls = max_solver_calls
        self.step_cost = float(step_cost)
        self.reset()

    def reset(self) -> dict[str, Any]:
        self._inspected = False
        self._state_read = False
        self._extraction: Any = None
        self._extraction_attempted = False
        self._revision = 0
        self._compiled: dict[str, Any] | None = None
        self._validation_error: str | None = None
        self._plan: dict[str, Any] | None = None
        self._plan_revision: int | None = None
        self._audit: dict[str, Any] | None = None
        self._audit_revision: int | None = None
        self._clarification_requested = False
        self._handed_off = False
        self._committed: dict[str, Any] | None = None
        self._done = False
        self._terminal_reason: str | None = None
        self._steps = 0
        self._solver_calls = 0
        self._extractor_calls = 0
        self._trace: list[dict[str, Any]] = []
        self._timings: list[dict[str, Any]] = []
        return self.observation()

    @property
    def terminated(self) -> bool:
        return self._done

    def _flags(self) -> dict[str, Any]:
        return {
            "notice_inspected": self._inspected, "state_read": self._state_read,
            "extraction_attempted": self._extraction_attempted,
            "update_validated": self._compiled is not None,
            "plan_computed": self._plan is not None,
            "plan_audited": self._audit is not None,
            "audit_passed": self._audit is not None and self._audit["valid"],
            "clarification_requested": self._clarification_requested,
            "revision": self._revision,
        }

    def action_mask(self) -> dict[str, bool]:
        if self._done:
            return {tool: False for tool in TOOLS}
        raw_ready = isinstance(self._extraction, dict) and self._extraction.get("status") == "ready"
        current_plan = self._plan is not None and self._plan_revision == self._revision
        return {
            "inspect_notice": True,
            "extract_notice": self._inspected,
            "validate_update": self._extraction_attempted and raw_ready,
            "read_state": True,
            "solve_plan": self._compiled is not None and self._state_read
            and self._solver_calls < self.max_solver_calls,
            "audit_plan": current_plan,
            "commit_plan": current_plan and self._audit is not None
            and self._audit["valid"] and self._audit_revision == self._revision,
            "request_clarification": self._inspected,
            "safe_handoff": self._clarification_requested,
        }

    def available_actions(self) -> list[str]:
        return [tool for tool, allowed in self.action_mask().items() if allowed]

    def observation(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "scope": "synthetic ASML-inspired known committed orders and announced notice",
            "goal": "Compile supported notice changes and submit a validated feasible plan, or hand off unresolved information",
            "flags": self._flags(), "steps_used": self._steps,
            "steps_remaining": max(0, self.max_steps - self._steps),
            "solver_calls": self._solver_calls,
            "solver_calls_remaining": self.max_solver_calls - self._solver_calls,
            "action_mask": self.action_mask(), "terminated": self._done,
        }
        if self._inspected:
            result["notice"] = copy.deepcopy(self._notice)
        if self._state_read:
            result["known_state"] = {
                "base_config": copy.deepcopy(self._base),
                "committed_orders": self._orders.tolist(),
                "initial_inventory": self._initial.tolist(), "carbon_cap": self._carbon_cap,
            }
        if self._extraction_attempted:
            result["extraction"] = copy.deepcopy(self._extraction)
        if self._validation_error:
            result["validation_error"] = self._validation_error
        if self._plan is not None:
            result["plan_summary"] = {
                key: self._plan.get(key)
                for key in ("success", "optimal", "status", "total_cost", "total_emissions")
            }
        if self._audit is not None:
            result["visible_audit"] = copy.deepcopy(self._audit)
        if self._clarification_requested:
            result["clarification"] = {
                "mode": "offline_simulation_no_message_sent",
                "response": "Additional information is unavailable in this episode; human handoff is available",
            }
        return result

    def business_state_hash(self) -> str:
        """Hash mutable workflow data, excluding budgets, timing and hidden truth."""
        return _hash({
            "flags": self._flags(), "extraction": self._extraction,
            "compiled": self._compiled, "validation_error": self._validation_error,
            "plan": self._plan, "audit": self._audit,
            "committed": self._committed, "handed_off": self._handed_off,
        })

    def _invalidate_plan(self) -> None:
        self._plan = None
        self._plan_revision = None
        self._audit = None
        self._audit_revision = None

    def _execute(self, tool: str) -> dict[str, Any]:
        if tool == "inspect_notice":
            self._inspected = True
            return {"text_characters": len(self._notice["text"]),
                    "context_sha256": _hash(self._notice["context"])}
        if tool == "read_state":
            self._state_read = True
            return {"orders_sha256": _hash(self._orders), "config_sha256": _hash(self._base),
                    "horizon": int(self._orders.shape[0]), "sku_count": int(self._orders.shape[1])}
        if tool == "extract_notice":
            self._extractor_calls += 1
            self._extraction_attempted = True
            self._revision += 1
            self._compiled = None
            self._validation_error = None
            self._invalidate_plan()
            try:
                value = self._extractor(self._notice["text"], context=copy.deepcopy(self._notice["context"]))
                self._extraction = _plain(copy.deepcopy(value))
                # Non-JSON custom extractor values cannot enter observations/traces.
                _hash(self._extraction)
            except Exception as error:
                self._extraction = None
                self._validation_error = f"extractor_exception:{type(error).__name__}"
            return {"extraction_sha256": _hash(self._extraction),
                    "reported_status": self._extraction.get("status") if isinstance(self._extraction, dict) else None,
                    "error": self._validation_error}
        if tool == "validate_update":
            try:
                normalized = normalize_output(self._extraction)
                compiled = compile_notice(self._base, normalized)
            except (KeyError, TypeError, ValueError) as error:
                self._validation_error = f"validation_failed:{type(error).__name__}"
                return {"valid": False, "error": self._validation_error}
            self._compiled = compiled
            self._validation_error = None
            self._invalidate_plan()
            return {"valid": True, "compiled_config_sha256": _hash(compiled)}
        if tool == "solve_plan":
            self._solver_calls += 1
            started = time.perf_counter()
            result, _ = solve_policy(
                self._compiled, self._orders, "cost_only", carbon_cap=self._carbon_cap,
                initial=self._initial,
            )
            elapsed = time.perf_counter() - started
            self._timings.append({"step": self._steps, "tool": tool, "solver_wall_seconds": elapsed})
            self._plan = _plain({key: value for key, value in result.items() if key != "solve_seconds"})
            self._plan_revision = self._revision
            self._audit = None
            self._audit_revision = None
            return {key: self._plan.get(key) for key in ("success", "optimal", "status", "total_cost", "total_emissions")}
        if tool == "audit_plan":
            self._audit = audit_plan_feasibility(
                self._compiled, self._orders, self._plan,
                initial_inventory=self._initial, carbon_cap=self._carbon_cap,
            )
            self._audit_revision = self._revision
            return copy.deepcopy(self._audit)
        if tool == "commit_plan":
            self._committed = copy.deepcopy(self._plan)
            self._done = True
            self._terminal_reason = "plan_committed"
            return {"committed": True, "plan_sha256": _hash(self._committed)}
        if tool == "request_clarification":
            self._clarification_requested = True
            return {"mode": "offline_simulation_no_message_sent", "additional_information_available": False}
        if tool == "safe_handoff":
            self._handed_off = True
            self._done = True
            self._terminal_reason = "safe_handoff"
            return {"handed_off": True, "shipment_committed": False}
        raise ValueError("Unknown tool")

    def step(self, action: str | dict[str, Any]) -> dict[str, Any]:
        if self._done:
            raise RuntimeError("Episode has terminated; reset before another action")
        mask = self.action_mask()
        observation_before = self.observation()
        before_hash = self.business_state_hash()
        tool = action if isinstance(action, str) else (
            action.get("tool") if isinstance(action, dict) and set(action) == {"tool"} else None
        )
        valid = isinstance(tool, str) and mask.get(tool, False)
        self._steps += 1
        components = {"tool_cost": -self.step_cost, "invalid_action": 0.0, "terminal": 0.0}
        if valid:
            response = self._execute(tool)
        else:
            components["invalid_action"] = -0.2
            response = {"error": "unknown_or_structurally_unavailable_action"}
        if not self._done and self._steps >= self.max_steps:
            self._done = True
            self._terminal_reason = "step_budget_exhausted"
        if self._done:
            evaluation = self.terminal_evaluation()
            components["terminal"] = 1.0 if evaluation["task_success"] else -1.0
        reward = sum(components.values())
        observation_after = self.observation()
        entry = {
            "step": self._steps, "action": tool if isinstance(tool, str) else "<malformed>",
            "action_mask": mask, "valid_action": bool(valid),
            "observation_before_sha256": _hash(observation_before),
            "observation_after_sha256": _hash(observation_after),
            "business_state_before_sha256": before_hash,
            "business_state_after_sha256": self.business_state_hash(),
            "response_summary": response, "reward_components": components,
            "reward": reward, "solver_calls": self._solver_calls,
            "extractor_calls": self._extractor_calls, "terminated": self._done,
        }
        self._trace.append(_plain(entry))
        info = {"valid_action": bool(valid), "response_summary": copy.deepcopy(response)}
        if self._done:
            info["evaluation"] = evaluation
        return {"observation": observation_after, "reward": reward,
                "terminated": self._done, "info": info}

    def terminal_evaluation(self) -> dict[str, Any]:
        if not self._done:
            raise RuntimeError("Hidden reference evaluation is available only after termination")
        try:
            normalized = normalize_output(self._extraction)
        except ValueError:
            normalized = None
        ready = self._reference["status"] == "ready"
        correct_handoff = bool(self._handed_off and not ready)
        unnecessary_handoff = bool(self._handed_off and ready)
        parameters_match = bool(
            ready and self._compiled is not None and _hash(self._compiled) == _hash(self._true_config)
        )
        true_audit = None
        if self._committed is not None and self._true_config is not None:
            true_audit = audit_plan_feasibility(
                self._true_config, self._orders, self._committed,
                initial_inventory=self._initial, carbon_cap=self._carbon_cap,
            )
        shipping = bool(true_audit is not None and true_audit["valid"])
        workflow_correct = bool((shipping and parameters_match) or correct_handoff)
        return {
            "task_success": workflow_correct, "successful_shipping": shipping,
            "correct_handoff": correct_handoff, "unnecessary_handoff": unnecessary_handoff,
            "reference_status": self._reference["status"],
            "extraction_exact_match": normalized == self._reference,
            "compiled_parameters_match": parameters_match,
            "true_feasibility": true_audit, "terminal_reason": self._terminal_reason,
            "steps": self._steps, "solver_calls": self._solver_calls,
            "extractor_calls": self._extractor_calls,
            "gate_requires_research": True,
            "gate_reason": "Fixed workflow solves sequencing; no substantive learned tool-selection advantage is established",
            "reward_scope": "Workflow completion and tool costs; not an optimized business-cost reward",
        }

    def trace(self) -> list[dict[str, Any]]:
        """Deterministic compact trace; excludes runtime and hidden reference."""
        return copy.deepcopy(self._trace)

    def runtime_metadata(self) -> dict[str, Any]:
        return {"solver_wall_seconds": sum(row["solver_wall_seconds"] for row in self._timings),
                "solver_timings": copy.deepcopy(self._timings)}


def run_fixed_workflow(env: ToolWorkflowEnv) -> dict[str, Any]:
    """Strong sequencing baseline that selects actions only from public inputs.

    It does not know whether the injected extractor is right. It deliberately
    remains capable of committing an incorrect but visibly valid interpretation,
    which the independent terminal evaluator can then detect.
    """
    while not env.terminated:
        observation = env.observation()
        flags = observation["flags"]
        if not flags["notice_inspected"]:
            action = "inspect_notice"
        elif not flags["extraction_attempted"]:
            action = "extract_notice"
        elif flags["clarification_requested"]:
            action = "safe_handoff"
        elif observation.get("validation_error"):
            action = "request_clarification"
        elif not isinstance(observation.get("extraction"), dict) or observation["extraction"].get("status") != "ready":
            action = "request_clarification"
        elif not flags["update_validated"]:
            action = "validate_update"
        elif not flags["state_read"]:
            action = "read_state"
        elif not flags["plan_computed"]:
            action = "solve_plan"
        elif not flags["plan_audited"]:
            action = "audit_plan"
        elif flags["audit_passed"]:
            action = "commit_plan"
        else:
            action = "request_clarification"
        if not observation["action_mask"].get(action, False):
            # A depleted budget must fail or hand off visibly; no hidden repair.
            action = "request_clarification" if observation["action_mask"].get("request_clarification") else "inspect_notice"
        env.step(action)
    return {"evaluation": env.terminal_evaluation(), "trace": env.trace(),
            "runtime": env.runtime_metadata()}
