"""Export only public aggregates from the local operating console."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

import server
from ops_evidence import product_labels, reproduction

BANNED = re.compile(r'/Users/|/private/tmp|OPENAI|sk-|X-Console-Token|\.jsonl|\bPOST\b|판정 대기|포기', re.I)
PRODUCT_NAMES = {'T2':'기존 경쟁 세트 재현','T4':'주음용 브랜드 재현'}
SAFE_ACTIONS = {'승인','반려','실행 차단','정량 조사 후보 제안','정량 조사 후보 확정','정합성 결과 확인'}


def verify_static(out):
    for path in out.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix not in {'.html','.js','.css','.json','.md','.png'}:
            raise ValueError(f'공개판에 허용되지 않은 파일 {path.name}')
        if path.suffix!='.png' and BANNED.search(path.read_text()):
            raise ValueError(f'공개판 가리기 검사 실패 {path.name}')


def write_export(out, commit, captures=None):
    out.mkdir(parents=True,exist_ok=True)
    folder=out/'data'
    folder.mkdir(exist_ok=True)
    if not re.fullmatch(r'[a-f0-9]{40}',commit):
        raise ValueError('코드 커밋 전체 해시 필요')
    demo=server.DEMO
    fit=server.fit_status()
    fit_gate=server.fit_gate(fit=fit)
    current=server.overview()
    source_files={'사전 등록':server.PROJECT/'preregistration-FIT.md','정합성 요약':demo/'results/FIT/fit_summary.json',
                  'T2 집계 보고서':demo/'results/T2/report.md','T4 집계 보고서':demo/'results/T4/report.md'}
    hashes={label:sha256(path.read_bytes()).hexdigest() for label,path in source_files.items() if path.is_file()}
    stamp={'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'commit':commit,
           'source_sha256':hashes,'verdict_fingerprint':sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()}
    def put(path,data,metadata=None):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({**(metadata or stamp),'data':data},ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    rows=[]
    for row in server.state().get('actions',[]):
        if row.get('action') in SAFE_ACTIONS:
            rows.append({k:row[k] for k in ('time','action','actor') if k in row})
    current['blocks']=[x for x in rows if x['action']=='실행 차단']
    current['recent']=rows[-5:][::-1]
    # Local concept titles, memos and free-form reasoning are outside the publication scope.
    current['shortlist']=[{'concept':f'콘셉트 {i}','decision':x['decision'],'basis':x['basis']}
                          for i,x in enumerate(current['shortlist'],1)]
    put(folder/'overview.json',{'overview':current,'gate':fit_gate,'fit':{'status':fit['status']}})
    put(folder/'fit.json',{'fit':fit,'limits':server.fit_limits()})
    put(folder/'audit.json',rows)
    products=product_labels(demo,server.specimens())
    for name,title in PRODUCT_NAMES.items():
        detail=server.detail(name)
        truth=server.read(demo/(detail['spec'].get('truth_file') or 'config/known_truth.json'),{})
        evidence=reproduction(detail,truth,products)
        sens=detail['sensitivity']
        sensitivity={k:sens[k] for k in ('changed','total','max_shift_pp','comparison_basis') if k in sens}
        sensitivity['rows']=[{k:x[k] for k in ('id','left_top','right_top','max_shift_pp','top_changed','spearman') if k in x}
                             for x in sens.get('shelves',[]) if isinstance(x,dict)]
        report_path=folder/f'{name}.md'
        rows_md=['| 세트 | 실제 순위 | 가상 순위 | 최하위 적중 | 유효 선택 |',
                 '|---|---|---|---|---:|']+[f"| {x['shelf']} | {x['actual']} | {x['virtual']} | {'O' if x['last_match'] else 'X'} | {x['valid']} |" for x in evidence]
        report_path.write_text(f"# {title} ({name})\n\n판정 {detail['verdict']['display_label']} · {detail['verdict']['reason']}\n\n"+'\n'.join(rows_md)+'\n')
        put(folder/'experiments'/f'{name}.json',{'title':title,'name':name,'rows':evidence,
              'verdict':detail['verdict']['display_label'],'reason':detail['verdict']['reason'],
              'observations':[{k:x[k] for k in ('shelf','valid','total')} for x in evidence],
              'sensitivity':sensitivity}, {**stamp,'verdict_fingerprint':detail.get('verdict_fingerprint',detail['report_hash'])})
    for name in ('index.html','public_view.js','public.css','fit_view.js'):
        src=server.HERE/'static'/name if name!='fit_view.js' else server.HERE/name
        shutil.copyfile(src,out/name)
    shutil.copyfile(source_files['사전 등록'],folder/'preregistration-FIT.md')
    if captures:
        target=out/'workflow'
        target.mkdir(exist_ok=True)
        for name in ('intake','setup','runs','checks','decision','survey'):
            shutil.copyfile(captures/(name+'.png'),target/(name+'.png'))
    verify_static(out)
    print(f'가리기 검사 통과 · {sum(p.is_file() for p in out.rglob("*"))}개 파일')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--commit',required=True)
    parser.add_argument('--captures',type=Path)
    args=parser.parse_args()
    write_export(args.out,args.commit,args.captures)
