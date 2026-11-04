"""14:00/14:30 config UI API: isolated fixture only, never edits shared L6/L7 config."""
import copy,importlib.util,json,os,shutil,sys,time,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent;PROJECT=HERE.parent
RUN=HERE/'test-workspace'/('config-'+str(time.time_ns()));RUN.mkdir(parents=True)
for folder in ['population/config','diffusion/config','demo/config','demo/experiments']:
 shutil.copytree(PROJECT/folder,RUN/folder)
for filename in ['diffusion/run.py','diffusion/plot_png.py','population/traits.py']:
 shutil.copy2(PROJECT/filename,RUN/filename)
os.environ.update(OPS_PROJECT_ROOT=str(RUN),OPS_DEMO_ROOT=str(RUN/'demo'),OPS_STATE_DIR=str(RUN/'state'))
spec=importlib.util.spec_from_file_location('config_console',HERE/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ConfigTests(unittest.TestCase):
 def test_01_read_and_role(self):
  inv=m.config_editor.inventory(RUN);self.assertEqual(inv['population']['status'],'사용 가능');self.assertTrue(inv['diffusion'])
  p=inv['population'];c=copy.deepcopy(p['data']);c['reaction_mode']='single_axis'
  with self.assertRaises(ValueError):m.mutate('config',{'kind':'population','name':'adopter.json','sha256':p['sha256'],'data':c})
  m.mutate('role',{'role':'데이터 담당'})
  c.update(keyword_enabled=False,age_signal_enabled=True,age_tilt=.3,sex_balance='none')
  result=m.mutate('config',{'kind':'population','name':'adopter.json','sha256':p['sha256'],'data':c})
  self.assertEqual(result['data'],c)
  with self.assertRaises(ValueError):m.mutate('config',{'kind':'population','name':'adopter.json','sha256':p['sha256'],'data':p['data']})
 def test_02_fixed_ratios_and_limits(self):
  p=m.config_editor.get(RUN,'population','adopter.json')
  for key,value in [('age_tilt',1.1),('age_tilt',float('nan')),('reaction_mode','unknown'),('ratios',{})]:
   c=copy.deepcopy(p['data']);c[key]=value
   with self.assertRaises(ValueError):m.mutate('config',{'kind':'population','name':'adopter.json','sha256':p['sha256'],'data':c})
  self.assertEqual(m.config_editor.get(RUN,'population','adopter.json')['sha256'],p['sha256'])
  with self.assertRaises(ValueError):m.config_editor.get(RUN,'diffusion','../../outside.json')
 def test_03_diffusion_copy_and_lock(self):
  p=m.config_editor.get(RUN,'diffusion','default.json');c=copy.deepcopy(p['data']);c['n']=100;c['reaction_mode']='two_axis_age'
  locked=RUN/'diffusion/out/existing/input_locked.json';locked.parent.mkdir(parents=True);locked.write_text(json.dumps({'config':p['data']}))
  with self.assertRaises(ValueError):m.mutate('config',{'kind':'diffusion','name':'default.json','sha256':p['sha256'],'data':c})
  out=m.mutate('config',{'kind':'diffusion','name':'default.json','sha256':p['sha256'],'new_name':'ops_variant.json','data':c});self.assertEqual(out['data']['n'],100)
  bad=copy.deepcopy(c);bad['sample_files']=['../../private.json']
  with self.assertRaises(ValueError):m.mutate('config',{'kind':'diffusion','name':'ops_variant.json','sha256':out['sha256'],'data':bad})
 def test_04_experiment_snapshot(self):
  m.mutate('role',{'role':'조사 담당'})
  spec=m.mutate('experiment',{'name':'OPS_config_snapshot','n':3,'batch':1,'diffusion_config':'ops_variant.json'})
  refs=spec['ops_config_refs'];self.assertEqual(set(refs),{'population','diffusion'})
  snap=m.STATE/refs['population']['snapshot'];before=snap.read_bytes()
  m.mutate('role',{'role':'데이터 담당'});p=m.config_editor.get(RUN,'population','adopter.json');c=copy.deepcopy(p['data']);c['reaction_mode']='two_axis_channel'
  m.mutate('config',{'kind':'population','name':'adopter.json','sha256':p['sha256'],'data':c})
  self.assertEqual(before,snap.read_bytes())
  self.assertTrue(list((m.STATE/'config-history').glob('*.json')))
if __name__=='__main__':
 print('Config fixture:',RUN,flush=True);unittest.main(verbosity=2)
