"""Independent planner extension; original rolling implementation stays frozen."""
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from rolling_inventory.environment import carbon, validate
from rolling_inventory.planning import path_cost, base_stock


def credit_rates(p, fraction):
    if not 0 <= fraction < 1: raise ValueError('credit_fraction_outside_nonarbitrage_range')
    return fraction * np.asarray(p['mass']) * min(np.asarray(p['freight']) + p['carbon_price']*np.asarray(p['emissions']))


def window_budget(obs,h,allocation):
    p=obs['public'];rem=p['periods']-obs['t'];b=obs['carbon_remaining']
    if allocation=='uniform': return b*h/rem
    if allocation=='free': return float(b)
    if allocation!='forecast': raise ValueError('unknown_allocation')
    mass=np.asarray(p['mass']);f=np.asarray(obs['forecast'])@mass
    backlog=float(np.asarray(obs['backlog'])@mass)
    return b*(float(f[:h].sum())+backlog)/(float(f.sum())+backlog) if f.sum()+backlog else b*h/rem


def final_stock(obs,schedule,demand):
    p=obs['public'];h=len(demand);net=np.asarray(obs['stock'])-np.asarray(obs['backlog'])
    net=net.astype(float)+np.asarray(obs['pipeline'][obs['t']:obs['t']+h]).sum(axis=0)-np.asarray(demand).sum(axis=0)
    for u,a in enumerate(schedule):
        for j,lead in enumerate(p['lead']):
            if u+lead<h:net+=np.asarray(a)[:,j]
    return np.maximum(net,0.)


def credited_path_cost(obs,schedule,demand,fraction):
    value=path_cost(obs,schedule,demand)
    if obs['t']+len(demand)==obs['public']['periods']:
        value-=float(final_stock(obs,schedule,demand)@credit_rates(obs['public'],fraction))
    return value


def samples(obs,count,seed):
    h=min(obs['public']['horizon'],len(obs['forecast']));means=np.asarray(obs['forecast'][:h])
    return np.random.default_rng(seed+obs['t']).poisson(means,size=(count,*means.shape))


def solve(obs, demands, allocation="uniform", terminal_fraction=0.):
    p = obs['public']; demands = np.asarray(demands, dtype=float)
    rates=credit_rates(p,terminal_fraction)
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
                objective[ii(k,u,i)] = (p['holding'][i] - (rates[i]
                    if obs['t']+u == p['periods']-1 else 0))/s
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
    budget=window_budget(obs,h,allocation)
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
    physical=float(np.mean([credited_path_cost(obs,schedule,d,terminal_fraction) for d in demands]))
    if abs(physical-res.fun)>1e-5+1e-8*abs(physical): raise ValueError('MILP_objective_replay')
    return schedule.tolist(), {'objective':physical,'scenarios':s,'horizon':h,
                               'dispatch_variables':qn,'continuous_variables':2*ivn,
                               'window_carbon_budget':float(budget),'status':int(res.status),'mip_gap':float(res.mip_gap or 0)}



def decide(obs,variant,z):
    if variant['kind']=='base_stock':return base_stock(obs,z)
    h=min(obs['public']['horizon'],len(obs['forecast']))
    if variant['kind']=='mean':demands=np.asarray(obs['forecast'][:h])[None,:,:]
    elif variant['kind']=='scenario':demands=samples(obs,variant['count'],variant['sampler'])
    else:raise ValueError('oracle_requires_explicit_private_path')
    plan,info=solve(obs,demands,variant['allocation'],variant['fraction'])
    return plan[0],dict(info,solver_calls=1)
