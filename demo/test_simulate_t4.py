"""L13 opt-in behavior and compatibility checks. All model calls are injected."""
import copy,hashlib,importlib.util,json,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import simulate as sim

REAL_ROOT=Path(__file__).resolve().parent
# Derive Vault root without relying on the caller's working directory.
VAULT_ROOT=next(p for p in REAL_ROOT.parents if (p/'wiki/projects').is_dir())
RETURN=VAULT_ROOT/'wiki/projects/lotte-ax-2026-returns/2026-11-04-T4'
SOURCE_BEER=REAL_ROOT.parent/'population/out/sample_beer_2000.json'
SOURCE_ADULTS=REAL_ROOT.parent/'population/out/sample_adults_2000.json'


class T4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_people=json.loads((REAL_ROOT/'data/drinkers.json').read_text())[:5]
        cls.shelves=sim.load_sets('config/sets_known.json')
        snap=json.loads((RETURN/'before/simulate-snapshot.json').read_text())
        snapshot_path=Path(snap['snapshot'])
        if not snapshot_path.is_absolute():snapshot_path=VAULT_ROOT/snapshot_path
        spec=importlib.util.spec_from_file_location('before_t4',snapshot_path)
        cls.before=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.before)
        cls.before.ROOT=REAL_ROOT
        cls.evidence={}

    def setUp(self):
        sim.OPTS.clear();sim.OPTS.update(scene=None,new_hint=True,equal_cards=False,ask_qty=False)

    def test_01_legacy_interfaces_unchanged(self):
        for equal in (False,True):
            sim.OPTS['equal_cards']=equal;self.before.OPTS['equal_cards']=equal
            for named in (False,True):
                for n in (1,5):
                    self.assertEqual(sim.build_messages(self.old_people[:n],self.shelves[0],named),self.before.build_messages(self.old_people[:n],self.shelves[0],named))
        self.assertEqual(sim.person_schema('ABC'),self.before.person_schema('ABC'))
        self.assertEqual(sim.schema('ABC',['P1','P2'],True),self.before.schema('ABC',['P1','P2'],True))
        self.evidence['legacy']={'message_variants_identical':8,'default_schema_identical':True}

    def test_02_individual_reverse_mapping(self):
        sim.OPTS['familiar_incumbents']=True
        st=self.shelves[1]
        system,user,orders,labels,keys=sim.build_person_order_messages(self.old_people,st,False)
        response={'people':{key:{'products':{label:{'reaction':key+label,'pull':'p','hesitate':'h'} for label in labels},'choice':'A','usual':'B','choice_reason':'fixture'} for key in keys}}
        rows=sim.decode_answers(self.old_people,st,orders,labels,keys,response,model='stub',named=True,rep=0,familiar=True)
        self.assertGreater(len({tuple(o) for o in orders}),1)
        for p,order,row,key in zip(self.old_people,orders,rows,keys):
            self.assertEqual(order,sim.order_for(p['uuid'],st['id'],len(st['products'])))
            self.assertEqual(row['choice'],st['products'][order[0]]['id'])
            self.assertEqual(row['usual'],st['products'][order[1]]['id'])
            self.assertEqual(row['by_product'][row['choice']]['reaction'],key+'A')
            self.assertNotIn(p['uuid'],user)
        self.assertIn('평소 경험대로',system)
        self.evidence['reverse_mapping']={'per_person_orders':orders,'choice_and_usual_per_person':True,'uuid_not_in_prompt':True}

    def test_03_names_and_dual_schema_opt_in(self):
        st=copy.deepcopy(self.shelves[0]);st['products'][0].update(target=True,real_name='SECRET_TARGET_BRAND',maker='SECRET_MAKER')
        sim.OPTS['familiar_incumbents']=True
        _,user,*_=sim.build_person_order_messages(self.old_people,st,False)
        self.assertNotIn('SECRET_TARGET_BRAND',user)
        self.assertIn(st['products'][1]['real_name'],user)
        self.assertIn('usual',sim.person_schema('ABC',ask_usual=True)['required'])
        self.assertNotIn('usual',sim.person_schema('ABC')['required'])
        with self.assertRaises((KeyError,ValueError)):
            sim.decode_answers(self.old_people[:1],st,[[0,1,2]],'ABC',None,{'products':{k:{} for k in 'ABC'},'choice':'A','choice_reason':''},model='stub',named=True,rep=0,familiar=True)

    def test_04_random_selection_and_adult_switch(self):
        beer=self.shelves[0];soda=self.shelves[-1]
        a,meta=sim.sample_people('population/out/sample_beer_2000.json',beer,150,20261104)
        b,_=sim.sample_people('../population/out/sample_beer_2000.json',self.shelves[1],150,20261104)
        c,_=sim.sample_people(str(SOURCE_BEER),beer,150,20261105)
        d,adult_meta=sim.sample_people(str(SOURCE_BEER),soda,150,20261104)
        original=json.loads(SOURCE_BEER.read_text())
        self.assertEqual([p['uuid'] for p in a],[p['uuid'] for p in b])
        self.assertNotEqual([p['uuid'] for p in a],[p['uuid'] for p in original[:150]])
        self.assertNotEqual({p['uuid'] for p in a},{p['uuid'] for p in c})
        self.assertEqual(meta['sha256'],hashlib.sha256(SOURCE_BEER.read_bytes()).hexdigest())
        self.assertEqual(adult_meta['path'],str(SOURCE_ADULTS))
        self.assertEqual(sum(meta['sex_distribution'].values()),150)
        self.assertEqual(sum(meta['age_distribution'].values()),150)
        self.evidence['sampling']={'beer_sha256':meta['sha256'],'adults_sha256':adult_meta['sha256'],'seed':20261104,'same_beer_cohort':True,'not_first_150':True,'beer_sex':meta['sex_distribution'],'adults_sex':adult_meta['sex_distribution']}

    def test_05_full_stub_metadata_cohort_cache_and_restart_guard(self):
        calls=[];loads=[]
        def fake(system,user,schema,**kwargs):
            calls.append(1)
            props=schema['properties']['people']['properties'];people={}
            for key,sch in props.items():
                self.assertIn('usual',sch['required'])
                labels=list(sch['properties']['products']['properties'])
                people[key]={'products':{l:{'reaction':'r','pull':'p','hesitate':'h'} for l in labels},'usual':labels[0],'choice':labels[1],'choice_reason':'stub'}
            return {'people':people}
        original_sampler=sim.sample_people
        def counted(*args,**kwargs):loads.append(args[0]);return original_sampler(*args,**kwargs)
        with tempfile.TemporaryDirectory(prefix='lotte-t4-test-') as temp:
            root=Path(temp)/'demo';(root/'config').mkdir(parents=True)
            (root/'config/sets.json').write_text(json.dumps(self.shelves,ensure_ascii=False))
            (root/'config/sets_fixture.json').write_text(json.dumps(self.shelves,ensure_ascii=False))
            argv=['simulate.py','--sets-file','config/sets_fixture.json','--tag','T4_stub','--limit','150','--batch','5','--workers','2','--people',str(SOURCE_BEER),'--per-person-order','--familiar-incumbents']
            with patch.object(sim,'ROOT',root),patch.object(sys,'argv',argv),patch.object(sim.llm,'backend',return_value='codex'),patch.object(sim.llm,'model_name',return_value='stub:T4'),patch.object(sim.llm,'check',return_value=None),patch.object(sim.llm,'ask_json',side_effect=fake),patch.object(sim,'sample_people',side_effect=counted):
                sim.main();self.assertEqual(len(loads),2);self.assertEqual(len(calls),150)
                out=root/'results/T4_stub';settings=json.loads((out/'settings.json').read_text());counts={};cohorts={}
                for st in self.shelves:
                    rows=[json.loads(x) for x in (out/(st['id']+'_named.jsonl')).read_text().splitlines()]
                    self.assertEqual(len(rows),150);self.assertEqual(len({r['uuid'] for r in rows}),150)
                    self.assertTrue(all('usual' in r and 'choice' in r and r['named'] for r in rows))
                    counts[st['id']]=len({tuple(r['order']) for r in rows});self.assertGreater(counts[st['id']],1)
                    cohorts[st['id']]=set(r['uuid'] for r in rows)
                self.assertTrue(all(cohorts[st['id']]==cohorts[self.shelves[0]['id']] for st in self.shelves[:-1]))
                self.assertEqual(len(settings['sources_by_shelf']),5)
                evidence_dir=RETURN/'simulation-stub';shutil.copytree(out,evidence_dir,dirs_exist_ok=True)
                sim.main();self.assertEqual(len(calls),150)
                def changed(*args,**kwargs):
                    people,meta=original_sampler(*args,**kwargs);meta['sha256']='0'*64;return people,meta
                with patch.object(sim,'sample_people',side_effect=changed):
                    with self.assertRaisesRegex(ValueError,'다른 표본|표본 파일|다릅니다'):sim.main()
                self.assertEqual(len(calls),150)
                self.evidence['full_stub']={'people_per_shelf':150,'shelves':5,'rows_total':750,'stub_calls':150,'unique_orders':counts,'source_loads_first_run':2,'complete_restart_extra_calls':0,'source_drift_rejected_before_call':True,'same_beer_cohort':True,'settings_path':str(evidence_dir/'settings.json')}

    def test_06_new_options_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix='lotte-t4-failure-') as temp:
            root=Path(temp)/'demo';(root/'config').mkdir(parents=True)
            (root/'config/sets.json').write_text(json.dumps(self.shelves,ensure_ascii=False))
            (root/'config/sets_fixture.json').write_text(json.dumps(self.shelves[:1],ensure_ascii=False))
            argv=['simulate.py','--sets-file','config/sets_fixture.json','--tag','failure','--limit','5','--batch','5','--workers','1','--people',str(SOURCE_BEER),'--per-person-order','--familiar-incumbents']
            with patch.object(sim,'ROOT',root),patch.object(sys,'argv',argv),patch.object(sim.llm,'backend',return_value='codex'),patch.object(sim.llm,'model_name',return_value='stub'),patch.object(sim.llm,'check',return_value=None),patch.object(sim.llm,'ask_json',side_effect=RuntimeError('injected failure')):
                with self.assertRaises(SystemExit):sim.main()
        self.evidence['failure']={'new_options_nonzero_on_model_failure':True,'real_model_calls':0}

    @classmethod
    def tearDownClass(cls):
        RETURN.mkdir(parents=True,exist_ok=True)
        (RETURN/'simulation-tests.json').write_text(json.dumps(cls.evidence,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':unittest.main(verbosity=2)
