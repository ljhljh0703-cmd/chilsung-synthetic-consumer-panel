#!/usr/bin/env python3
"""Local-only Korean operations console. Python stdlib; existing demo code stays untouched."""
import argparse, csv, datetime as dt, hashlib, importlib.util, io, json, os, re, secrets, subprocess, sys, threading
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import config_editor
import analytics
import fit_console
from ops_evidence import product_labels, reproduction
PROJECT=Path(os.environ.get('OPS_PROJECT_ROOT', HERE.parent)).resolve()
DEMO=Path(os.environ.get('OPS_DEMO_ROOT', HERE.parent/'demo')).resolve()
STATE=Path(os.environ.get('OPS_STATE_DIR', HERE)).resolve()
STATE.mkdir(parents=True,exist_ok=True)
LOCK=threading.RLock(); TOKEN=secrets.token_urlsafe(32); JOBS={}
ROLES=['BM','조사 담당','데이터 담당']
ATTRS=['종류','도수','용량','가격','맛','포장','컨셉']

def now(): return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='seconds')
def read(p,default=None): return json.loads(p.read_text()) if p.exists() else default

def dump(p,data,exclusive=False):
    p.parent.mkdir(parents=True,exist_ok=True)
    if exclusive:
        with p.open('x',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
    else:
        tmp=p.with_suffix(p.suffix+'.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)); tmp.replace(p)

def state(): return read(STATE/'state.json',{'role':'BM','receipts':[],'actions':[],'surveys':[],'jobs':{}})
def event(s,action,detail,actor=None):
    row={'time':now(),'actor':actor or s['role'],'action':action,'detail':detail}
    s['actions'].append(row); dump(STATE/'state.json',s)
    with (STATE/'audit.log').open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')

def ident(v):
    if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',v): raise ValueError('이름은 영문·숫자·밑줄·붙임표 64자 이내로 적으세요.')
    return v

def unique_name(prefix): return prefix+dt.datetime.now().strftime('%Y%m%d_%H%M%S_')+secrets.token_hex(3)
def guard(s,roles):
    if s['role'] not in roles: raise ValueError('이 작업은 '+', '.join(roles)+' 역할만 가능합니다.')
def ingest(kind,rows,name):
    spec=importlib.util.spec_from_file_location('console_ingest',DEMO/'ingest.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); m.ROOT=DEMO
    out=DEMO/f'config/{"sets" if kind=="cards" else "survey"}_{name}.json'
    if out.exists(): raise ValueError('같은 이름의 결과가 이미 있습니다.')
    return getattr(m,kind)(rows,name)

def specimens():
    base=read(DEMO/'config/sets.json',[]); out={}
    for group in base:
        for p in group.get('products',[]): out[p['id']]={**p,'category':group.get('category',''),'launch':group.get('launch','')}
    return list(out.values())

def recompute(name,spec):
    truth=read(DEMO/spec.get('truth_file','_absent'),{}) if spec.get('truth_file') else {}
    res={}
    for named in (False,True):
        shelves={}; ok=total=wok=wt=last=0; cats=defaultdict(lambda:[0,0])
        for sid,t in truth.items():
            if sid.startswith('_'):continue
            p=DEMO/'results'/name/(sid+('_named' if named else '')+'.jsonl')
            if not p.exists():continue
            try: rows=[json.loads(l) for l in p.read_text().splitlines() if l.strip()]
            except json.JSONDecodeError:continue # file still being written
            if not rows:continue
            ids=list(t['value']); counts=Counter(r.get('choice') for r in rows); den=sum(counts[i] for i in ids) or 1
            sim={i:counts[i]/den for i in ids}; tr=t['value']; worst=min(ids,key=lambda i:tr[i]); hit_last=min(ids,key=lambda i:sim[i])==worst
            last+=hit_last
            for ai,a in enumerate(ids):
                for b in ids[ai+1:]:
                    if tr[a]==tr[b]:continue
                    hi,lo=(a,b) if tr[a]>tr[b] else (b,a); hit=1 if sim[hi]>sim[lo] else .5 if sim[hi]==sim[lo] else 0
                    ok+=hit;total+=1;cats[t.get('category','기타')][0]+=hit;cats[t.get('category','기타')][1]+=1
                    if worst in (a,b):wok+=hit;wt+=1
            shelves[sid]={'n':len(rows),'last_match':hit_last,'sim':sim,'none_rate':counts['없음']/len(rows)}
        if shelves:res['이름공개·선택비율' if named else '이름가림·선택비율']={'pair_acc':round(ok/total,3) if total else None,'pairs':total,'weak_pair_acc':round(wok/wt,3) if wt else None,'weak_pairs':wt,'last_match_rate':round(last/len(shelves),3),'last_count':last,'shelves':shelves,'by_category':{k:{'pair_acc':round(v[0]/v[1],3),'pairs':v[1]} for k,v in cats.items() if v[1]}}
    return res

def verdict(checks):
    for k,reason in [('reproduction','기존 경쟁 세트 재현 기준 미달'),('baseline','기준 모델 미달'),('leakage','데이터 누수')]:
        if checks.get(k)=='fail':return {'label':'포기','display_label':'보류','status':'fail','reason':reason,'show_rank':False}
    if checks.get('source_validity')=='fail':return {'label':'포기','display_label':'보류','status':'fail','reason':'입력 판본 검증이 끝나지 않아 유효성 보류','show_rank':False}
    if checks.get('reproduction')=='pass' and checks.get('card_sensitivity')=='fail':return {'label':'보정','display_label':'보정','status':'calibrate','reason':'자극물만 바꿔도 1순위 브랜드가 달라져 신뢰 판정을 제한합니다.','show_rank':False}
    if checks.get('reproduction')=='pass' and (checks.get('human_mismatch') is True or checks.get('stability')=='fail'):
        return {'label':'보정','display_label':'보정','status':'calibrate','reason':'소비자 조사와의 차이 또는 모델 간 순위 차이 보정이 필요합니다.','show_rank':False}
    if all(checks.get(k)=='pass' for k in ['reproduction','baseline','leakage','stability','noise','card_sensitivity']):return {'label':'신뢰','display_label':'신뢰','status':'pass','reason':'자기 점검 6가지 모두 통과','show_rank':True}
    return {'label':'판정 대기','display_label':'판정 대기','status':'unknown','reason':'미확인 점검이 있어 순위를 추천하지 않습니다.','show_rank':False}

def response_fingerprint(name):
    files=sorted((DEMO/'results'/name).glob('*.jsonl'))
    return hashlib.sha256(b''.join(f.name.encode()+f.read_bytes() for f in files)).hexdigest()

def corrected_view(name,metrics):
    approved=[x for x in state()['surveys'] if x['experiment']==name and x['status']=='승인']
    if not approved:return {'status':'미적용','reason':'데이터 담당 승인 전','shelves':{}}
    item=approved[-1]
    if item.get('response_fingerprint')!=response_fingerprint(name):return {'status':'재검증 필요','reason':'승인 후 가상 응답이 바뀌었습니다.','shelves':{}}
    key=item.get('metric_key','이름가림·선택비율');current=metrics.get(key,{}).get('shelves',{});shelves={}
    for sid,cal in item['calibration'].items():
        sim=current.get(sid,{}).get('sim',{})
        raw={p:sim.get(p,0)*v['factor'] for p,v in cal.items() if v.get('factor') is not None}
        total=sum(raw.values())
        if total<=0:continue
        shelves[sid]={p:{'before':sim.get(p,0),'after':v/total,'human':cal[p]['human_share']} for p,v in raw.items()}
    return {'status':'적용','survey':item['id'],'reason':'승인된 배수 적용 후 합이 1이 되도록 재계산. 순위 사용 여부는 자기 점검 판정을 따릅니다.','shelves':shelves}

def brand_comparison(name,spec,metrics):
    bare=lambda sp:[f for f in sp.get('flags',[]) if f!='--named']
    match=None
    for p in sorted((DEMO/'experiments').glob('*.json')):
        other=read(p)
        if other.get('name')==name:continue
        if other.get('sets_file')!=spec.get('sets_file') or other.get('n')!=spec.get('n') or bare(other)!=bare(spec):continue
        if ('--named' in other.get('flags',[]))==('--named' in spec.get('flags',[])):continue
        match=other;break
    allmetrics=dict(metrics)
    if match:allmetrics.update(recompute(match['name'],match))
    b=allmetrics.get('이름가림·선택비율',{}).get('shelves',{});n=allmetrics.get('이름공개·선택비율',{}).get('shelves',{})
    diffs={sid:{pid:{'blind':share,'named':n[sid]['sim'].get(pid),'difference_pp':round(100*(n[sid]['sim'].get(pid,0)-share),2)} for pid,share in sh['sim'].items()} for sid,sh in b.items() if sid in n}
    return {'paired_experiment':match.get('name') if match else None,'difference':diffs,'note':'같은 진열대·표본 수·질문 방식의 공개/가림 선택 비중 차이. 브랜드 영향과 기억 누수를 분리해 증명하지 못함.'}

def detail(name,_seen=None):
    name=ident(name);spec=read(DEMO/'experiments'/f'{name}.json',{});out=DEMO/'results'/name
    seen=set(_seen or ());seen.add(name)
    is_dual='--familiar-incumbents' in spec.get('flags',[]) or spec.get('primary_metric')=='usual'
    dual=read(out/'known_eval_dual.json',{}) if is_dual else {}
    stored=read(out/'known_eval.json') or read(DEMO/'results/known_eval.json',{}).get(name)
    primary='usual' if is_dual else 'choice'
    metrics=dual.get('metrics',{}).get('usual',{}) if is_dual else stored or recompute(name,spec)
    secondary=dual.get('metrics',{}).get('choice',{}) if is_dual else {}
    raw_choice=analytics.raw_shares(DEMO,name,spec,'choice')
    choice_metrics={raw_choice['key']:{'shelves':raw_choice['shelves']}}
    report=(out/'report.md').read_text() if (out/'report.md').exists() else '아직 결과 보고서가 없습니다.'
    checks={k:'unknown' for k in ['reproduction','baseline','leakage','stability','noise','card_sensitivity']}
    key='이름공개·선택비율' if '--named' in spec.get('flags',[]) or is_dual else '이름가림·선택비율'
    gate=spec.get('console_gate')
    if not gate and '5개 중 꼴찌 일치 4개 이상' in spec.get('pass_rule','') and '80%' in spec.get('pass_rule',''):gate={'shelves':5,'last_min':4,'weak_min':.8}
    v=metrics.get(key,{})
    if is_dual:
        decision=dual.get('decision',{})
        if decision.get('status') in ('pass','fail') and not dual.get('errors') and all(x.get('complete') for x in dual.get('completeness',{}).values()) and len(dual.get('completeness',{}))==5:checks['reproduction']=decision['status']
    elif gate and v and all(x.get('n',0)==spec.get('n',1) for x in v.get('shelves',{}).values()) and len(v.get('shelves',{}))==gate['shelves']:
        lc=sum(bool(x.get('last_match')) for x in v['shelves'].values());checks['reproduction']='pass' if lc>=gate['last_min'] and (v.get('weak_pair_acc') or 0)>=gate['weak_min'] else 'fail'
    benchmark=None
    ref=spec.get('validation_reference')
    if ref:
        if ref in seen:benchmark={'name':ref,'status':'unknown','reason':'재현 실험 참조가 순환합니다.'}
        elif not (DEMO/'experiments'/f'{ident(ref)}.json').is_file():benchmark={'name':ref,'status':'unknown','reason':'연결한 재현 실험이 없습니다.'}
        else:
            r=detail(ref,seen);status='fail' if r['verdict']['status']=='fail' else r['checks']['reproduction']
            prior=read(DEMO/'results'/ref/'settings.json',{})
            benchmark={'name':ref,'status':status,'reason':r['verdict']['reason'],'primary_metric':r['primary_metric'],
                       'report_hash':r['report_hash'],'population_id':prior.get('population_id'),
                       'model':str(prior.get('model','')).split(':')[-1]}
        checks['reproduction']=benchmark['status']
    checks_path=STATE/'verdict-inputs'/name/'checks.json'
    evidence=read(checks_path,{})
    for k in ['baseline','leakage','stability','noise']:
        e=evidence.get(k,{})
        if isinstance(e,dict) and e.get('status') in ['pass','fail'] and e.get('source'):checks[k]=e['status']
    if evidence.get('human_mismatch',{}).get('source'):checks['human_mismatch']=evidence['human_mismatch'].get('value') is True
    locked_input=verdict_inputs(name)
    pair=locked_input.get('sensitivity_pair',{})
    sens=analytics.sensitivity(DEMO,pair.get('left'),pair.get('right'))
    checks['card_sensitivity']=sens['status']
    source_dir=STATE/'verdict-inputs'
    if not (source_dir/name/'verification.json').is_file():source_dir=HERE/'fixtures/verdict-inputs'
    prov=analytics.provenance(source_dir,name)
    if prov['status']=='hold':checks['source_validity']='fail'
    primary_raw=analytics.raw_shares(DEMO,name,spec,primary)
    cautions=list(prov['warnings'])
    zeros=[sid for sid,x in primary_raw['shelves'].items() if x['valid_n']==0]
    if zeros:cautions.append('주 지표에서 유효 선택이 0인 경쟁 세트가 있습니다. 해당 세트의 순위·1위 적중을 성과로 해석하지 않습니다.')
    data={'name':name,'spec':spec,'metrics':metrics,'metric_key':key,'primary_metric':primary,'secondary_metrics':secondary,'primary_observations':primary_raw,'metrics_source':'두 기준 평가의 주음용 브랜드' if is_dual else 'known_eval.json' if stored else '응답 원문과 정답 자료 재계산','report':report,'display_report':analytics.term(report),'report_hash':hashlib.sha256(report.encode()).hexdigest(),'checks':checks,'verdict':verdict(checks),'benchmark':benchmark,'sensitivity':sens,'provenance':prov,'cautions':cautions,'locked':(out/'spec_locked.json').exists(),'log':(STATE/'logs'/f'{name}.log').read_text(errors='replace')[-18000:] if (STATE/'logs'/f'{name}.log').exists() else '', 'evidence':evidence,'calibrated':corrected_view(name,choice_metrics),'raw_choice':raw_choice,'brand_comparison':brand_comparison(name,spec,metrics)}
    fit=fit_status()
    settings=read(out/'settings.json',{})
    data['receipt_id']=spec.get('receipt_id')
    data['fit_gate']=fit_gate(spec,benchmark,fit) if spec.get('validation_reference') or spec.get('receipt_id') else None
    if data['fit_gate'] is not None and settings and data['fit_gate']['allowed']:
        if str(settings.get('model','')).split(':')[-1]!=data['fit_gate']['model']:
            data['verdict']={'label':'판정 대기','display_label':'보류','status':'unknown',
                             'reason':'실행 모델 불일치','show_rank':False}
    if data['fit_gate'] is None and not settings.get('population_id'):
        data['cautions'].append('정합성 검증 전 모집단으로 돌림 · 같은 모집단인지 확인할 수 없습니다.')
    data['reproduction_rows']=reproduction(data,read(DEMO/(spec.get('truth_file') or 'config/known_truth.json'),{}),
                                          product_labels(DEMO,specimens()))
    data['concept_choices']=[]
    if data['fit_gate'] and data['fit_gate']['allowed'] and data['verdict']['reason']!='실행 모델 불일치' and (out/'report.md').is_file():
        for shelf in read(DEMO/(spec.get('sets_file') or 'config/sets_known.json'),[]):
            product=next((p for p in shelf.get('products',[]) if p.get('target')),None)
            observed=raw_choice['shelves'].get(shelf['id'],{})
            if product and observed.get('valid_n'):
                data['concept_choices'].append({'title':product.get('real_name',product['id']),
                    'rate':observed['sim'].get(product['id'],0),'valid':observed['valid_n']})
    fingerprint={'spec':spec,'responses':response_fingerprint(name),'pair':pair,
                 'pair_responses':[response_fingerprint(pair[k]) for k in ('left','right') if pair.get(k)],
                 'checks':fit_console.hash_file(checks_path),
                 'source':[fit_console.hash_file(source_dir/name/f) for f in ('verification.json','source-reconciliation.json')],
                 'fit':fit.get('sha256'),'fit_status':fit.get('status'),'rules':FIT_RULES,
                 'truth':fit_console.hash_file(DEMO/spec['truth_file']) if spec.get('truth_file') else None,
                 'sets':fit_console.hash_file(DEMO/spec['sets_file']) if spec.get('sets_file') else None,
                 'primary':fit_console.hash_file(out/('known_eval_dual.json' if is_dual else 'known_eval.json')),
                 'report':data['report_hash']}
    data['verdict_fingerprint']=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()
    data['display_report']=analytics.operating_report(data)
    return data

def experiments():
    ledger=list(csv.DictReader((DEMO/'experiments/ledger.tsv').open(),delimiter='\t')) if (DEMO/'experiments/ledger.tsv').exists() else []
    s=state(); rows=[]
    for p in sorted((DEMO/'experiments').glob('*.json')):
        sp=read(p); name=sp.get('name',p.stem)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',name):continue
        out=DEMO/'results'/name; settings=read(out/'settings.json',{})
        j=s['jobs'].get(name); status=j['status'] if j else '끝' if (out/'report.md').exists() else '일부 응답 있음' if out.exists() else '대기'
        # A previous process cannot be called running after a server restart.
        if status=='실행 중' and name not in JOBS:status='실행 확인 필요'
        rows.append({'name':name,'status':status,'n':sp.get('n'),'model':settings.get('model','미실행'),'receipt_id':sp.get('receipt_id'),
                     'concept_title':sp.get('concept_title'),'goal':sp.get('goal',''),'locked':(out/'spec_locked.json').exists()})
    return rows,ledger

FIT_RULES = fit_console.FIT_RULES


def verdict_inputs(name):
    path=STATE/'verdict-inputs'/f'{name}.json'
    return read(path, read(HERE/'fixtures/verdict-inputs'/f'{name}.json',{}))


def shortlist_memo(rows, receipt):
    lines=['# 정량 조사 의뢰 메모','',f'접수 {receipt}']
    for row in rows:
        if row['receipt']==receipt and row.get('confirmed_by'):
            lines += ['',f"## {row['concept']}",f"- 결정 {row['decision']}",f"- 이유 {row['reason']}",
                      f"- 근거 {row['basis']}",f"- 당시 게이트 {row['gate']}",f"- 판정 입력 지문 {row['fingerprint']}"]
    return '\n'.join(lines)+'\n'


def fit_status():
    return fit_console.fit_status(PROJECT, DEMO)


def fit_gate(spec=None, benchmark=None, fit=None):
    return fit_console.gate(fit or fit_status(), spec, benchmark)


def fit_limits():
    doc=PROJECT/'preregistration-FIT.md'
    text=doc.read_text() if doc.is_file() else ''
    section=re.search(r'^## 10\. [^\n]+\n(.*?)(?=^## |\Z)',text,re.M|re.S)
    return [line[2:] for line in section[1].splitlines() if line.startswith('- ')] if section else []


def overview():
    s=state()
    actions=s.get('actions',[])
    held=[]
    for name in ('T2','T3','T4'):
        if (DEMO/'results'/name/'report.md').is_file():
            info=detail(name)
            if info['verdict']['status']=='fail':
                held.append({'name':name,'reason':info['verdict']['reason']})
    return {'held':held,'blocks':[row for row in actions if row['action']=='실행 차단'],
            'rank_rejections':sum(row['action']=='순위 사용 승인 거절' for row in actions),
            'shortlist':[x for x in s.get('shortlist',[]) if x.get('confirmed_by')],
            'recent':actions[-5:][::-1],
            'reproduction':'미달' if any(x['name'] in ('T2','T4') for x in held) else '확인 필요'}


def category_readiness():
    latest={}
    for name in ('T0','T1','T2','T3','T4'):
        spec=read(DEMO/'experiments'/f'{name}.json',{})
        report=DEMO/'results'/name/'report.md'
        if not spec or not report.is_file():continue
        shelves=read(DEMO/(spec.get('sets_file') or 'config/sets_known.json'),[])
        checked=detail(name)
        for category in {x.get('category') for x in shelves}:
            latest[category]={'name':name,'status':checked['checks']['reproduction'],'reason':checked['verdict']['reason']}
    return latest


def receipt_progress(s, rows):
    for receipt in s['receipts']:
        exp=next((x for x in reversed(rows) if x.get('receipt_id')==receipt['id']),None)
        done=[x for x in s.get('shortlist',[]) if x['receipt']==receipt['id'] and x.get('confirmed_by')]
        if len(done)>=len(receipt.get('concepts') or [receipt]):
            receipt.update(progress='정량 조사 후보 결정됨',next_role='조사 담당')
        elif exp:
            progress={'막힘':'막힘','끝':'실행 끝'}.get(exp['status'],'설정됨')
            receipt.update(progress=progress,next_role='BM' if progress in ('막힘','실행 끝') else '조사 담당')
        else:receipt.update(progress='설정 전',next_role='조사 담당')
    return s


def make_spec(s,d):
    guard(s,['조사 담당']); name=ident(d['name']); p=DEMO/'experiments'/f'{name}.json'
    if p.exists() or (DEMO/'results'/name).exists():raise ValueError('기존 실험 이름은 쓸 수 없습니다. 새 이름으로 만드세요.')
    n=int(d.get('n',150))
    if not name.startswith('OPS_'):raise ValueError('새 실험 이름은 OPS_로 시작하세요.')
    if int(d.get('batch',5)) not in (1,5,15):raise ValueError('배치는 1명, 5명, 15명 중에서 선택하세요.')
    if not 1<=n<=10000:raise ValueError('표본 수는 1~10000명입니다.')
    receipt=next((x for x in s['receipts'] if x['id']==d.get('receipt')),None)
    source=receipt['sets_file'] if receipt else 'config/sets_known.json'
    sets=read(DEMO/source)
    category=d.get('category','전체')
    if category!='전체':sets=[x for x in sets if x.get('category')==category]
    if not sets:raise ValueError('선택한 범주에 진열대가 없습니다.')
    base={p['id']:p for sh in read(DEMO/'config/sets.json',[]) for p in sh.get('products',[])}
    for sh in sets:
        if 'product_ids' in sh:
            inline={p['id']:p for p in sh.get('products_inline',[])}
            sh['products']=[]
            for pid in sh.pop('product_ids'):
                product=inline.get(pid) or base[pid]
                sh['products'].append({**product,'target':False,'attrs':{**product['attrs'],**sh.get('override',{}).get(pid,{})}})
    sets_file=f'config/sets_{name}.json';dump(DEMO/sets_file,sets,True)
    # Freeze truth at setup so the current benchmark cannot drift after the run.
    truth=None
    if not receipt:
        old=read(DEMO/'config/known_truth.json',{});truth=f'config/truth_{name}.json';dump(DEMO/truth,{k:v for k,v in old.items() if k.startswith('_') or k in {x['id'] for x in sets}},True)
    flags=['--no-new-hint','--workers','1','--batch',str(int(d.get('batch',5)))]
    if d.get('per_person_order',True):flags.append('--per-person-order')
    if d.get('named'):flags.append('--named')
    if d.get('equal'):flags.append('--equal-cards')
    spec={'name':name,'goal':str(d.get('goal','운영 화면에서 만든 비교 실험')),'sets_file':sets_file,'truth_file':truth,'n':n,'flags':flags,'category':category,'created_at':now(),'pass_rule':'사전 기준 미설정: 자동 신뢰 판정 불가'}
    if not receipt and len(sets)==5:
        spec['console_gate']={'shelves':5,'last_min':4,'weak_min':.8}
        spec['pass_rule']='작가 결정 2026-11-04: 기존 진열대 5개 중 꼴찌 일치 4개 이상 + 약한 제품이 낀 짝 맞힘 80% 이상'
    refs={}
    for kind,filename in [('population','adopter.json'),('diffusion',d.get('diffusion_config','default.json'))]:
        item=config_editor.get(PROJECT,kind,filename)
        if item.get('status')=='사용 가능':
            snapshot=STATE/'config-snapshots'/name/(kind+'.json');dump(snapshot,item['data'],True)
            refs[kind]={'source':kind+'/config/'+filename,'sha256':item['sha256'],'snapshot':str(snapshot.relative_to(STATE))}
    spec['ops_config_refs']=refs
    if receipt:
        spec['receipt_id']=receipt['id']
        spec['concept_title']=receipt['title']
        spec['validation_reference']=ident(d.get('validation_reference') or 'T2')
        spec['flags'][spec['flags'].index('--batch')+1]='1'
        if '--per-person-order' not in spec['flags']:spec['flags'].append('--per-person-order')
    sensitivity=d.get('sensitivity_pair')
    if sensitivity:
        peer=ident(sensitivity)
        if not (DEMO/'experiments'/f'{peer}.json').is_file():raise ValueError('등록된 비교 실험을 선택하세요.')
        dump(STATE/'verdict-inputs'/f'{name}.json',{'sensitivity_pair':{'left':name,'right':peer}},True)
    dump(p,spec,True);event(s,'실험 설정',{'name':name,'spec':spec});return spec

def receive_concepts(s,d):
    concepts=d['concepts']; competitors=d.get('competitors',[]); category=d.get('category')
    if not isinstance(concepts,list) or not 1<=len(concepts)<=3:raise ValueError('콘셉트는 1~3개 접수할 수 있습니다.')
    catalog={p['id']:p for p in specimens()}
    if category not in {p['category'] for p in catalog.values()}:raise ValueError('등록된 경쟁 제품이 있는 범주를 고르세요.')
    if not 2<=len(competitors)<=5 or len(set(competitors))!=len(competitors) or any(c not in catalog for c in competitors):
        raise ValueError('서로 다른 경쟁 제품 2~5개를 고르세요.')
    sets=[]; entries=[]; name=unique_name('OPS_CARD_')
    for i,concept in enumerate(concepts,1):
        title=str(concept.get('title','')).strip(); attrs=concept.get('attrs',{})
        if not title or any(not str(attrs.get(k,'')).strip() for k in ATTRS):
            raise ValueError(f'콘셉트 {i}의 이름과 7개 속성을 모두 채우세요.')
        key=f'c{i}'; product={'id':f'{name}_{key}','real_name':title,'maker':'','target':True,
                              'attrs':{k:str(attrs[k]).strip() for k in ATTRS}}
        sets.append({'id':f'{name}_{key}','category':category,'launch':d.get('launch','현재'),
                     'seen_at':'동네 마트·편의점','sample':'drinkers' if category in ('맥주','소주') else 'adults',
                     'products':[product]+[{**catalog[c],'target':False} for c in competitors]})
        entries.append({'id':key,'title':title})
    path=f'config/sets_{name}.json'
    dump(DEMO/path,sets,True)
    receipt={'id':name,'created_at':now(),'category':category,'title':' / '.join(x['title'] for x in entries),
             'concepts':entries,'sets_file':path}
    s['receipts'].append(receipt);event(s,'콘셉트 접수',receipt);return receipt


def mutate(action,d):
    with LOCK:
        s=state()
        if action=='migrate-t2-pair':
            pair=s.get('sensitivity_pairs',{}).get('T2')
            path=STATE/'verdict-inputs/T2.json'
            if pair and not path.exists():
                dump(path,{'sensitivity_pair':pair},True)
                event(s,'이전',{'name':'T2','sensitivity_pair':pair},actor='운영 도구')
            return verdict_inputs('T2')
        if action=='fit-review':
            guard(s,['조사 담당'])
            note=str(d.get('memo','')).strip()
            fit=fit_status()
            if not note or not fit.get('sha256'):raise ValueError('정합성 결과와 확인 메모가 필요합니다.')
            event(s,'정합성 결과 확인',{'memo':note,'sha256':fit['sha256']});return {'status':'기록됨'}
        if action=='report':
            guard(s,ROLES);name=ident(d['name']);info=detail(name)
            lines=[info['display_report']]
            path=STATE/'reports'/name/'report.md';path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(lines),encoding='utf-8');event(s,'운영 보고서 생성',{'name':name,'path':str(path)});return {'path':str(path)}
        if action=='sensitivity':
            guard(s,['조사 담당']);name=ident(d['name']);left=ident(d['left']);right=ident(d['right'])
            if name not in (left,right) or left==right:raise ValueError('현재 실험을 포함한 서로 다른 비교 쌍을 선택하세요.')
            finished=(DEMO/'results'/name/'report.md').is_file() or (DEMO/'results'/name/'spec_locked.json').is_file()
            reason=str(d.get('reason','')).strip()
            if finished and not reason:raise ValueError('실행 뒤 비교 쌍을 바꾸려면 재판정 이유를 적으세요.')
            previous=detail(name)
            path=STATE/'verdict-inputs'/f'{name}.json'
            dump(path,{**verdict_inputs(name),'sensitivity_pair':{'left':left,'right':right}})
            updated=detail(name)
            event(s,'재판정' if finished else '비교 쌍 지정',{'name':name,'left':left,'right':right,'reason':reason,
                  'before':previous['verdict'],'after':updated['verdict'],'fingerprint':updated['verdict_fingerprint']})
            return updated['sensitivity']
        if action=='external-checks':
            guard(s,['데이터 담당']);name=ident(d['name']);checks=d.get('checks')
            if not isinstance(checks,dict) or not checks or any(k not in ('baseline','leakage','stability','noise','human_mismatch')
                or not isinstance(v,dict) or not str(v.get('source','')).strip()
                or (type(v.get('value')) is not bool if k=='human_mismatch' else v.get('status') not in ('pass','fail'))
                for k,v in checks.items()):raise ValueError('검사 항목·결과와 출처를 확인하세요.')
            target=STATE/'verdict-inputs'/name/'checks.json'
            dump(target,checks)
            event(s,'외부 점검 결과 연결',{'name':name,'sha256':fit_console.hash_file(target),'fingerprint':detail(name)['verdict_fingerprint']})
            return {'status':'연결됨'}
        if action in ('shortlist','shortlist-confirm'):
            guard(s,['BM'] if action=='shortlist' else ['조사 담당'])
            name=ident(d['name']);info=detail(name);rid=info.get('receipt_id')
            receipt=next((x for x in s['receipts'] if x['id']==rid),None)
            if not receipt:raise ValueError('콘셉트 접수로 만든 실험을 선택하세요.')
            options=receipt.get('concepts') or [{'id':'c1','title':receipt['title']}]
            concept=next((x for x in options if x['id']==d.get('concept')),None)
            if not concept:raise ValueError('접수에 포함된 콘셉트를 선택하세요.')
            rows=s.setdefault('shortlist',[])
            pending=next((r for r in reversed(rows) if r['experiment']==name and r['concept_id']==concept['id']),None)
            gate=info['fit_gate']
            may_use=bool(gate and gate['allowed'] and info['concept_choices'] and info['verdict']['reason']!='실행 모델 불일치')
            if action=='shortlist':
                reason=str(d.get('reason','')).strip();decision=d.get('decision');basis=d.get('basis')
                if not reason or decision not in ('올림','뺌','다음으로 미룸') or basis not in ('가상 결과','가상 결과 쓰지 않음(기존 방식)'):
                    raise ValueError('결정·이유·근거를 적으세요.')
                if basis=='가상 결과' and not may_use:raise ValueError('막힌 가상 결과를 후보 결정 근거로 쓸 수 없습니다.')
                if pending and pending.get('confirmed_by'):raise ValueError('이미 확정된 콘셉트입니다.')
                if pending:rows.remove(pending)
                row={'receipt':rid,'experiment':name,'concept_id':concept['id'],'concept':concept['title'],'decision':decision,
                     'reason':reason,'basis':basis,'gate':gate['status'] if gate else '확인 불가',
                     'proposed_by':s['role'],'proposed_at':now(),'fingerprint':info['verdict_fingerprint']}
                rows.append(row);event(s,'정량 조사 후보 제안',row);return row
            if not pending or pending.get('confirmed_by') or pending['proposed_by']==s['role']:
                raise ValueError('BM이 제안한 미확정 결정을 선택하세요.')
            if pending['fingerprint']!=info['verdict_fingerprint'] or (pending['basis']=='가상 결과' and not may_use):
                raise ValueError('판정 입력이 바뀌었습니다. BM이 다시 제안해야 합니다.')
            pending.update(confirmed_by=s['role'],confirmed_at=now())
            event(s,'정량 조사 후보 확정',pending);return pending
        if action=='config':
            kind=d.get('kind');guard(s,['데이터 담당'] if kind=='population' else ['조사 담당','데이터 담당'])
            def finite(v):
                if isinstance(v,float) and not __import__('math').isfinite(v):raise ValueError('무한대·NaN 설정은 허용하지 않습니다.')
                if isinstance(v,dict):
                    for x in v.values():finite(x)
                if isinstance(v,list):
                    for x in v:finite(x)
            finite(d.get('data'))
            source,target,old=config_editor.prepare(PROJECT,kind,d.get('name'),d.get('sha256'),d.get('data'),d.get('new_name') or None)
            history=STATE/'config-history'/unique_name('edit_')
            dump(history.with_suffix('.json'),{'source':str(source),'before':old,'after':d['data'],'actor':s['role'],'time':now()},True)
            dump(target,d['data'],exclusive=source!=target)
            event(s,'설정 저장',{'kind':kind,'file':str(target.relative_to(PROJECT)),'before_sha256':d['sha256'],'after_sha256':config_editor.digest(target),'rebuild_required':True})
            return config_editor.get(PROJECT,kind,target.name)
        if action=='role':
            if d.get('role') not in ROLES:raise ValueError('알 수 없는 역할')
            prev=s['role'];s['role']=d['role'];event(s,'역할 변경',{'from':prev,'to':s['role']});return s
        if action=='cards':
            guard(s,['BM'])
            if 'concepts' in d:return receive_concepts(s,d)
            products=d.get('products',[])
            if not 2<=len(products)<=6:raise ValueError('시안과 경쟁 제품을 합쳐 2~6개 넣으세요.')
            if len({x.get('id') for x in products})!=len(products):raise ValueError('제품 번호가 중복됩니다.')
            name=unique_name('OPS_CARD_'); rows=[]
            for i,p in enumerate(products):
                ident(p['id']);attrs=p.get('attrs',{})
                if not attrs.get('종류') or not attrs.get('컨셉'):raise ValueError('종류와 콘셉트는 필수입니다.')
                rows.append({'set_id':name,'launch':d.get('launch','현재'),'category':d.get('category','맥주'),'seen_at':'동네 마트·편의점','sample':'drinkers' if d.get('category','맥주') in ['맥주','소주'] else 'adults','product_id':p['id'],'real_name':p.get('real_name',''),'maker':p.get('maker',''),'target':'1' if i==0 else '0',**{k:attrs.get(k,'') for k in ATTRS}})
            path=DEMO/f'inbox/cards/{name}.csv';path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            out=ingest('cards',rows,name);receipt={'id':name,'created_at':now(),'category':d.get('category','맥주'),'title':products[0].get('real_name') or products[0]['id'],'sets_file':str(out.relative_to(DEMO)),'csv':str(path.relative_to(DEMO)),'profile_balance':analytics.profile_balance(products)};s['receipts'].append(receipt);event(s,'시안 접수',receipt);return receipt
        if action=='experiment':return make_spec(s,d)
        if action=='run':
            guard(s,['조사 담당']);name=ident(d['name']);sp=read(DEMO/'experiments'/f'{name}.json')
            if not sp:raise ValueError('실험 설정이 없습니다.')
            if not d.get('confirmed'):raise ValueError('실행 확인이 필요합니다.')
            if name in JOBS or (DEMO/'results'/name/'spec_locked.json').exists():raise ValueError('실행된 설정은 잠겨 있습니다. 새 이름으로 설정하세요.')
            if not name.startswith('OPS_'):raise ValueError('기존 실험 보호: 화면에서 OPS_로 시작하는 새 설정을 만드세요.')
            eligibility=None
            if sp.get('validation_reference') or sp.get('receipt_id'):
                ref_name=sp.get('validation_reference')
                ref=detail(ref_name) if ref_name else None
                recorded=read(DEMO/'results'/str(ref_name)/'settings.json',{}) if ref else {}
                benchmark={'status':ref['checks']['reproduction'],'population_id':recorded.get('population_id'),
                           'model':str(recorded.get('model','')).split(':')[-1]} if ref else None
                eligibility=fit_gate(sp,benchmark)
                if not eligibility['allowed']:
                    s['jobs'][name]={'status':'막힘'}
                    event(s,'실행 차단',{'name':name,'stage':eligibility['stage'],'reason':eligibility['reason']})
                    raise ValueError(f"{eligibility['stage']}단계 · {eligibility['reason']}")
            stub=bool(d.get('stub',False))
            if stub and os.environ.get('OPS_ALLOW_STUB')!='1':raise ValueError('가짜 응답은 격리 시험 서버에서만 허용됩니다.')
            py=os.environ.get('OPS_PYTHON',sys.executable)
            if not stub and subprocess.run([py,'-c','import numpy'],capture_output=True).returncode:raise ValueError('기존 시연판 실행용 Python에 numpy가 없습니다. OPS_PYTHON으로 설치된 환경을 지정하세요.')
            s['jobs'][name]={'status':'실행 중','mode':'가짜 응답 시험' if stub else '실제 모델','started':now()};event(s,'실행 시작',{'name':name,'stub':stub})
            (STATE/'logs').mkdir(exist_ok=True)
            initiator=s['role']
            def job():
                try:
                    env=os.environ.copy()
                    if eligibility:
                        env['LLM_BACKEND']=eligibility['backend'];env['LLM_MODEL']=eligibility['model']
                    if stub:env['PYTHONPATH']=str(HERE/'stub')+os.pathsep+env.get('PYTHONPATH','');env['OPS_STUB']='1'
                    with (STATE/'logs'/f'{name}.log').open('w') as log:r=subprocess.run([py,str(DEMO/'run_experiment.py'),f'experiments/{name}.json'],cwd=DEMO,env=env,stdout=log,stderr=subprocess.STDOUT)
                    result='끝' if r.returncode==0 else '실패'
                except Exception as e:result='실패';(STATE/'logs'/f'{name}.log').write_text(str(e))
                with LOCK:
                    ss=state();ss['jobs'][name]['status']=result;ss['jobs'][name]['finished']=now();event(ss,'실행 종료',{'name':name,'status':result},actor=initiator);JOBS.pop(name,None)
            t=threading.Thread(target=job,daemon=True);JOBS[name]=t;t.start();return {'name':name,'status':'실행 중'}
        if action=='decision':
            guard(s,['BM','조사 담당']);name=ident(d['name']);info=detail(name);kind=d.get('decision')
            if kind not in ['승인','반려','메모']:raise ValueError('처리 유형 오류')
            if not str(d.get('memo','')).strip():raise ValueError('처리 이유를 적으세요.')
            if kind=='승인' and info['verdict']['label'] in ['포기','판정 대기'] and d.get('route')!='사람 조사':
                event(s,'순위 사용 승인 거절',{'name':name,'fingerprint':info['verdict_fingerprint']})
                raise ValueError('지금은 사람 조사 전환만 승인할 수 있습니다.')
            event(s,kind,{'name':name,'route':d.get('route','사람 조사'),'memo':d['memo'],'verdict':info['verdict'],'fingerprint':info['verdict_fingerprint']});return info['verdict']
        if action=='survey':
            guard(s,['조사 담당']);name=ident(d['name']);original=read(DEMO/'experiments'/f'{name}.json')
            if not original:raise ValueError('연결할 실험이 없습니다.')
            rows=list(csv.DictReader(io.StringIO(d.get('csv','').lstrip('\ufeff'))))
            if not rows or len(rows)>50000:raise ValueError('사람 조사 CSV가 비었거나 너무 큽니다.')
            sets=read(DEMO/original['sets_file']);base={p['id']:p for x in read(DEMO/'config/sets.json',[]) for p in x.get('products',[])}
            allowed={x['id']:set(x.get('product_ids') or [p['id'] for p in x.get('products',[])]) for x in sets}
            seen=set()
            for r in rows:
                if not all(k in r and r[k].strip() for k in ['set_id','respondent_id','choice_product_id']):raise ValueError('CSV 필수 칸을 확인하세요.')
                if r['set_id'] not in allowed or r['choice_product_id'] not in allowed[r['set_id']]:raise ValueError('진열대·제품 번호가 실험과 다릅니다. 무응답은 별도 보관하세요.')
                key=(r['set_id'],r['respondent_id'])
                if key in seen:raise ValueError('같은 사람·진열대 응답이 중복됩니다.')
                seen.add(key)
            raw=analytics.raw_shares(DEMO,name,original,'choice')
            missing_sets={r['set_id'] for r in rows}-set(raw['shelves'])
            if missing_sets:raise ValueError('소비자 조사 대상의 가상 1순위 선택 응답이 미완결입니다: '+', '.join(sorted(missing_sets)))
            sn=unique_name('OPS_SURVEY_');path=DEMO/f'inbox/human_survey/{sn}.csv';path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=['set_id','respondent_id','choice_product_id']);w.writeheader();w.writerows(rows)
            truth=ingest('survey',rows,sn)
            # Zero-choice products must stay in the comparison; ingest counts only observed choices.
            tr=read(truth)
            for sid in [k for k in tr if not k.startswith('_')]:
                for pid in allowed[sid]:tr[sid]['value'].setdefault(pid,0)
            dump(truth,tr)
            sp={**original,'name':sn,'truth_file':str(truth.relative_to(DEMO)),'goal':'사람 조사와 같은 시안의 가상 응답 비교','pass_rule':'사람 조사 비교용. 자동 통과 기준 미설정'};sp.pop('console_gate',None);dump(DEMO/'experiments'/f'{sn}.json',sp,True)
            # Current synthetic shares are observed response counts, never guessed.
            current={raw['key']:{'shelves':raw['shelves']}};key=raw['key'];cal={}
            for sid,t in tr.items():
                if sid.startswith('_'):continue
                total=sum(t['value'].values());sim=current.get(key,{}).get('shelves',{}).get(sid,{}).get('sim',{})
                cal[sid]={p:{'human_share':v/total,'sim_share':sim.get(p),'factor':v/total/sim[p] if sim.get(p,0)>0 else None} for p,v in t['value'].items()}
            item={'id':sn,'experiment':name,'n':len(rows),'status':'데이터 담당 승인 대기','comparison':sn,'calibration':cal,'metric_key':key,'response_fingerprint':response_fingerprint(name),'truth_file':str(truth.relative_to(DEMO))};s['surveys'].append(item);event(s,'사람 조사 접수',item);return item
        if action=='calibration':
            guard(s,['데이터 담당']);item=next((x for x in s['surveys'] if x['id']==d.get('id')),None)
            if not item:raise ValueError('조사 결과가 없습니다.')
            if item['status']=='승인':raise ValueError('이미 승인한 보정입니다.')
            if not item['calibration'] or any(x['factor'] is None for sh in item['calibration'].values() for x in sh.values()):raise ValueError('가상 응답 0 또는 미실행 제품의 보정값은 계산할 수 없습니다. 비교 실험이 필요합니다.')
            if item.get('response_fingerprint')!=response_fingerprint(item['experiment']):raise ValueError('사람 조사 접수 뒤 가상 응답이 바뀌었습니다. 비교를 다시 접수하세요.')
            item['status']='승인';item['approved_at']=now();dump(STATE/'calibration'/f"{item['id']}.json",item,True);event(s,'보정 승인',{'id':item['id'],'scope':'해당 실험 보정 전후 표시 및 다음 사이클용 보정 파일 저장, 원본 응답 불변'});return item
        raise ValueError('알 수 없는 작업')

class Handler(BaseHTTPRequestHandler):
    def output(self,data,status=200,ctype='application/json; charset=utf-8'):
        b=data.encode() if isinstance(data,str) else json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(b)
    def do_GET(self):
        if urlparse('http://'+self.headers.get('Host','')).hostname not in ('localhost','127.0.0.1'):return self.output({'error':'로컬 주소만 허용'},403)
        u=urlparse(self.path)
        try:
            if u.path=='/':return self.output((HERE/'index.html').read_text(),ctype='text/html; charset=utf-8')
            if u.path in ('/fit_view.js','/operation_view.js'):return self.output((HERE/u.path[1:]).read_text(),ctype='text/javascript; charset=utf-8')
            if u.path=='/api/fit':return self.output(fit_status())
            if u.path=='/api/shortlist-memo':
                receipt=ident(parse_qs(u.query)['receipt'][0])
                return self.output(shortlist_memo(state().get('shortlist',[]),receipt),ctype='text/markdown; charset=utf-8')
            if u.path=='/api/state':
                fit=fit_status();ex,led=experiments();return self.output({'state':receipt_progress(state(),ex),'readiness':category_readiness(),'fit':fit,'fit_gate':fit_gate(fit=fit),'fit_limits':fit_limits(),'overview':overview(),'experiments':ex,'ledger':led,'products':specimens(),'token':TOKEN,'demo':str(DEMO),'stub_allowed':os.environ.get('OPS_ALLOW_STUB')=='1','configs':config_editor.inventory(PROJECT)})
            if u.path=='/api/config':
                q=parse_qs(u.query);return self.output(config_editor.get(PROJECT,q['kind'][0],q['name'][0]))
            if u.path=='/api/detail':return self.output(detail(parse_qs(u.query)['name'][0]))
            return self.output({'error':'찾을 수 없음'},404)
        except Exception as e:return self.output({'error':str(e)},400)
    def do_POST(self):
        if urlparse('http://'+self.headers.get('Host','')).hostname not in ('localhost','127.0.0.1'):return self.output({'error':'로컬 주소만 허용'},403)
        if self.headers.get('X-Console-Token')!=TOKEN:return self.output({'error':'화면을 새로고침하세요.'},403)
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.output({'error':'다른 사이트 요청 차단'},403)
        n=int(self.headers.get('Content-Length',0))
        if n>4_000_000:return self.output({'error':'파일은 4MB까지'},413)
        try:return self.output(mutate(self.path.removeprefix('/api/'),json.loads(self.rfile.read(n))))
        except Exception as e:return self.output({'error':str(e)},400)
    def log_message(self,*args):pass

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=8765);a=ap.parse_args()
    if not (STATE/'state.json').exists():dump(STATE/'state.json',state())
    mutate('migrate-t2-pair',{})
    print(f'운영 화면: http://localhost:{a.port} (로컬 역할 시연, 인증 서버 아님)',flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
if __name__=='__main__':main()
