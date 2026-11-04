"""Test real FIT evidence and operational status changes without model calls."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from fit_console import fit_status

ROOT = Path(__file__).resolve().parent.parent


class FitStates(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.summary = self.root/'results/FIT/fit_summary.json'
        self.summary.parent.mkdir(parents=True)
        for name in ('preregistration-FIT.md','research/fit-questionnaire.md'):
            target = self.root/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,target)
        source = ROOT/'demo/results/FIT/fit_summary.json'
        if not source.is_file():
            source = ROOT/'results/FIT/fit_summary.json'
        self.real = json.loads(source.read_bytes())

    def status(self, data=None):
        if data is not None:
            self.summary.write_text(json.dumps(data))
        return fit_status(self.root,self.root)

    def test_actual_and_missing(self):
        self.assertEqual(self.status()['status'],'실행 전')
        actual = self.status(self.real)
        self.assertEqual(actual['status'],'미달')
        self.assertEqual(actual['computed'],{'rq1':False,'rq2':True,'rq3':True,'h4':False})
        self.assertEqual(actual['per_source']['4'],[False,True,False])

    def test_pass_and_wrong_top_two(self):
        fixture = deepcopy(self.real)
        fixture.pop('own_verdict')
        for data in fixture['rq1']['3'].values():
            for cell in data['cells'].values():
                cell['pct'] = cell['reference_pct']
        self.assertEqual(self.status(fixture)['status'],'통과')
        cells = fixture['rq1']['3']['V3']['cells']
        cells['청주']['pct'] = 78
        self.assertEqual(self.status(fixture)['status'],'미달')

    def test_excluded_and_drift(self):
        fixture = deepcopy(self.real)
        fixture.pop('own_verdict')
        fixture['combos'][2]['excluded_rate'] = .06
        self.assertEqual(self.status(fixture)['status'],'판정 불가')
        fixture = deepcopy(self.real)
        fixture['own_verdict']['rq1'] = True
        self.assertEqual(self.status(fixture)['reason'],'계산 불일치')
        (self.root/'preregistration-FIT.md').write_text('다른 판본')
        self.assertEqual(self.status(self.real)['status'],'재검증 필요')


if __name__=='__main__':
    unittest.main()
