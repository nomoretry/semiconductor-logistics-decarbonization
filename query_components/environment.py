"""Independent environment legality, bounded rejection and economic scoring."""
from __future__ import annotations

import numpy as np
from query_policy.features import encode
from query_policy.model import probabilities
from query_policy.solver import Planner
from .potential import phi


def inputs(public, history, action_mask):
    x, legal = encode(public, history)
    # Only real candidates exist here; training padding is always masked later.
    return x, legal, legal.copy() if action_mask else np.ones_like(legal)


def step(model, history, action, answer, cfg, fitted):
    h = tuple(history); k = model.k
    if type(action) is not int or not 0 <= action <= k:
        raise ValueError("candidate_index")
    legal = model.legal(h)
    invalid = action != 0 and action - 1 not in legal
    done = action == 0 or invalid
    nxt = h
    if done:
        if answer is not None:
            raise ValueError("terminal_has_no_query_answer")
        cost = model.terminal(h)[0] + cfg["invalid_action_penalty"] * invalid
    else:
        if type(answer) is not int or answer not in (0, 1):
            raise ValueError("binary_answer_required")
        cost = model.c["query_fees"][action - 1]
        nxt = list(h); nxt[action - 1] = answer; nxt = tuple(nxt)
    before = phi(model.c, h, fitted)
    after = phi(model.c, nxt, fitted, terminal=done)
    base = -cost / cfg["reward_scale"]
    bonus = cfg["gamma"] * after - before
    return {"next_history": list(nxt), "done": done, "invalid": invalid,
            "base_reward": base, "phi_before": before, "phi_after": after,
            "shaping_reward": bonus, "reward": base + bonus}


def tree(public, actor, action_mask, penalty, backend=None, detailed=True):
    model = Planner(public) if backend is None else backend
    nodes = []
    def visit(h, reach):
        x, legal, policy_mask = inputs(public, h, action_mask)
        if legal.tolist() != [True, *[i in model.legal(h) for i in range(model.k)]]:
            raise ValueError("independent_legality_mismatch")
        probs = probabilities(actor, x, policy_mask)[0]
        action = int(probs.argmax())
        invalid = not bool(legal[action]); done = action == 0 or invalid
        node = {"history": list(h), "reach": reach, "action": action,
                "legal": legal.tolist(), "policy_mask": policy_mask.tolist(),
                "probabilities": probs.tolist(), "invalid": invalid,
                "commit_plan": None, "terminal_cost": None}
        if detailed: nodes.append(node)
        if done:
            cost, plan = model._terminal(h) if detailed else model.terminal(h)
            node.update(commit_plan=plan, terminal_cost=cost,
                        rejection_penalty=penalty if invalid else 0.0)
            return np.array([cost + penalty * invalid, cost, 0., 1., float(invalid)])
        branches = [visit(nxt, reach * p) for p, nxt in model.branch(h, action - 1)]
        p = public["prior"][action - 1]
        result = (1 - p) * branches[0] + p * branches[1]
        fee = public["query_fees"][action - 1]
        result += [fee, fee, 1., 1., 0.]
        return result
    values = visit((-1,) * model.k, 1.)
    return {"expected_loss": float(values[0]), "expected_economic_cost": float(values[1]),
            "expected_queries": float(values[2]), "expected_decisions": float(values[3]),
            "rejection_probability": float(values[4]), "expected_milp_calls": 1., "nodes": nodes}
