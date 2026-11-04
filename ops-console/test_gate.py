"""Exercise the server gate and its audit trail in an isolated state folder."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import fit_console
import server


class GateTests(unittest.TestCase):
    def setUp(self):
        self.fit = {'status':'통과','allowed_models':['gpt-6.1-terra'],
                    'data':{'population':{'population_id':'frozen'}}}
        self.spec = {'population_id':'frozen','flags':['--batch','1','--per-person-order']}
        self.reference = {'status':'pass','population_id':'frozen','model':'gpt-6.1-terra'}

    def test_representativeness_blocks_but_warnings_do_not(self):
        for status in ('실행 전','미달','판정 불가','재검증 필요'):
            self.assertFalse(fit_console.gate({**self.fit,'status':status,'reason':'시험'},self.spec,self.reference)['allowed'])
        result = fit_console.gate({**self.fit,'warnings':['정보 기여 미확인','판정 안정성 주의','세그먼트 방향 미지지']},self.spec,self.reference)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['model'],'gpt-6.1-terra')

    def test_remaining_gate_stages(self):
        self.assertEqual(fit_console.gate(self.fit,{**self.spec,'requested_model':'claude-haiku-5-5'},self.reference)['stage'],2)
        self.assertEqual(fit_console.gate(self.fit,{**self.spec,'population_id':'different'},self.reference)['stage'],3)
        self.assertEqual(fit_console.gate(self.fit,{**self.spec,'flags':['--batch','5','--per-person-order']},self.reference)['stage'],4)
        self.assertEqual(fit_console.gate(self.fit,self.spec,{**self.reference,'status':'fail'})['stage'],5)

    def test_rejected_run_is_recorded_without_starting(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            server.dump(root/'experiments/OPS_fixture.json',{'receipt_id':'sample'})
            server.dump(root/'state.json',{'role':'조사 담당','receipts':[],'actions':[],'surveys':[],'jobs':{}})
            with patch.object(server,'DEMO',root),patch.object(server,'STATE',root),patch.object(server.threading,'Thread') as worker:
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError,'1단계'):
                        server.mutate('run',{'name':'OPS_fixture','confirmed':True,'stub':True})
                worker.assert_not_called()
                self.assertEqual(len(server.overview()['blocks']),2)
                self.assertEqual(len((root/'audit.log').read_text().splitlines()),2)


if __name__=='__main__':
    unittest.main()
