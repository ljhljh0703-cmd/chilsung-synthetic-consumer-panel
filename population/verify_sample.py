"""Execute unchanged demo/simulate.py with the real generated sample and a fake response adapter."""
import importlib.util,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent;DEMO=ROOT.parent/'demo'
def answer(schema):
    if 'enum' in schema:return schema['enum'][0]
    if schema['type']=='object':return {k:answer(v) for k,v in schema['properties'].items()}
    if schema['type']=='integer':return 1
    return '시험용 가짜 응답. 실제 소비자 의견 아님.'
def main():
    sys.path.insert(0,str(DEMO));spec=importlib.util.spec_from_file_location('unchanged_simulate',DEMO/'simulate.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    people=json.loads((ROOT/'out/sample_beer_2000.json').read_text())[:3]
    with tempfile.TemporaryDirectory(prefix='lotte-sample-test-') as tmp:
        dest=Path(tmp);(dest/'data').mkdir();(dest/'config').mkdir()
        (dest/'data/drinkers.json').write_text(json.dumps(people,ensure_ascii=False))
        sets=json.loads((DEMO/'config/sets.json').read_text());s=next(s for s in sets if s['sample']=='drinkers')
        (dest/'config/sets.json').write_text(json.dumps([s],ensure_ascii=False))
        m.ROOT=dest
        class Fake:
            @staticmethod
            def backend():return 'fixture'
            @staticmethod
            def model_name():return 'fixture:no_model_call'
            @staticmethod
            def check():return None
            @staticmethod
            def ask_json(system,user,schema):return answer(schema)
        m.llm=Fake
        sys.argv=['simulate.py','--limit','3','--batch','1','--workers','1','--tag','schema_test'];m.main()
        rows=[json.loads(l) for l in (dest/'results/schema_test'/f"{s['id']}.jsonl").read_text().splitlines()]
        assert len(rows)==3 and {r['uuid'] for r in rows}=={p['uuid'] for p in people}
        evidence={'mode':'fake_response','original_simulate_modified':False,'real_model_run':False,'n':3,'all_sample_fields_accepted':True,'result':rows}
        (ROOT/'out/sample_compatibility.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        print('PASS: original simulate.py accepted population sample, 3/3 fixture responses')
if __name__=='__main__':main()
