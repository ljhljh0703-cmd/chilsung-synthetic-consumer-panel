import argparse,copy,json,subprocess,sys,unittest,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import price_sweep as sw


def args(**kwargs):
    d=dict(exp='experiments/T2.json',product='cider_2021',price='1800,2000,2200',volume=None,shelf='soda_2023_known',n=6,batch=6,max_calls=4,timeout=90,name='fixture',python=sys.executable,stub=True,prepare_only=False)
    d.update(kwargs);return argparse.Namespace(**d)


class SweepChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.suffix=str(time.time_ns())
    def test_price_keeps_volume_and_card_order(self):
        p=sw.build_plan(args());self.assertEqual(len(p['variants']),4)
        self.assertEqual(p['base_price'],2100);self.assertEqual(p['base_volume'],500)
        for v in p['variants']:
            self.assertEqual(v['shelf']['id'],'soda_2023_known')
            target=next(x for x in v['shelf']['products'] if x['id']=='cider_2021')
            self.assertIn('500ml',target['attrs']['가격'])
            self.assertIn(f"{v['price']:,}원",v['prompt']['target_block'])
            self.assertTrue(all(uid not in v['prompt']['user'] for uid in p['expected_uuids']))
        self.assertEqual(len({v['target_label'] for v in p['variants']}),1)
        self.assertTrue(p['public_source_proof']['all_matched'])

    def test_volume_cartesian_plus_control(self):
        p=sw.build_plan(args(volume='355,500'));self.assertEqual(len(p['variants']),7)
        for v in p['variants']:
            target=next(x for x in v['shelf']['products'] if x['id']=='cider_2021')
            self.assertEqual(target['attrs']['용량'],str(v['volume'])+'ml')
            self.assertIn(str(v['volume'])+'ml',target['attrs']['가격'])

    def test_hidden_price_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'target price is absent'):sw.build_plan(args(exp='experiments/T3.json'))

    def test_zero_and_tied_rank(self):
        r=sw.metrics([{'choice':'없음'}]*6,['a','b'],'a');self.assertIsNone(r['rank']);self.assertEqual(r['none_share'],1)
        r=sw.metrics([{'choice':'a'},{'choice':'b'},{'choice':'없음'}],['a','b'],'a');self.assertEqual(r['rank'],1);self.assertTrue(r['tied']);self.assertEqual(r['choice_share_all'],1/3)

    def test_model_budget_preflight(self):
        with self.assertRaisesRegex(ValueError,'exceed max_calls'):sw.build_plan(args(volume='355,500',stub=False))
        p=sw.build_plan(args(price='1800,2000,2100',stub=False));self.assertEqual(len(p['variants']),3)

    def test_stub_generation_complete_and_resume_zero_calls(self):
        a=args(name='cider_stub_'+self.suffix);folder=sw.execute(a);summary=json.loads((folder/'summary.json').read_text());self.assertEqual(summary['actual_calls'],4);self.assertEqual(len(summary['rows']),4)
        counts={v.name:json.loads((v/'call_audit.json').read_text()) for v in folder.iterdir() if v.is_dir() and (v/'call_audit.json').exists()}
        sw.execute(a)
        after={v.name:json.loads((v/'call_audit.json').read_text()) for v in folder.iterdir() if v.is_dir() and (v/'call_audit.json').exists()}
        self.assertEqual(counts,after)
        self.assertTrue(json.loads((folder/'ledger_preservation.json').read_text())['prefix_preserved'])

    def test_cumulative_budget_survives_partial_retry(self):
        a=args(name='cider_cap_'+self.suffix);folder=sw.execute(a);first=folder/'p1800_voriginal';file=first/'soda_2023_known.jsonl'
        (first/'complete-response-backup.jsonl').write_bytes(file.read_bytes());file.write_text('')
        sw.save(first/'completeness.json',{'complete':False,'fixture':'simulate incomplete retry'})
        (first/'report.md').rename(first/'report-before-partial-fixture.md')
        before=json.loads((first/'call_audit.json').read_text())
        with self.assertRaisesRegex(RuntimeError,'failed'):sw.execute(a)
        self.assertEqual(before,json.loads((first/'call_audit.json').read_text()))
        self.assertIn('sweep call cap exceeded',(first/'execution.log').read_text())


if __name__=='__main__':unittest.main(verbosity=2)
