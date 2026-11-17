"""Common-shock scenarios built from the observation only.

A policy sees the environment observation and nothing else: no task id, process label,
demand seed or hidden factor. Random numbers depend on public seeds, the period and the
tree node, never on the realized path.
"""
from itertools import combinations, product

import numpy as np
from scipy.stats import norm, poisson

from rolling_inventory.environment import seasonal

HIDDEN_KEYS = ('id', 'profile', 'seed', 'demand', 'split')


def one_step_forecasts(public, history):
    """Forecasts available before each past period; identical to Environment.observe()."""
    level = np.array(public['base_mean'], dtype=float); alpha = public['forecast_alpha']; out = []
    for t, d in enumerate(history):
        out.append(np.maximum(.05, level*seasonal(t)))
        level = (1-alpha)*level + alpha*np.asarray(d)/seasonal(t)
    return out


def residual_products(public, history):
    """Same-period cross-SKU products of standardized residuals; mean v when Var(F)=v."""
    values = []
    for forecast, demand in zip(one_step_forecasts(public, history), history):
        r = (np.asarray(demand)-forecast)/forecast
        values += [float(r[i]*r[j]) for i, j in combinations(range(len(r)), 2)]
    return values


def fit_common_variance(tasks, cap):
    """Pooled estimate on fitting paths, which are never used for policy evaluation."""
    values = [x for task in tasks for x in residual_products(task['public'], task['demand'])]
    return float(np.clip(np.mean(values), 0., cap)), len(values)


def common_variance(obs, fitted, strength, cap):
    """History-conditioned v: fitted value as `strength` pseudo-observations plus own past."""
    values = residual_products(obs['public'], obs['history'])
    return float(np.clip((strength*fitted+sum(values))/(strength+len(values)), 0., cap))


def check_observation(obs):
    leaked = [k for k in HIDDEN_KEYS if k in obs or k in obs['public']]
    if leaked:
        raise ValueError(f'hidden_fields_in_observation:{leaked}')


def window(obs):
    return min(obs['public']['horizon'], len(obs['forecast']))


def _rng(*key):
    return np.random.default_rng(np.random.SeedSequence([int(k) for k in key]))


def factor_points(v, branching):
    """Equal-probability lognormal quantiles, rescaled to mean one."""
    if branching == 1 or v <= 0:
        return np.ones(branching)
    s = np.sqrt(np.log1p(v))
    points = np.exp(-s*s/2+s*norm.ppf((np.arange(branching)+.5)/branching))
    return points/points.mean()


def tree_labels(depth, branching, continuation):
    return [(prefix, j) for prefix in product(range(branching), repeat=depth)
            for j in range(continuation)]


def joint_tree(obs, v, depth, branching, continuation, seed):
    """Paths (S, h, n). Window-period u<depth demand depends only on branch labels up to u."""
    check_observation(obs)
    h = window(obs); depth = min(depth, h); t = obs['t']
    mu = np.asarray(obs['forecast'][:h], dtype=float); n = mu.shape[1]
    points = factor_points(v, branching); s = np.sqrt(np.log1p(v))
    labels = tree_labels(depth, branching, continuation)
    paths = np.zeros((len(labels), h, n), dtype=int)
    for k, (prefix, j) in enumerate(labels):
        for u in range(depth):
            paths[k, u] = _rng(seed, t, u, *prefix[:u+1]).poisson(mu[u]*points[prefix[u]])
        rng = _rng(seed, t, 1000+j, *prefix)
        for u in range(depth, h):
            factor = np.exp(-s*s/2+s*rng.standard_normal())
            paths[k, u] = rng.poisson(mu[u]*factor)
    return paths, labels, depth


def automorphism(labels, branching, continuation, depth, seed, t, sku):
    """Label permutation that permutes children at every node, keyed by the original prefix."""
    images = []
    for prefix, j in labels:
        image = tuple(int(_rng(seed, t, sku, u, *prefix[:u]).permutation(branching)[prefix[u]])
                      for u in range(depth))
        images.append((image, int(_rng(seed, t, sku, depth, *prefix).permutation(continuation)[j])))
    return images


def shuffled_tree(paths, labels, depth, branching, continuation, seed, t):
    """Same per-SKU marginal tree, cross-SKU pairing changed for SKUs after the first."""
    index = {label: k for k, label in enumerate(labels)}
    out = paths.copy()
    for sku in range(1, paths.shape[2]):
        for k, image in enumerate(automorphism(labels, branching, continuation, depth, seed, t, sku)):
            out[k, :, sku] = paths[index[image], :, sku]
    return out


def open_loop_paths(obs, v, count, seed):
    """Independent common-shock paths for the equal-time open-loop comparison."""
    check_observation(obs)
    h = window(obs); mu = np.asarray(obs['forecast'][:h], dtype=float); s = np.sqrt(np.log1p(v))
    paths = np.zeros((count, h, mu.shape[1]), dtype=int)
    for k in range(count):
        rng = _rng(seed, obs['t'], 2000+k)
        for u in range(h):
            paths[k, u] = rng.poisson(mu[u]*np.exp(-s*s/2+s*rng.standard_normal()))
    return paths


def node_keys(paths, depth):
    """Decision node of each (scenario, stage): the observed window demand before that stage.

    Keys are demand values, not branch labels, so scenarios whose observed histories coincide
    always share a decision even when they come from different branches.
    """
    S, h, _ = paths.shape
    return [[tuple(tuple(int(x) for x in paths[k, s]) for s in range(min(u, depth)))
             for u in range(h)] for k in range(S)]


# ----------------------------------------------------------------------------------------------- v2
# Development version 2 (docs/rolling_tree_protocol_v2.md). The v1 functions above stay unchanged so the
# first pilot's evidence still regenerates. v2 changes only how the planner samples its own scenarios:
# per-depth branching (a wider first stage) and stratified draws of every random component within a node,
# so that a tree's first-period sample is no coarser than the open-loop comparators'.

def _strata(rng, count):
    """One uniform in each of `count` equal strata of (0, 1), in random order."""
    return np.clip((rng.permutation(count)+rng.random(count))/count, 1e-12, 1-1e-12)


def _poisson_at(levels, mean):
    return np.asarray(poisson.ppf(levels, mean), dtype=int)


def tree_labels_v2(branching, continuation):
    return [(prefix, j) for prefix in product(*(range(b) for b in branching)) for j in range(continuation)]


def joint_tree_v2(obs, v, branching, continuation, seed):
    """Paths (S, h, n) of a tree with branching[u] children at depth u.

    Children of one node share the common factor's equal-probability quantiles (as in v1); each SKU's
    Poisson component takes one stratified uniform per child, independently across SKUs, so the common
    factor is the only cross-SKU link. Continuation paths below the last branching depth stratify their
    factor and Poisson draws across the `continuation` paths of the node, period by period.
    """
    check_observation(obs)
    h = window(obs); depth = min(len(branching), h); branching = tuple(branching[:depth]); t = obs['t']
    mu = np.asarray(obs['forecast'][:h], dtype=float); n = mu.shape[1]; s = np.sqrt(np.log1p(v))
    labels = tree_labels_v2(branching, continuation)
    paths = np.zeros((len(labels), h, n), dtype=int)
    node_draws = {}

    def children(u, prefix):  # demand of every child of the node `prefix` (length u) in window period u
        if (u, prefix) not in node_draws:
            b = branching[u]; points = factor_points(v, b); out = np.zeros((b, n), dtype=int)
            for i in range(n):
                levels = _strata(_rng(seed, t, u, 77, i, *prefix), b)
                out[:, i] = _poisson_at(levels, mu[u, i]*points)
            node_draws[u, prefix] = out
        return node_draws[u, prefix]

    continuation_draws = {}

    def continued(prefix):  # (m, h-depth, n) demand of the continuation paths of a depth-D node
        if prefix not in continuation_draws:
            out = np.zeros((continuation, h-depth, n), dtype=int)
            for u in range(depth, h):
                g = _strata(_rng(seed, t, 1000+u, 78, *prefix), continuation)
                factor = np.exp(-s*s/2+s*norm.ppf(g)) if v > 0 else np.ones(continuation)
                for i in range(n):
                    levels = _strata(_rng(seed, t, 1000+u, 79, i, *prefix), continuation)
                    out[:, u-depth, i] = _poisson_at(levels, mu[u, i]*factor)
            continuation_draws[prefix] = out
        return continuation_draws[prefix]

    for k, (prefix, j) in enumerate(labels):
        for u in range(depth):
            paths[k, u] = children(u, prefix[:u])[prefix[u]]
        if depth < h:
            paths[k, depth:] = continued(prefix)[j]
    return paths, labels, depth


def automorphism_v2(labels, branching, continuation, depth, seed, t, sku):
    """Children permuted at every node (and continuation paths at every depth-D node), keyed by the prefix."""
    images = []
    for prefix, j in labels:
        image = tuple(int(_rng(seed, t, sku, u, *prefix[:u]).permutation(branching[u])[prefix[u]])
                      for u in range(depth))
        images.append((image, int(_rng(seed, t, sku, depth, *prefix).permutation(continuation)[j])))
    return images


def shuffled_tree_v2(paths, labels, depth, branching, continuation, seed, t):
    """Same per-SKU marginal tree as `joint_tree_v2`; cross-SKU pairing changed for SKUs after the first."""
    index = {label: k for k, label in enumerate(labels)}
    out = paths.copy()
    for sku in range(1, paths.shape[2]):
        for k, image in enumerate(automorphism_v2(labels, tuple(branching[:depth]), continuation, depth,
                                                  seed, t, sku)):
            out[k, :, sku] = paths[index[image], :, sku]
    return out


def open_loop_paths_v2(obs, v, count, seed):
    """Equal-time open-loop paths with the same stratified sampling as the v2 tree, period by period."""
    check_observation(obs)
    h = window(obs); mu = np.asarray(obs['forecast'][:h], dtype=float); s = np.sqrt(np.log1p(v)); t = obs['t']
    paths = np.zeros((count, h, mu.shape[1]), dtype=int)
    for u in range(h):
        g = _strata(_rng(seed, t, 2000+u, 78), count)
        factor = np.exp(-s*s/2+s*norm.ppf(g)) if v > 0 else np.ones(count)
        for i in range(mu.shape[1]):
            paths[:, u, i] = _poisson_at(_strata(_rng(seed, t, 2000+u, 79, i), count), mu[u, i]*factor)
    return paths


def first_period_error(paths, obs):
    """Sum over SKUs of |mean first-period scenario demand - forecast| (the pilot's diagnostic)."""
    return float(np.abs(np.asarray(paths)[:, 0, :].mean(axis=0)-np.asarray(obs['forecast'][0])).sum())


def energy_score(samples, observed):
    """Energy score of a joint sample (N, n) for one observed vector; lower is better."""
    x = np.asarray(samples, dtype=float); y = np.asarray(observed, dtype=float)
    first = np.linalg.norm(x-y, axis=1).mean()
    second = np.linalg.norm(x[:, None, :]-x[None, :, :], axis=2).mean()
    return float(first-second/2)


def one_step_samples(obs, v, count, seed):
    """Joint one-step predictive sample: Poisson(mu F) with one common lognormal F per draw."""
    rng = _rng(seed, obs['t'], 3000); mu = np.asarray(obs['forecast'][0], dtype=float); s = np.sqrt(np.log1p(v))
    factor = np.exp(-s*s/2+s*rng.standard_normal(count)) if v > 0 else np.ones(count)
    return rng.poisson(mu[None, :]*factor[:, None])
