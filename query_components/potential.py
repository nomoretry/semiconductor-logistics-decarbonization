"""Frozen public-state prediction of immediate commitment cost, train only."""
from __future__ import annotations

import numpy as np
from query_policy.features import encode


def fit(tasks, teachers, cfg, reward_scale):
    if not tasks or any(t["split"] != "train" for t in tasks):
        raise ValueError("potential_accepts_training_contexts_only")
    by_id = {t["id"]: t for t in teachers}
    x, y, weights = [], [], []
    for task in tasks:
        teacher = by_id[task["id"]]
        if teacher["split"] != "train":
            raise ValueError("potential_teacher_split")
        states = teacher["states"]
        for state in states:
            x.append(encode(task["public"], state["history"])[0][0, :20])
            y.append(state["q_values"][0] / reward_scale)
            weights.append(1.0 / len(states))
    x, y, w = np.asarray(x), np.asarray(y), np.asarray(weights)
    w /= w.sum()
    mean = np.sum(x * w[:, None], axis=0)
    scale = np.sqrt(np.sum((x - mean) ** 2 * w[:, None], axis=0))
    scale = np.where(scale > 1e-12, scale, 1.0)
    design = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    penalty = np.eye(21) * cfg["potential_ridge"]; penalty[0, 0] = 0.0
    coef = np.linalg.solve(design.T @ (w[:, None] * design) + penalty, design.T @ (w * y))
    prediction = design @ coef
    return {"kind": "train_only_ridge_commit_cost", "train_ids": [t["id"] for t in tasks],
            "states": len(y), "mean": mean.tolist(), "scale": scale.tolist(),
            "coefficients": coef.tolist(), "reward_scale": reward_scale,
            "upper": float(max(y) * cfg["potential_clip_training_max_multiplier"]),
            "weighted_training_rmse": float(np.sqrt(np.sum(w * (prediction - y) ** 2))),
            "target": "immediate_commit_cost_not_optimal_query_value_or_success_probability"}


def phi(public, history, fitted, terminal=False):
    if terminal or fitted is None:
        return 0.0
    x = encode(public, history)[0][0, :20]
    row = np.r_[1.0, (x - np.asarray(fitted["mean"])) / np.asarray(fitted["scale"])]
    prediction = float(row @ np.asarray(fitted["coefficients"]))
    if not np.isfinite(prediction):
        raise ValueError("nonfinite_potential")
    return -float(np.clip(prediction, 0.0, fitted["upper"]))
