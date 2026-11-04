"""Read FIT aggregates, recompute registered decisions, and gate concept runs."""
from hashlib import sha256
import json
from pathlib import Path
from statistics import correlation, fmean, StatisticsError

FIT_RULES = {'revision':'FIT-7', 'max_pp':10, 'min_rho':.8, 'exclude':.05}
STATUS = {True:'통과', False:'미달', None:'판정 불가'}
MODELS = {'3':'gpt-6.1-terra','4':'claude-haiku-5-5'}


def hash_file(path):
    return sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def ranks(values):
    ordered = sorted(values)
    return [(ordered.index(v) + len(ordered) - ordered[::-1].index(v) - 1) / 2 for v in values]


def source_verdict(metric, index):
    if not metric or len(metric.get('cells',{})) != (2,6,10)[index]:
        return None
    rows = metric['cells']
    truth, sim = ([row[key] for row in rows.values()] for key in ('reference_pct','pct'))
    gaps = [abs(x-y) for x,y in zip(sim,truth)]
    if index == 0:
        return max(gaps) <= FIT_RULES['max_pp']
    try:
        rho = correlation(ranks(truth),ranks(sim))
    except StatisticsError:
        return False
    top = sorted(rows, key=lambda k:rows[k]['pct'],reverse=True)
    top_ok = set(top[:2]) == {'맥주','소주'} and rows[top[1]]['pct'] > rows[top[2]]['pct']
    return rho >= FIT_RULES['min_rho'] and fmean(gaps) <= FIT_RULES['max_pp'] and (index != 2 or top_ok)


def fit_status(project, demo):
    prereg = project/'preregistration-FIT.md'
    summary = demo/'results/FIT/fit_summary.json'
    if not summary.exists():
        summary = project/'results/FIT/fit_summary.json'
    if not summary.exists():
        return {'status':'실행 전','reason':'모집단 정합성 검증 결과가 없습니다.',
                'prereg_sha256':hash_file(prereg),'allowed_models':[],'warnings':[]}
    try:
        data = json.loads(summary.read_bytes())
        combos = {str(c['id']):c for c in data['combos']}
        per_source = {c:[source_verdict(data['rq1'].get(c,{}).get(f'V{i+1}'),i) for i in range(3)]
                      if combos[c]['excluded_rate'] <= FIT_RULES['exclude'] else [None]*3 for c in ('3','4','5')}
        overall = {c:None if None in rows else all(rows) for c,rows in per_source.items()}
        contribution = {k:row['mae_by_combo']['1']-row['mae_by_combo']['3'] > row['rep_spread_combo3']
                        for k,row in data['rq2'].items()}
        h4 = [x['estimate'] for x in data['h4']['within_age_table'] if x['age']=='전체']
        own = {'rq1':overall['3'],'rq2':sum(contribution.values())>=2,
               'rq3':None if None in overall.values() else len(set(overall.values()))==1,
               'h4':None if len(h4)!=3 or None in h4 else all(
                   x['diff_pp'] > max(x['repeat_pp'])-min(x['repeat_pp']) for x in h4)}
        status, reason = STATUS[own['rq1']], '사전 등록 대표성 기준'
        if data['run']['status'] != 'complete':
            status, reason = '판정 불가','정합성 검증이 끝나지 않았습니다.'
        elif data.get('own_verdict') and own != data['own_verdict']:
            status, reason = '판정 불가','계산 불일치'
        elif data['prereg']['sha256'] != hash_file(prereg) or hash_file(project/'research/fit-questionnaire.md') != data['questionnaire_sha256']['A']:
            status, reason = '재검증 필요','사전 등록 또는 문항 판본 변경'
        elif any(hash_file(project/path) != data['population'][key] for path,key in (
                ('population/config/adopter.json','config_sha256'),('population/stats/population_cells.csv','stats_sha256'))
                if (project/path).is_file()):
            status, reason = '재검증 필요','모집단 설정 또는 인구 가중 표 판본 변경'
        elif any(c.get('models_returned') and set(c['models_returned']) != {c['model_requested']} for c in combos.values()):
            status, reason = '재검증 필요','실제 모델 판본 변경 또는 불일치'
        return {'status':status,'reason':reason,'data':data,'sha256':hash_file(summary),
                'computed':own,'per_source':per_source,'overall':overall,'contribution':contribution,
                'allowed_models':[model for c,model in MODELS.items() if overall[c] is True] if status=='통과' else [],
                'warnings':[label for k,label in [('rq2','정보 기여 미확인'),('rq3','판정 안정성 주의'),
                            ('h4','세그먼트 방향 미지지')] if own[k] is not True]}
    except (KeyError, TypeError, ValueError, OSError):
        return {'status':'판정 불가','reason':'정합성 결과 형식을 확인하세요.','allowed_models':[],'warnings':[]}


def gate(fit, spec=None, benchmark=None):
    def blocked(stage, reason):
        return {'allowed':False,'stage':stage,'reason':reason,'status':fit['status']}
    if fit['status'] != '통과':
        stage=3 if fit['status']=='재검증 필요' and fit['reason'].startswith('모집단') else 1
        return blocked(stage,f"모집단 정합성 {fit['status']} · 신제품 가상 실행 막힘. {fit['reason']}")
    if spec is None:
        return {'allowed':None,'stage':None,'reason':'실험의 모집단·질문 방식과 재현 기록을 확인하세요.','status':'통과'}
    model = spec.get('requested_model') or next(iter(fit['allowed_models']),None)
    if model not in fit['allowed_models']:
        return blocked(2,'선택한 모델은 대표성 통과 모델이 아닙니다.')
    pid = fit['data']['population']['population_id']
    if spec.get('population_id') != pid:
        return blocked(3,'모집단 확인 불가' if not spec.get('population_id') else '모집단 판본 차이 · 재검증 필요')
    flags = spec.get('flags',[])
    batch = flags[flags.index('--batch')+1:flags.index('--batch')+2] if '--batch' in flags else []
    if batch != ['1'] or '--per-person-order' not in flags:
        return blocked(4,'한 명씩 질문하고 사람마다 보기 순서를 섞어야 합니다.')
    if not benchmark or benchmark.get('status') != 'pass' or benchmark.get('population_id') != pid or benchmark.get('model') != model:
        return blocked(5,'같은 모델·모집단의 경쟁 세트 재현 통과 기록이 필요합니다.')
    return {'allowed':True,'stage':None,'reason':'대표성과 경쟁 세트 재현을 통과했습니다.',
            'status':'통과','model':model,'backend':'claude' if model.startswith('claude-') else 'codex'}
