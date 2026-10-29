"""Auditable finite-horizon inventory/freight planning with SciPy/HiGHS.

The optimizer receives a *forecast/scenario*, never a simulator or a hidden
future-demand stream. Orders dispatched in period t on route j arrive at
t + lead_times[t, j]. Only future dispatches incur freight cost/emissions;
the transport of the supplied initial pipeline is already committed/sunk.

Quantities are SKU units, route capacities are total SKU units per period,
costs use one common currency, and emissions are kg CO2e. Production, product
embodied carbon, cargo damage, vehicle manufacture and fixed warehouse energy
are outside this first-stage logistics model. Warehouse coefficients represent
only inventory-dependent allocated emissions per unit per period.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


def _array(value: Any, shape: tuple[int, ...], name: str,
           *, allow_infinite: bool = False, nonnegative: bool = True) -> np.ndarray:
    """Broadcast documented scalar/vector inputs without silently changing units."""
    try:
        result = np.broadcast_to(np.asarray(value, dtype=float), shape).copy()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must broadcast to shape {shape}") from exc
    if np.isnan(result).any() or (not allow_infinite and not np.isfinite(result).all()):
        raise ValueError(f"{name} must contain finite values")
    if np.isneginf(result).any() or (nonnegative and (result < 0).any()):
        raise ValueError(f"{name} must be nonnegative")
    return result


def solve_plan(
    demand,
    initial_inventory,
    pipeline_arrivals,
    lead_times,
    unit_costs,
    unit_emissions,
    holding_cost,
    backlog_cost,
    route_capacity,
    warehouse_emissions,
    carbon_cap=None,
    terminal_inventory=None,
    integer=True,
    time_limit=5.0,
    *,
    initial_backlog=None,
    mip_rel_gap=1e-4,
    backlog_limit=None,
    eligibility=None,
    route_origin=None,
    origin_capacity=None,
) -> dict[str, Any]:
    """Solve one forecast-horizon inventory/freight MILP (or its LP relaxation).

    Parameters
    ----------
    demand : array (T, K)
        Nonnegative SKU demand. Fractional forecasts are permitted even when
        purchase quantities are integer; physical states then remain real.
    initial_inventory : array (K,)
        Beginning net inventory I-B; negative values denote existing backlog.
        Alternatively pass physical I here and ``initial_backlog`` separately.
    pipeline_arrivals : array (T, K)
        Previously dispatched, committed receipts by arrival period.
    lead_times : array (J,) or (T, J)
        Positive integer route leads, indexed by *dispatch* period.
    unit_costs, unit_emissions : array (J, K) or (T, J, K)
        Freight cost / kg CO2e per newly dispatched SKU unit.
    holding_cost, backlog_cost, warehouse_emissions : array (K,)
        Per-unit/end-period coefficients. Scalars also broadcast.
    route_capacity : array (J,) or (T, J)
        Maximum total SKU units per route/dispatch period; +inf is permitted.
    carbon_cap : float or None
        Hard budget for new freight plus inventory-dependent warehousing over
        this horizon. It excludes emissions of already committed transport.
    terminal_inventory : array (K,) or None
        Optional physical end-inventory lower bound. Final backlog is ALWAYS
        zero, so unserved demand cannot manufacture apparent decarbonization.
    integer : bool
        True uses integer order quantities; False is an explicitly labeled LP
        relaxation, not an integer approximation silently rounded afterwards.
    backlog_limit : scalar, array (K,) or (T, K), optional
        Upper bound on each end-period backlog. Set to zero for identical hard
        service in every period; None permits temporary backlogs.
    eligibility : array (J, K) or (T, J, K), optional
        Boolean/0-1 route-SKU qualification. False forbids that dispatch.
    route_origin : array (J,), optional
        Origin group ID/label for each route. Supply with origin_capacity;
        origins are ordered by first appearance of their labels in this list.
    origin_capacity : array (O,) or (T, O), optional
        Joint dispatch capacity across all routes (e.g. air and ocean) belonging
        to each origin. This is additional to per-route capacities.

    Returns
    -------
    dict
        On a feasible incumbent: orders(T,J,K), inventory/backlog(T,K),
        arrivals(T,K), cost/emission decompositions and solver metadata.
        ``success`` means a validated feasible plan exists; ``optimal`` means
        HiGHS terminated normally within its specified MIP-gap tolerance.
        A time-limited feasible incumbent can have success=True, optimal=False.
        Infeasible/no-incumbent results contain None arrays and None totals.
        There is no fabricated emergency action or carbon-budget relaxation.
    """
    started = time.perf_counter()
    demand = np.asarray(demand, dtype=float)
    if demand.ndim != 2 or not all(demand.shape):
        raise ValueError("demand must have nonempty shape (T, K)")
    if not np.isfinite(demand).all() or (demand < 0).any():
        raise ValueError("demand must contain finite nonnegative values")
    T, K = demand.shape
    lead = np.asarray(lead_times, dtype=float)
    if lead.ndim not in (1, 2) or lead.shape[-1] == 0:
        raise ValueError("lead_times must have shape (J,) or (T, J)")
    J = lead.shape[-1]
    lead = _array(lead, (T, J), "lead_times")
    if (lead < 1).any() or not np.equal(lead, np.floor(lead)).all():
        raise ValueError("lead_times must be positive integers")
    lead = lead.astype(int)
    initial = _array(initial_inventory, (K,), "initial_inventory", nonnegative=False)
    if initial_backlog is not None:
        initial -= _array(initial_backlog, (K,), "initial_backlog")
    pipeline = _array(pipeline_arrivals, (T, K), "pipeline_arrivals")
    cost = _array(unit_costs, (T, J, K), "unit_costs")
    freight_ef = _array(unit_emissions, (T, J, K), "unit_emissions")
    hold = _array(holding_cost, (K,), "holding_cost")
    penalty = _array(backlog_cost, (K,), "backlog_cost")
    warehouse_ef = _array(warehouse_emissions, (K,), "warehouse_emissions")
    capacity = _array(route_capacity, (T, J), "route_capacity", allow_infinite=True)
    terminal = np.zeros(K) if terminal_inventory is None else _array(
        terminal_inventory, (K,), "terminal_inventory")
    backlog_maximum = None if backlog_limit is None else _array(
        backlog_limit, (T, K), "backlog_limit", allow_infinite=True)
    eligible = np.ones((T, J, K), dtype=bool)
    if eligibility is not None:
        eligibility_values = _array(eligibility, (T, J, K), "eligibility")
        if not np.isin(eligibility_values, [0, 1]).all():
            raise ValueError("eligibility must contain only booleans/0-1 values")
        eligible = eligibility_values.astype(bool)
    groups, group_routes, origin_maximum = [], [], None
    if (route_origin is None) != (origin_capacity is None):
        raise ValueError("Supply route_origin and origin_capacity together")
    if route_origin is not None:
        origins = np.asarray(route_origin, dtype=object)
        if origins.shape != (J,):
            raise ValueError(f"route_origin must have shape {(J,)}")
        try:
            groups = list(dict.fromkeys(origins.tolist()))
        except TypeError as exc:
            raise ValueError("route_origin labels must be hashable") from exc
        if any(g is None or (isinstance(g, (int, float)) and not np.isfinite(g)) for g in groups):
            raise ValueError("route_origin labels must be nonempty finite IDs")
        group_routes = [np.flatnonzero(origins == group) for group in groups]
        origin_maximum = _array(origin_capacity, (T, len(groups)), "origin_capacity",
                                allow_infinite=True)
    if carbon_cap is not None and (not np.isscalar(carbon_cap)
            or not np.isfinite(carbon_cap) or carbon_cap < 0):
        raise ValueError("carbon_cap must be finite and nonnegative, or None")
    if not isinstance(integer, (bool, np.bool_)):
        raise ValueError("integer must be a boolean")
    if not np.isscalar(time_limit) or not np.isfinite(time_limit) or time_limit <= 0:
        raise ValueError("time_limit must be finite and positive")
    if not np.isscalar(mip_rel_gap) or not np.isfinite(mip_rel_gap) or mip_rel_gap < 0:
        raise ValueError("mip_rel_gap must be finite and nonnegative")

    n_q, n_state = T * J * K, T * K
    n_variables = n_q + 2 * n_state
    q_index = np.arange(n_q).reshape(T, J, K)
    inventory_index = np.arange(n_q, n_q + n_state).reshape(T, K)
    backlog_index = np.arange(n_q + n_state, n_variables).reshape(T, K)
    objective = np.concatenate((cost.ravel(), np.tile(hold, T), np.tile(penalty, T)))
    lower, upper = np.zeros(n_variables), np.full(n_variables, np.inf)
    if backlog_maximum is not None:
        upper[backlog_index] = backlog_maximum
    upper[backlog_index[-1]] = 0.0
    upper[q_index[~eligible]] = 0.0
    lower[inventory_index[-1]] = terminal
    integrality = np.zeros(n_variables, dtype=np.uint8)
    if integer:
        integrality[:n_q] = 1

    # Build sparse rows for I_t - B_t - I_(t-1) + B_(t-1)
    # - arrivals_from_new_dispatches = committed_receipts_t - demand_t.
    rows, columns, coefficients, lo, hi = [], [], [], [], []

    def append(row_number, indices, values):
        rows.extend([row_number] * len(indices))
        columns.extend(np.asarray(indices).ravel().tolist())
        coefficients.extend(np.asarray(values).ravel().tolist())

    for t in range(T):
        for k in range(K):
            row = t * K + k
            append(row, [inventory_index[t, k], backlog_index[t, k]], [1.0, -1.0])
            if t:
                append(row, [inventory_index[t - 1, k], backlog_index[t - 1, k]], [-1.0, 1.0])
            rhs = pipeline[t, k] - demand[t, k] + (initial[k] if t == 0 else 0.0)
            lo.append(rhs)
            hi.append(rhs)
    for t in range(T):
        for j in range(J):
            arrival = t + lead[t, j]
            if arrival >= T:
                upper[q_index[t, j]] = 0.0
            else:
                for k in range(K):
                    append(arrival * K + k, [q_index[t, j, k]], [-1.0])
            if np.isfinite(capacity[t, j]):
                row = len(lo)
                append(row, q_index[t, j], np.ones(K))
                lo.append(-np.inf)
                hi.append(capacity[t, j])
    if origin_maximum is not None:
        for t in range(T):
            for origin_index, route_indices in enumerate(group_routes):
                if np.isfinite(origin_maximum[t, origin_index]):
                    indices = q_index[t, route_indices].ravel()
                    append(len(lo), indices, np.ones(len(indices)))
                    lo.append(-np.inf)
                    hi.append(origin_maximum[t, origin_index])
    if carbon_cap is not None:
        row = len(lo)
        append(row, q_index.ravel(), freight_ef.ravel())
        append(row, inventory_index.ravel(), np.tile(warehouse_ef, T))
        lo.append(-np.inf)
        hi.append(float(carbon_cap))
    matrix = coo_matrix((coefficients, (rows, columns)), shape=(len(lo), n_variables)).tocsc()
    result = milp(objective, integrality=integrality, bounds=Bounds(lower, upper),
                  constraints=LinearConstraint(matrix, np.asarray(lo), np.asarray(hi)),
                  options={"time_limit": float(time_limit), "mip_rel_gap": float(mip_rel_gap),
                           "disp": False})
    gap = getattr(result, "mip_gap", None)
    gap = float(gap) if gap is not None and np.isfinite(gap) else None
    metadata = {"success": False, "optimal": False, "status": int(result.status),
                "solver_message": str(result.message), "mip_gap": gap,
                "optimality_gap": gap, "solver": "scipy.optimize.milp / HiGHS",
                "integer_orders": bool(integer), "orders": None,
                "inventory": None, "backlog": None, "arrivals": None,
                "total_cost": None, "total_emissions": None,
                "transport_cost": None, "holding_cost": None, "backlog_cost": None,
                "transport_emissions": None, "warehouse_emissions": None,
                "origin_order": groups,
                "solve_seconds": time.perf_counter() - started}
    if result.x is None or not np.isfinite(result.x).all():
        return metadata

    orders = np.maximum(result.x[:n_q].reshape(T, J, K), 0.0)
    if integer:
        if np.max(np.abs(orders - np.rint(orders))) > 1e-4:
            metadata["solver_message"] += "; incumbent rejected: noninteger orders"
            return metadata
        orders = np.rint(orders).astype(np.int64)
    receipts = pipeline.copy()
    for t in range(T):
        for j in range(J):
            arrival = t + lead[t, j]
            if arrival < T:
                receipts[arrival] += orders[t, j]
            elif np.any(orders[t, j] > 1e-6):
                metadata["solver_message"] += "; incumbent rejected: receipt beyond horizon"
                return metadata
    net = initial + np.cumsum(receipts - demand, axis=0)
    # Net states have unique physical positive/negative parts. This also removes
    # any zero-cost degeneracy in the solver's redundant I/B representation.
    inventory, backlog = np.maximum(net, 0.0), np.maximum(-net, 0.0)
    transport_cost = float(np.sum(orders * cost))
    holding_total = float(np.sum(inventory * hold))
    backlog_total = float(np.sum(backlog * penalty))
    freight_total = float(np.sum(orders * freight_ef))
    warehouse_total = float(np.sum(inventory * warehouse_ef))
    tolerance = 1e-5
    origin_violation = origin_maximum is not None and any(
        np.any(orders[:, route_indices].sum(axis=(1, 2)) > origin_maximum[:, origin_index] + tolerance)
        for origin_index, route_indices in enumerate(group_routes))
    if (np.any(orders.sum(axis=2) > capacity + tolerance)
            or np.any(orders[~eligible] > tolerance)
            or origin_violation
            or (backlog_maximum is not None and np.any(backlog > backlog_maximum + tolerance))
            or np.any(backlog[-1] > tolerance)
            or np.any(inventory[-1] + tolerance < terminal)
            or (carbon_cap is not None and freight_total + warehouse_total > carbon_cap + tolerance)):
        metadata["solver_message"] += "; incumbent rejected by independent feasibility check"
        return metadata
    metadata.update({"success": True, "optimal": bool(result.status == 0),
                     "orders": orders, "inventory": inventory, "backlog": backlog,
                     "arrivals": receipts,
                     "transport_cost": transport_cost, "holding_cost": holding_total,
                     "backlog_cost": backlog_total,
                     "total_cost": transport_cost + holding_total + backlog_total,
                     "transport_emissions": freight_total, "warehouse_emissions": warehouse_total,
                     "total_emissions": freight_total + warehouse_total,
                     "solve_seconds": time.perf_counter() - started})
    return metadata
