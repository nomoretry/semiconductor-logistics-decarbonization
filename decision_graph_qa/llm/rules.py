"""Registered wording of the v2 statements. This module imports nothing, so that a reader of the prompt text
shares only the words with the code that writes them.
"""

RULES = """Planning rules

Names starting with "public." are fields of the public parameters. The other names are state fields listed below or are defined here. Every index starts at 0. i is a SKU and j is a route.

Window: h = min(public.horizon, public.periods - t). Offset u = 0, ..., h-1 stands for period t+u.

Plan: x[u][i][j] is a nonnegative integer, the units of SKU i dispatched on route j at offset u. One plan is fixed now for all demand scenarios and does not react to demand. The current dispatch is x[0].

Order of events at offset u:
1. Receipts arrive: pipeline[t+u][i] plus every x[v][i][j] with v + public.lead[j] = u. Receipts due in the current period (offset 0) are already counted in stock and backlog.
2. The dispatch x[u] leaves.
3. The demand of offset u occurs.

Net inventory: in each scenario, SKU i starts at stock[i] - backlog[i]. Receipts add to it and demand subtracts from it, offset by offset. A negative value is unfilled demand that later receipts fill. N[u][i] is the net inventory after the demand of offset u.

Kilograms and emissions: the dispatch x[u] puts the sum over i of public.mass[i] * x[u][i][j] kilograms on route j, and emits the sum over i and j of public.mass[i] * public.emissions[j] * x[u][i][j]. Both are whole numbers.

Cost of a plan = dispatch cost + mean inventory cost over the scenarios.
- Dispatch cost: sum over u, i and j of x[u][i][j] * public.mass[i] * (public.freight[j] + public.carbon_price * public.emissions[j]).
- Inventory cost of a scenario: sum over u and i of public.holding[i] * max(N[u][i], 0) + public.backlog[i] * max(-N[u][i], 0). In the last period of the episode (t+u = public.periods - 1), add public.terminal_backlog[i] * max(-N[u][i], 0).
Nothing else is charged. Inventory, backlog and pipeline arrivals after the window have no further cost or value.

Constraints:
- The kilograms on route j at offset u are at most public.capacity[j], for every u and j.
- x[u][i][j] = 0 whenever u + public.lead[j] >= h, so every dispatch arrives inside the window.
- The emissions of all dispatches in the window add up to at most carbon_remaining * h / (public.periods - t).

An optimal plan has the lowest cost among all plans that satisfy the constraints. If several plans share the lowest cost, each of them is optimal.

The demand scenarios listed below are the only demand in this cost, and they are equally likely. They replace any draw with public.scenario_seed. The forecast and the past demand do not enter the cost."""

SCENARIO_LABEL = "Demand scenarios (scenario, offset, SKU)"
ANSWERED = ("Questions already answered about this decision. The answers are correct, and those about an optimal plan "
            "describe one and the same optimal plan.")
