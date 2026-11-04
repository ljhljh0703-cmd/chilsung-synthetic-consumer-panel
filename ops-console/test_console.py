"""Behavioral integration tests. Writes only ops-console/test-workspace and return evidence."""
import importlib.util,json,os,shutil,time,unittest,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent; REAL=ROOT.parent/'demo'; TEST=ROOT/'test-workspace'; RETURN=ROOT.parents[2]/'..' # explicit below
TEST.mkdir(exist_ok=True)
# Preserve previous evidence: each test invocation receives a new isolated workspace.
RUN=TEST/(time.strftime('%Y%m%d-%H%M%S')+'-'+str(time.time_ns()%1000000)); D=RUN/'demo'; S=RUN/'state'
D.mkdir(parents=True);S.mkdir()
for name in ['run_experiment.py','simulate.py','known_eval.py','ingest.py','llm.py']:
 shutil.copy2(REAL/name,D/name)
for name in ['config','data','experiments']:
 shutil.copytree(REAL/name,D/name)
for name in ['T0','T1']:
 shutil.copytree(REAL/'results'/name,D/'results'/name)
os.environ.update(OPS_PROJECT_ROOT=str(RUN),OPS_DEMO_ROOT=str(D),OPS_STATE_DIR=str(S),OPS_ALLOW_STUB='1',OPS_PYTHON='/private/tmp/lotte-l6-env/bin/python')
spec=importlib.util.spec_from_file_location('console_server',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def test_01_verdict(self):
  good={k:'pass' for k in ['reproduction','baseline','leakage','stability','noise','card_sensitivity']}
  self.assertEqual(m.verdict(good)['label'],'신뢰')
  for fail in ['reproduction','baseline','leakage']:
   self.assertEqual(m.verdict({**good,fail:'fail'})['label'],'포기')
   self.assertFalse(m.verdict({**good,fail:'fail'})['show_rank'])
  self.assertEqual(m.verdict({})['label'],'판정 대기')
  self.assertEqual(m.verdict({**good,'stability':'fail'})['label'],'보정')
 def test_02_intake_and_permissions(self):
  with self.assertRaises(ValueError):m.mutate('experiment',{'name':'OPS_forbidden'})
  self.r=m.mutate('cards',{'category':'맥주','products':[{'id':'test_a','real_name':'시험 시안','attrs':{'종류':'라거','컨셉':'연결 시험'}},{'id':'test_b','real_name':'시험 경쟁','attrs':{'종류':'라거','컨셉':'연결 시험'}}]})
  self.assertTrue((D/self.r['csv']).exists());self.assertEqual(len(m.read(D/self.r['sets_file'])[0]['products']),2)
  m.mutate('role',{'role':'조사 담당'})
  with self.assertRaises(ValueError):m.mutate('experiment',{'name':'../escape'})
 def test_03_runner_and_lock(self):
  p=m.mutate('experiment',{'name':'OPS_smoke','n':3,'category':'전체','batch':1})
  frozen=m.read(D/p['sets_file'])
  self.assertEqual(len(frozen),5)
  self.assertNotIn('product_ids',frozen[0]);self.assertTrue(frozen[0]['products'])
  original_card=m.read(D/'config/sets.json');original_card[0]['products'][0]['attrs']['컨셉']='외부 원본 변화 시험'
  m.dump(D/'config/sets.json',original_card)
  self.assertEqual(m.read(D/p['sets_file']),frozen)
  m.mutate('run',{'name':'OPS_smoke','stub':True,'confirmed':True})
  deadline=time.time()+30
  while 'OPS_smoke' in m.JOBS and time.time()<deadline:time.sleep(.1)
  self.assertEqual(m.state()['jobs']['OPS_smoke']['status'],'끝')
  self.assertTrue((D/'results/OPS_smoke/spec_locked.json').exists())
  self.assertIn('STUB:',(D/'results/OPS_smoke/settings.json').read_text())
  for f in (D/'results/OPS_smoke').glob('*.jsonl'):self.assertEqual(len(f.read_text().splitlines()),3)
  with self.assertRaises(ValueError):m.mutate('run',{'name':'OPS_smoke','stub':True,'confirmed':True})
 def test_04_existing_metrics(self):
  d=m.detail('T0');self.assertEqual(d['metrics']['이름가림·선택비율']['pair_acc'],.667)
  self.assertIn('0.667',d['report']);self.assertEqual(d['checks']['reproduction'],'unknown')
  m.mutate('decision',{'name':'T0','decision':'승인','route':'사람 조사','memo':'시험: 미확인 결과의 사람 조사 전환'})
  m.mutate('decision',{'name':'T0','decision':'반려','memo':'시험: 점검 미완료'})
 def test_05a_bad_inputs(self):
  m.mutate('role',{'role':'조사 담당'})
  r=m.state()['receipts'][0]
  spec=m.mutate('experiment',{'name':'OPS_new_blocked','receipt':r['id'],'n':2,'batch':1,'validation_reference':'T0'})
  with self.assertRaises(ValueError):m.mutate('run',{'name':spec['name'],'stub':True,'confirmed':True})
  with self.assertRaises(ValueError):m.mutate('decision',{'name':'T0','decision':'승인','route':'자동 출시','memo':'시험'})
 def test_05_survey(self):
  body='set_id,respondent_id,choice_product_id\nbeer_2019_known,H1,cass_2019\nbeer_2019_known,H2,hite_2019\n'
  x=m.mutate('survey',{'name':'T0','csv':body});self.assertTrue((D/'experiments'/f"{x['id']}.json").exists())
  self.assertEqual(m.read(D/x['truth_file'])['beer_2019_known']['value']['cloud_2019'],0)
  with self.assertRaises(ValueError):m.mutate('calibration',{'id':x['id']})
  before=m.response_fingerprint('T0')
  self.assertEqual(m.detail('T0')['calibrated']['status'],'미적용')
  m.mutate('role',{'role':'데이터 담당'});m.mutate('calibration',{'id':x['id']})
  c=m.detail('T0')['calibrated'];self.assertEqual(c['status'],'적용')
  vals=c['shelves']['beer_2019_known'];self.assertAlmostEqual(sum(v['after'] for v in vals.values()),1)
  self.assertAlmostEqual(vals['cass_2019']['after'],.5);self.assertEqual(before,m.response_fingerprint('T0'))
  self.assertTrue((S/'calibration'/f"{x['id']}.json").exists())
  # Calibration is invalidated if response files change after approval.
  existing=next((D/'results/T0').glob('*.jsonl'))
  with existing.open('a') as f:f.write(existing.read_text().splitlines()[0]+'\n')
  self.assertEqual(m.detail('T0')['calibrated']['status'],'재검증 필요')
  audit=[json.loads(x) for x in (S/'audit.log').read_text().splitlines()]
  self.assertTrue({'승인','반려','역할 변경','보정 승인','실행 종료'} <= {x['action'] for x in audit})
if __name__=='__main__':
 print('Evidence workspace:',RUN,flush=True)
 unittest.main(verbosity=2)
