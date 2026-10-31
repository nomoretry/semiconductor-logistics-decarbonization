"""Predict from public parameters and observed history; score only afterwards."""
from copy import deepcopy
import numpy as np
from scipy.special import gammaln
from rolling_inventory.environment import seasonal


def predict(public, history, t, model):
    if t != len(history) or not 0 <= t < public['periods']:
        raise ValueError('history_must_end_before_forecast_origin')
    level = np.asarray(public['base_mean'], dtype=float).copy()
    adjusted = [np.asarray(d, dtype=float) / seasonal(i) for i, d in enumerate(history)]
    if model['family'] == 'ewma':
        alpha = model['alpha']
        if not 0 < alpha <= 1:
            raise ValueError('invalid_alpha')
        for d in adjusted:
            level = (1-alpha)*level + alpha*d
    elif model['family'] == 'window':
        width = model['window']
        if type(width) is not int or width < 1:
            raise ValueError('invalid_window')
        if adjusted:
            level = np.mean(adjusted[-width:], axis=0)
    else:
        raise ValueError('unknown_forecast_family')
    return [np.maximum(0.05, level*seasonal(i)).tolist() for i in range(t, public['periods'])]


def policy_observation(observation, model):
    # Explicit allowlist: task IDs, profiles and future demand cannot enter here.
    keys = ['t', 'public', 'stock', 'backlog', 'arrivals', 'served_old',
            'pipeline', 'carbon_remaining', 'history']
    obs = {k: deepcopy(observation[k]) for k in keys}
    obs['forecast'] = predict(obs['public'], obs['history'], obs['t'], model)
    return obs


def score_path(task, model, name):
    rows = []
    for t in range(task['public']['periods']):
        forecast = predict(task['public'], task['demand'][:t], t, model)
        # Realized demand is used after the forecast was constructed.
        for lead, mean in enumerate(forecast[:task['public']['horizon']], 1):
            observed = np.asarray(task['demand'][t+lead-1])
            mean = np.asarray(mean)
            error = mean-observed
            nll = mean-observed*np.log(mean)+gammaln(observed+1)
            rows.append({'id':task['id'], 'profile':task['profile'], 'model':name,
                         'origin':t, 'lead':lead, 'mean':mean.tolist(),
                         'observed':observed.tolist(), 'error':error.tolist(), 'nll':nll.tolist()})
    return rows


def scores(rows):
    errors = np.asarray([r['error'] for r in rows])
    return {'n':int(errors.size), 'mae':float(np.mean(np.abs(errors))),
            'rmse':float(np.sqrt(np.mean(errors**2))), 'bias':float(np.mean(errors)),
            'poisson_nll':float(np.mean([r['nll'] for r in rows]))}


def select(calibration, cfg):
    if not calibration or any(t['split'] != 'forecast-calibration' for t in calibration):
        raise ValueError('selection_requires_calibration_only')
    families = {
        'fast_ewma':[{'family':'ewma', 'alpha':x} for x in cfg['fast_alpha_candidates']],
        'seasonal_window':[{'family':'window', 'window':x} for x in cfg['window_candidates']],
    }
    selected = {'original_ewma':{'family':'ewma', 'alpha':0.35}}
    all_rows = []; ranking = {}
    for name, candidates in families.items():
        values = []
        for candidate_index, model in enumerate(candidates):
            per_case = []
            for task in calibration:
                rows = [r for r in score_path(task, model, name) if r['lead'] == 1]
                value = scores(rows)
                all_rows.append({'id':task['id'], 'family':name, 'candidate_index':candidate_index,
                                 'model':model, 'scores':value})
                per_case.append(value['poisson_nll'])
            values.append(float(np.mean(per_case)))
        winner = min(range(len(values)), key=lambda i:(values[i], i))
        selected[name] = candidates[winner]
        ranking[name] = {'candidate_scores':values, 'selected_index':winner}
    return {'criterion':'calibration_one_step_marginal_poisson_nll', 'models':selected,
            'ranking':ranking, 'calibration_paths':len(calibration)}, all_rows
