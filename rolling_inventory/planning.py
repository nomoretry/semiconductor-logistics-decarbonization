"""Shared dispatch variables across all demand scenarios prevent anticipation."""
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from .environment import carbon, dispatch_cost, validate


def path_cost(obs, schedule, demand):
    """Independent physical cost of a complete open-loop dispatch schedule."""
    p = obs['public']; h = len(demand); net = np.asarray(obs['stock'])-np.asarray(obs['backlog'])
    net = net.astype(float); pipe = np.asarray(obs['pipeline'], dtype=float).copy()
    value = 0.0
    for u in range(h):
        t = obs['t']+u
        net += pipe[t]  # Today's arrivals have already been removed in observe().
        value += dispatch_cost(schedule[u], p)
        for r, lead in enumerate(p['lead']):
            if t+lead < len(pipe): pipe[t+lead] += np.asarray(schedule[u])[:, r]
        net -= demand[u]
        value += float(np.maximum(net, 0) @ p['holding'] + np.maximum(-net, 0) @ p['backlog'])
        if t == p['periods']-1: value += float(np.maximum(-net, 0) @ p['terminal_backlog'])
    return value


def solve(obs, demands, paced=True):
    p = obs['public']; demands = np.asarray(demands, dtype=float)
    s, h, n = demands.shape; r = len(p['lead']); qn = h*n*r
    ivn = s*h*n; size = qn+2*ivn
    def qi(u, i, j): return (u*n+i)*r+j
    def ii(k, u, i): return qn+(k*h+u)*n+i
    def bi(k, u, i): return qn+ivn+(k*h+u)*n+i
    objective = np.zeros(size); ub = np.full(size, np.inf)
    for u in range(h):
        for i in range(n):
            for j in range(r):
                q = qi(u, i, j)
                objective[q] = p['mass'][i]*(p['freight'][j]+p['carbon_price']*p['emissions'][j])
                ub[q] = p['capacity'][j]//p['mass'][i]
                # No dispatch without an arrival inside the planning horizon.
                if u+p['lead'][j] >= h: ub[q] = 0
            for k in range(s):
                objective[ii(k,u,i)] = p['holding'][i]/s
                objective[bi(k,u,i)] = (p['backlog'][i]+(p['terminal_backlog'][i]
                    if obs['t']+u == p['periods']-1 else 0))/s
    rows = s*h*n+h*r+1
    mat = lil_matrix((rows,size), dtype=float); lower = np.full(rows,-np.inf); upper=np.zeros(rows)
    row=0
    for k in range(s):
        for u in range(h):
            for i in range(n):
                mat[row,ii(k,u,i)]=1; mat[row,bi(k,u,i)]=-1
                if u:
                    mat[row,ii(k,u-1,i)]=-1; mat[row,bi(k,u-1,i)]=1
                for j, lead in enumerate(p['lead']):
                    if u >= lead: mat[row,qi(u-lead,i,j)]=-1
                rhs = obs['pipeline'][obs['t']+u][i]-demands[k,u,i]
                if not u: rhs += obs['stock'][i]-obs['backlog'][i]
                lower[row]=upper[row]=rhs; row+=1
    for u in range(h):
        for j in range(r):
            for i in range(n): mat[row,qi(u,i,j)]=p['mass'][i]
            upper[row]=p['capacity'][j]; row+=1
    for u in range(h):
        for i in range(n):
            for j in range(r): mat[row,qi(u,i,j)]=p['mass'][i]*p['emissions'][j]
    budget=obs['carbon_remaining']
    if paced: budget *= h/(p['periods']-obs['t'])
    upper[row]=budget
    matrix=mat.tocsr()
    res=milp(objective, integrality=np.r_[np.ones(qn),np.zeros(2*ivn)],
             bounds=Bounds(np.zeros(size),ub), constraints=LinearConstraint(matrix,lower,upper),
             options={'mip_rel_gap':0.0,'time_limit':30.0})
    if res.status != 0 or res.x is None: raise ValueError(f'MILP_not_optimal:{res.message}')
    if np.max(np.abs(res.x[:qn]-np.rint(res.x[:qn])))>1e-5: raise ValueError('noninteger_MILP')
    schedule=np.rint(res.x[:qn]).astype(int).reshape(h,n,r)
    # Recheck the dispatch plan independently of solver slacks.
    if sum(carbon(a,p) for a in schedule)>budget+1e-6: raise ValueError('plan_carbon')
    for u,a in enumerate(schedule):
        adjusted=dict(obs,t=obs['t']+u); validate(a,adjusted)
    physical=float(np.mean([path_cost(obs,schedule,d) for d in demands]))
    if abs(physical-res.fun)>1e-5+1e-8*abs(physical): raise ValueError('MILP_objective_replay')
    return schedule.tolist(), {'objective':physical,'scenarios':s,'horizon':h,
                               'dispatch_variables':qn,'continuous_variables':2*ivn,
                               'status':int(res.status),'mip_gap':float(res.mip_gap or 0)}


def allowance(obs):
    return obs['carbon_remaining']/(obs['public']['periods']-obs['t'])


def feasible(a, obs, budget):
    try: validate(a,obs)
    except ValueError: return False
    return carbon(a,obs['public'])<=budget+1e-9


def base_stock(obs, z):
    p=obs['public']; n=len(p['mass']); a=np.zeros((n,len(p['lead'])),dtype=int)
    net=np.asarray(obs['stock'])-np.asarray(obs['backlog']); f=np.asarray(obs['forecast'])
    order=sorted(range(n),key=lambda i:(-p['backlog'][i]/p['mass'][i],i))
    for j in sorted(range(len(p['lead'])),key=lambda j:p['freight'][j]+p['carbon_price']*p['emissions'][j]):
        lead=p['lead'][j]
        if obs['t']+lead>=p['periods']: continue
        for i in order:
            need=f[:lead+1,i].sum(); target=need+z*np.sqrt(need)
            due=sum(obs['pipeline'][t][i] for t in range(obs['t'],obs['t']+lead+1))
            due+=sum(a[i,k] for k,l in enumerate(p['lead']) if l<=lead)
            gap=max(0,int(np.ceil(target-net[i]-due)))
            for _ in range(gap):
                candidate=a.copy();candidate[i,j]+=1
                if not feasible(candidate,obs,allowance(obs)):break
                a=candidate
    return a.tolist(), {'solver_calls':0}


def marginal(obs):
    p=obs['public']; n=len(p['mass']); h=min(p['horizon'],len(obs['forecast']))
    schedule=np.zeros((h,n,len(p['lead'])),dtype=int); f=np.asarray(obs['forecast'][:h])
    evaluations=0
    while True:
        old=path_cost(obs,schedule,f); best=None; gain=1e-8
        for i in range(n):
            for j in range(len(p['lead'])):
                trial=schedule.copy();trial[0,i,j]+=1
                if not feasible(trial[0],obs,allowance(obs)):continue
                value=path_cost(obs,trial,f);evaluations+=1
                if old-value>gain:gain=old-value;best=trial
        if best is None:break
        schedule=best
    return schedule[0].tolist(), {'solver_calls':0,'candidate_evaluations':evaluations}


def decide(obs, method, z=0.):
    if method=='base_stock':return base_stock(obs,z)
    if method=='marginal_cost':return marginal(obs)
    if method not in ('mpc_mean','mpc_scenarios'):raise ValueError('unknown_method')
    p=obs['public']; h=min(p['horizon'],len(obs['forecast'])); means=np.asarray(obs['forecast'][:h])
    if method=='mpc_mean':demands=means[None,:,:]
    else:
        # Independent of actual demand seed/profile/path. Same CRN across policies/cases.
        rng=np.random.default_rng(p['scenario_seed']+obs['t'])
        demands=rng.poisson(means,size=(p['scenarios'],h,len(p['mass'])))
    schedule,info=solve(obs,demands)
    return schedule[0], dict(info,solver_calls=1)
