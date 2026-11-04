#!/usr/bin/env python3
"""Two-stage diffusion demonstration; Python standard library only.
All counts are synthetic scenario outputs, never calibrated market predictions.
Paths inside configs are relative to applications/lotte-ax-2026 (project root).
"""
from __future__ import annotations
import argparse
import collections
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time
from plot_png import chart

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
TYPES = ('innovator','early_adopter','early_majority','late_majority','laggard')
LABELS = dict(zip(TYPES, ('혁신자','초기 수용자','초기 다수','후기 다수','지체자')))
VERSION = 'l7-1.3'
REACTION_MODES=('two_axis_channel','two_axis_age','single_axis')


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)


def path_for(value):
    p=Path(value)
    return p if p.is_absolute() else PROJECT/p


def validate(c):
    for key in ('n','rounds','seed'):
        if type(c.get(key)) is not int: raise ValueError(key+' must be integer')
    if not 2 <= c['n'] <= 100000: raise ValueError('n must be 2..100000')
    if not 1 <= c['rounds'] <= 520: raise ValueError('rounds must be 1..520')
    if c['mode'] not in ('rules','llm'): raise ValueError('mode must be rules or llm')
    if c.get('reaction_mode') is not None and c['reaction_mode'] not in REACTION_MODES:raise ValueError('invalid reaction_mode')
    prob(c.get('cross_channel_visibility',0.15),'cross_channel_visibility')
    if not c.get('sample_files'): raise ValueError('sample_files required')
    if not c.get('product_id'): raise ValueError('product_id required')
    ratios=c['population']['ratios']
    if set(ratios)!=set(TYPES) or any(not math.isfinite(float(x)) or x<0 for x in ratios.values()) or abs(sum(ratios.values())-1)>1e-8:
        raise ValueError('five type ratios must sum to 1')
    for typ in TYPES:
        for field in ('launch_sensitivity','viral_sensitivity'):
            prob(c['population']['types'][typ][field],field)
    b=c['behavior']
    for key in ('post_probability','view_probability','purchase_multiplier','launch_influence','repost_multiplier','repeat_probability'):
        prob(b[key],key)
    if type(b['max_exposures_per_week']) is not int or b['max_exposures_per_week'] < 1: raise ValueError('max_exposures_per_week must be positive integer')
    net=c['network']
    if not 0 <= net['mean_friends'] < c['n']:raise ValueError('mean_friends must be 0..n-1')
    if not 1 <= net['candidate_pool'] <= 1000:raise ValueError('candidate_pool must be 1..1000')
    for k in ('base','same_province','age_similarity','hobby_similarity'):
        if not math.isfinite(float(net[k])) or net[k] < 0:raise ValueError('negative/nonfinite network weight')
    if net['base'] <= 0 or net['age_scale'] <= 0:raise ValueError('positive network base and age_scale required')
    for k in ('max_people_total','max_people_per_round','max_calls_total'):
        if type(c['llm'][k]) is not int or not 0 <= c['llm'][k] <= 10000:raise ValueError('invalid llm cap')
    if not 1 <= c['llm']['timeout_seconds'] <= 600:raise ValueError('invalid timeout')


def prob(value, field):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(field+' must be numeric in [0,1]')
    return value


def novelty(p,c):
    s=c['signal']; words=' '.join(str(p.get(k,'')) for k in s['fields']).lower()
    hits=[w for w in s['keywords'] if w.lower() in words]
    score=len(hits)*s['keyword_points'] + max(0,min(1,(100-int(p['age']))/81))*s['age_weight']
    return score,hits


def enrich(people,c):
    """Missing traits only by default; exact quotas by largest remainders."""
    pop=c['population']; n=len(people)
    complete=all(p.get('adopter') in TYPES and p.get('launch_sensitivity') is not None and p.get('viral_sensitivity') is not None for p in people)
    if pop.get('use_input_traits',True) and complete:
        for p in people:
            prob(p['launch_sensitivity'],'launch_sensitivity');prob(p['viral_sensitivity'],'viral_sensitivity')
        return 'input_traits',[]
    warnings=[]
    if any(p.get('adopter') for p in people):warnings.append('일부 유형 칸만 있어 표본 전체를 설정 비율로 다시 배정함')
    raw={t:n*pop['ratios'][t] for t in TYPES};quota={t:int(raw[t]) for t in TYPES}
    for t in sorted(TYPES,key=lambda t:(-(raw[t]-quota[t]),TYPES.index(t)))[:n-sum(quota.values())]:quota[t]+=1
    scored=[]
    for p in people:
        score,hits=novelty(p,pop);p['adopter_signal']={'score':score,'keywords':hits,'basis':'미정. 시연용 문장·나이 신호'}
        scored.append(p)
    scored.sort(key=lambda p:(-p['adopter_signal']['score'],p['uuid']))
    off=0
    for t in TYPES:
        for p in scored[off:off+quota[t]]:
            p.update(adopter=t,launch_sensitivity=pop['types'][t]['launch_sensitivity'],viral_sensitivity=pop['types'][t]['viral_sensitivity'],sensitivity_basis=pop['types'][t]['basis'])
        off+=quota[t]
    warnings.append('유형·성향은 기존 표본에 설정 가정으로 부착했으며 L6 모집단 보정 검증을 대신하지 않음')
    return 'config_signal_rank',warnings


def load_inputs(c):
    files=[path_for(f) for f in c['sample_files']]
    stage=path_for(c['stage1_file'])
    extra=[]
    if c.get('reaction_config'):
        extra=[path_for(c['reaction_config']),PROJECT/'population/traits.py']
    manifest=[{'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size} for p in files+[stage]+extra]
    available={}
    for f in files:
        rows=json.loads(f.read_text(encoding='utf-8'))
        if not isinstance(rows,list):raise ValueError('sample must be a JSON list')
        for p in rows:
            if not isinstance(p.get('uuid'),str) or not p['uuid']:raise ValueError('sample uuid required')
            if p['uuid'] in available and available[p['uuid']] != p:raise ValueError('conflicting duplicate persona '+p['uuid'])
            available[p['uuid']]=p
    stage_rows=[];seen=set();eligible_choices=set();stage_ids=set()
    for line in stage.read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        r=json.loads(line)
        if r.get('rep',0)!=c.get('stage1_rep',0):continue
        if 'choice' not in r or 'uuid' not in r:raise ValueError('stage1 must contain uuid and choice')
        if r['uuid'] in seen:raise ValueError('duplicate uuid in selected stage1 repetition')
        seen.add(r['uuid']);stage_rows.append(r);stage_ids.add(r['uuid']);eligible_choices.update(r.get('order',[]))
    if not stage_rows:raise ValueError('no stage1 rows at selected rep')
    if c['product_id'] not in eligible_choices:raise ValueError('product_id not in stage1 offered product ids')
    seed_ids={r['uuid'] for r in stage_rows if r['choice']==c['product_id']}
    missing=seed_ids-set(available)
    if missing:raise ValueError(f'{len(missing)} first buyers missing from sample; supply matching personas, never invent them')
    if len(seed_ids)>c['n']:raise ValueError('n smaller than number of first buyers')
    if len(available)<c['n']:raise ValueError(f"need {c['n']} unique people; only {len(available)} available")
    # Preserve all actual seed buyers, then fill a deterministic random sample.
    extra=sorted(set(available)-seed_ids); random.Random(c['seed']).shuffle(extra)
    selected=sorted(seed_ids|set(extra[:c['n']-len(seed_ids)]))
    people=[copy.deepcopy(available[u]) for u in selected]
    origin,warnings=enrich(people,c)
    reaction_info=None
    if c.get('reaction_config'):
        settings=json.loads(path_for(c['reaction_config']).read_text(encoding='utf-8'))
        spec=importlib.util.spec_from_file_location('lotte_population_traits',PROJECT/'population/traits.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.validate_settings(settings)
        if c['population']['ratios']!=settings['ratios']:raise ValueError('shared reaction modes require fixed Rogers ratios')
        mode=c.get('reaction_mode') or settings.get('reaction_mode','two_axis_channel')
        for person in people:person.update(module.reaction_values(person,settings,mode=mode))
        reaction_info={'mode':mode,'settings':settings,'source':c['reaction_config']}
    return people,seed_ids,manifest,{'stage1_rows':len(stage_rows),'first_buyers':len(seed_ids),'sample_available':len(available),'stage1_in_selected':len(stage_ids&set(selected)),'trait_source':origin,'warnings':warnings,'first_buyer_ids':sorted(seed_ids),'reaction':reaction_info}


def tokens(p):
    return set(re.findall(r'[가-힣A-Za-z]{2,}',str(p.get('hobbies_and_interests','')).lower()))


def network(people,c,seed):
    """Undirected, no loops, no duplicates; weighted candidate edges.
    Expected degree approximates mean_friends, actual degree is reported.
    """
    rng=random.Random(seed+17);n=len(people);adj=[set() for _ in people];h=[tokens(p) for p in people]
    target=min(n*(n-1)//2,round(n*c['mean_friends']/2))
    for i,p in enumerate(people):
        attempts=(target//n)+(1 if i < target%n else 0)
        for _ in range(attempts):
            candidates=[j for j in rng.sample(range(n),min(n,c['candidate_pool'])) if j!=i and j not in adj[i]]
            if not candidates:continue
            weights=[]
            for j in candidates:
                q=people[j];union=h[i]|h[j]
                hobby=len(h[i]&h[j])/len(union) if union else 0
                weights.append(c['base']+c['same_province']*(p.get('province')==q.get('province'))+c['age_similarity']*math.exp(-abs(int(p['age'])-int(q['age']))/c['age_scale'])+c['hobby_similarity']*hobby)
            j=rng.choices(candidates,weights,k=1)[0];adj[i].add(j);adj[j].add(i)
    return [sorted(x) for x in adj]


def configured_network(people,c):
    mode=c.get('reaction_mode') or (people[0].get('reaction_mode') if people else None)
    if mode!='two_axis_channel':return network(people,c['network'],c['seed'])
    defaults={
        'sns':dict(c['network'],same_province=0.5,age_similarity=1.0,hobby_similarity=8.0),
        'acquaintance_tv':dict(c['network'],same_province=7.0,age_similarity=4.0,hobby_similarity=1.0)}
    overrides=c.get('network_channels',{})
    if set(overrides)-set(defaults):raise ValueError('unknown network channel')
    for channel in defaults:
        test=copy.deepcopy(c);test['network']={**defaults[channel],**overrides.get(channel,{})};validate(test)
    return {channel:network(people,{**defaults[channel],**overrides.get(channel,{})},c['seed']+offset)
            for channel,offset in [('sns',0),('acquaintance_tv',7919)]}


REVIEW_SCHEMA={'type':'object','additionalProperties':False,'properties':{'post':{'type':'boolean'},'review':{'type':'string'}},'required':['post','review']}
REACTION_SCHEMA={'type':'object','additionalProperties':False,'properties':{'action':{'type':'string','enum':['buy','ignore','repost']},'reason':{'type':'string'}},'required':['action','reason']}


def demo_llm_module():
    spec=importlib.util.spec_from_file_location('diffusion_demo_llm',PROJECT/'demo/llm.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def model_identity():
    mod=demo_llm_module();backend=mod.backend()
    return {'backend':backend,'requested_model':os.environ.get('LLM_MODEL') or ('gpt-5-mini' if backend=='api' else 'default'),
            'requested_effort':os.environ.get('LLM_EFFORT','low') if backend=='codex' else 'not_applicable'}


OUTBOUND_FIELDS=('age','sex','province','hobbies_and_interests','culinary_persona','adopter','launch_sensitivity','viral_sensitivity')


def outbound_profile(person):
    """Author-approved public synthetic attributes only. UUID is local-only."""
    return {key:person.get(key,'') for key in OUTBOUND_FIELDS}


class LLMClient:
    """Bounded, cached calls through demo.llm.ask_json, preserving empty-cwd CLI.
    Errors are cached too, so replay cannot silently change a failed round.
    """
    def __init__(self, config, cache_dir, ask=None, identity=None):
        self.cfg=config;self.cache=cache_dir;self.ask=ask;self.calls=0;self.people=set();self.round_people=set();self.events=[]
        self.identity=identity or model_identity()
        self.actual_metadata=[]
    def begin(self):self.round_people=set()
    def room(self,uuid):
        return (len(self.round_people)<self.cfg['max_people_per_round'] or uuid in self.round_people) and (len(self.people)<self.cfg['max_people_total'] or uuid in self.people) and self.calls<self.cfg['max_calls_total']
    def request(self,week,p,kind,product,context):
        u=p['uuid']
        if not self.room(u):return None
        self.calls+=1;self.people.add(u);self.round_people.add(u)
        # Only persona text and local simulation context; no truth or future outcomes.
        profile=outbound_profile(p)
        system='가상의 한국 소비자로서 아래 인물의 생활만 보고 답하세요. 실제 제품 흥행·판매량을 추측하지 마세요. 웹 검색이나 파일 읽기 없이 주어진 내용만 쓰세요.'
        task='이미 시안을 골라 첫 구매를 했다고 가정합니다. 후기를 올릴지와 올린다면 짧은 후기 한 문장을 답하세요.' if kind=='review' else '친구 후기를 보고 구매, 무시, 재전파 중 하나와 이유를 답하세요.'
        user=canonical({'week':week,'persona':profile,'product_id':product,'task':task,'context':context})
        schema=REVIEW_SCHEMA if kind=='review' else REACTION_SCHEMA
        key=hashlib.sha256((system+user+canonical(schema)+canonical(self.identity)).encode()).hexdigest();f=self.cache/(key+'.json')
        if f.exists():result=json.loads(f.read_text(encoding='utf-8'))
        else:
            try:
                if self.ask is None:
                    mod=demo_llm_module()
                    # Keep only declared model metadata within this task, never demo/results.
                    def record(log):
                        info={}
                        for line in log.splitlines():
                            text=line.strip()
                            for label in ('model:', 'reasoning effort:', 'provider:'):
                                if text.lower().startswith(label):info[label[:-1]]=text.split(':',1)[1].strip()
                        if info and info not in self.actual_metadata:self.actual_metadata.append(info)
                    mod.record_model=record
                    self.ask=mod.ask_json
                answer=self.ask(system,user,schema,timeout=self.cfg['timeout_seconds'])
                if not isinstance(answer,dict):raise ValueError('empty or non-object response')
                if kind=='review':
                    if type(answer.get('post')) is not bool or not isinstance(answer.get('review'),str):raise ValueError('invalid review response')
                    if answer['post'] and not answer['review'].strip():raise ValueError('empty review')
                elif answer.get('action') not in ('buy','ignore','repost') or not isinstance(answer.get('reason'),str):raise ValueError('invalid reaction response')
                result={'answer':answer,'requested_model_identity':self.identity,'actual_model_metadata':list(self.actual_metadata) or 'unknown'}
            except Exception as e:result={'error':type(e).__name__+': '+str(e)[:400],'requested_model_identity':self.identity,'actual_model_metadata':list(self.actual_metadata) or 'unknown'}
            save(f,result)
        event={'week':week,'uuid':u,'kind':kind,'key':key,'outbound_fields':list(profile),'uuid_sent':False,**result};self.events.append(event)
        if 'error' in result:raise RuntimeError(result['error'])
        return result['answer']


def simulate(people,seed_ids,adj,c,client=None):
    n=len(people);byid={p['uuid']:i for i,p in enumerate(people)};buyers={byid[u] for u in seed_ids};first=set(buyers)
    dual=isinstance(adj,dict);graphs=adj if dual else {'single':adj}
    repeats=set();queued_reposts={k:set() for k in graphs};history=[];posts_total=0;repeat_total=0;examples=[];fallbacks=[];event_rows=[]
    def row(week,new,repeat,posts,exposed,mode,channels=None):
        types={}
        for t in TYPES:
            members={i for i,p in enumerate(people) if p['adopter']==t};count=len(members&buyers)
            types[t]={'population':len(members),'buyers':count,'buyer_rate':round(count/len(members),6) if members else None}
        return {'week':week,'new_buyers':new,'cumulative_buyers':len(buyers),'repeat_events':repeat,'cumulative_repeat':repeat_total,'repeat_people':len(repeats),'posts':posts,'cumulative_posts':posts_total,'exposed_people':exposed,'mode':mode,'by_type':types,'channels':channels or {}}
    history.append(row(0,len(buyers),0,0,0,'stage1'))
    for week in range(1,c['rounds']+1):
        def one_round(use_llm):
            rng=random.Random(c['seed']+week*100003);b=c['behavior'];post_candidates=[]
            posters={ch:set(queued_reposts[ch]) for ch in graphs}
            for i in sorted(buyers):
                if rng.random()<b['post_probability']*people[i]['viral_sensitivity']:
                    channel=people[i].get('viral_channel','sns') if dual else 'single'
                    if channel not in graphs:raise ValueError('unknown viral_channel')
                    posters[channel].add(i);post_candidates.append(i)
            week_examples=[];llm_review={}
            if use_llm:
                client.begin();review_budget=client.cfg['max_people_per_round']//2
                for i in post_candidates[:review_budget]:
                    ans=client.request(week,people[i],'review',c['product_id'],{'purchase':'synthetic stage1 choice or previous simulated adoption'})
                    if ans is None:break
                    if not ans['post']:
                        for post_set in posters.values():post_set.discard(i)
                    else:llm_review[i]=ans['review'];week_examples.append({'week':week,'uuid':people[i]['uuid'],'kind':'review','text':ans['review']})
            exposed=collections.Counter();by_channel={ch:collections.Counter() for ch in graphs};seen_reviews=collections.defaultdict(list)
            for channel,post_set in posters.items():
                for i in sorted(post_set):
                    for j in graphs[channel][i]:
                        visibility=b['view_probability']
                        if dual and people[j].get('viral_channel')!=channel:visibility*=c.get('cross_channel_visibility',0.15)
                        if rng.random()<visibility:
                            exposed[j]+=1;by_channel[channel][j]+=1
                            if i in llm_review:seen_reviews[j].append(llm_review[i])
            new=set();reposts={ch:set() for ch in graphs};react_overrides={}
            if use_llm:
                for j in sorted(set(exposed)-buyers):
                    if not client.room(people[j]['uuid']):break
                    context={'friend_posts_seen':exposed[j],'reviews':seen_reviews[j][:3],'note':'후기 문장이 없으면 친구가 제품을 언급했다는 사실만 주어짐'}
                    ans=client.request(week,people[j],'reaction',c['product_id'],context)
                    if ans is not None:react_overrides[j]=ans['action'];week_examples.append({'week':week,'uuid':people[j]['uuid'],'kind':'reaction','text':ans['reason'],'action':ans['action']})
            for i,hits in sorted(exposed.items()):
                p=people[i];h=min(hits,b['max_exposures_per_week'])
                per_view=b['purchase_multiplier']*((1-b['launch_influence'])*p['viral_sensitivity']+b['launch_influence']*p['launch_sensitivity'])
                buy_chance=1-(1-per_view)**h;buy_draw=rng.random();share_draw=rng.random();action=react_overrides.get(i)
                if i not in buyers and ((action=='buy') if action is not None else buy_draw<buy_chance):new.add(i)
                share=(action=='repost') if action is not None else share_draw<b['repost_multiplier']*p['viral_sensitivity']
                if share:
                    channel=p.get('viral_channel','sns') if dual else 'single';reposts[channel].add(i)
            rep={i for i in sorted(buyers) if rng.random()<b['repeat_probability']}
            channel_stats={ch:{'posts':len(posters[ch]),'exposed_people':len(by_channel[ch]),'exposures':sum(by_channel[ch].values()),'new_buyers_exposed':len(new&set(by_channel[ch]))} for ch in graphs}
            return new,rep,posters,reposts,len(exposed),week_examples,channel_stats
        mode='rules'
        if client:
            try:
                before=client.calls;result=one_round(True);mode='llm_sample' if client.calls>before else 'rules_budget_exhausted'
            except Exception as e:
                fallbacks.append({'week':week,'reason':str(e)[:450],'action':'whole_round_rules'})
                result=one_round(False);mode='rules_fallback'
        else:result=one_round(False)
        new,rep,posters,queued_reposts,exposed,week_examples,channel_stats=result
        post_count=sum(map(len,posters.values()));buyers|=new;repeats|=rep;posts_total+=post_count;repeat_total+=len(rep);examples+=week_examples
        history.append(row(week,len(new),len(rep),post_count,exposed,mode,channel_stats))
        event_rows.append({'week':week,'new_buyer_ids':[people[i]['uuid'] for i in sorted(new)],'repeat_ids':[people[i]['uuid'] for i in sorted(rep)],'poster_ids':{ch:[people[i]['uuid'] for i in sorted(v)] for ch,v in posters.items()},'next_week_repost_ids':{ch:[people[i]['uuid'] for i in sorted(v)] for ch,v in queued_reposts.items()}})
    return {'history':history,'examples':examples,'fallbacks':fallbacks,'events':event_rows,'first_buyers':len(first),'llm_calls':client.calls if client else 0,'llm_people':len(client.people) if client else 0,'llm_events':client.events if client else [],'model_identity':client.identity if client else None}


def report(result,c,meta,compare=None):
    r=result['history'];last=r[-1];lines=['검증 전 시연','',f'# 2단계 가상 SNS 확산 · {c["product_id"]}','',
        '- 상태: provisional / gate_pending. 실제 확산 정답 자료 없음. 판매량·흥행·인구 전체 구매율로 해석하지 않음.',
        f'- 반응 방식: {c.get("reaction_mode") or (meta.get("reaction") or {}).get("mode","기존 두 성향")} · 확산 통로 {"SNS + 지인·TV 두 망" if meta.get("channels") else "단일 망"}',
        f'- 표본: 합성 인물 {c["n"]:,}명 · {c["rounds"]}주 · 난수 {c["seed"]} · 요청 모드 {c["mode"]}',
        f'- 표본 범위: {c.get("sample_scope","미기재")}',
        f'- 1단계: `{c["stage1_file"]}` 반복 {c.get("stage1_rep",0)} · {meta["stage1_rows"]}응답 중 `{c["product_id"]}` 선택 {meta["first_buyers"]}명을 최초 구매자로 연결.',
        f'- 실제 구매를 관측한 자료가 아님: 1단계의 가상 선택을 첫 구매 상태로 가정.',
        f'- 망: 평균 친구 {meta["mean_degree"]:.2f}명, 양방향 연결 {meta["edges"]:,}개. 고립 {meta["isolates"]}명.',
        '- 비교 단위: 누적 구매자는 중복 없는 사람 수, 재구매는 회차별 사건 수(같은 사람이 여러 번 포함), 후기는 새 후기와 재전파 합계.',
        '- 시차: 이번 주 새 구매자·재전파자는 다음 주부터 후기·재구매·전파에 참여. 판매 재고·광고·이탈·부정 반응은 미구현.',
        '- 가중치: 인구 weight는 보존하되 현재 확산 계산은 개별 노드 동등 취급. 모집단 구매율로 환산하지 않음.',
        '', '## 회차 결과','', '| 주 | 새 구매자 | 누적 구매자 | 재구매 사건 | 누적 재구매 | 후기·재전파 | 노출 인원 | 처리 |','|---|---:|---:|---:|---:|---:|---:|---|']
    for x in r:lines.append(f'| {x["week"]} | {x["new_buyers"]} | {x["cumulative_buyers"]} | {x["repeat_events"]} | {x["cumulative_repeat"]} | {x["posts"]} | {x["exposed_people"]} | {x["mode"]} |')
    lines+=['','![회차 곡선](curve.png)','','곡선: 초록=누적 구매자, 주황=누적 재구매 사건, 파랑=누적 후기·재전파. 가로축=주, 세로축=수.','','## 유형별 최종 결과','','| 유형 | 인원 | 구매자 | 유형 안 구매율 |','|---|---:|---:|---:|']
    for t,x in last['by_type'].items():lines.append(f'| {LABELS[t]} | {x["population"]} | {x["buyers"]} | {x["buyer_rate"]:.1%} |' if x['buyer_rate'] is not None else f'| {LABELS[t]} | 0 | 0 | 해당 없음 |')
    if meta.get('channels'):
        lines+=['','## 통로별 동작','','| 통로 | 연결 수 | 평균 친구 | 전체 노출 횟수 | 후기·재전파 |','|---|---:|---:|---:|---:|']
        for ch,g in meta['channels'].items():
            exposures=sum(x.get('channels',{}).get(ch,{}).get('exposures',0) for x in r)
            posts=sum(x.get('channels',{}).get(ch,{}).get('posts',0) for x in r)
            lines.append(f'| {ch} | {g["edges"]} | {g["mean_degree"]:.2f} | {exposures} | {posts} |')
        lines.append('\nSNS 망은 취미 유사성, 지인·TV 망은 지역·나이 유사성 비중이 큼. 지인·TV는 실제 방송 전달 모델이 아닌 별도 전파 통로 가정. 선호하지 않는 통로 노출 확률에는 '+str(c.get('cross_channel_visibility',0.15))+'를 곱함(근거 미정).')
    lines+=['','## 설정 가정과 한계','']
    for section in ('network','population','behavior'):lines.append(f'- {section}: {c[section].get("basis","미정")}')
    for t in TYPES:lines.append(f'- {LABELS[t]} 성향 근거: {c["population"]["types"][t].get("basis","미정")}')
    lines.extend('- '+x for x in meta['warnings'])
    lines+=['','## 언어모델 사용','',f'- 호출 {result["llm_calls"]}/{c["llm"]["max_calls_total"]}, 고유 인물 {result["llm_people"]}/{c["llm"]["max_people_total"]}, 회차 상한 {c["llm"]["max_people_per_round"]}명. 캐시 재생도 논리 호출 수에 포함.',
        f'- 요청 모델: {canonical(result.get("model_identity"))}. 실제 모델명은 호출 기록에서 추출한 경우만 기록하며 미수신은 unknown.',
        '- 현재 언어모델 프롬프트는 제품 속성 전체를 포함하지 않음. 후기·반응은 시연 문장으로만 보고 실제 맛·품질 평가로 사용하지 않음.',
        '- 언어모델의 새 응답은 난수 고정만으로 재현되지 않음. 같은 입력·설정은 성공/실패 응답 캐시를 재생. 캐시를 지우거나 입력을 바꾸면 새 실험으로 취급.',
        f'- 실패 회차 {len(result["fallbacks"])}개. 부분 응답은 적용하지 않고 해당 회차 전체를 규칙으로 다시 계산.']
    for f in result['fallbacks']:lines.append(f'- {f["week"]}주: {f["reason"]}')
    if result['examples']:
        lines+=['','### 가상 후기·반응 예시','']
        for x in result['examples'][:12]:lines.append(f'- {x["week"]}주 / {x["uuid"][:8]} / {x["kind"]}: {x["text"].replace(chr(10)," ")}')
    else:lines.append('- 후기 예시 문장 없음: 규칙 모드는 문장을 생성하지 않음.')
    if compare:
        prior=compare['history'];lines+=['','## 비교 실험 차이','','같은 주 차이 = 이번 실험 누적 구매자 − 비교 실험 누적 구매자. 정답과의 정확도 차이가 아님.','','| 주 | 비교 | 이번 | 차이 |','|---|---:|---:|---:|']
        for a,b in zip(prior,r):lines.append(f'| {b["week"]} | {a["cumulative_buyers"]} | {b["cumulative_buyers"]} | {b["cumulative_buyers"]-a["cumulative_buyers"]:+} |')
        lines.append('\n비교 입력·설정 식별자는 `comparison.json`에 보존.')
    lines+=['','## 출처와 해석','', '- 합성 인물: [NVIDIA Nemotron-Personas-Korea](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea), CC BY 4.0. 합성 인물에 유형·성향 가정과 연결망을 추가.',
        '- 구조 참고: [MiroFish README](https://github.com/666ghj/MiroFish)와 [OASIS README](https://github.com/camel-ai/oasis)의 인물·관계망·회차·행동·기록 분리. 외부 코드는 복사하거나 의존성으로 설치하지 않음.',
        '- 원본 입력 SHA-256, 실행 설정, 최초 구매자 UUID, 실제 연결망, 회차별 사건을 같은 폴더에 보존.']
    return '\n'.join(lines)+'\n'


def execute(c,output,compare_path=None,ask=None):
    validate(c);start=time.perf_counter();people,seeds,manifest,meta=load_inputs(c)
    identity=model_identity() if c['mode']=='llm' else None
    code_hash=digest(Path(__file__))
    signature=hashlib.sha256(canonical({'version':VERSION,'config':c,'inputs':manifest,'code_sha256':code_hash,'model_identity':identity}).encode()).hexdigest()
    output.mkdir(parents=True,exist_ok=True);lock=output/'input_locked.json'
    expected={'signature':signature,'config':c,'inputs':manifest,'code_version':VERSION,'code_sha256':code_hash,'model_identity':identity}
    if lock.exists() and json.loads(lock.read_text(encoding='utf-8')) != expected:raise ValueError('output already belongs to different inputs/config/code; use a new --exp')
    save(lock,expected)
    adj=configured_network(people,c)
    graphs=adj if isinstance(adj,dict) else {'single':adj}
    stats={ch:{'edges':sum(map(len,g))//2,'mean_degree':sum(map(len,g))/len(g),'isolates':sum(not a for a in g)} for ch,g in graphs.items()}
    meta.update(edges=sum(x['edges'] for x in stats.values()),mean_degree=sum(x['mean_degree'] for x in stats.values()),isolates=sum(not any(g[i] for g in graphs.values()) for i in range(len(people))))
    if isinstance(adj,dict):meta['channels']=stats
    if meta.get('reaction'):save(output/'reaction_config_snapshot.json',meta['reaction']['settings'])
    client=LLMClient(c['llm'],output/'llm_cache',ask,identity=identity) if c['mode']=='llm' else None
    result=simulate(people,seeds,adj,c,client)
    result.update(signature=signature,config=c,metadata=meta,inputs=manifest)
    save(output/'summary.json',result);save(output/'network.json',{'uuids':[p['uuid'] for p in people],'channels':{ch:{'edges':[[i,j] for i,a in enumerate(g) for j in a if i<j]} for ch,g in graphs.items()}})
    save(output/'people.json',people)
    comparison=None
    if compare_path:
        comparison=json.loads(Path(compare_path).read_text(encoding='utf-8'))
        save(output/'comparison.json',{'source':str(compare_path),'sha256':digest(Path(compare_path)),'baseline_signature':comparison.get('signature'),'current_signature':signature})
    (output/'report.md').write_text(report(result,c,meta,comparison),encoding='utf-8')
    chart(output/'curve.png',result['history'],c['n'])
    runtime={'seconds':round(time.perf_counter()-start,4),'python':sys.version,'execution_time_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'input_signature':signature}
    save(output/'execution.json',runtime)
    return result,runtime


def compare_modes(c,output,ask=None):
    if not c.get('reaction_config'):raise ValueError('--compare-modes requires reaction_config')
    output.mkdir(parents=True,exist_ok=True)
    source=path_for(c['reaction_config']);snapshot=output/'reaction_config_snapshot.json'
    cfg=json.loads(source.read_text(encoding='utf-8'))
    if snapshot.exists() and json.loads(snapshot.read_text(encoding='utf-8'))!=cfg:raise ValueError('reaction settings changed; use new experiment')
    save(snapshot,cfg)
    # Freeze identical first-stage and person bytes for all three modes.
    frozen=[];origins=[]
    paths=[path_for(value) for value in c['sample_files']]+[path_for(c['stage1_file'])]
    for index,source_path in enumerate(paths):
        payload=source_path.read_bytes();target=output/'inputs'/f'{index:02d}{source_path.suffix}'
        if target.exists() and target.read_bytes()!=payload:raise ValueError('comparison source changed; use new experiment')
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():target.write_bytes(payload)
        frozen.append(str(target.resolve()));origins.append({'original_path':str(source_path),'frozen_path':str(target.resolve()),'sha256':hashlib.sha256(payload).hexdigest()})
    save(output/'input_sources.json',origins)
    results={};runs={};allocations={};total_calls=c['llm']['max_calls_total'];total_people=c['llm']['max_people_total']
    for index,mode in enumerate(REACTION_MODES):
        cc=copy.deepcopy(c);cc['reaction_mode']=mode;cc['reaction_config']=str(snapshot.resolve());cc['sample_files']=frozen[:-1];cc['stage1_file']=frozen[-1]
        cc['llm']['max_calls_total']=total_calls//3+(index<total_calls%3)
        cc['llm']['max_people_total']=total_people//3+(index<total_people%3)
        cc['llm']['max_people_per_round']=min(cc['llm']['max_people_per_round'],cc['llm']['max_people_total'])
        result,runtime=execute(cc,output/mode,ask=ask)
        results[mode]=result;runs[mode]=runtime
        allocations[mode]={k:cc['llm'][k] for k in ('max_calls_total','max_people_total','max_people_per_round')}
    first=results[REACTION_MODES[0]]
    for r in results.values():
        if r['metadata']['first_buyer_ids']!=first['metadata']['first_buyer_ids'] or r['inputs']!=first['inputs']:raise ValueError('inputs changed during comparison')
        if r['config']['stage1_file']!=first['config']['stage1_file']:raise ValueError('different stage1 input')
    spent=sum(r['llm_calls'] for r in results.values());identities={e['uuid'] for r in results.values() for e in r['llm_events']}
    if spent>total_calls or len(identities)>total_people:raise AssertionError('combined model budget exceeded')
    summary={'state':'provisional','gate':'gate_pending','config':c,'modes':{m:{'signature':r['signature'],'final_buyers':r['history'][-1]['cumulative_buyers'],'llm_calls':r['llm_calls'],'llm_people':r['llm_people'],'fallback_rounds':len(r['fallbacks']),'seconds':runs[m]['seconds']} for m,r in results.items()},'allocations':allocations,'combined_llm_calls':spent,'combined_llm_unique_people':len(identities),'history':{m:r['history'] for m,r in results.items()},'shared_reaction_config_sha256':digest(snapshot)}
    save(output/'comparison_modes.json',summary)
    plot_rows=[]
    for index,row in enumerate(first['history']):
        plot_rows.append({'week':row['week'],'cumulative_buyers':results['two_axis_channel']['history'][index]['cumulative_buyers'],'cumulative_repeat':results['two_axis_age']['history'][index]['cumulative_buyers'],'cumulative_posts':results['single_axis']['history'][index]['cumulative_buyers']})
    chart(output/'comparison_modes.png',plot_rows,c['n'],series_labels=['TWO AXIS CHANNEL','TWO AXIS AGE','SINGLE AXIS'],title='REACTION MODE COMPARISON')
    lines=['검증 전 시연','','# 같은 1단계 결과의 반응 방식 3종 비교','',
           '- 신뢰도·예측 정확도 비교가 아님. 입력 가정에 따른 가상 누적 구매자 곡선 비교.',
           '- 같은 최초 구매자 UUID·표본 수·난수를 사용. 채널 방식은 SNS/지인·TV 두 망, 나머지 두 방식은 같은 단일 망.',
           '- 반응 성향은 L6 공유 함수를 그대로 호출. 실제 사용한 설정 사본과 해시를 이 폴더에 보존.',
           f'- 전체 언어모델 사용: {spent}/{total_calls}호출, 고유 {len(identities)}/{total_people}명. 세 방식 합산 상한이며 모드별로 미리 분할.',
           '- 실모델은 공개 합성 속성만 전송, UUID는 로컬 기록에만 사용. 웹 검색 금지·빈 폴더·기존 Codex 구독 경로.',
           '', '| 주 | 두 축·통로 | 두 축·나이 | 단일 축 |','|---|---:|---:|---:|']
    for row in plot_rows:lines.append(f'| {row["week"]} | {row["cumulative_buyers"]} | {row["cumulative_repeat"]} | {row["cumulative_posts"]} |')
    lines+=['','![세 곡선 비교](comparison_modes.png)','','## 실제 호출과 대체','', '| 방식 | 호출 | 고유 인물 | 실패 대체 회차 |','|---|---:|---:|---:|']
    for mode,r in results.items():lines.append(f'| {mode} | {r["llm_calls"]} | {r["llm_people"]} | {len(r["fallbacks"])} |')
    lines+=['','가설값 근거는 미정. 채널/연령 구분은 작가가 실험할 설정이며 검증된 소비자 법칙이 아니다. 제품 속성 전체가 프롬프트에 없어 후기·반응은 시연 문장이다. 각 방식의 report.md에 망·노출·반응·모델 근거를 따로 기록했다.']
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--compare-modes',action='store_true');ap.add_argument('--exp',required=True);ap.add_argument('--config',default=str(ROOT/'config/default.json'));ap.add_argument('--compare',help='path to baseline summary.json')
    a=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',a.exp):ap.error('exp must be a safe identifier')
    c=json.loads(Path(a.config).read_text(encoding='utf-8'))
    try:
        if a.compare_modes:
            result=compare_modes(c,ROOT/'out'/a.exp)
            print(json.dumps(result['modes'],ensure_ascii=False,indent=2));print(ROOT/'out'/a.exp/'report.md');return
        r,t=execute(c,ROOT/'out'/a.exp,a.compare)
    except (ValueError,FileNotFoundError,KeyError) as e:ap.exit(2,str(e)+'\n')
    print(f"검증 전 시연: {c['n']}명 × {c['rounds']}주 / {t['seconds']}초 / 최초 {r['first_buyers']} → 최종 {r['history'][-1]['cumulative_buyers']}명")
    print(ROOT/'out'/a.exp/'report.md')


if __name__=='__main__':main()
