#!/usr/bin/env python3
"""Price/volume variants through unmodified run_experiment.py, capped and audited.
Example: python3 price_sweep.py --exp experiments/T2.json --product cider_2021 --price 1800,2000,2200 --n 6 --batch 6 --name cider_demo
"""
from __future__ import annotations
import argparse,collections,copy,hashlib,importlib.util,itertools,json,math,os,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SUPPORT=ROOT/'price_sweep_support'
sys.path.insert(0,str(SUPPORT))
from common import FIELDS,persona_text,readonly_json,save,sha
import simulate

PREFIX='가격 수준이 아닌 가격을 바꿨을 때의 순위 변화 방향만 본다'


def numbers(text):
    vals=[int(x.strip()) for x in text.split(',')]
    if not vals or any(x<=0 for x in vals) or len(set(vals))!=len(vals):raise ValueError('positive distinct integer values required')
    return vals


def find_path(value):
    p=Path(value)
    return p.resolve() if p.exists() else ROOT/p


def option(flags,key,default=None):
    return flags[flags.index(key)+1] if key in flags else default


def run_flags(flags,batch,workers):
    flags=list(flags)
    if '--dry-run' in flags or '--set' in flags or '--sets-file' in flags or '--tag' in flags or '--limit' in flags:raise ValueError('base flags contain a run-scope override; use a clean experiment config')
    for flag in ('--batch','--workers'):
        if flag in flags:
            k=flags.index(flag);del flags[k:k+2]
    return flags+['--batch',str(batch),'--workers',str(workers)]


def price_value(product):
    text=product['attrs'].get('가격','');matches=list(re.finditer(r'([0-9][0-9,]*)\s*원',text))
    if len(matches)!=1 or '~' in text:raise ValueError('target card must have one unambiguous KRW amount')
    return int(matches[0].group(1).replace(',',''))


def volume_value(product):
    for text in (product['attrs'].get('용량',''),product['attrs'].get('가격','')):
        match=re.search(r'(\d+)\s*(?:ml|mL|㎖)',text)
        if match:return int(match.group(1))
    return None


def mutate(shelf,product_id,price,volume=None):
    result=copy.deepcopy(shelf)
    product=next(p for p in result['products'] if p['id']==product_id)
    original=next(p for p in shelf['products'] if p['id']==product_id)
    product['attrs']['가격']=re.sub(r'([0-9][0-9,]*)\s*원',f'{price:,}원',original['attrs']['가격'])
    if volume is not None:
        product['attrs']['용량']=f'{volume}ml'
        product['attrs']['가격']=re.sub(r'\d+\s*(?:ml|mL|㎖)',f'{volume}ml',product['attrs']['가격'])
    a=copy.deepcopy(shelf);b=copy.deepcopy(result)
    for row in (a,b):
        target=next(p for p in row['products'] if p['id']==product_id)
        for key in ('가격','용량'):target['attrs'].pop(key,None)
    if a!=b:raise AssertionError('non-price/volume mutation detected')
    return result


def preview(shelf,people,flags,product_id):
    simulate.persona_text=persona_text
    simulate.OPTS.update(scene=option(flags,'--scene'),new_hint='--no-new-hint' not in flags,equal_cards='--equal-cards' in flags,ask_qty='--ask-qty' in flags)
    named='--named' in flags;system,user,order,labels,keys=simulate.build_messages(people,shelf,named)
    target=next(p for p in shelf['products'] if p['id']==product_id)
    index=next(i for i,j in enumerate(order) if shelf['products'][j]['id']==product_id)
    label=labels[index]
    marker=f'[{label}]\n';block=user.split(marker,1)[1].split('\n\n',1)[0] if marker in user else ''
    # Check effective target block, not a price elsewhere in prompt/persona.
    if '가격: '+target['attrs']['가격'] not in block:raise ValueError('target price is absent/truncated in effective prompt (for example --equal-cards removes it); base flags are not silently changed')
    if '용량' in target['attrs'] and '용량: '+target['attrs']['용량'] not in block:raise ValueError('target volume is absent/truncated in effective prompt; change experiment explicitly')
    if any(p['uuid'] in user or p['uuid'] in system for p in people):raise AssertionError('UUID in outbound prompt')
    return {'system':system,'user':user,'target_label':label,'target_block':block,'uuid_sent':False,'persona_fields':list(FIELDS)}


def metrics(rows,ids,target):
    n=len(rows);count=collections.Counter(r['choice'] for r in rows);votes=sum(count[i] for i in ids)
    rank=None if votes==0 else 1+sum(count[i]>count[target] for i in ids)
    tied=rank is not None and sum(count[i]==count[target] for i in ids)>1
    return {'n_responses':n,'target_count':count[target],'choice_share_all':count[target]/n if n else None,'rank':rank,'tied':tied,'none_count':count['없음'],'none_share':count['없음']/n if n else None,'product_counts':{i:count[i] for i in ids}}


def build_plan(args):
    base_path=find_path(args.exp);base=json.loads(base_path.read_text(encoding='utf-8'))
    shelves=simulate.load_sets(base['sets_file']);matches=[s for s in shelves if any(p['id']==args.product for p in s['products'])]
    if args.shelf:matches=[s for s in matches if s['id']==args.shelf]
    if len(matches)!=1:raise ValueError('target occurs on zero or multiple shelves; select exactly one --shelf')
    shelf=matches[0];target=next(p for p in shelf['products'] if p['id']==args.product)
    base_price=price_value(target);base_volume=volume_value(target);prices=numbers(args.price);volumes=numbers(args.volume) if args.volume else [None]
    if args.volume and base_volume is None:raise ValueError('volume sweep requires an identifiable original ml volume for control')
    n=args.n if args.n is not None else min(6,max(1,int(base['n'])-1))
    if not 0<n<int(base['n']):raise ValueError('sweep n must be positive and below base experiment n')
    flags=run_flags(base.get('flags',[]),args.batch,1);reps=int(option(flags,'--reps','1'))
    if reps<1:raise ValueError('reps must be positive')
    if args.batch<1 or args.batch>n:raise ValueError('batch must be 1..n')
    sample_path=ROOT/f"data/{shelf['sample']}.json";all_people=json.loads(sample_path.read_text(encoding='utf-8'));people=all_people[:n]
    if len(people)!=n or len({p['uuid'] for p in people})!=n:raise ValueError('missing/duplicate input people')
    origin_path=ROOT.parent/'population/out/legacy_enriched.json'
    origin={row['uuid']:row for row in json.loads(origin_path.read_text(encoding='utf-8'))}
    proof=[]
    for person in people:
        if person['uuid'] not in origin:raise ValueError('persona UUID not matched to verified public synthetic source')
        fields=[field for field in FIELDS if field in person]
        if any(person[field]!=origin[person['uuid']].get(field) for field in fields):raise ValueError('outbound attribute differs from verified public source')
        proof.append({'uuid':person['uuid'],'matched_fields':fields,'matches_public_source':True})
    combos=list(itertools.product(prices,volumes));control=(base_price,base_volume if args.volume else None)
    if control not in combos:combos.append(control)
    calls_per=math.ceil(n/args.batch)*reps;planned=len(combos)*calls_per
    if not args.stub and planned>args.max_calls:raise ValueError(f'planned model calls {planned} exceed max_calls {args.max_calls}')
    inputs=[base_path,ROOT/base['sets_file'],ROOT/'config/sets.json',sample_path,origin_path,ROOT/'run_experiment.py',ROOT/'simulate.py',ROOT/'llm.py',ROOT/'known_eval.py',Path(__file__),*sorted(SUPPORT.glob('*.py'))]
    sources=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in inputs]
    signature_data={'base_sha256':sha(base_path),'sources':sources,'product':args.product,'shelf':shelf['id'],'prices':prices,'volumes':volumes,'n':n,'flags':flags,'stub':args.stub,'max_calls':args.max_calls,'timeout_seconds':args.timeout}
    signature=hashlib.sha256(json.dumps(signature_data,sort_keys=True).encode()).hexdigest()
    name=args.name or f'{base["name"]}_{args.product}_{signature[:10]}'
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,90}',name):raise ValueError('name must be a safe identifier')
    folder=ROOT/'results'/('sweep_'+name);variants=[]
    for price,vol in combos:
        key=f'p{price}_v{vol if vol is not None else "original"}'
        changed=mutate(shelf,args.product,price,vol);prompt=preview(changed,people[:args.batch],flags,args.product)
        variants.append({'key':key,'price':price,'volume':vol,'effective_volume':vol or base_volume,'control':(price,vol)==control,'shelf':changed,'prompt':prompt,'experiment_name':f'sweep_{name}/{key}','n':n,'reps':reps,'sample':shelf['sample'],'shelf_id':shelf['id'],'product_ids':[p['id'] for p in shelf['products']],'named':'--named' in flags,'target_label':prompt['target_label'],'calls_cap':calls_per,'timeout_seconds':args.timeout})
    return {'signature':signature,**signature_data,'name':name,'folder':str(folder),'base':base,'base_price':base_price,'base_volume':base_volume,'planned_calls':planned,'control':list(control),'expected_uuids':[p['uuid'] for p in people],'variants':variants,'public_source_proof':{'source':str(origin_path),'source_sha256':sha(origin_path),'people':proof,'all_matched':True}}


def verify_sources(plan):
    for source in plan['sources']:
        if sha(source['path'])!=source['sha256']:raise ValueError('input/source changed during sweep: '+source['path'])


def execute(args):
    plan=build_plan(args);folder=Path(plan['folder']);folder.mkdir(parents=True,exist_ok=True)
    readonly_json(folder/'sweep_locked.json',plan)
    readonly_json(folder/'public_source_proof.json',plan['public_source_proof'])
    flags=plan['flags'];exp_files=[]
    for variant in plan['variants']:
        sets_path=ROOT/f'config/sets_sweep_{plan["name"]}_{variant["key"]}.json'
        exp_path=ROOT/f'experiments/SWEEP_{plan["name"]}_{variant["key"]}.json'
        readonly_json(sets_path,[variant['shelf']])
        spec={'name':variant['experiment_name'],'goal':f'가격·용량 방향 시연: {args.product}; same-person control, not market validation','sets_file':str(sets_path.relative_to(ROOT)),'flags':flags,'n':variant['n'],'pass_rule':'가상 선택 비율·순위의 변화만 보고. 시장 정답 통과 판정 없음.'}
        readonly_json(exp_path,spec);exp_files.append(exp_path)
        out=folder/variant['key'];out.mkdir(exist_ok=True)
        readonly_json(out/'variant.json',variant)
        (out/'prompt_preview.txt').write_text(variant['prompt']['system']+'\n\n'+variant['prompt']['user'],encoding='utf-8')
    save(folder/'preflight.json',{'variant_count':len(plan['variants']),'planned_calls':plan['planned_calls'],'n':plan['n'],'stub':args.stub,'price_visible_all':True,'only_price_volume_attrs_changed':True,'uuid_sent':False,'control_price':plan['base_price'],'control_volume':plan['base_volume']})
    if args.prepare_only:return folder
    python=args.python or sys.executable
    check=subprocess.run([python,'-c','import numpy; print(numpy.__version__)'],capture_output=True,text=True)
    if check.returncode:raise ValueError('run_experiment requires numpy; choose the existing interpreter with --python')
    ledger=ROOT/'experiments/ledger.tsv';old=ledger.read_bytes() if ledger.exists() else b''
    if not (folder/'ledger_before.tsv').exists():(folder/'ledger_before.tsv').write_bytes(old)
    original_ledger=(folder/'ledger_before.tsv').read_bytes()
    actual=[];started=time.perf_counter()
    for variant,exp_path in zip(plan['variants'],exp_files):
        verify_sources(plan);out=folder/variant['key'];completion=out/'completeness.json'
        if completion.exists() and json.loads(completion.read_text()).get('complete') and (out/'report.md').exists():continue
        env=os.environ.copy();env['PRICE_SWEEP_VARIANT']=str(out/'variant.json');env['PRICE_SWEEP_STUB']='1' if args.stub else '0';env['PYTHONDONTWRITEBYTECODE']='1'
        with (out/'execution.log').open('a',encoding='utf-8') as log:
            log.write('\n=== invocation '+time.strftime('%Y-%m-%dT%H:%M:%S')+' ===\n');log.flush()
            proc=subprocess.run([python,str(SUPPORT/'runner.py'),str(exp_path.relative_to(ROOT))],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        if proc.returncode:
            tail='\n'.join((out/'execution.log').read_text().splitlines()[-12:]);save(folder/'failure.json',{'variant':variant['key'],'returncode':proc.returncode,'tail':tail});raise RuntimeError(f'variant {variant["key"]} failed; {tail}')
        if not json.loads(completion.read_text())['complete']:raise RuntimeError('incomplete simulation')
    verify_sources(plan)
    now=ledger.read_bytes() if ledger.exists() else b''
    if not now.startswith(old) or not now.startswith(original_ledger):raise RuntimeError('pre-existing experiment ledger rows changed')
    save(folder/'ledger_preservation.json',{'old_bytes':len(original_ledger),'old_sha256':hashlib.sha256(original_ledger).hexdigest(),'prefix_preserved':True,'new_bytes':len(now)})
    for variant in plan['variants']:
        out=folder/variant['key'];f=out/(variant['shelf_id']+('_named' if variant['named'] else '')+'.jsonl')
        rows=[json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        expected={(u,k) for u in plan['expected_uuids'] for k in range(variant['reps'])}
        if len(rows)!=len(expected) or {(r['uuid'],r['rep']) for r in rows}!=expected:raise ValueError('final completeness failed')
        actual.append({k:variant[k] for k in ('key','price','effective_volume','control')}|metrics(rows,variant['product_ids'],args.product))
    control=next(x for x in actual if x['control'])
    for row in actual:row['delta_choice_pp']=100*(row['choice_share_all']-control['choice_share_all']);row['rank_delta']=None if row['rank'] is None or control['rank'] is None else row['rank']-control['rank']
    audit=[]
    for variant in plan['variants']:
        f=folder/variant['key']/'call_audit.json'
        audit.extend(json.loads(f.read_text()) if f.exists() else [])
    if not args.stub and len(audit)>args.max_calls:raise AssertionError('total call cap exceeded')
    result={'state':'provisional','gate':'gate_pending','stub':args.stub,'plan_signature':plan['signature'],'n_personas':plan['n'],'planned_calls':plan['planned_calls'],'actual_calls':len(audit),'failed_calls':sum(x.get('status')=='failed' for x in audit),'response_calls':sum(x.get('status') in ('response_received','stub_response') for x in audit),'rows':actual,'elapsed_seconds':round(time.perf_counter()-started,3),'numpy_version':check.stdout.strip(),'python':python}
    save(folder/'summary.json',result);(folder/'report.md').write_text(report(plan,result),encoding='utf-8')
    from plot import plot
    plot(folder/'curve.png',actual,plan['base_price'],plan['base_volume'])
    return folder


def report(plan,result):
    lines=[PREFIX,'','# 가격·용량 변화 시연','',f'- {"가짜 응답 기능 시험" if result["stub"] else "실모델 소표본 시연"}. 판매량·지불 의향·적정 가격·가격탄력성 예측 아님.',f'- 제품 `{plan["product"]}` · 진열대 `{plan["shelf"]}` · 같은 첫 {plan["n"]}명 · 총 {result["actual_calls"]}호출.',f'- 기준은 이번에 같은 사람·묶음·질문으로 다시 돌린 원가격 {plan["base_price"]:,}원 × {plan["base_volume"] or "미상"}ml. 과거 {plan["base"]["name"]} 전체 표본 결과와 직접 비교하지 않음.',f'- 기준 실험 flags를 유지하고 실행 묶음/동시성만 {plan["flags"]}로 명시. 전송은 승인된 공개 합성 속성 allowlist이며 UUID 제외.', '- 가격·용량 외 카드 속성·제품 순서·진열대 시점은 유지. 가격 문장 안의 원래 용량을 보존하고 용량 변형일 때만 함께 변경.', '- 용량 변형을 요청한 경우 모든 변형과 control에 용량 칸을 동일하게 명시하는 정규화를 적용.', '', '| 가격(원) | 용량(ml) | 구분 | 선택/전체 응답 | 선택 비율 | 공동순위 포함 순위 | 없음/전체 | 없음 비율 | control 대비 선택 차이 |','|---:|---:|---|---:|---:|---|---:|---:|---:|']
    for r in sorted(result['rows'],key=lambda r:(r['effective_volume'] or 0,r['price'])):
        rank='순위 없음' if r['rank'] is None else ('공동 ' if r['tied'] else '')+str(r['rank'])+'위'
        lines.append(f'| {r["price"]} | {r["effective_volume"] or "미상"} | {"control" if r["control"] else "변형"} | {r["target_count"]}/{r["n_responses"]} | {r["choice_share_all"]:.1%} | {rank} | {r["none_count"]}/{r["n_responses"]} | {r["none_share"]:.1%} | {r["delta_choice_pp"]:+.1f}%p |')
    lines+=['','![가격별 가상 선택 비율](curve.png)','','## 한계','', '- 선택 비율 분모는 없음 응답을 포함한 전체 응답 수. 순위는 제품별 선택 수로 계산하며 동률은 공동순위. 전부 없음이면 순위 없음.', '- 경쟁 제품의 가격이 비어 있는 기존 카드가 있음. 이번 작업에서 임의로 채우지 않았다.', '- 소표본 한 번 응답으로 가격 변화의 참 방향을 검증하지 못한다. 같은 사람의 여러 가상응답도 독립적인 실사용 관측이 아니다.', '- 선택이 그대로거나 역방향이어도 그대로 기록한다. 성공처럼 보이게 가격·프롬프트를 다시 고르지 않는다.', '- 지불 의향 과대평가 위험 때문에 절대 가격을 추천하지 않는다. 정답이 있는 실가격 조사·손익 검증은 별도로 필요하다.', '', '## 증거','', '- `sweep_locked.json`: 입력·소스 해시와 잠긴 전체 계획. `preflight.json`: 실제 prompt 가격 노출·허용 속성 변경 검사.', '- 변형별 `prompt_preview.txt`, `spec_locked.json`, 응답 JSONL, `actual_models.json`, `call_audit.json`, `completeness.json`, `execution.log`.', '- 기존 `run_experiment.py` 원본 main을 호출하고 simulate 호출에 한정된 임시 adapter로 전송 허용 속성·상한·완결성을 검사. 원본 소스는 변경하지 않음.', '- `ledger_preservation.json`: 기존 기록 prefix 보존 확인. 원본 실행기의 정상 동작대로 신규 실험 행만 append.']
    return '\n'.join(lines)+'\n'


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--exp',required=True);ap.add_argument('--product',required=True);ap.add_argument('--price',required=True);ap.add_argument('--volume');ap.add_argument('--shelf');ap.add_argument('--n',type=int);ap.add_argument('--batch',type=int,default=6);ap.add_argument('--max-calls',type=int,default=4);ap.add_argument('--timeout',type=int,default=90);ap.add_argument('--name');ap.add_argument('--python');ap.add_argument('--stub',action='store_true');ap.add_argument('--prepare-only',action='store_true')
    args=ap.parse_args()
    if not 1<=args.timeout<=600 or args.max_calls<0:ap.error('invalid timeout or call cap')
    try:folder=execute(args)
    except (ValueError,RuntimeError,FileNotFoundError) as e:ap.exit(2,str(e)+'\n')
    print(folder/('preflight.json' if args.prepare_only else 'report.md'))


if __name__=='__main__':main()
