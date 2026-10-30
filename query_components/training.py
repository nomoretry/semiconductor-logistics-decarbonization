"""Same PPO optimizer with explicit mask, rejection and potential transitions."""
from __future__ import annotations
import numpy as np
from notice_benchmark.api_runner import canonical_bytes as canonical, sha256
from query_policy.model import probabilities
from query_policy.solver import Planner
from query_ppo.algorithm import Adam, actor_objective, critic_objective, gae, initialize_critic, l2, value
from query_ppo.training import copy_parameters, checkpoint as raw_checkpoint
from .environment import inputs, step, tree


def collect(tasks, models, actor, critic, cfg, rng, iteration, fitted=None):
    episodes, rows = [], []
    for t in tasks:
        model = models[t["id"]]
        for repeat in range(cfg["episodes_per_context"]):
            h = (-1,)*model.k; steps = []
            while True:
                x, legal, mask = inputs(t["public"], h, cfg["action_mask"])
                if legal.tolist() != [True,*[i in model.legal(h) for i in range(model.k)]]:
                    raise ValueError("independent_mask_mismatch")
                probs,_,logits = probabilities(actor,x,mask)
                action = int(rng.choice(len(mask),p=probs))
                logp = float(logits[action]-np.logaddexp.reduce(logits))
                v = float(value(critic,x[0,:20])[0]); answer = None
                if action and legal[action]:
                    answer = int(rng.random() < t["public"]["prior"][action-1])
                transition = step(model,h,action,answer,cfg,fitted)
                record = {"history":list(h),"action":action,"answer":answer,
                          "old_logp":logp,"old_value":v,**transition}
                steps.append(record)
                rows.append((x,mask,action,logp,v,transition["reward"],transition["done"]))
                if transition["done"]:break
                h = tuple(transition["next_history"])
                if len(steps)>t["public"]["max_queries"]:raise ValueError("unbounded_episode")
            adv,ret=gae([s["reward"] for s in steps],[s["old_value"] for s in steps],
                        np.array([s["done"] for s in steps]),cfg["gamma"],cfg["gae_lambda"])
            for s,a,r in zip(steps,adv,ret):s.update(advantage=float(a),value_target=float(r))
            # With gamma=1 and terminal phi=0, shaping sums to -phi(initial).
            if abs(sum(s["shaping_reward"] for s in steps)+steps[0]["phi_before"])>1e-10:
                raise ValueError("potential_did_not_telescope")
            episodes.append({"iteration":iteration,"id":t["id"],"repeat":repeat,"steps":steps})
    width=max(len(row[1]) for row in rows); size=len(rows)
    x=np.zeros((size,width,37)); mask=np.zeros((size,width),bool)
    for i,row in enumerate(rows):x[i,:len(row[1])]=row[0];mask[i,:len(row[1])]=row[1]
    advantages,returns=gae([r[5] for r in rows],[r[4] for r in rows],
                           np.array([r[6] for r in rows]),cfg["gamma"],cfg["gae_lambda"])
    normalized=(advantages-advantages.mean())/max(advantages.std(),1e-8)
    data=(x,mask,np.asarray([r[2] for r in rows]),np.asarray([r[3] for r in rows]),
          normalized,np.asarray([r[4] for r in rows]),returns)
    return data,episodes


def dev_cost(tasks,models,actor,cfg):
    costs=[]
    for t in tasks:
        r=tree(t["public"],actor,cfg["action_mask"],cfg["invalid_action_penalty"],models[t["id"]],False)
        costs.append({"id":t["id"],"expected_loss":r["expected_loss"]})
    return float(np.mean([r["expected_loss"] for r in costs])),costs


def train(tasks, initial_actor, cfg, fitted=None, verbose=False):
    checkpoints = []
    def checkpoint(actor, critic):
        payload = raw_checkpoint(actor, critic)
        checkpoints.append(payload)
        return payload
    train_tasks = [t for t in tasks if t["split"]=="train"]
    dev_tasks = [t for t in tasks if t["split"]=="dev"]
    # No evaluation contexts or teacher labels can enter this training boundary.
    if len(train_tasks)+len(dev_tasks) != len(tasks) or not train_tasks or not dev_tasks:
        raise ValueError("training_accepts_only_train_and_dev")
    actor = copy_parameters(initial_actor);critic = initialize_critic(cfg["training_seed"]+1)
    initial = checkpoint(actor,critic);best = initial
    actor_optimizer,critic_optimizer = Adam(actor),Adam(critic)
    rng = np.random.default_rng(cfg["training_seed"])
    models = {t["id"]:Planner(t["public"]) for t in tasks}
    best_loss,dev_rows = dev_cost(dev_tasks,models,actor,cfg);selected = 0
    validations = [{"iteration":0,"mean_expected_loss":best_loss,"contexts":dev_rows,
                    "checkpoint_sha256":sha256(canonical(initial))}]
    logs,trajectories = [],[]
    for iteration in range(1,cfg["iterations"]+1):
        data,episodes = collect(train_tasks,models,actor,critic,cfg,rng,iteration,fitted)
        x,mask,actions,oldlog,advantages,oldvalues,returns = data
        updates_before = actor_optimizer.steps;batch_logs=[];early_stop=False
        for epoch in range(cfg["update_epochs"]):
            order = rng.permutation(len(x))
            for start in range(0,len(order),cfg["minibatch_size"]):
                idx = order[start:start+cfg["minibatch_size"]]
                _,ag,_ = actor_objective(actor,x[idx],mask[idx],actions[idx],oldlog[idx],advantages[idx],
                                         cfg["ratio_clip"],cfg["entropy_coefficient"])
                _,cg = critic_objective(critic,x[idx,0,:20],oldvalues[idx],returns[idx],cfg["value_clip"])
                cg = {k:v*cfg["value_coefficient"] for k,v in cg.items()}
                norm = np.sqrt(sum(float((v*v).sum()) for v in [*ag.values(),*cg.values()]))
                if not np.isfinite(norm):
                    raise ValueError("nonfinite_gradient")
                divisor = max(1.,norm/cfg["max_grad_norm"])
                actor_optimizer.step(actor,ag,cfg["learning_rate"],divisor)
                critic_optimizer.step(critic,cg,cfg["learning_rate"],divisor)
                # Log full rollout-batch diagnostics after every actual update.
                loss,_,metrics = actor_objective(actor,x,mask,actions,oldlog,advantages,cfg["ratio_clip"],cfg["entropy_coefficient"])
                value_loss,_ = critic_objective(critic,x[:,0,:20],oldvalues,returns,cfg["value_clip"])
                batch_logs.append({"update":actor_optimizer.steps,"epoch":epoch+1,"actor_loss":loss,
                                   "value_loss":value_loss,"gradient_norm":float(norm),**metrics})
                if metrics["approx_kl"] > cfg["target_kl"]:
                    early_stop=True;break
            if early_stop:
                break
        trajectories.extend(episodes)
        row = {"iteration":iteration,"episodes":len(episodes),"steps":len(x),
               "updates":actor_optimizer.steps-updates_before,"total_updates":actor_optimizer.steps,
               "early_stop_kl":early_stop,"sample_mean_cost":float(np.mean([-sum(s["base_reward"] for s in e["steps"])*cfg["reward_scale"] for e in episodes])),
               "actor_l2_from_bc":l2(actor,initial_actor),"updates_log":batch_logs}
        logs.append(row)
        if iteration%cfg["evaluate_every"]==0 or iteration==cfg["iterations"]:
            loss,dev_rows = dev_cost(dev_tasks,models,actor,cfg)
            current = checkpoint(actor,critic)
            validations.append({"iteration":iteration,"mean_expected_loss":loss,"contexts":dev_rows,
                                "checkpoint_sha256":sha256(canonical(current))})
            if loss < best_loss-1e-10:
                best_loss,selected,best = loss,iteration,current
            if verbose:
                print(f"PPO iteration {iteration}/{cfg['iterations']}: validation cost {loss:.6f}; selected {selected}",flush=True)
    final = checkpoint(actor,critic)
    from query_policy.model import deserialize
    training = {"iterations":logs,"validation":validations,"selected_iteration":selected,
                "total_updates":actor_optimizer.steps,"episodes":len(trajectories),
                "sampled_steps":sum(r["steps"] for r in logs),
                "selected_actor_l2_from_bc":l2(deserialize(best["actor"],32),initial_actor),
                "last_actor_l2_from_bc":l2(actor,initial_actor),
                "offline_terminal_milp_calls":{split:sum(models[t["id"]].calls for t in tasks if t["split"]==split) for split in ("train","dev")}}
    return initial,best,final,training,trajectories,checkpoints
