"""Episode-safe GAE and independently differentiable NumPy PPO objectives."""
from __future__ import annotations

import numpy as np

from query_policy.model import probabilities


def gae(rewards, values, dones, gamma=1., lam=.95):
    rewards, values = np.asarray(rewards, float), np.asarray(values, float)
    dones = np.asarray(dones)
    if (rewards.ndim != 1 or rewards.shape != values.shape or dones.shape != values.shape
            or dones.dtype != bool or not len(rewards) or not dones[-1]
            or not np.isfinite(rewards).all() or not np.isfinite(values).all()
            or not 0 <= gamma <= 1 or not 0 <= lam <= 1):
        raise ValueError("complete_finite_episodes_required")
    advantages = np.zeros_like(rewards)
    carry = 0.
    for i in range(len(rewards)-1, -1, -1):
        next_value = 0. if dones[i] else values[i+1]
        residual = rewards[i] + gamma*next_value - values[i]
        carry = residual + gamma*lam*(not dones[i])*carry
        advantages[i] = carry
    return advantages, advantages+values


def actor_objective(parameters, x, mask, actions, old_logp, advantages, clip, entropy_coefficient):
    probs, hidden, logits = probabilities(parameters, x, mask)
    n = len(x); indices = np.arange(n)
    if (actions.shape != (n,) or not np.issubdtype(actions.dtype,np.integer)
            or (actions < 0).any() or (actions >= mask.shape[1]).any()
            or not mask[indices,actions].all()):
        raise ValueError("illegal_training_action")
    if (old_logp.shape != (n,) or advantages.shape != (n,)
            or not np.isfinite(old_logp).all() or not np.isfinite(advantages).all()):
        raise ValueError("nonfinite_training_targets")
    top = logits.max(axis=1, keepdims=True)
    logp = logits - top - np.log(np.exp(logits-top).sum(axis=1, keepdims=True))
    logp = np.where(mask, logp, 0.)
    logratio = logp[indices,actions] - old_logp
    ratio = np.exp(logratio)
    if not np.isfinite(ratio).all():
        raise ValueError("nonfinite_ratio")
    surrogate = np.minimum(ratio*advantages, np.clip(ratio,1-clip,1+clip)*advantages)
    entropy = -(probs*logp).sum(axis=1)
    active = np.where(advantages >= 0, ratio <= 1+clip, ratio >= 1-clip)
    chosen_gradient = -ratio*advantages*active/n
    gradient = -chosen_gradient[:,None]*probs
    gradient[indices,actions] += chosen_gradient
    gradient += entropy_coefficient*probs*(logp+entropy[:,None])/n
    delta = gradient[...,None]*parameters["v"]*(1-hidden**2)
    grads = {"w":np.einsum("baf,bah->fh",x,delta), "b":delta.sum(axis=(0,1)),
             "v":np.einsum("ba,bah->h",gradient,hidden)}
    metrics = {"policy_loss":float(-surrogate.mean()), "entropy":float(entropy.mean()),
               "approx_kl":float(np.mean(np.expm1(logratio)-logratio)),
               "clip_fraction":float(np.mean(np.abs(ratio-1)>clip))}
    return float(-surrogate.mean()-entropy_coefficient*entropy.mean()), grads, metrics


def initialize_critic(seed, hidden=32):
    rng = np.random.default_rng(seed)
    return {"w":rng.normal(0,1/np.sqrt(20),(20,hidden)), "b":np.zeros(hidden),
            "v":rng.normal(0,.01,hidden), "c":np.zeros(1)}


def value(parameters, states):
    hidden = np.tanh(states@parameters["w"]+parameters["b"])
    return hidden@parameters["v"]+parameters["c"][0], hidden


def critic_objective(parameters, states, old_values, returns, clip):
    predicted, hidden = value(parameters,states)
    difference = predicted-old_values
    clipped = old_values+np.clip(difference,-clip,clip)
    direct_error, clipped_error = predicted-returns, clipped-returns
    use_clipped = clipped_error**2 > direct_error**2
    derivative = np.where(use_clipped,clipped_error*(np.abs(difference)<clip),direct_error)/len(states)
    delta = derivative[:,None]*parameters["v"]*(1-hidden**2)
    gradients = {"w":states.T@delta, "b":delta.sum(axis=0), "v":hidden.T@derivative,
                 "c":np.asarray([derivative.sum()])}
    return float(.5*np.maximum(direct_error**2,clipped_error**2).mean()), gradients


class Adam:
    def __init__(self, parameters):
        self.m = {k:np.zeros_like(v) for k,v in parameters.items()}
        self.v = {k:np.zeros_like(v) for k,v in parameters.items()}
        self.steps = 0

    def step(self, parameters, gradients, learning_rate, divisor=1.):
        self.steps += 1
        for key in parameters:
            g = gradients[key]/divisor
            if not np.isfinite(g).all():
                raise ValueError("nonfinite_gradient")
            self.m[key] = .9*self.m[key]+.1*g
            self.v[key] = .999*self.v[key]+.001*g*g
            parameters[key] -= learning_rate*(self.m[key]/(1-.9**self.steps))/(np.sqrt(self.v[key]/(1-.999**self.steps))+1e-8)


def l2(a,b):
    return float(np.sqrt(sum(float(((a[k]-b[k])**2).sum()) for k in a)))


def decode_critic(payload):
    expected = {"w":(20,32),"b":(32,),"v":(32,),"c":(1,)}
    if set(payload) != set(expected):
        raise ValueError("critic_keys")
    result = {k:np.asarray(v,dtype=float) for k,v in payload.items()}
    if any(result[k].shape != shape or not np.isfinite(result[k]).all() for k,shape in expected.items()):
        raise ValueError("critic_shape_or_finiteness")
    return result
