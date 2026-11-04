"""Independently recompute latest L9 output contracts from parquet."""
import collections,csv,json,math,hashlib
from pathlib import Path
import pyarrow.parquet as pq
from build import canonical
ROOT=Path(__file__).resolve().parent
out=ROOT/'out'
def main():
    weights=collections.Counter();counts=collections.Counter();types=collections.Counter();women=collections.Counter();ages=collections.Counter();drink=collections.Counter();fd=collections.Counter();n=0;invalid=0
    cols=['province','sex','age','weight','drinker','adopter','launch_sensitivity','viral_sensitivity','viral_channel','reaction_mode']
    for b in pq.ParquetFile(out/'population.parquet').iter_batches(batch_size=20000,columns=cols):
        for r in b.to_pylist():
            n+=1;k=(canonical(r['province']),r['sex'],str(r['age']//10*10));weights[k]+=r['weight'];counts[k]+=1;t=r['adopter'];types[t]+=1;ages[t]+=r['age'];women[t]+=r['sex']=='여자'
            d=r['weight']*r['drinker'];drink[t]+=d;fd[t]+=d*(r['sex']=='여자')
            invalid+=not(math.isfinite(r['weight']) and r['weight']>0 and all(0<=r[f]<=1 for f in ['drinker','launch_sensitivity','viral_sensitivity']))
            assert r['reaction_mode']=='two_axis_channel' and r['viral_sensitivity']==.6
            assert r['viral_channel']==('sns' if r['age']<=39 else 'acquaintance_tv')
    target={(r['province'],r['sex'],r['age_band']):int(r['population']) for r in csv.DictReader((ROOT/'stats/population_cells.csv').open())}
    diff=max(abs(weights[k]/sum(weights.values())-v/sum(target.values()))*100 for k,v in target.items())
    a=json.loads((out/'l9_first_run_summary.json').read_text());b=json.loads((out/'summary.json').read_text())
    cfg=json.loads((ROOT/'config/adopter.json').read_text());female=sum(women.values())/n
    result={'n':n,'cells':len(counts),'invalid_values':invalid,'max_diff_pp':diff,'type_counts':dict(types),'population_female_ratio':female,
      'same_config_same_parquet_sha256':a['output_sha256']==b['output_sha256'],
      'keyword_source_hash_matches':b['keyword_sha256']==hashlib.sha256((ROOT/cfg['keywords_file']).read_bytes()).hexdigest(),
      'demographics':{t:{'mean_age':ages[t]/types[t],'female_ratio':women[t]/types[t],'drinker_weighted_female_ratio':fd[t]/drink[t]} for t in types}}
    assert n==1000000 and len(counts)==306 and invalid==0 and diff<=1
    for t in types:
        assert abs(types[t]/n-cfg['ratios'][t])<=.005
        assert abs(women[t]/types[t]-female)<=2/types[t]
    assert result['same_config_same_parquet_sha256'] and result['keyword_source_hash_matches']
    result['passed']=True
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
