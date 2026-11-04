"""Bounded configuration editing for L6 and L7; no dataset build or model call."""
import copy,hashlib,importlib.util,json,math,sys
from pathlib import Path
RATIOS={'innovator':.025,'early_adopter':.135,'early_majority':.34,'late_majority':.34,'laggard':.16}
MODES=('two_axis_channel','two_axis_age','single_axis')

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def safe_file(project,kind,name):
    if kind not in ('population','diffusion'):raise ValueError('설정 종류 오류')
    if not isinstance(name,str) or not __import__('re').fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.json',name):raise ValueError('설정 파일 이름이 올바르지 않습니다.')
    if kind=='population' and name!='adopter.json':raise ValueError('페르소나 설정은 adopter.json만 편집합니다.')
    folder=project/kind/'config';root=folder.resolve()
    if folder.is_symlink() or not root.is_relative_to(project.resolve()):raise ValueError('허용한 설정 폴더가 아닙니다.')
    p=root/name
    if p.resolve().parent!=root or p.is_symlink():raise ValueError('허용한 설정 폴더 밖 경로입니다.')
    return p

def locks(project,data):
    # Existing run snapshots remain immutable. Editing the source they used requires a new file.
    matches=[]
    for p in (project/'diffusion/out').glob('*/input_locked.json'):
        try:
            if json.loads(p.read_text()).get('config')==data:matches.append(p.parent.name)
        except (ValueError,OSError):continue
    return matches

def get(project,kind,name):
    p=safe_file(project,kind,name)
    if not p.exists():return {'status':'준비 중','kind':kind,'name':name}
    data=json.loads(p.read_text());return {'status':'사용 가능','kind':kind,'name':name,'sha256':digest(p),'data':data,'locked_runs':locks(project,data) if kind=='diffusion' else []}

def inventory(project):
    return {'population':get(project,'population','adopter.json'),'diffusion':[get(project,'diffusion',p.name) for p in sorted((project/'diffusion/config').glob('*.json')) if not p.is_symlink()]}

def validate_population(c):
    if c.get('ratios')!=RATIOS:raise ValueError('유형 비율은 작가가 고정한 2.5/13.5/34/34/16%를 유지합니다.')
    if c.get('reaction_mode') not in MODES:raise ValueError('반응 성향 방식은 세 가지 중에서 고르세요.')
    if isinstance(c.get('age_tilt'),bool) or not isinstance(c.get('age_tilt'),(int,float)) or not math.isfinite(c['age_tilt']) or not 0<=c['age_tilt']<=1:raise ValueError('나이 영향은 0~1 사이여야 합니다.')
    if c.get('sex_balance') not in ('none','within_sex'):raise ValueError('성비 방식 오류')
    # Actual key locations are shared with the L6 builder.
    for k in ('keyword_enabled','age_signal_enabled'):
        if k in c and type(c[k]) is not bool:raise ValueError(k+' 값은 켜기/끄기여야 합니다.')

def validate_diffusion(project,c):
    if c.get('reaction_mode','two_axis_channel') not in MODES:raise ValueError('반응 성향 방식 오류')
    if c.get('population',{}).get('ratios')!=RATIOS:raise ValueError('유형 비율은 현재 고정입니다.')
    # Keep configuration references inside the exact project root.
    paths=list(c.get('sample_files',[]))+[c.get('stage1_file'),c.get('reaction_config')]
    for v in paths:
        if v is None:continue
        if not isinstance(v,str) or Path(v).is_absolute() or not (project/v).resolve().is_relative_to(project.resolve()):raise ValueError('입력 경로는 프로젝트 안의 상대 경로만 허용합니다.')
    runner=project/'diffusion/run.py'
    if not runner.exists():raise ValueError('확산 도구가 준비 중입니다.')
    folder=str(runner.parent);sys.path.insert(0,folder)
    try:
        spec=importlib.util.spec_from_file_location('ops_diffusion_validator',runner);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.validate(c)
    finally:sys.path.remove(folder)

def prepare(project,kind,name,expected_sha,data,new_name=None):
    p=safe_file(project,kind,name)
    if not p.exists():raise ValueError('원본 설정이 준비 중입니다.')
    if digest(p)!=expected_sha:raise ValueError('다른 작업에서 설정이 바뀌었습니다. 다시 불러온 뒤 수정하세요.')
    old=json.loads(p.read_text())
    if not isinstance(data,dict):raise ValueError('설정은 JSON 객체여야 합니다.')
    if kind=='population':
        # The UI can change only the author-selected knobs, preserving source paths and model assumptions.
        allowed={'reaction_mode','age_tilt','sex_balance','keyword_enabled','age_signal_enabled'}
        changed={k for k in set(old)|set(data) if old.get(k)!=data.get(k)}
        if changed-allowed:raise ValueError('이 화면에서는 지정한 페르소나 조절 칸만 수정할 수 있습니다.')
        validate_population(data)
        traits=project/'population/traits.py'
        if traits.exists():
            sp=importlib.util.spec_from_file_location('ops_population_validator',traits);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
            if hasattr(m,'validate_settings'):m.validate_settings(data)
        if new_name:raise ValueError('페르소나 설정은 지정 파일에 저장합니다.')
    else:
        validate_diffusion(project,data)
        if locks(project,old) and not new_name:raise ValueError('이미 실행한 확산 설정입니다. 새 이름으로 복사해 저장하세요.')
    target=safe_file(project,kind,new_name) if new_name else p
    if new_name and target.exists():raise ValueError('같은 이름의 설정이 이미 있습니다.')
    return p,target,old
