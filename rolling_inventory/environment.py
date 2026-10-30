"""Demand is private until after dispatch; observations expose past demand only."""
from copy import deepcopy
import numpy as np


def seasonal(t):
    return (0.85, 1.0, 1.15, 1.0)[t % 4]


def generate(cfg, split, seeds):
    tasks = []
    for profile_index, profile in enumerate(cfg['profiles']):
        for seed in seeds:
            rng = np.random.default_rng(np.random.SeedSequence([seed, profile_index, 771]))
            public = {k: deepcopy(cfg[k]) for k in (
                'periods', 'horizon', 'scenarios', 'forecast_alpha', 'scenario_seed',
                'holding', 'backlog', 'terminal_backlog', 'mass', 'lead', 'capacity',
                'freight', 'emissions', 'carbon_price', 'initial_inventory')}
            public['base_mean'] = (np.asarray(cfg['base_mean']) * rng.uniform(.85, 1.15, 3)).tolist()
            public['carbon_budget'] = cfg['carbon_budget_per_period'] * cfg['periods']
            public['initial_pipeline'] = [[0, 0, 0] for _ in range(cfg['periods'])]
            public['initial_pipeline'][1] = [1, 0, 1]
            demand = []
            for t in range(cfg['periods']):
                factor = 1.0
                if profile == 'volatile': factor = float(rng.lognormal(-.4**2/2, .4))
                if profile == 'upshift' and t >= cfg['periods']//2: factor = 1.7
                if profile == 'downshift' and t >= cfg['periods']//2: factor = .55
                demand.append(rng.poisson(np.asarray(public['base_mean']) * seasonal(t) * factor).tolist())
            tasks.append({'id': f'{split}-{profile}-{seed}', 'split': split,
                          'profile': profile, 'seed': seed, 'public': public, 'demand': demand})
    return tasks


def carbon(action, p):
    return int(np.sum(np.asarray(action) * np.asarray(p['mass'])[:, None]
                      * np.asarray(p['emissions'])[None, :]))


def dispatch_cost(action, p):
    weights = np.asarray(p['freight']) + p['carbon_price'] * np.asarray(p['emissions'])
    return float(np.sum(np.asarray(action) * np.asarray(p['mass'])[:, None] * weights))


def validate(action, observation):
    p = observation['public']; a = np.asarray(action)
    if a.shape != (len(p['mass']), len(p['lead'])) or a.dtype.kind not in 'iu' or np.any(a < 0):
        raise ValueError('dispatch_must_be_nonnegative_integers')
    if np.any(np.asarray(p['mass']) @ a > np.asarray(p['capacity'])):
        raise ValueError('shared_route_capacity')
    if carbon(a, p) > observation['carbon_remaining']:
        raise ValueError('cumulative_carbon_budget')
    for r, lead in enumerate(p['lead']):
        if observation['t'] + lead >= p['periods'] and np.any(a[:, r]):
            raise ValueError('arrival_after_episode')


class Environment:
    def __init__(self, task):
        self.p = deepcopy(task['public'])
        self._demand = deepcopy(task['demand'])
        self.stock = np.array(self.p['initial_inventory'], dtype=int)
        self.backlog = np.zeros(len(self.stock), dtype=int)
        self.pipeline = np.array(self.p['initial_pipeline'], dtype=int)
        self.remaining = self.p['carbon_budget']; self.t = 0; self.history = []

    def observe(self):
        if self.t >= self.p['periods']: raise ValueError('episode_finished')
        arriving = self.pipeline[self.t]
        available = self.stock + arriving
        old_served = np.minimum(available, self.backlog)
        level = np.array(self.p['base_mean'], dtype=float)
        alpha = self.p['forecast_alpha']
        for t, d in enumerate(self.history):
            level = (1-alpha)*level + alpha*np.asarray(d)/seasonal(t)
        forecast = [np.maximum(.05, level*seasonal(t)).tolist()
                    for t in range(self.t, self.p['periods'])]
        outstanding = self.pipeline.copy(); outstanding[self.t] = 0
        return {'t': self.t, 'public': deepcopy(self.p),
                'stock': (available-old_served).tolist(),
                'backlog': (self.backlog-old_served).tolist(),
                'arrivals': arriving.tolist(), 'served_old': old_served.tolist(),
                'pipeline': outstanding.tolist(), 'carbon_remaining': self.remaining,
                'history': deepcopy(self.history), 'forecast': forecast}

    def step(self, action):
        obs = self.observe(); validate(action, obs)  # All checks before mutation.
        a = np.asarray(action); p = self.p; t = self.t
        d = np.array(self._demand[t], dtype=int)
        filled = np.minimum(np.asarray(obs['stock']), d)
        stock = np.asarray(obs['stock']) - filled
        backlog = np.asarray(obs['backlog']) + d - filled
        pipeline = np.array(obs['pipeline'], dtype=int)
        for r, lead in enumerate(p['lead']):
            if t+lead < p['periods']: pipeline[t+lead] += a[:, r]
        emission = carbon(a, p)
        costs = {
            'freight': float(np.sum(a*np.asarray(p['mass'])[:, None]*np.asarray(p['freight']))),
            'carbon': p['carbon_price']*emission,
            'holding': float(stock @ np.asarray(p['holding'])),
            'backlog': float(backlog @ np.asarray(p['backlog'])),
            'terminal_backlog': float(backlog @ np.asarray(p['terminal_backlog'])) if t == p['periods']-1 else 0.0}
        row = {'observation': obs, 'action': a.tolist(), 'demand': d.tolist(),
               'filled_new': filled.tolist(), 'stock_end': stock.tolist(),
               'backlog_end': backlog.tolist(), 'pipeline_end': pipeline.tolist(),
               'emissions': emission, 'costs': costs, 'cost': sum(costs.values()),
               'forecast_error': (d-np.asarray(obs['forecast'][0])).tolist()}
        self.stock, self.backlog, self.pipeline = stock, backlog, pipeline
        self.remaining -= emission; self.history.append(d.tolist()); self.t += 1
        return row
