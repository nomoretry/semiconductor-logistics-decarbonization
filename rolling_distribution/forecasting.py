"""Past-only dispersion; joint rearrangement preserves entire SKU paths."""
import numpy as np
from scipy.stats import nbinom, poisson
from rolling_forecast.forecasting import predict, policy_observation

MEAN_MODEL = {'family': 'ewma', 'alpha': 0.35}


def residual_rows(public, history):
    rows = []
    for t, value in enumerate(history):
        mean = np.asarray(predict(public, history[:t], t, MEAN_MODEL)[0])
        y = np.asarray(value, dtype=float)
        rows.append({'mean': mean.tolist(), 'observed': y.tolist(),
                     'numerator': ((y-mean)**2-y).tolist(),
                     'denominator': (mean**2).tolist(),
                     'standardized': ((y-mean)/np.sqrt(mean)).tolist()})
    return rows


def fit(tasks):
    if not tasks or any(t['split'] != 'distribution-fit' for t in tasks):
        raise ValueError('fit_split_required')
    rows = [dict(r, id=t['id'], origin=i) for t in tasks
            for i, r in enumerate(residual_rows(t['public'], t['demand']))]
    return {'paths': len(tasks), 'observations': len(rows),
            'numerator_mean': np.mean([r['numerator'] for r in rows], axis=0).tolist(),
            'denominator_mean': np.mean([r['denominator'] for r in rows], axis=0).tolist(),
            'standardized': [r['standardized'] for r in rows]}, rows


def observation(raw):
    # policy_observation has an explicit input allowlist and ignores task metadata.
    return policy_observation(raw, MEAN_MODEL)


def estimate(obs, prior, strength, cap=2.):
    if strength <= 0 or cap <= 0:
        raise ValueError('invalid_dispersion_settings')
    if len(obs['history']) != obs['t']:
        raise ValueError('history_boundary')
    rows = residual_rows(obs['public'], obs['history'])
    num = strength*np.asarray(prior['numerator_mean'])
    den = strength*np.asarray(prior['denominator_mean'])
    for r in rows:
        num = num + np.asarray(r['numerator'])
        den = den + np.asarray(r['denominator'])
    return np.clip(num/den, 0., cap)


def nll(y, mean, kappa):
    y, mean, kappa = np.broadcast_arrays(y, mean, kappa)
    value = np.empty_like(mean, dtype=float)
    nb = kappa > 1e-8
    value[~nb] = -poisson.logpmf(y[~nb], mean[~nb])
    shape = 1/kappa[nb]
    value[nb] = -nbinom.logpmf(y[nb], shape, shape/(shape+mean[nb]))
    if not np.all(np.isfinite(value)):
        raise ValueError('nonfinite_probability_score')
    return value


def sample(obs, prior, strength, method, count, seed, cap=2.):
    if type(count) is not int or count < 1:
        raise ValueError('positive_member_count_required')
    h = min(obs['public']['horizon'], len(obs['forecast']))
    means = np.asarray(obs['forecast'][:h])
    rng = np.random.default_rng(seed+obs['t'])
    if method == 'poisson':
        return rng.poisson(means, size=(count, *means.shape)), np.zeros(means.shape[1])
    if method != 'residual_nb':
        raise ValueError('unknown_distribution')
    kappa = estimate(obs, prior, strength, cap)
    u = np.clip(rng.random((count, *means.shape)), 1e-12, 1-1e-12)
    values = np.empty_like(u)
    for i, k in enumerate(kappa):
        if k <= 1e-8:
            values[:, :, i] = poisson.ppf(u[:, :, i], means[:, i])
        else:
            shape = 1/k
            values[:, :, i] = nbinom.ppf(u[:, :, i], shape, shape/(shape+means[:, i]))
    if not np.all(np.isfinite(values)):
        raise ValueError('nonfinite_scenarios')
    return values.astype(int), kappa


def couple(paths, obs, prior, strength, seed):
    """Only reorder whole column-paths, never individual horizon entries."""
    paths = np.asarray(paths)
    count, _, n = paths.shape
    old = np.asarray(prior['standardized'])
    recent = np.asarray([r['standardized'] for r in residual_rows(obs['public'], obs['history'])])
    rng = np.random.default_rng(np.random.SeedSequence([seed, obs['t'], 779]))
    ranks = old[rng.integers(len(old), size=count)].copy()
    if len(recent):
        choose = rng.random(count) < len(recent)/(strength+len(recent))
        ranks[choose] = recent[rng.integers(len(recent), size=int(choose.sum()))]
    result = np.empty_like(paths)
    for i in range(n):
        # Random tie breaking is independent across SKUs, including equal residuals.
        target_order = np.lexsort((rng.random(count), ranks[:, i]))
        source_order = np.lexsort((rng.random(count), paths[:, :, i].sum(axis=1)))
        result[target_order, :, i] = paths[source_order, :, i]
        if sorted(map(tuple, result[:, :, i])) != sorted(map(tuple, paths[:, :, i])):
            raise ValueError('sku_path_marginals_changed')
    return result


def ensemble_scores(members, truth):
    x = np.asarray(members, dtype=float); y = np.asarray(truth, dtype=float)
    if x.ndim != 2 or x.shape[1:] != y.shape or not np.all(np.isfinite(x)):
        raise ValueError('invalid_ensemble')
    pair = x[:, None, :]-x[None, :, :]
    crps = np.mean(np.abs(x-y), axis=0)-.5*np.mean(np.abs(pair), axis=(0, 1))
    energy = np.mean(np.linalg.norm(x-y, axis=1))-.5*np.mean(np.linalg.norm(pair, axis=2))
    variogram = sum((abs(y[i]-y[j])**.5-np.mean(np.abs(x[:, i]-x[:, j])**.5))**2
                    for i in range(len(y)) for j in range(i+1, len(y)))
    low, high = np.quantile(x, [.1, .9], axis=0, method='inverted_cdf')
    return {'marginal_crps': float(np.mean(crps)), 'energy': float(energy),
            'variogram_p05': float(variogram),
            'coverage80': float(np.mean((y >= low) & (y <= high))),
            'width80': float(np.mean(high-low))}


def select(tasks, prior, cfg):
    if not tasks or any(t['split'] != 'distribution-tune' for t in tasks):
        raise ValueError('tune_split_required')
    from rolling_inventory.environment import Environment
    scores = []; rows = []
    for strength in cfg['prior_strength_candidates']:
        values = []
        for task in tasks:
            env = Environment(task); case = []
            for t, y in enumerate(task['demand']):
                obs = observation(env.observe())
                kappa = estimate(obs, prior, strength, cfg['dispersion_cap'])
                score = float(nll(y, obs['forecast'][0], kappa).mean())
                rows.append({'id': task['id'], 'origin': t, 'strength': strength,
                             'mean': obs['forecast'][0], 'kappa': kappa.tolist(), 'nll': score})
                case.append(score)
                env.step(np.zeros((3, 2), dtype=int))
            values.append(float(np.mean(case)))
        scores.append(float(np.mean(values)))
    winner = min(range(len(scores)), key=lambda i: (scores[i], i))
    return {'criterion': 'tuning_one_step_marginal_nb_nll', 'tuning_paths': len(tasks),
            'candidates': cfg['prior_strength_candidates'], 'candidate_nll': scores,
            'selected_index': winner, 'strength': cfg['prior_strength_candidates'][winner]}, rows
