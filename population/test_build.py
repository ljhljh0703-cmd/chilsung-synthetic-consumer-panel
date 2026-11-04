"""Hand-check statistical contracts; fixture counts are not official statistics."""
import importlib.util, math, tempfile, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('population_build',Path(__file__).with_name('build.py'))
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class Contracts(unittest.TestCase):
    def test_quota_remainder(self):
        q=b.quotas(2000,dict(zip(b.TYPES,[.025,.135,.34,.34,.16])))
        self.assertEqual(list(q.values()),[50,270,680,680,320])
        self.assertEqual(sum(b.quotas(7,dict(zip(b.TYPES,[.025,.135,.34,.34,.16]))).values()),7)
    def test_invalid_ratios(self):
        for ratios in [{t:0 for t in b.TYPES},{t:float('nan') for t in b.TYPES}]:
            with self.assertRaises(ValueError):b.quotas(2000,ratios)
    def test_cell_boundaries(self):
        self.assertEqual(b.band(19),'10');self.assertEqual(b.band(20),'20');self.assertEqual(b.band(99),'90')
        self.assertEqual(b.canonical('강원도'),'강원특별자치도')
    def test_signal_has_trace(self):
        cfg={'signals':[{'id':'new','fields':['persona'],'keywords':['신상'],'score':3},{'id':'young','age_min':19,'age_max':39,'score':1}]}
        self.assertEqual(b.signal({'persona':'신상을 본다','age':30},cfg),(4.,['new','young']))
        self.assertEqual(b.signal({'persona':'익숙한 것을 먹는다','age':50},cfg),(0.,[]))
    def test_duplicates_are_not_summed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cells.csv';p.write_text('province,sex,age_band,population\n서울특별시,남자,20,20\n서울특별시,남자,20,30\n')
            with self.assertRaises(ValueError):b.load_targets(p)
    def test_weighting_hand_calculation(self):
        # 75/25 source, 40/60 target => weights 0.533333 / 2.4, no missing cells.
        counts=[75,25];target=[40,60]
        weights=[(t/sum(target))/(n/sum(counts)) for t,n in zip(target,counts)]
        self.assertAlmostEqual(weights[0],8/15)
        self.assertAlmostEqual(weights[1],2.4)
        self.assertEqual([round(w*n) for w,n in zip(weights,counts)],target)
if __name__=='__main__':unittest.main()
