"""Small NumPy candidate scorer; analytic gradients checked by finite differences."""
from __future__ import annotations

import numpy as np


def initialize(seed, width=37, hidden=32):
    rng = np.random.default_rng(seed)
    return {"w": rng.normal(0, 1/np.sqrt(width), (width, hidden)),
            "b": np.zeros(hidden), "v": rng.normal(0, .01, hidden)}


def probabilities(parameters, x, mask):
    if x.shape[:-1] != mask.shape or mask.dtype != bool or not mask.any(axis=-1).all():
        raise ValueError("candidate_mask")
    hidden = np.tanh(x @ parameters["w"] + parameters["b"])
    logits = hidden @ parameters["v"]
    if not np.isfinite(logits).all():
        raise ValueError("nonfinite_logits")
    logits = np.where(mask, logits, -np.inf)
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True), hidden, logits


def loss_gradient(parameters, x, mask, positives, weights):
    if (positives.dtype != bool or positives.shape != mask.shape
            or not positives.any(axis=1).all() or (positives & ~mask).any()):
        raise ValueError("positive_mask")
    if weights.shape != (len(x),) or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("sample_weights")
    probs, hidden, logits = probabilities(parameters, x, mask)
    positive_logits = np.where(positives, logits, -np.inf)
    pos_shift = positive_logits - positive_logits.max(axis=1, keepdims=True)
    pos_exp = np.exp(pos_shift)
    conditional = pos_exp / pos_exp.sum(axis=1, keepdims=True)
    def lse(a):
        top = a.max(axis=1)
        return top + np.log(np.exp(a-top[:, None]).sum(axis=1))
    losses = lse(logits) - lse(positive_logits)
    # Weights have global mean one; random minibatches estimate the same objective.
    gradient = (probs - conditional) * (weights/len(x))[:, None]
    delta = gradient[..., None] * parameters["v"] * (1-hidden**2)
    gradients = {"w": np.einsum("baf,bah->fh", x, delta),
                 "b": delta.sum(axis=(0,1)), "v": np.einsum("ba,bah->h", gradient, hidden)}
    return float(np.mean(weights*losses)), gradients


def metrics(parameters, batch):
    x, mask, positive, weights = batch
    loss, _ = loss_gradient(parameters, x, mask, positive, weights)
    probs, _, _ = probabilities(parameters, x, mask)
    pred = probs.argmax(axis=1)
    return {"set_nll": loss, "positive_accuracy": float(np.average(positive[np.arange(len(x)), pred], weights=weights))}


def train(train_batch, dev_batch, cfg):
    p = initialize(cfg["training_seed"], hidden=cfg["hidden"])
    initial = {k: v.copy() for k, v in p.items()}
    best = {k: v.copy() for k, v in p.items()}
    m, v = ({k: np.zeros_like(a) for k, a in p.items()} for _ in range(2))
    rng = np.random.default_rng(cfg["training_seed"])
    log = [{"epoch": 0, "updates": 0, "train": metrics(p, train_batch), "dev": metrics(p, dev_batch)}]
    best_loss, best_epoch, updates = log[0]["dev"]["set_nll"], 0, 0
    for epoch in range(1, cfg["epochs"]+1):
        order = rng.permutation(len(train_batch[0]))
        for start in range(0, len(order), cfg["batch_size"]):
            idx = order[start:start+cfg["batch_size"]]
            _, grads = loss_gradient(p, *(a[idx] for a in train_batch))
            norm = np.sqrt(sum(float((g*g).sum()) for g in grads.values()))
            if not np.isfinite(norm):
                raise ValueError("nonfinite_gradient")
            updates += 1
            for key in p:
                g = grads[key] / max(1., norm)
                m[key] = .9*m[key] + .1*g
                v[key] = .999*v[key] + .001*g*g
                p[key] -= cfg["learning_rate"]*(m[key]/(1-.9**updates))/(np.sqrt(v[key]/(1-.999**updates))+1e-8)
        row = {"epoch": epoch, "updates": updates, "train": metrics(p, train_batch), "dev": metrics(p, dev_batch)}
        log.append(row)
        if row["dev"]["set_nll"] < best_loss - 1e-12:
            best_loss, best_epoch = row["dev"]["set_nll"], epoch
            best = {k: a.copy() for k, a in p.items()}
    delta = np.sqrt(sum(float(((best[k]-initial[k])**2).sum()) for k in p))
    return initial, best, {"epochs": log, "selected_epoch": best_epoch, "updates": updates,
                           "selected_parameter_l2_delta": float(delta)}


def serialize(parameters):
    return {key: value.tolist() for key, value in parameters.items()}


def deserialize(payload, hidden):
    if set(payload) != {"w", "b", "v"}:
        raise ValueError("parameter_keys")
    result = {key: np.asarray(value, dtype=np.float64) for key, value in payload.items()}
    if (result["w"].shape != (37,hidden) or result["b"].shape != (hidden,)
            or result["v"].shape != (hidden,) or not all(np.isfinite(x).all() for x in result.values())):
        raise ValueError("parameter_shape_or_finiteness")
    return result
