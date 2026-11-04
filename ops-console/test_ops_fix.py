"""L16 regression and new-concept end-to-end fixtures. Never calls a real model."""
import copy,importlib.util,json,os,shutil,time,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent;REAL=HERE.parent;OUT=REAL.parent.parent/'wiki/projects/lotte-ax-2026-returns/2026-11-04-ops-fix'
RUN=HERE/'test-workspace'/('opsfix-'+str(time.time_ns()));D=RUN/'demo';D.mkdir(parents=True)
for filename in ['run_experiment.py','simulate.py','known_eval.py','known_eval_dual.py','ingest.py','llm.py']:shutil.copy2(REAL/'demo'/filename,D/filename)
for folder in ['config','data']:shutil.copytree(REAL/'demo'/folder,D/folder)
(D/'experiments').mkdir();(D/'results').mkdir()
os.environ.update(OPS_PROJECT_ROOT=str(RUN),OPS_DEMO_ROOT=str(D),OPS_STATE_DIR=str(RUN/'state'),OPS_ALLOW_STUB='1',OPS_PYTHON='/private/tmp/lotte-l6-env/bin/python')
spec=importlib.util.spec_from_file_location('ops_fix_server',HERE/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
evidence={'scope':'isolated synthetic fixture; no real model calls','workspace':str(RUN),'steps':[]}
class FixTests(unittest.TestCase):
 def test_01_real_T4_primary_and_T2_sensitivity_read_only(self):
  with patch.object(m,'DEMO',REAL/'demo'),patch.object(m,'PROJECT',REAL):
   x=m.detail('T4');v=x['metrics'][x['metric_key']]
   self.assertEqual(x['primary_metric'],'usual');self.assertEqual(v['weak_pair_acc'],.786)
   self.assertEqual(x['secondary_metrics'][x['metric_key']]['weak_pair_acc'],.679)
   self.assertEqual(x['verdict']['display_label'],'보류')
   counts=[sh['valid_n'] for sh in x['primary_observations']['shelves'].values()]
   self.assertEqual(counts,[1,53,76,0,3]);self.assertTrue(x['cautions'])
   pair=m.analytics.sensitivity(m.DEMO,'T2','T3');self.assertEqual(pair['changed'],3);self.assertAlmostEqual(pair['max_shift_pp'],51.31856540084387)
   self.assertEqual(m.analytics.sensitivity(m.DEMO,'T4','T2')['status'],'unknown')
   evidence['real_read_only']={'T4_primary_weak':v['weak_pair_acc'],'valid_choices':counts,'T2_T3':pair,'T4_T2':'unknown: unlike conditions'}
 def test_02_profile_defaults_and_cycle_guards(self):
  info=m.analytics.profile_balance([{'id':'a','attrs':dict.fromkeys(m.ATTRS,'x')},{'id':'b','attrs':{'종류':'라거','컨셉':'간단'}}]);self.assertTrue(info['unbalanced']);self.assertEqual([len(x['filled']) for x in info['rows']],[7,2])
  for name,ref in [('OPS_cycle_a','OPS_cycle_b'),('OPS_cycle_b','OPS_cycle_a'),('OPS_missing','OPS_absent')]:m.dump(D/'experiments'/f'{name}.json',{'name':name,'n':1,'validation_reference':ref})
  self.assertEqual(m.detail('OPS_cycle_a')['checks']['reproduction'],'unknown');self.assertEqual(m.detail('OPS_missing')['checks']['reproduction'],'unknown')
  good={k:'pass' for k in ['reproduction','baseline','leakage','stability','noise','card_sensitivity']}
  self.assertEqual(m.verdict(good)['display_label'],'신뢰')
  self.assertNotEqual(m.verdict({**good,'card_sensitivity':'unknown'})['display_label'],'신뢰')
  self.assertNotEqual(m.verdict({**good,'card_sensitivity':'fail'})['display_label'],'신뢰')
  self.assertEqual(m.verdict({**good,'reproduction':'unknown','card_sensitivity':'fail'})['display_label'],'판정 대기')
 def test_03_new_concept_full_journey(self):
  m.mutate('role',{'role':'조사 담당'})
  bench=m.mutate('experiment',{'name':'OPS_BENCH_FIXTURE','n':30,'category':'전체'})
  self.assertIn('--per-person-order',bench['flags']);self.assertEqual(bench['flags'][bench['flags'].index('--batch')+1],'5')
  truth=m.read(D/bench['truth_file']);out=D/'results'/bench['name'];out.mkdir()
  for sid,t in truth.items():
   if sid.startswith('_'):continue
   ids=sorted(t['value'],key=t['value'].get,reverse=True);counts={3:[17,9,4],4:[15,8,5,2],5:[12,8,5,3,2]}[len(ids)];votes=[pid for pid,n in zip(ids,counts) for _ in range(n)]
   (out/(sid+'.jsonl')).write_text('\n'.join(json.dumps({'uuid':'fixture-'+str(i),'rep':0,'choice':p,'named':False,'model':'STUB:benchmark'}) for i,p in enumerate(votes))+'\n')
  self.assertEqual(m.detail(bench['name'])['checks']['reproduction'],'pass')
  m.mutate('role',{'role':'BM'})
  receipt=m.mutate('cards',{'category':'맥주','products':[{'id':'new_concept','real_name':'합성 연결 시험 콘셉트','attrs':dict.fromkeys(m.ATTRS,'시험용')},{'id':'competitor','real_name':'합성 연결 시험 경쟁 제품','attrs':{'종류':'라거','컨셉':'시험용'}}]})
  self.assertTrue(receipt['profile_balance']['unbalanced']);evidence['steps'].append({'step':'concept_received','receipt':receipt})
  m.mutate('role',{'role':'조사 담당'});fresh=m.mutate('experiment',{'name':'OPS_NEW_FIXTURE','n':30,'receipt':receipt['id'],'validation_reference':bench['name']})
  self.assertIsNone(fresh['truth_file']);self.assertEqual(m.detail(fresh['name'])['checks']['reproduction'],'pass')
  m.mutate('run',{'name':fresh['name'],'stub':True,'confirmed':True})
  end=time.time()+30
  while fresh['name'] in m.JOBS and time.time()<end:time.sleep(.1)
  self.assertEqual(m.state()['jobs'][fresh['name']]['status'],'끝')
  x=m.detail(fresh['name']);self.assertTrue(x['raw_choice']['complete']);self.assertEqual(x['checks']['reproduction'],'pass')
  evidence['steps'].append({'step':'synthetic_simulation_complete','job':m.state()['jobs'][fresh['name']],'raw_choice':x['raw_choice']})
  m.mutate('decision',{'name':fresh['name'],'decision':'승인','route':'사람 조사','memo':'가짜 응답 흐름 시험. 실제 업무 승인이 아닙니다.'})
  sid=receipt['id'];csv='set_id,respondent_id,choice_product_id\n'+'\n'.join(f"{sid},H{i},{'new_concept' if i%2 else 'competitor'}" for i in range(20))
  survey=m.mutate('survey',{'name':fresh['name'],'csv':csv});self.assertEqual(m.detail(fresh['name'])['calibrated']['status'],'미적용')
  before=m.response_fingerprint(fresh['name']);m.mutate('role',{'role':'데이터 담당'});m.mutate('calibration',{'id':survey['id']})
  calibrated=m.detail(fresh['name'])['calibrated'];self.assertEqual(calibrated['status'],'적용')
  for value in calibrated['shelves'][sid].values():self.assertAlmostEqual(value['after'],.5)
  self.assertEqual(before,m.response_fingerprint(fresh['name']))
  evidence['steps'].append({'step':'calibration_approved','survey':survey['id'],'calibrated':calibrated,'original_response_preserved':True})
  # A later benchmark failure must propagate without changing concept responses.
  for sid,t in truth.items():
   if sid.startswith('_'):continue
   bad=min(t['value'],key=t['value'].get);(out/(sid+'.jsonl')).write_text('\n'.join(json.dumps({'uuid':'fixture-'+str(i),'rep':0,'choice':bad}) for i in range(30))+'\n')
  self.assertEqual(m.detail(fresh['name'])['checks']['reproduction'],'fail');self.assertEqual(m.detail(fresh['name'])['verdict']['display_label'],'보류')
  evidence['benchmark_failure_inherited']=True
 @classmethod
 def tearDownClass(cls):
  OUT.mkdir(parents=True,exist_ok=True);(OUT/'end-to-end.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
if __name__=='__main__':unittest.main(verbosity=2)
