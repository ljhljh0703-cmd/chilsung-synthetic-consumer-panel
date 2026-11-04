"""Read-only operational metrics, public terminology, and stimulus comparisons."""
import hashlib,json,math
from collections import Counter
from pathlib import Path
ATTRS=['종류','도수','용량','가격','맛','포장','컨셉']
TERMS=[('약한 제품이 낀 짝 맞힘','최하위 포함 쌍대 정확도'),('실제 꼴찌가 낀 짝 맞힘','최하위 포함 쌍대 정확도'),('약한 제품 짝 맞힘','최하위 포함 쌍대 정확도'),('꼴찌 일치','최하위 브랜드 적중'),('짝 맞힘','쌍대 순위 정확도'),('사람 조사','소비자 조사(정량 조사)'),('평소 구매','주음용 브랜드'),('평소 사는 것','주음용 브랜드'),('하나만 고른다면','1순위 선택'),('이번 선택','1순위 선택'),('입력값만 쓴 계산','기준 모델'),('결과 누수','데이터 누수'),('이름가림','블라인드'),('이름공개','브랜드 공개'),('이름 가림','블라인드'),('이름 공개','브랜드 공개'),('카드 민감도','자극물 민감도'),('응답 흔들림','응답 변동성'),('순서 섞기','제시 순서 무작위화'),('시안','콘셉트'),('진열대','경쟁 세트'),('카드','제품 프로필'),('묶음','배치'),('포기','보류'),('입소문','구전'),('소비자 유형','세그먼트(혁신 확산 5분류)')]
def term(text):
 for a,b in TERMS:text=str(text).replace(a,b)
 return str(text)
def load(p,default=None):return json.loads(p.read_text()) if p.exists() else default

def profile_balance(products):
 rows=[{'id':p['id'],'name':p.get('real_name') or p['id'],'filled':[k for k in ATTRS if str(p.get('attrs',{}).get(k,'')).strip()],'missing':[k for k in ATTRS if not str(p.get('attrs',{}).get(k,'')).strip()]} for p in products]
 return {'rows':rows,'unbalanced':len({len(r['filled']) for r in rows})>1,'message':'제품 프로필 정보량이 다르면 정보가 많은 쪽으로 쏠립니다. T2 원인 후보.'}

def raw_shares(demo,name,spec,field='choice'):
 """Response-only shares. No truth file required; no invented votes or smoothing."""
 groups=load(demo/spec.get('sets_file','_absent'),[]) if spec.get('sets_file') else []
 named='--named' in spec.get('flags',[]) or '--familiar-incumbents' in spec.get('flags',[])
 shelves={};errors=[]
 for st in groups:
  ids=st.get('product_ids') or [p['id'] for p in st.get('products',[])];sid=st['id'];p=demo/'results'/name/(sid+('_named' if named else '')+'.jsonl')
  if not p.exists():errors.append(sid+': 응답 없음');continue
  try:rows=[json.loads(l) for l in p.read_text().splitlines() if l.strip()]
  except (ValueError,OSError):errors.append(sid+': 응답 파일 미완결');continue
  pairs=[(r.get('uuid'),r.get('rep',0)) for r in rows]
  expected=spec.get('n',0)
  if not rows or len(rows)!=expected or len(set(pairs))!=len(pairs) or any(not r.get('uuid') or r.get(field) not in ids+['없음'] for r in rows):errors.append(sid+': 인원·중복·응답 칸 확인 필요');continue
  counts=Counter(r[field] for r in rows);den=sum(counts[i] for i in ids)
  shelves[sid]={'n':len(rows),'valid_n':den,'none_n':counts['없음'],'none_rate':counts['없음']/len(rows),'sim':{i:counts[i]/den if den else 0 for i in ids},'counts':{i:counts[i] for i in ids},'cohort':sorted(pairs),'category':st.get('category','')}
 key='이름공개·선택비율' if named else '이름가림·선택비율'
 return {'key':key,'shelves':shelves,'errors':errors,'complete':bool(groups) and not errors and len(shelves)==len(groups),'field':field}

def ranks(values):
 ordered=sorted(range(len(values)),key=lambda i:values[i]);out=[0.]*len(values);start=0
 while start<len(values):
  end=start+1
  while end<len(values) and values[ordered[end]]==values[ordered[start]]:end+=1
  for i in ordered[start:end]:out[i]=(start+end-1)/2
  start=end
 return out

def spearman(a,b):
 if len(a)<2:return None
 a,b=ranks(a),ranks(b);ma=sum(a)/len(a);mb=sum(b)/len(b);den=math.sqrt(sum((x-ma)**2 for x in a)*sum((x-mb)**2 for x in b))
 return sum((x-ma)*(y-mb) for x,y in zip(a,b))/den if den else None

def profile_signature(demo,spec,settings):
 groups=load(demo/spec.get('sets_file','_absent'),[]);base={p['id']:p for sh in load(demo/'config/sets.json',[]) for p in sh.get('products',[])};out={}
 for sh in groups:
  products=sh.get('products')
  if products is None:
   inline={p['id']:p for p in sh.get('products_inline',[])}
   products=[{**(inline.get(i) or base[i]),'attrs':{**(inline.get(i) or base[i])['attrs'],**sh.get('override',{}).get(i,{})}} for i in sh.get('product_ids',[])]
  common=set.intersection(*[{k for k,v in p.get('attrs',{}).items() if str(v).strip()} for p in products]) if products else set()
  values={}
  for p in products:
   attrs={k:str(v) for k,v in p.get('attrs',{}).items() if str(v).strip()}
   if settings.get('equal_cards'):
    attrs={k:(v if len(v)<=30 else v[:30].rsplit(' ',1)[0].rstrip(',·') or v[:30]) for k,v in attrs.items() if k in common}
   values[p['id']]=attrs
  out[sh['id']]=values
 return out

def question_context(demo,spec):
 groups=load(demo/spec.get('sets_file','_absent'),[])
 return {sh['id']:{'launch':sh.get('launch'),'category':sh.get('category'),'sample':sh.get('sample'),'seen_at':sh.get('seen_at'),'targets':{pid:False for pid in sh['product_ids']} if 'product_ids' in sh else {p['id']:bool(p.get('target')) for p in sh.get('products',[])}} for sh in groups}

def sensitivity(demo,left,right):
 result={'left':left,'right':right,'status':'unknown','reason':'비교 조건 미확인','shelves':[]}
 if not left or not right:return {**result,'reason':'비교 대상 미선택'}
 if left==right:return {**result,'reason':'서로 다른 두 실험을 선택하세요.'}
 specs=[load(demo/'experiments'/f'{n}.json',{}) for n in (left,right)]
 if not all(specs):return {**result,'reason':'비교 실험 설정 없음'}
 ss=[load(demo/'results'/n/'settings.json',{}) for n in (left,right)]
 # Product profile formatting may differ. All other recorded question conditions must match.
 keys=['model','batch','scene','new_hint','ask_qty','per_person_order','familiar_incumbents']
 defaults={'scene':None,'new_hint':True,'ask_qty':False,'per_person_order':False,'familiar_incumbents':False}
 def flags(s):return [x for x in s.get('flags',[]) if x!='--equal-cards']
 mismatch=[]
 if specs[0].get('n')!=specs[1].get('n'):mismatch.append('표본 수')
 if question_context(demo,specs[0])!=question_context(demo,specs[1]):mismatch.append('경쟁 세트의 시점·장소·범주·신규 여부')
 if flags(specs[0])!=flags(specs[1]):mismatch.append('질문 조건')
 if any(ss[0].get(k,defaults.get(k))!=ss[1].get(k,defaults.get(k)) for k in keys):mismatch.append('기록된 모델·배치·질문 모드')
 if not all(s.get('model') and s.get('batch') for s in ss):mismatch.append('모델·배치 기록 없음')
 try:
  if profile_signature(demo,specs[0],ss[0])==profile_signature(demo,specs[1],ss[1]):mismatch.append('제품 프로필 변경 없음')
 except (KeyError,TypeError,ValueError):mismatch.append('제품 프로필 대조 불가')
 raw=[raw_shares(demo,n,s) for n,s in zip((left,right),specs)]
 if not all(r['complete'] for r in raw):mismatch.append('응답 완결성')
 if raw[0]['key']!=raw[1]['key']:mismatch.append('브랜드 공개 조건')
 if set(raw[0]['shelves'])!=set(raw[1]['shelves']):mismatch.append('경쟁 세트')
 for sid,a in raw[0]['shelves'].items():
  b=raw[1]['shelves'].get(sid)
  if not b:continue
  if set(a['sim'])!=set(b['sim']):mismatch.append('제품 ID')
  if a['cohort']!=b['cohort']:mismatch.append('응답자 명단')
 if mismatch:return {**result,'reason':'비교 조건 다름: '+', '.join(dict.fromkeys(mismatch))}
 for sid,a in raw[0]['shelves'].items():
  b=raw[1]['shelves'][sid];ids=sorted(a['sim']);valid=a['valid_n']>0 and b['valid_n']>0
  topa=sorted(i for i in ids if a['sim'][i]==max(a['sim'].values())) if valid else []
  topb=sorted(i for i in ids if b['sim'][i]==max(b['sim'].values())) if valid else []
  result['shelves'].append({'id':sid,'left_top':topa,'right_top':topb,'top_changed':topa!=topb if valid else None,'max_shift_pp':max(abs(a['sim'][i]-b['sim'][i])*100 for i in ids),'spearman':spearman([a['sim'][i] for i in ids],[b['sim'][i] for i in ids]) if valid else None,'valid_n':[a['valid_n'],b['valid_n']]})
 if any(x['top_changed'] is None for x in result['shelves']):return {**result,'reason':'유효 선택이 0인 경쟁 세트가 있어 비교 불가'}
 changed=sum(x['top_changed'] for x in result['shelves'])
 result.update(status='fail' if changed else 'pass',reason='1순위 브랜드 변동으로 신뢰 판정 제한' if changed else '선택한 두 실험의 1순위 브랜드 유지',changed=changed,total=len(result['shelves']),top_match=len(result['shelves'])-changed,max_shift_pp=max(x['max_shift_pp'] for x in result['shelves']),comparison_basis='기록된 모델 라벨·배치·질문 조건·응답자·제품 ID 일치. 실제 모델 판본과 원인 관계를 독립 입증하지 않음.')
 return result

def provenance(inputs,name):
 p=inputs/name/'verification.json'
 data=load(p,{})
 warnings=[]
 if any(str(x).startswith('source_changed:') for x in data.get('issues',[])):
  reconciliation=load(p.parent/'source-reconciliation.json',{})
  if reconciliation.get('runtime_field_counts_inferred')==[7,7,7,7,7]:warnings.append('사전 검사 이후 제품 프로필이 보강됐습니다. 파일 시각·코드 근거로 실행 시점의 7개 속성 판본을 재구성했으며, 직접 전송 해시는 없어 출처 한계를 유지합니다.')
  else:warnings.append('사전 검사 스냅샷과 실행 시점 제품 프로필의 판본 차이가 있습니다. 실행 판본은 파일 시각·코드로 재구성 중이며 직접 전송 해시는 없습니다.')
 return {'status':'hold' if warnings else 'unknown','warnings':warnings,'source':str(p) if p.exists() else None}

def operating_report(d):
 key=d['metric_key'];m=d['metrics'].get(key,{});raw=d['primary_observations'];obs=raw['shelves']
 lines=['# 콘셉트 검증 운영 보고서: '+d['name'],'','- 운영 판정: '+d['verdict']['display_label'],'- 판정 사유: '+d['verdict']['reason'],'- 주 지표: '+('주음용 브랜드' if d['primary_metric']=='usual' else '1순위 선택'),'- 가상 결과는 처음 집어 드는 끌림입니다. 점유율·판매량 추정에 쓰지 않습니다.','']
 lines+=['> '+x for x in d['cautions']]
 if d.get('benchmark'):lines+=['','- 연결 재현 실험: '+d['benchmark']['name']+' / '+{'pass':'통과','fail':'보류','unknown':'미확인'}[d['benchmark']['status']]]
 if m:
  hits=sum(x.get('last_match',False) for x in m.get('shelves',{}).values())
  lines+=['','## 사전 기준 평가','',f'- 최하위 브랜드 적중: {hits}/{len(m.get("shelves",{}))}',f'- 최하위 포함 쌍대 정확도: {m.get("weak_pair_acc")}',f'- 전체 쌍대 순위 정확도: {m.get("pair_acc")}']
 lines+=['','## 주 지표 유효 응답','','| 경쟁 세트 | 전체 응답 | 유효 선택 | 없음 | 해석 |','|---|---:|---:|---:|---|']
 for sid,x in obs.items():lines.append(f'| {sid} | {x["n"]} | {x["valid_n"]} | {x["none_n"]} | '+('순위 해석 불가' if not x['valid_n'] else '유효 선택 분모 확인 필요')+' |')
 secondary=d.get('secondary_metrics',{}).get(key)
 if secondary:lines+=['','## 보조 지표: 1순위 선택','',f'- 최하위 포함 쌍대 정확도: {secondary["weak_pair_acc"]}','- 주음용 브랜드 판정을 대체하지 않습니다.']
 sens=d['sensitivity'];lines+=['','## 자극물 민감도','',sens['reason']]
 if sens.get('total'):lines+=[f'- 1순위 브랜드 변동: {sens["changed"]}/{sens["total"]}',f'- 제품별 최대 비중 이동: {sens["max_shift_pp"]:.3f}%p']
 lines+=['','## 원본과 한계','','- 원본 실험 보고서와 응답 파일은 수정하지 않았습니다.','- 원본 보고서 SHA-256: `'+d['report_hash']+'`','- 이 운영 보고서는 유효 선택이 0인 경쟁 세트의 1위 적중을 성과로 제시하지 않습니다.','- 기록된 결과의 판정이며 예측 정확도나 사용자 승인을 뜻하지 않습니다.']
 return '\n'.join(lines)+'\n'
