"""Scenario-tree MILP: decisions indexed by observed history, carbon accumulated per path.

`build` reproduces rolling_inventory.planning.solve when every scenario shares one node
(depth 0). Tie-robust selection solves a second MILP that keeps a model's own optimum within
a numerical tolerance and picks the first action that is best under another model.
"""
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import block_diag, csr_matrix, lil_matrix, vstack

from rolling_inventory.environment import carbon, validate
from rolling_inventory.planning import path_cost
from .scenarios import node_keys


class Model:
    """MILP arrays plus the node map needed to read and independently replay a solution."""

    def __init__(self, obs, paths, depth, paced=True):
        p = obs['public']; paths = np.asarray(paths, dtype=float)
        S, h, n = paths.shape; r = len(p['lead'])
        self.obs, self.paths, self.depth = obs, paths, depth
        keys = node_keys(paths, depth)
        self.nodes = []  # per stage: key -> node id
        for u in range(h):
            ids = {}
            for k in range(S):
                ids.setdefault(keys[k][u], len(ids))
            self.nodes.append(ids)
        self.node_of = [[self.nodes[u][keys[k][u]] for u in range(h)] for k in range(S)]
        offsets, size = [], 0
        for u in range(h):
            offsets.append(size); size += len(self.nodes[u])*n*r
        qn = size; ivn = S*h*n; size = qn+2*ivn
        q = lambda u, m, i, j: offsets[u]+(m*n+i)*r+j
        inv = lambda k, u, i: qn+(k*h+u)*n+i
        bac = lambda k, u, i: qn+ivn+(k*h+u)*n+i
        weight = np.zeros((h, max(len(x) for x in self.nodes)))
        for k in range(S):
            for u in range(h):
                weight[u, self.node_of[k][u]] += 1/S
        c = np.zeros(size); ub = np.full(size, np.inf)
        for u in range(h):
            for m in range(len(self.nodes[u])):
                for i in range(n):
                    for j in range(r):
                        c[q(u, m, i, j)] = weight[u, m]*p['mass'][i]*(
                            p['freight'][j]+p['carbon_price']*p['emissions'][j])
                        ub[q(u, m, i, j)] = 0 if u+p['lead'][j] >= h else p['capacity'][j]//p['mass'][i]
        for k in range(S):
            for u in range(h):
                for i in range(n):
                    c[inv(k, u, i)] = p['holding'][i]/S
                    c[bac(k, u, i)] = (p['backlog'][i]+(p['terminal_backlog'][i]
                                       if obs['t']+u == p['periods']-1 else 0))/S
        paths_by_nodes = sorted({tuple(row) for row in self.node_of})
        rows = ivn+sum(len(x) for x in self.nodes)*r+len(paths_by_nodes)
        mat = lil_matrix((rows, size)); lo = np.full(rows, -np.inf); hi = np.zeros(rows); row = 0
        for k in range(S):
            for u in range(h):
                for i in range(n):
                    mat[row, inv(k, u, i)] = 1; mat[row, bac(k, u, i)] = -1
                    if u:
                        mat[row, inv(k, u-1, i)] = -1; mat[row, bac(k, u-1, i)] = 1
                    for j, lead in enumerate(p['lead']):
                        if u >= lead:
                            mat[row, q(u-lead, self.node_of[k][u-lead], i, j)] = -1
                    rhs = obs['pipeline'][obs['t']+u][i]-paths[k, u, i]
                    if not u:
                        rhs += obs['stock'][i]-obs['backlog'][i]
                    lo[row] = hi[row] = rhs; row += 1
        for u in range(h):
            for m in range(len(self.nodes[u])):
                for j in range(r):
                    for i in range(n):
                        mat[row, q(u, m, i, j)] = p['mass'][i]
                    hi[row] = p['capacity'][j]; row += 1
        self.budget = obs['carbon_remaining']*(h/(p['periods']-obs['t']) if paced else 1)
        for sequence in paths_by_nodes:  # Exclusive branches never share one carbon sum.
            for u, m in enumerate(sequence):
                for i in range(n):
                    for j in range(r):
                        mat[row, q(u, m, i, j)] += p['mass'][i]*p['emissions'][j]
            hi[row] = self.budget; row += 1
        self.c, self.matrix, self.lo, self.hi = c, mat.tocsr(), lo, hi
        self.ub = ub; self.qn = qn; self.q = q
        self.integrality = np.r_[np.ones(qn), np.zeros(2*ivn)]
        self.first = [q(0, 0, i, j) for i in range(n) for j in range(r)]
        self.shape = (n, r)

    @property
    def size(self):
        return len(self.c)

    def any_dispatch(self):
        return bool(np.any(self.ub[:self.qn] > 0))

    def decisions(self, x):
        n, r = self.shape
        z = np.rint(x[:self.qn]).astype(int)
        return [[z[self.q(u, m, 0, 0):self.q(u, m, 0, 0)+n*r].reshape(n, r)
                 for m in range(len(ids))] for u, ids in enumerate(self.nodes)]

    def replay(self, x, tolerance=1e-6):
        """Independent physical cost; checks integrality, constraints and pathwise carbon."""
        if np.max(np.abs(x[:self.qn]-np.rint(x[:self.qn]))) > 1e-5:
            raise ValueError('noninteger_MILP')
        nodes = self.decisions(x); p = self.obs['public']; costs = []
        for k, sequence in enumerate(self.node_of):
            schedule = [nodes[u][m] for u, m in enumerate(sequence)]
            if sum(carbon(a, p) for a in schedule) > self.budget+tolerance:
                raise ValueError('path_carbon')
            for u, a in enumerate(schedule):
                validate(a, dict(self.obs, t=self.obs['t']+u))
            costs.append(path_cost(self.obs, schedule, self.paths[k]))
        return float(np.mean(costs))

    def first_action(self, x):
        return self.decisions(x)[0][0].tolist()

    def summary(self):
        return {'scenarios': len(self.node_of), 'horizon': len(self.nodes), 'depth': self.depth,
                'nodes_per_stage': [len(x) for x in self.nodes],
                'integer_variables': int(self.qn), 'continuous_variables': int(self.size-self.qn),
                'rows': int(self.matrix.shape[0])}


def tolerance(value, rule):
    return rule['relative']*max(1., abs(value))+rule['absolute']


def _milp(c, integrality, ub, matrix, lo, hi, time_limit):
    wall, cpu = time.perf_counter(), time.process_time()
    res = milp(c, integrality=integrality, bounds=Bounds(np.zeros(len(c)), ub),
               constraints=LinearConstraint(matrix, lo, hi),
               options={'mip_rel_gap': 0.0, 'time_limit': time_limit})
    record = {'status': int(res.status), 'message': str(res.message),
              'objective': None if res.fun is None else float(res.fun),
              'dual_bound': _num(getattr(res, 'mip_dual_bound', None)),
              'mip_gap': _num(getattr(res, 'mip_gap', None)),
              'nodes': _num(getattr(res, 'mip_node_count', None)),
              'feasible_solution': res.x is not None,
              'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu}
    return res, record


def _num(value):
    return None if value is None else float(value)


def solve(model, time_limit):
    """Optimal solution and its record; nonoptimal or timed-out solves return None."""
    res, record = _milp(model.c, model.integrality, model.ub, model.matrix, model.lo, model.hi, time_limit)
    record.update(model.summary())
    if res.status != 0 or res.x is None:
        return None, record
    physical = model.replay(res.x)
    if abs(physical-res.fun) > 1e-5+1e-8*abs(physical):
        raise ValueError('MILP_objective_replay')
    record['replayed_objective'] = physical
    return {'x': res.x, 'value': physical, 'action': model.first_action(res.x)}, record


def tie_robust(primary, own, own_value, rule, time_limit):
    """min primary objective s.t. own objective <= own optimum + tolerance; first action shared."""
    bound = own_value+tolerance(own_value, rule)
    n_primary = primary.size
    link = lil_matrix((len(primary.first)+1, n_primary+own.size))
    for row, (a, b) in enumerate(zip(primary.first, own.first)):
        link[row, a] = 1; link[row, n_primary+b] = -1
    link[len(primary.first), n_primary:] = own.c
    matrix = vstack([block_diag([primary.matrix, own.matrix]), csr_matrix(link)]).tocsr()
    lo = np.r_[primary.lo, own.lo, np.zeros(len(primary.first)), -np.inf]
    hi = np.r_[primary.hi, own.hi, np.zeros(len(primary.first)), bound]
    c = np.r_[primary.c, np.zeros(own.size)]
    res, record = _milp(c, np.r_[primary.integrality, own.integrality], np.r_[primary.ub, own.ub],
                        matrix, lo, hi, time_limit)
    record.update({'primary': primary.summary(), 'own': own.summary(), 'own_bound': bound})
    if res.status != 0 or res.x is None:
        return None, record
    x_primary, x_own = res.x[:n_primary], res.x[n_primary:]
    value = primary.replay(x_primary); own_cost = own.replay(x_own)
    if abs(value-res.fun) > 1e-5+1e-8*abs(value):
        raise ValueError('tie_objective_replay')
    if own_cost > bound+1e-6:
        raise ValueError('tie_own_bound')
    action = primary.first_action(x_primary)
    if action != own.first_action(x_own):
        raise ValueError('tie_first_action_link')
    record.update({'replayed_objective': value, 'own_replayed_cost': own_cost})
    return {'value': value, 'own_cost': own_cost, 'action': action}, record
