"""Behavioral checks against existing persona/first-stage inputs; no model bill."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import unittest

import run

EVIDENCE=Path(__file__).resolve().parent/'out'/'verification'


class DiffusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=json.loads((run.ROOT/'config/legacy_rules.json').read_text())
        cls.people,cls.seeds,cls.manifest,cls.meta=run.load_inputs(cls.c)
        cls.adj=run.network(cls.people,cls.c['network'],cls.c['seed'])
        EVIDENCE.mkdir(parents=True,exist_ok=True)
        cls.evidence={}

    def test_01_actual_first_stage_and_performance(self):
        started=time.perf_counter()
        adj=run.network(self.people,self.c['network'],self.c['seed'])
        result=run.simulate(self.people,self.seeds,adj,self.c)
        elapsed=time.perf_counter()-started
        self.assertEqual(len(self.people),2000)
        self.assertEqual(result['first_buyers'],116)
        self.assertEqual(result['history'][0]['cumulative_buyers'],116)
        self.assertEqual(len(result['history']),9)
        self.assertLess(elapsed,60)
        self.assertTrue(all(b['cumulative_buyers']>=a['cumulative_buyers'] for a,b in zip(result['history'],result['history'][1:])))
        self.assertTrue(all(r['cumulative_buyers']<=2000 for r in result['history']))
        self.evidence['rule_performance']={'seconds':elapsed,'n':2000,'rounds':8,'first_buyers':116,'final_buyers':result['history'][-1]['cumulative_buyers']}

    def test_02_reproducible_and_network(self):
        again=run.network(self.people,self.c['network'],self.c['seed'])
        self.assertEqual(again,self.adj)
        a=run.simulate(self.people,self.seeds,self.adj,self.c)
        b=run.simulate(self.people,self.seeds,self.adj,self.c)
        self.assertEqual(a,b)
        for i,edges in enumerate(self.adj):
            self.assertNotIn(i,edges)
            self.assertEqual(len(edges),len(set(edges)))
            self.assertTrue(all(i in self.adj[j] for j in edges))
        self.evidence['reproducibility']={'identical':True,'mean_friends':sum(map(len,again))/len(again),'history_sha256':hashlib.sha256(run.canonical(a['history']).encode()).hexdigest()}

    def test_03_config_changes_curve_and_no_exposure(self):
        low=copy.deepcopy(self.c);low['behavior']['purchase_multiplier']=0
        hi=copy.deepcopy(self.c);hi['behavior']['purchase_multiplier']=0.9
        a=run.simulate(self.people,self.seeds,self.adj,low);b=run.simulate(self.people,self.seeds,self.adj,hi)
        self.assertEqual(a['history'][-1]['cumulative_buyers'],116)
        self.assertGreater(b['history'][-1]['cumulative_buyers'],a['history'][-1]['cumulative_buyers'])
        no_view=copy.deepcopy(self.c);no_view['behavior']['view_probability']=0
        z=run.simulate(self.people,self.seeds,self.adj,no_view)
        self.assertEqual(z['history'][-1]['cumulative_buyers'],116)
        self.evidence['config_effect']={'zero_purchase':a['history'][-1]['cumulative_buyers'],'high_purchase':b['history'][-1]['cumulative_buyers'],'zero_view':z['history'][-1]['cumulative_buyers']}

    def test_04_types_change_and_missing_seed_rejected(self):
        c=copy.deepcopy(self.c);c['population']['use_input_traits']=False
        c['population']['ratios']={t:int(t=='innovator') for t in run.TYPES}
        people=copy.deepcopy(self.people);run.enrich(people,c)
        self.assertTrue(all(p['adopter']=='innovator' for p in people))
        x=run.simulate(people,self.seeds,self.adj,c)
        y=run.simulate(self.people,self.seeds,self.adj,self.c)
        self.assertNotEqual(x['history'][-1]['cumulative_buyers'],y['history'][-1]['cumulative_buyers'])
        c=copy.deepcopy(self.c);c['sample_files']=['demo/data/adults.json']
        with self.assertRaisesRegex(ValueError,'first buyers missing'):run.load_inputs(c)
        self.evidence['ratio_effect']={'all_innovator_final':x['history'][-1]['cumulative_buyers'],'default_final':y['history'][-1]['cumulative_buyers'],'missing_seed_rejected':True}

    def test_05_llm_success_caps_and_cache(self):
        c=copy.deepcopy(self.c);c['mode']='llm';c['llm'].update(max_people_total=6,max_people_per_round=4,max_calls_total=7)
        calls=[]
        def fake(system,user,schema,timeout):
            calls.append(user)
            if 'post' in schema['properties']:return {'post':True,'review':'시험용 가상 후기'}
            return {'action':'buy','reason':'시험용 가상 반응'}
        client=run.LLMClient(c['llm'],EVIDENCE/'success_cache',fake)
        result=run.simulate(self.people,self.seeds,self.adj,c,client)
        self.assertLessEqual(client.calls,7);self.assertLessEqual(len(client.people),6)
        by_week={}
        for e in client.events:by_week.setdefault(e['week'],set()).add(e['uuid'])
        self.assertTrue(all(len(v)<=4 for v in by_week.values()))
        self.assertTrue(result['examples'])
        def forbidden(*args,**kwargs):raise AssertionError('cache must avoid another call')
        replay=run.LLMClient(c['llm'],EVIDENCE/'success_cache',forbidden)
        other=run.simulate(self.people,self.seeds,self.adj,c,replay)
        self.assertEqual(result,other)
        run.save(EVIDENCE/'llm_stub_success.json',result)
        self.evidence['llm_stub_success']={'calls':client.calls,'unique_people':len(client.people),'max_people_in_round':max(map(len,by_week.values())),'examples':len(result['examples']),'cache_replay_identical':True,'live_model':False}

    def test_06_empty_llm_whole_round_fallback(self):
        c=copy.deepcopy(self.c);c['mode']='llm';c['llm'].update(max_people_total=20,max_people_per_round=4,max_calls_total=20)
        def empty(*args,**kwargs):return None
        client=run.LLMClient(c['llm'],EVIDENCE/'empty_cache',empty)
        result=run.simulate(self.people,self.seeds,self.adj,c,client)
        reference=run.simulate(self.people,self.seeds,self.adj,self.c)
        self.assertEqual(len(result['fallbacks']),8)
        for a,b in zip(result['history'],reference['history']):
            self.assertEqual({k:v for k,v in a.items() if k!='mode'},{k:v for k,v in b.items() if k!='mode'})
        self.assertEqual(result['events'],reference['events'])
        run.save(EVIDENCE/'llm_stub_failure.json',result)
        self.evidence['llm_empty_fallback']={'fallback_weeks':len(result['fallbacks']),'identical_to_rule_events':True,'calls':client.calls,'live_model':False}

    def test_07_validation_and_zero_budget(self):
        c=copy.deepcopy(self.c);c['population']['ratios']['innovator']=0.7
        with self.assertRaises(ValueError):run.validate(c)
        c=copy.deepcopy(self.c);c['behavior']['view_probability']=float('nan')
        with self.assertRaises(ValueError):run.validate(c)
        c=copy.deepcopy(self.c);c['mode']='llm';c['llm']['max_calls_total']=0
        def forbidden(*args,**kwargs):raise AssertionError('zero budget called model')
        client=run.LLMClient(c['llm'],EVIDENCE/'zero_cache',forbidden)
        result=run.simulate(self.people,self.seeds,self.adj,c,client)
        self.assertEqual(client.calls,0)
        self.assertTrue(all(r['mode']=='rules_budget_exhausted' for r in result['history'][1:]))

    def test_08_model_identity_separates_cache(self):
        c=copy.deepcopy(self.c);calls=[]
        def fake(*args,**kwargs):
            calls.append(1);return {'post':True,'review':'모델 경계 시험'}
        folder=EVIDENCE/'identity_cache'
        one=run.LLMClient(c['llm'],folder,fake,{'backend':'test','requested_model':'A','requested_effort':'low'})
        two=run.LLMClient(c['llm'],folder,fake,{'backend':'test','requested_model':'B','requested_effort':'low'})
        one.request(1,self.people[0],'review','test',{})
        two.request(1,self.people[0],'review','test',{})
        self.assertNotEqual(one.events[0]['key'],two.events[0]['key'])
        self.assertEqual(one.events[0]['requested_model_identity']['requested_model'],'A')
        self.assertEqual(two.events[0]['requested_model_identity']['requested_model'],'B')
        self.assertEqual(one.events[0]['actual_model_metadata'],'unknown')
        self.evidence['model_identity']={'different_model_distinct_cache':True,'requested_logged':True,'unknown_actual_explicit':True}

    def test_09_authorized_payload_excludes_identifiers(self):
        sent=[]
        def inspect(system,user,schema,timeout):
            obj=json.loads(user);sent.append(obj)
            self.assertEqual(set(obj['persona']),set(run.OUTBOUND_FIELDS))
            self.assertNotIn('uuid',obj['persona'])
            self.assertNotIn(self.people[0]['uuid'],user)
            return {'post':True,'review':'합성 인물 시험'}
        client=run.LLMClient(self.c['llm'],EVIDENCE/'allowlist_cache',inspect,{'backend':'payload-test','requested_model':'test','requested_effort':'none'})
        # Unique trial context ensures the inspected payload is emitted in this test invocation.
        context={'test_token':time.time_ns()}
        client.request(1,self.people[0],'review','public-test',context)
        self.assertEqual(len(sent),1)
        self.evidence['outbound_allowlist']={'uuid_absent':True,'allowlist_keys':list(run.OUTBOUND_FIELDS),'actual_transmission':False}

    def test_10_two_networks_and_shared_traits(self):
        c=copy.deepcopy(self.c);c['reaction_config']='population/config/adopter.json';c['reaction_mode']='two_axis_channel'
        people,seeds,_,meta=run.load_inputs(c);graphs=run.configured_network(people,c)
        self.assertEqual(set(graphs),{'sns','acquaintance_tv'})
        self.assertNotEqual(graphs['sns'],graphs['acquaintance_tv'])
        result=run.simulate(people,seeds,graphs,c)
        self.assertTrue(any(x['channels']['sns']['posts'] for x in result['history'][1:]))
        self.assertTrue(any(x['channels']['acquaintance_tv']['posts'] for x in result['history'][1:]))
        # Removing only the acquaintance graph changes its exposures without rewriting the SNS graph.
        blank={'sns':graphs['sns'],'acquaintance_tv':[[] for _ in people]}
        zero=run.simulate(people,seeds,blank,c)
        self.assertTrue(all(x['channels']['acquaintance_tv']['exposures']==0 for x in zero['history'][1:]))
        self.assertNotEqual(result['history'][-1]['cumulative_buyers'],zero['history'][-1]['cumulative_buyers'])
        self.evidence['dual_network']={'separate_graphs':True,'both_channels_post':True,'disabled_channel_zero_exposure':True,'baseline_final':result['history'][-1]['cumulative_buyers'],'channel_removed_final':zero['history'][-1]['cumulative_buyers'],'settings_mode':meta['reaction']['mode']}

    @classmethod
    def tearDownClass(cls):
        run.save(EVIDENCE/'checks.json',cls.evidence)


if __name__=='__main__':unittest.main(verbosity=2)
