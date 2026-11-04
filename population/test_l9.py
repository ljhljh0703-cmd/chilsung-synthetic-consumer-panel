import copy,json,sys,tempfile,unittest
from pathlib import Path
from traits import KeywordScorer,reaction_values,validate_settings,RATIOS
from assignment import adjusted_order,assign,correlation
ROOT=Path(__file__).resolve().parent
class Tests(unittest.TestCase):
 def setUp(self):
  self.cfg=json.loads((ROOT/'config/adopter.json').read_text());self.scorer=KeywordScorer(ROOT/self.cfg['keywords_file'])
 def test_comparison_and_avoidance(self):
  score,hits=self.scorer.score({'persona':'새로운 메뉴에 도전하기보다 검증된 맛을 찾는다.','age':30},self.cfg)
  self.assertNotIn('새로움 추구',hits);self.assertIn('새것 회피·신중',hits);self.assertLess(score,0)
 def test_valid_later_match_and_punctuation(self):
  _,hits=self.scorer.score({'persona':'전시보다는 산책. 그러나 새로운 메뉴를 먹는다.','age':30},self.cfg)
  self.assertIn('새로움 추구',hits);self.assertNotIn('쾌락·경험 소비',hits)
 def test_negative_lookahead(self):
  _,hits=self.scorer.score({'persona':'커리어와 수제비를 좋아한다.','age':30},self.cfg)
  self.assertNotIn('맛 탐색·다양성 추구',hits);self.assertNotIn('주류·음료 관여',hits)
 def test_missing_and_disabled_dictionary(self):
  s=KeywordScorer(ROOT/'config/does-not-exist.json');self.assertTrue(s.missing)
  self.assertEqual(s.score({'age':30},self.cfg),(0.,[]))
  s=KeywordScorer(ROOT/self.cfg['keywords_file'],False);self.assertEqual(s.score({'persona':'신제품','age':30},self.cfg),(0.,[]))
 def test_reaction_modes(self):
  a={'age':25,'adopter':'early_adopter'};b={'age':75,'adopter':'early_adopter'}
  va=reaction_values(a,self.cfg);vb=reaction_values(b,self.cfg)
  self.assertEqual(va['viral_sensitivity'],vb['viral_sensitivity']);self.assertNotEqual(va['viral_channel'],vb['viral_channel'])
  self.assertGreater(reaction_values(a,self.cfg,'two_axis_age')['viral_sensitivity'],reaction_values(b,self.cfg,'two_axis_age')['viral_sensitivity'])
  z=reaction_values(a,self.cfg,'single_axis');self.assertEqual(z['launch_sensitivity'],z['viral_sensitivity'])
 def test_settings(self):
  validate_settings(self.cfg)
  for key,value in [('sex_balance','drinker_ratio'),('reaction_mode','made_up'),('age_tilt',1.01)]:
   x=copy.deepcopy(self.cfg);x[key]=value
   with self.assertRaises(ValueError):validate_settings(x)
  x=copy.deepcopy(self.cfg);x['ratios']['innovator']=.1
  with self.assertRaises(ValueError):validate_settings(x)
 def test_age_tilt_and_sex(self):
  rows=[(100-i,str(i).zfill(5),'u'+str(i),20 if i<100 else 60,'여자' if i%2 else '남자') for i in range(200)]
  one,_=adjusted_order(rows,1);zero,scores=adjusted_order(rows,0)
  self.assertEqual(one[0][2],'u0');self.assertAlmostEqual(correlation([scores[r[2]] for r in rows],[r[3] for r in rows]),0,places=8)
  labels={}
  for sex in ('남자','여자'):labels.update(assign([r for r in zero if r[4]==sex],RATIOS))
  for typ in RATIOS:
   members=[r for r in rows if labels[r[2]]==typ];self.assertEqual(sum(r[4]=='여자' for r in members)*2,len(members))
if __name__=='__main__':unittest.main()
