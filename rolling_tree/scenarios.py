"""Common-shock scenarios built from the observation only.

A policy sees the environment observation and nothing else: no task id, process label,
demand seed or hidden factor. Random numbers depend on public seeds, the period and the
tree node, never on the realized path.
"""
from itertools import combinations, product

import numpy as np
from scipy.stats import norm

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
