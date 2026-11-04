"""10k raw-person probe of config effects; not a separate official population build."""
import copy,hashlib,json
from pathlib import Path
import pyarrow.parquet as pq
from traits import KeywordScorer,reaction_values
from assignment import adjusted_order,assign,correlation
ROOT=Path(__file__).resolve().parent
cfg=json.loads((ROOT/'config/adopter.json').read_text());scorer=KeywordScorer(ROOT/cfg['keywords_file'])
rows=next(pq.ParquetFile(ROOT/'raw/train-00000-of-00009.parquet').iter_batches(batch_size=10000)).to_pylist()
records=[(scorer.score(r,cfg)[0],hashlib.sha256((str(cfg['seed'])+r['uuid']).encode()).hexdigest(),r['uuid'],r['age'],r['sex']) for r in rows]
results={};labels={}
for tilt,sex in [(1,'within_sex'),(0,'within_sex'),(1,'none')]:
 ordered,scores=adjusted_order(records,tilt,sex=='within_sex');groups=[[r for r in ordered if r[4]==s] for s in ['남자','여자']] if sex=='within_sex' else [ordered]
 assigned={}
 for g in groups:assigned.update(assign(g,cfg['ratios']))
 key=f'{tilt}:{sex}';labels[key]=assigned
 corr=correlation([scores[r[2]] for r in records],[r[3] for r in records])
 results[key]={'age_rank_correlation':corr,'type_female_ratio':{t:sum(r[4]=='여자' for r in records if assigned[r[2]]==t)/sum(assigned[r[2]]==t for r in records) for t in cfg['ratios']}}
results['changed_personas_age_tilt']=sum(labels['0:within_sex'][u]!=t for u,t in labels['1:within_sex'].items())
results['changed_personas_sex_balance']=sum(labels['1:none'][u]!=t for u,t in labels['1:within_sex'].items())
assert results['changed_personas_age_tilt']>0 and results['changed_personas_sex_balance']>0
assert abs(results['0:within_sex']['age_rank_correlation']) < abs(results['1:within_sex']['age_rank_correlation'])
results['scope']='10,000 original rows; config-effect probe, not full-population demographic claim'
results['passed']=True
(ROOT/'out/control-probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');print(json.dumps(results,ensure_ascii=False,indent=2))
