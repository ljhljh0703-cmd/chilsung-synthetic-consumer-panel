"""Export aggregate FIT evidence from the sealed run, without modifying its inputs."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from main_run import digest
from metrics import evaluate
from render import response_concentration
from survey import COMBOS, DESIGN_HASH, POPULATION, PREREG, QUESTION_HASH, ROOT, SAMPLE_SEED, questionnaire, sample

FIT = ROOT / 'demo/results/FIT'


def make_summary():
    report = (FIT/'registered/report.md').read_text()
    log = (FIT/'run-1825-active.log').read_text()
    started = re.search(r'^본 실행 시작 (\S+)', log, re.M)
    if not started or '완료. 등록 보고서' not in log:
        raise ValueError('L17 완료 로그가 필요합니다.')
    path = (FIT/'.checkpoint.sqlite3').as_uri()
    with sqlite3.connect(path+'?mode=ro', uri=True) as db:
        manifest = json.loads(db.execute('SELECT signature FROM manifest').fetchone()[0])
        run_rows = db.execute('SELECT combo,repeat,route,generation FROM runs').fetchall()
        if len(run_rows) != 15 or db.execute('SELECT count(*) FROM responses').fetchone()[0] != 4500:
            raise ValueError('15회 및 응답 자리 4,500개가 필요합니다.')
        groups = {combo: [] for combo in COMBOS}
        counts = {combo: Counter() for combo in COMBOS}
        paths = {combo: Counter() for combo in COMBOS}
        for combo, repeat, route, generation in sorted(run_rows):
            rows = db.execute('SELECT person,answer FROM responses WHERE combo=? AND repeat=? ORDER BY person',
                              (combo, repeat)).fetchall()
            if [i for i,_ in rows] != list(range(300)):
                raise ValueError('응답 자리 판본 불일치')
            groups[combo].append([json.loads(answer) for _,answer in rows])
            paths[combo][route] += len(rows)
            counts[combo].update(row[0] for row in db.execute(
                'SELECT model FROM calls WHERE combo=? AND repeat=? AND generation=? AND status=?',
                (combo,repeat,generation,'returned')))
    population = json.loads((POPULATION.parent/'summary.json').read_text())
    if digest(POPULATION) != manifest['population'] or population['output_sha256'] != manifest['population']:
        raise ValueError('실행 모집단 판본 불일치')
    people, options = sample(), questionnaire()['options']
    evidence = evaluate(people, groups, options)
    sample_hash = sha256(json.dumps(people,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    combos = []
    for combo, (model, level, form) in COMBOS.items():
        result = evidence['combos'][combo]
        combos.append({'id':combo, 'persona_info':['없음','나이·성별·지역만','전체 서술'][level],
                       'model_requested':model,'models_returned':dict(counts[combo]), 'paths':dict(paths[combo]),
                       'questionnaire':form,'reps':3,'responses':900,'excluded':sum(result['excluded_by_repeat']),
                       'excluded_rate':result['excluded_rate'],'skew_flags':response_concentration(groups[combo],options)})
    own = {k:evidence[k] for k in ('rq1','rq2','rq3','h4')}
    expected = {'rq1':False,'rq2':True,'rq3':True,'h4':False}
    if own != expected or not all(text in report for text in
            ('RQ1 대표성: 미달','RQ2 정보 기여: 있음','RQ3 판정 안정성: 안정','H4 세그먼트 방향: 입증 안 됨')):
        raise ValueError('19:25 총괄 판정과 계산이 다릅니다. 원인을 반환하세요.')
    return {
        'prereg':{'file':PREREG.name,'sha256':DESIGN_HASH,'revision':'개정 4 + 18:10 구현 정정',
                  'locked_at':manifest['published_commit_at']},
        'questionnaire_sha256':{'A':QUESTION_HASH,'B':QUESTION_HASH},
        'population':{'population_id':manifest['population'],'source':'NVIDIA Nemotron-Personas-Korea',
                      'dataset_revision':population['dataset_revision'],'weighting':'KOSIS 2025-12 성·연령·시도 306칸',
                      'config_sha256':population['config_sha256'],'stats_sha256':population['stats_sha256'],
                      'n':300,'seed':SAMPLE_SEED,'sample_sha256':sample_hash},
        'run':{'started_at':started[1],'finished_at':__import__('datetime').datetime.fromtimestamp(
            (FIT/'registered/report.md').stat().st_mtime,__import__('datetime').timezone.utc).isoformat(),'status':'complete'},
        'combos':combos,
        'rq1':{str(c):{f'V{i}':m for i,m in enumerate(evidence['combos'][c].get('metrics',[]),1)} for c in (3,4,5)},
        'rq2':{f'V{i+1}':{'mae_by_combo':{str(c):evidence['combos'][c]['metrics'][i]['mae_pp'] for c in (1,2,3)},
                           'rep_spread_combo3':evidence['combos'][3]['metrics'][i]['mae_range_pp'][1]-evidence['combos'][3]['metrics'][i]['mae_range_pp'][0],
                           'registered_noise':evidence['rq2_by_source'][i]['noise_pp']} for i in range(3)},
        'h4':{'within_age_table':evidence['h4_table'],'age_correlation':-.43},
        'own_verdict':own,'exploratory':[],
    }


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=FIT/'fit_summary.json')
    args=parser.parse_args()
    result=make_summary()
    with args.out.open('x',encoding='utf-8') as output:
        json.dump(result,output,ensure_ascii=False,indent=2,allow_nan=False)
        output.write('\n')
    print(result['own_verdict'])
