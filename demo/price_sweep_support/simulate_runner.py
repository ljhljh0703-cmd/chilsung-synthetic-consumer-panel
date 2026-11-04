"""Temporary adapters for approved public attributes, call cap, and completeness.
Uses original simulate.main and llm.ask_json; no original file is changed.
"""
import collections,json,os,re,sys
from pathlib import Path
from common import DEMO,FIELDS,persona_text,save
sys.path.insert(0,str(DEMO))
import simulate
import llm


def flag(name,default=None):
    return sys.argv[sys.argv.index(name)+1] if name in sys.argv else default

spec_path=Path(os.environ['PRICE_SWEEP_VARIANT'])
meta=json.loads(spec_path.read_text(encoding='utf-8'))
out=DEMO/'results'/meta['experiment_name'];out.mkdir(parents=True,exist_ok=True)
people=json.loads((DEMO/f"data/{meta['sample']}.json").read_text(encoding='utf-8'))[:meta['n']]
expected={(p['uuid'],rep) for p in people for rep in range(meta['reps'])}
identifiers=[p['uuid'] for p in people]
raw_ask=llm.ask_json
calls=json.loads((out/'call_audit.json').read_text()) if (out/'call_audit.json').exists() else []
models=json.loads((out/'actual_models.json').read_text()) if (out/'actual_models.json').exists() else []
stub=os.environ.get('PRICE_SWEEP_STUB')=='1'


def record_model(log):
    data={}
    for line in log.splitlines():
        for label in ('model:','reasoning effort:','provider:'):
            if line.strip().lower().startswith(label):data[label[:-1]]=line.split(':',1)[1].strip()
    if data and data not in models:models.append(data)
    save(out/'actual_models.json',models)


def fake_person(schema,index):
    labels=list(schema['properties']['products']['properties'])
    target=meta['target_label']
    # Deterministic mechanical fixture, not a consumer/model response.
    choose=target if index%6 < (4 if meta['price']<=2000 else 2) else labels[(labels.index(target)+1)%len(labels)]
    answer={'products':{l:{'reaction':'시험용 응답','pull':'시험','hesitate':'시험'} for l in labels},'choice':choose,'choice_reason':'가짜 응답 시험'}
    if 'weekly_qty' in schema['properties']:answer['weekly_qty']=1
    return answer


def ask(system,user,schema,timeout=600):
    if len(calls)>=meta['calls_cap']:raise RuntimeError('sweep call cap exceeded')
    if any(identifier in user or identifier in system for identifier in identifiers):raise RuntimeError('UUID appeared in outbound prompt')
    calls.append({'number':len(calls)+1,'backend':'stub' if stub else 'codex','requested_model':os.environ.get('LLM_MODEL') or 'default','requested_effort':os.environ.get('LLM_EFFORT','low'),'uuid_sent':False,'persona_fields':sorted({k for p in people for k in FIELDS if k in p}),'status':'attempted'})
    save(out/'call_audit.json',calls)
    if stub:
        calls[-1]['status']='stub_response';save(out/'call_audit.json',calls)
        if 'people' in schema['properties']:
            return {'people':{key:fake_person(s,index) for index,(key,s) in enumerate(schema['properties']['people']['properties'].items())}}
        return fake_person(schema,0)
    if llm.backend()!='codex':raise RuntimeError('only existing Codex subscription backend is authorized')
    try:
        answer=raw_ask(system,user,schema,timeout=meta['timeout_seconds'])
        if not isinstance(answer,dict):raise RuntimeError('empty or invalid model response')
        calls[-1]['status']='response_received';save(out/'call_audit.json',calls);return answer
    except Exception as exc:
        calls[-1]['status']='failed';calls[-1]['error']=type(exc).__name__+': '+str(exc)[:500];save(out/'call_audit.json',calls);raise

simulate.persona_text=persona_text
llm.ask_json=ask;llm.record_model=record_model
if stub:
    llm.check=lambda:None
    llm.backend=lambda:'codex'
    llm.model_name=lambda:'stub:price-sweep'
else:
    if llm.backend()!='codex':raise SystemExit('price sweep only uses existing Codex backend')
    if os.environ.get('LLM_MODEL'):raise SystemExit('this approved example requires unchanged Codex default; explicit LLM_MODEL is not permitted')
simulate.main()
name=meta['shelf_id']+('_named' if meta['named'] else '')+'.jsonl'
f=out/name
rows=[json.loads(line) for line in f.read_text(encoding='utf-8').splitlines() if line.strip()] if f.exists() else []
keys=[(r.get('uuid'),r.get('rep')) for r in rows]
valid=(len(keys)==len(expected) and len(set(keys))==len(keys) and set(keys)==expected and all(r.get('choice') in meta['product_ids']+['없음'] and set(r.get('by_product',{}))==set(meta['product_ids']) for r in rows))
check={'complete':valid,'expected_rows':len(expected),'actual_rows':len(rows),'missing':len(expected-set(keys)),'duplicate_rows':len(keys)-len(set(keys)),'stub':stub}
save(out/'completeness.json',check)
if not valid:raise SystemExit('INCOMPLETE: original simulate returned but expected rows/UUIDs are missing or invalid')
