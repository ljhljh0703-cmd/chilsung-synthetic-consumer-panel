"""Shared L6/L7 reaction assumptions and L9 text scoring; standard library only."""
import json,math,re
from pathlib import Path
TYPES=('innovator','early_adopter','early_majority','late_majority','laggard')
MODES=('two_axis_channel','two_axis_age','single_axis')
RATIOS=dict(zip(TYPES,(.025,.135,.34,.34,.16)))
DEFAULT_FIELDS=['persona','culinary_persona','family_persona','hobbies_and_interests']
def unit(v):return type(v) in (int,float) and math.isfinite(v) and 0<=v<=1
def validate_settings(cfg):
    if cfg.get('ratios')!=RATIOS:raise ValueError('로저스 원비율은 작가 결정으로 고정되어 있습니다.')
    if cfg.get('reaction_mode') not in MODES:raise ValueError('반응 방식 오류')
    if not unit(cfg.get('age_tilt')):raise ValueError('age_tilt는 0~1')
    if cfg.get('sex_balance') not in ('none','within_sex'):raise ValueError('성비 보정 방식 오류')
    for k in ('keyword_enabled','age_signal_enabled'):
        if type(cfg.get(k)) is not bool:raise ValueError(k+'는 boolean')
    if not unit(cfg.get('age_signal_weight',0)):raise ValueError('보조 나이 가중치는 0~1')
    m=cfg.get('reaction_models',{})
    for key in ('launch_by_type','single_by_type'):
        if set(m.get(key,{}))!=set(TYPES) or not all(unit(x) for x in m[key].values()):raise ValueError(key+' invalid')
    for key in ('channel_launch_age_weight','channel_viral_value','age_launch_weight','age_viral_weight'):
        if not unit(m.get(key)):raise ValueError(key+' invalid')
    for key in ('launch_by_age','viral_by_age'):
        if set(m.get(key,{}))!=set(str(n) for n in range(10,100,10)) or not all(unit(x) for x in m[key].values()):raise ValueError(key+' invalid')
    if type(m.get('sns_max_age')) is not int or not 19<=m['sns_max_age']<=99:raise ValueError('sns_max_age invalid')
    if not m.get('basis'):raise ValueError('reaction basis required')

def reaction_values(person,cfg,mode=None):
    mode=mode or cfg['reaction_mode'];m=cfg['reaction_models'];typ=person['adopter'];age=int(person['age']);a=str(min(90,max(10,age//10*10)))
    base=m['launch_by_type'][typ]
    if mode=='two_axis_channel':
        alpha=m['channel_launch_age_weight'];launch=(1-alpha)*base+alpha*m['launch_by_age'][a];viral=m['channel_viral_value']
    elif mode=='two_axis_age':
        alpha=m['age_launch_weight'];beta=m['age_viral_weight'];launch=(1-alpha)*base+alpha*m['launch_by_age'][a];viral=(1-beta)*base+beta*m['viral_by_age'][a]
    elif mode=='single_axis':launch=viral=m['single_by_type'][typ]
    else:raise ValueError('Unknown reaction mode')
    return {'launch_sensitivity':float(launch),'viral_sensitivity':float(viral),'viral_channel':'sns' if age<=m['sns_max_age'] else 'acquaintance_tv','reaction_mode':mode,'sensitivity_basis':m['basis']}

class KeywordScorer:
    def __init__(self,path,enabled=True):
        self.path=Path(path);self.missing=not self.path.exists();self.enabled=enabled
        self.raw=json.loads(self.path.read_text()) if not self.missing else {}
        self.fields=self.raw.get('_설명',{}).get('검사_칸',DEFAULT_FIELDS)
        if not isinstance(self.fields,list) or not all(isinstance(x,str) for x in self.fields):raise ValueError('Invalid keyword fields')
        self.patterns=[]
        for name,item in self.raw.items():
            if name.startswith('_'):continue
            direction=item.get('가리키는_유형_방향','')
            if direction.startswith('앞쪽'):sign=1
            elif direction.startswith('뒤쪽'):sign=-1
            else:raise ValueError('키워드 방향 미확인: '+name)
            keys=item['keywords']
            if not keys:continue
            expr='|'.join('(?:'+(k[3:] if k.startswith('re:') else re.escape(k))+')' for k in keys)
            self.patterns.append((name,sign,re.compile(expr,re.I)))
    def score(self,person,cfg):
        score=0.;hits=[]
        if self.enabled:
            text='\n'.join(str(person.get(f) or '') for f in self.fields)
            for name,sign,pattern in self.patterns:
                for match in pattern.finditer(text):
                    suffix=re.split(r'[.,\n]',text[match.end():match.end()+20],maxsplit=1)[0]
                    if sign==1 and '보다' in suffix:continue
                    score+=sign;hits.append(name);break
        if cfg.get('age_signal_enabled'):
            score+=cfg.get('age_signal_weight',.25)*(99-int(person['age']))/80;hits.append('보조 나이 신호')
        return score,hits
