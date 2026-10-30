"""Crossed inference, lossless records, grouped splits and freeze/replay binding."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from query_study.common import (config,read,write,read_lines,write_lines,pack_episodes,
                                expand_episodes,canonical,sha256,seal,LEARNED,BASELINES)
from query_study.statistics import paired_interval,summarize
from query_study import development,final


class QueryStudyTests(unittest.TestCase):
    def test_crossed_interval_preserves_constant_paired_difference(self):
        result=paired_interval(np.full((5,12),-.02),['a']*6+['b']*6,100,3)
        np.testing.assert_allclose(result['ci95'],[-.02,-.02])
        self.assertAlmostEqual(result['mean'],-.02)

    def test_seed_effect_does_not_disappear_when_cases_repeat(self):
        # Case duplication cannot manufacture many independent training seeds.
        small=np.repeat(np.array([[-1.],[-.5],[0.],[.5],[1.]]),10,axis=1)
        large=np.repeat(small,100,axis=1)
        a=paired_interval(small,['a']*10,1000,5)
        b=paired_interval(large,['a']*1000,1000,5)
        self.assertGreater(a['ci95'][1]-a['ci95'][0],.7)
        self.assertGreater(b['ci95'][1]-b['ci95'][0],.7)

    def test_pairing_is_order_invariant_and_coverage_is_strict(self):
        cfg=config(True);tasks=[{'id':'x','public':{'known_orders':[{}]*4,'delay_bits':2}}]
        rows=[{'method':m,'seed':s,'id':'x','regret':.1,'expected_loss':10.,'expected_queries':1.,'expected_milp_calls':1.}
              for m in (*LEARNED,*BASELINES) for s in ([None] if m in BASELINES else cfg['training_seeds'])]
        self.assertEqual(summarize(rows,tasks,cfg,'smoke'),summarize(rows[::-1],tasks,cfg,'smoke'))
        for invalid in (rows[:-1],rows+rows[:1]):
            with self.assertRaises(ValueError):summarize(invalid,tasks,cfg,'smoke')

    def test_frozen_thousand_is_unique_stratified_and_has_distinct_rng_streams(self):
        cfg=config();tasks=final.generate_tasks(cfg)
        self.assertEqual(len(tasks),1000)
        self.assertEqual(len({sha256(canonical(t['public'])) for t in tasks}),1000)
        counts={};streams=set()
        for t in tasks:
            n,k=len(t['public']['known_orders']),t['public']['delay_bits']
            counts[(n,k)]=counts.get((n,k),0)+1;streams.add(t['generator_seed']+100*n+10000*k)
        self.assertEqual(counts[(4,2)],112);self.assertEqual(sorted(counts.values()),[111]*8+[112])
        self.assertEqual(len(streams),1000)

    def test_final_is_disjoint_from_smoke_and_superseded_preflight(self):
        cfg=config();final_tasks=final.generate_tasks(cfg)
        old_cfg={**cfg,'final_generator_seed_start':10000}
        other=final.generate_tasks(config(True))+final.generate_tasks(old_cfg)
        content=lambda ts:{sha256(canonical(t['public'])) for t in ts}
        streams=lambda ts:{t['generator_seed']+100*len(t['public']['known_orders'])+10000*t['public']['delay_bits'] for t in ts}
        self.assertFalse(content(final_tasks)&content(other))
        self.assertFalse(streams(final_tasks)&streams(other))

    def test_compact_episode_roundtrip_keeps_all_original_values(self):
        from query_ppo.training import collect
        from query_ppo.algorithm import initialize_critic
        from query_ppo.experiment import initial_actor,config as pc
        from query_policy.solver import Planner
        tasks,_=development.datasets(True);train=[t for t in tasks if t['split']=='train'];cfg=pc(True)
        _,episodes=collect(train,{t['id']:Planner(t['public']) for t in train},initial_actor(),initialize_critic(18),cfg,np.random.default_rng(17),1)
        restored=expand_episodes(pack_episodes(episodes),train,cfg)
        self.assertEqual(episodes,restored)
        bad=pack_episodes(episodes);bad[0][3][-1][0]=-1
        with self.assertRaises(ValueError):expand_episodes(bad,train,cfg)

    def test_ablation_changes_exactly_the_declared_config_field(self):
        cfg=config(True);tasks,_=development.datasets(True);teachers=development.prepare_teachers(tasks)
        bc,runs=development.train_seed(17,tasks,teachers,cfg,True)
        by_name={name:payload for name,payload,_ in runs};base=by_name['ppo']
        for name,key in [('ppo_no_entropy','entropy_coefficient'),('ppo_lambda1','gae_lambda')]:
            differences={k for k in base['config'] if base['config'][k]!=by_name[name]['config'][k]}
            self.assertEqual(differences,{key});self.assertEqual(base['initial'],by_name[name]['initial'])
        self.assertEqual(base['initial']['actor'],bc['selected'])

    def test_freeze_does_not_execute_models_and_final_replays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d,f,o=(root/p for p in ('dev','freeze','final'))
            development.run(d,True);self.assertTrue(development.verify(d,False)['training_reexecuted'])
            with patch('query_study.final.evaluate_models',side_effect=AssertionError('no outputs before freeze')):
                result=final.freeze(d,f)
            self.assertFalse(result['final_outputs_computed'])
            final.run(d,f,o,'0'*40);self.assertTrue(final.verify(d,f,o)['statistics_recomputed'])
            with self.assertRaisesRegex(ValueError,'output_not_empty'):final.run(d,f,o,'0'*40)
            # Rehashing a mutated final cost must still fail model reexecution.
            rows=read_lines(o/'outcomes.jsonl');rows[0]['expected_loss']+=1
            write_lines(o/'outcomes.jsonl',rows)
            m=read(o/'manifest.json');m['files']['outcomes.jsonl']=sha256((o/'outcomes.jsonl').read_bytes());write(o/'manifest.json',m)
            with self.assertRaises(ValueError):final.verify(d,f,o)

    def test_rehashed_training_action_and_changed_frozen_model_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d,f=(root/p for p in ('dev','freeze'))
            development.run(d,True);final.freeze(d,f)
            path=d/'episodes/17-ppo.jsonl';original=path.read_bytes();rows=read_lines(path)
            rows[0][3][0][2]+=.1;write_lines(path,rows)
            m=read(d/'manifest.json');m['files']['episodes/17-ppo.jsonl']=sha256(path.read_bytes());write(d/'manifest.json',m)
            with self.assertRaises(ValueError):development.verify(d,False)
            with self.assertRaisesRegex(ValueError,'frozen_training_binding'):final.load_frozen(d,f)


if __name__=='__main__':unittest.main()
