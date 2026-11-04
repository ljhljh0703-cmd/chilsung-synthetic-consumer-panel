"""Stream all pinned shards, post-stratify to KOSIS cells and export reusable samples.
Run from the project root: python3 population/build.py --config population/config/adopter.json
"""
import argparse, collections, csv, hashlib, heapq, json, math, os, random, sys, time
from pathlib import Path
from traits import KeywordScorer, reaction_values, validate_settings
from assignment import adjusted_order, assign, correlation
import pyarrow as pa
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent
TYPES=['innovator','early_adopter','early_majority','late_majority','laggard']
ALIASES={'서울특별시':'서울특별시','부산광역시':'부산광역시','대구광역시':'대구광역시','인천광역시':'인천광역시','광주광역시':'광주광역시','대전광역시':'대전광역시','울산광역시':'울산광역시','세종특별자치시':'세종특별자치시','경기도':'경기도','강원도':'강원특별자치도','강원특별자치도':'강원특별자치도','충청북도':'충청북도','충청남도':'충청남도','전라북도':'전북특별자치도','전북특별자치도':'전북특별자치도','전라남도':'전라남도','경상북도':'경상북도','경상남도':'경상남도','제주도':'제주특별자치도','제주특별자치도':'제주특별자치도'}
ALIASES.update(dict(zip(['강원','경기','경상남','경상북','광주','대구','대전','부산','서울','세종','울산','인천','전라남','전북','제주','충청남','충청북'],['강원특별자치도','경기도','경상남도','경상북도','광주광역시','대구광역시','대전광역시','부산광역시','서울특별시','세종특별자치시','울산광역시','인천광역시','전라남도','전북특별자치도','제주특별자치도','충청남도','충청북도'])))
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def write(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True); temp=p.with_suffix(p.suffix+'.tmp'); temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n'); temp.replace(p)
def canonical(province):
    if province not in ALIASES:raise ValueError('Unknown province: '+province)
    return ALIASES[province]
def band(age):return str(int(age)//10*10)
def cell(r):return (canonical(r['province']),r['sex'],band(r['age']))
def load_targets(path):
    targets={}
    with path.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            k=(canonical(r['province']),r['sex'],str(int(r['age_band'])))
            v=float(r['population'])
            if k in targets or v<0 or not math.isfinite(v):raise ValueError('Duplicate or invalid target cell '+str(k))
            targets[k]=v
    if not targets or sum(targets.values())<=0:raise ValueError('Empty target population')
    return targets

def signal(r,cfg):
    score=0.; hits=[]
    for rule in cfg['signals']:
        text=' '.join(str(r.get(f) or '') for f in rule.get('fields',[])).lower()
        match=(any(k.lower() in text for k in rule.get('keywords',[])) if 'keywords' in rule
          else rule['age_min']<=int(r['age'])<=rule['age_max'])
        if match: score+=float(rule['score']); hits.append(rule['id'])
    return score,hits

def quotas(n,ratios):
    if set(ratios)!=set(TYPES) or any(not math.isfinite(float(v)) or v<0 for v in ratios.values()) or abs(sum(ratios.values())-1)>1e-8:
        raise ValueError('Adopter ratios must be all five types and sum to 1')
    q={k:int(n*ratios[k]) for k in TYPES}
    for k in sorted(TYPES,key=lambda k:(-(n*ratios[k]-q[k]),TYPES.index(k)))[:n-sum(q.values())]:q[k]+=1
    return q

def validate_config(cfg):
    validate_settings(cfg)
    if type(cfg['seed']) is not int or type(cfg['sample_n']) is not int or cfg['sample_n']<1:raise ValueError('Invalid seed/sample_n')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--out');a=ap.parse_args()
    cp=Path(a.config).resolve();cfg=json.loads(cp.read_text());validate_config(cfg)
    stats=ROOT/cfg['stats_file'];targets=load_targets(stats)
    manifest=json.loads((ROOT/'source_manifest.json').read_text())
    if not manifest['download_complete']:raise RuntimeError('All shards must be downloaded and verified')
    sources=[ROOT/'raw'/Path(x['path']).name for x in manifest['shards']]
    for p,m in zip(sources,manifest['shards']):
        if not p.exists() or p.stat().st_size!=m['size'] or sha(p)!=m['lfs']['oid']:raise RuntimeError('Source hash mismatch '+str(p))
    out=Path(a.out).resolve() if a.out else ROOT/'out';out.mkdir(parents=True,exist_ok=True)
    start=time.monotonic();counts=collections.Counter();records=[];seen=set();signal_cache={}
    scorer=KeywordScorer(ROOT/cfg['keywords_file'],cfg['keyword_enabled'])
    cols={'uuid','age','sex','province'}|set(scorer.fields)
    for p in sources:
        for batch in pq.ParquetFile(p).iter_batches(batch_size=10000,columns=sorted(cols)):
            for r in batch.to_pylist():
                if not 19<=int(r['age'])<=99:raise ValueError('Population scope requires ages 19..99')
                if r['uuid'] in seen:raise ValueError('Duplicate UUID')
                seen.add(r['uuid']);counts[cell(r)]+=1
                score,hits=scorer.score(r,cfg);signal_cache[r['uuid']]=(score,hits)
                tie=hashlib.sha256(f"{cfg['seed']}:{r['uuid']}".encode()).hexdigest()
                records.append((score,tie,r['uuid'],int(r['age']),r['sex']))
    n=len(records);target_total=sum(targets.values())
    missing=[k for k,v in targets.items() if v>0 and not counts[k]]
    uncovered=[k for k in counts if k not in targets]
    if missing or uncovered:raise ValueError(f'Unsupported population cells: missing_source={missing}; missing_statistics={uncovered}')
    weights={k:(targets[k]/target_total)/(counts[k]/n) for k in counts}
    ordered,adjusted=adjusted_order(records,cfg['age_tilt'],cfg['sex_balance']=='within_sex')
    if cfg['sex_balance']=='within_sex':
        assigned={}
        for sex in ('남자','여자'):assigned.update(assign([r for r in ordered if r[4]==sex],cfg['ratios']))
    else:assigned=assign(ordered,cfg['ratios'])
    age_correlations={'raw_score':correlation([r[0] for r in records],[r[3] for r in records]),
                      'adjusted_rank':correlation([adjusted[r[2]] for r in records],[r[3] for r in records])}
    del records,ordered,seen
    rates=json.loads((PROJECT/'demo/config/drink_rates.json').read_text())
    heaps={'adults':[],'beer':[]};rng=random.Random(cfg['seed']);sample_n=cfg['sample_n']
    writer=None;temp=out/'population.parquet.partial';weighted=collections.Counter();kindcounts=collections.Counter()
    existing_ids=set()
    for filename in ['adults.json','drinkers.json']:
        p=PROJECT/'demo/data'/filename
        if p.exists():existing_ids.update(r['uuid'] for r in json.loads(p.read_text()))
    legacy={};type_age=collections.Counter();type_female=collections.Counter();type_drinkers=collections.Counter();type_female_drinkers=collections.Counter()
    try:
        for p in sources:
            for batch in pq.ParquetFile(p).iter_batches(batch_size=5000):
                rows=batch.to_pylist()
                for r in rows:
                    k=cell(r);t=assigned[r['uuid']];r['name']=r['persona'].split(' 씨')[0].strip()
                    r['age_band']=band(r['age']);r['weight']=weights[k]
                    r['drinker']=rates[r['sex']][str(min(70,max(20,int(r['age'])//10*10)))]/100
                    r['adopter']=t;r['adopter_score'],r['adopter_signals']=signal_cache[r['uuid']]
                    r['adopter_adjusted_score']=adjusted[r['uuid']]
                    r.update(reaction_values(r,cfg))
                    type_age[t]+=r['age'];type_female[t]+=r['sex']=='여자'
                    dw=r['drinker']*r['weight'];type_drinkers[t]+=dw
                    if r['sex']=='여자':type_female_drinkers[t]+=dw
                    weighted[k]+=r['weight'];kindcounts[t]+=1
                    if r['uuid'] in existing_ids:legacy[r['uuid']]=dict(r)
                    for category in heaps:
                        w=r['weight']*(r['drinker'] if category=='beer' else 1)
                        if w<=0:continue
                        priority=math.log(max(rng.random(),1e-300))/w
                        entry=(priority,r['uuid'],r)
                        if len(heaps[category])<sample_n:heapq.heappush(heaps[category],entry)
                        elif entry[:2]>heaps[category][0][:2]:heapq.heapreplace(heaps[category],entry)
                table=pa.Table.from_pylist(rows)
                if writer is None:writer=pq.ParquetWriter(temp,table.schema,compression='zstd')
                writer.write_table(table)
            print('processed',p.name,flush=True)
    finally:
        if writer:writer.close()
    temp.replace(out/'population.parquet')
    for category,h in heaps.items():write(out/f'sample_{category}_{len(h)}.json',[r for _,uid,r in sorted(h,key=lambda x:x[1])])
    write(out/'legacy_enriched.json',[legacy[k] for k in sorted(legacy)])
    total_w=sum(weighted.values());maxdiff=max(abs(weighted[k]/total_w-targets[k]/target_total)*100 for k in targets)
    summary={'n':n,'cells':len(targets),'target_total':target_total,'max_cell_diff_pp':maxdiff,
      'weighted_pass':maxdiff<=1,'type_counts':dict(kindcounts),'type_ratios':{t:kindcounts[t]/n for t in TYPES},
      'type_pass':all(abs(kindcounts[t]/n-cfg['ratios'][t])<=.005 for t in TYPES),
      'sample_counts':{k:len(v) for k,v in heaps.items()},'legacy_matched':len(legacy),'legacy_requested':len(existing_ids),
      'seconds':round(time.monotonic()-start,3),'config_sha256':sha(cp),'stats_sha256':sha(stats),
      'dataset_revision':manifest['revision'],'seed':cfg['seed'],'output_sha256':sha(out/'population.parquet'),
      'reaction_mode':cfg['reaction_mode'],'age_tilt':cfg['age_tilt'],'sex_balance':cfg['sex_balance'],
      'keyword_file':cfg['keywords_file'],'keyword_sha256':sha(scorer.path) if not scorer.missing else None,
      'keyword_dictionary_missing':scorer.missing,'keyword_enabled':scorer.enabled,'age_signal_enabled':cfg['age_signal_enabled'],
      'age_correlations':age_correlations,'type_demographics':{t:{'mean_age':type_age[t]/kindcounts[t],'female_ratio':type_female[t]/kindcounts[t],'drinker_weighted_female_ratio':type_female_drinkers[t]/type_drinkers[t]} for t in TYPES}}
    write(out/'summary.json',summary)
    with (out/'cells.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['province','sex','age_band','source_count','population','target_pct','before_pct','after_pct','diff_pp','weight'])
        for k in sorted(targets):
            w.writerow([*k,counts[k],targets[k],targets[k]/target_total*100,counts[k]/n*100,weighted[k]/total_w*100,(weighted[k]/total_w-targets[k]/target_total)*100,weights.get(k,0)])
    lines=['# 페르소나 모집단 결과','',f'- 전체 {n:,}명, 성×10세 연령대×시도 {len(targets)}칸.',f'- 가중 후 최대 오차 {maxdiff:.10f}%p (허용 1%p).',f'- 유형 비율은 전체 인원 기준. 가중 인구 기준 유형 비율과 같다는 뜻은 아님.',f'- 음주 확률과 두 민감도는 실측 개인 속성이 아님. 성향 근거는 미정.',f'- 표본은 가중 비복원 추출이므로 전체의 정확한 칸 비율을 보증하지 않음.',f'- 모집단 범위 19~99세. 19세는 10대 칸, 100세 이상 제외. 월간음주율의 19세는 기존 20대 값, 70세 이상은 기존 70대 이상 값 사용.',f'- 원본 revision: {manifest["revision"]}',f'- 통계 출처: stats/source.json. 입력·산출 해시: summary.json.','', '| 유형 | 인원 | 비율 | 설정 |','|---|---:|---:|---:|']
    for t in TYPES:lines.append(f'| {t} | {kindcounts[t]} | {kindcounts[t]/n:.3%} | {cfg["ratios"][t]:.3%} |')
    lines += ['', '## 배정 방식과 유형별 쏠림', '',f"- reaction_mode: {cfg['reaction_mode']}, age_tilt: {cfg['age_tilt']}, sex_balance: {cfg['sex_balance']}",f"- 나이 상관: 사전 원점수 {age_correlations['raw_score']}, 조정 순위 {age_correlations['adjusted_rank']}", '- age_tilt=0은 10세 나이대 사이 순위 차이를 제거. 나이대 안의 세부 나이 상관은 남을 수 있음.', '| 유형 | 평균 나이 | 여성 비율(원본 인원) | 여성 비율(음주 확률×인구 가중) |','|---|---:|---:|---:|']
    for t in TYPES:lines.append(f'| {t} | {type_age[t]/kindcounts[t]:.3f} | {type_female[t]/kindcounts[t]:.3%} | {type_female_drinkers[t]/type_drinkers[t]:.3%} |')
    lines+=['','## 칸별 가중 전후 분포','', '| 시도 | 성 | 연령대 | 원본 인원 | 통계 인원 | 목표 % | 가중 전 % | 가중 후 % |','|---|---|---:|---:|---:|---:|---:|---:|']
    for k in sorted(targets):lines.append(f'| {k[0]} | {k[1]} | {k[2]} | {counts[k]} | {targets[k]:.0f} | {targets[k]/target_total*100:.6f} | {counts[k]/n*100:.6f} | {weighted[k]/total_w*100:.6f} |')
    (out/'summary.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
