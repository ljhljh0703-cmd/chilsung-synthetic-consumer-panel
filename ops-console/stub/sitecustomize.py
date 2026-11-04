"""Only enabled in an explicitly isolated OPS_STUB=1 subprocess."""
import os,sys,types
if os.environ.get('OPS_STUB')=='1':
    llm=types.ModuleType('llm')
    llm.backend=lambda:'stub'
    llm.model_name=lambda:'STUB:deterministic-offline'
    llm.check=lambda:None
    def answer(s):
        if 'people' in s['properties']:
            return {'people':{k:answer(v) for k,v in s['properties']['people']['properties'].items()}}
        labels=list(s['properties']['products']['properties'])
        return {'products':{k:{'reaction':'가짜 응답 시험입니다. 실제 소비자 반응이 아닙니다.','pull':'시험용','hesitate':'시험용'} for k in labels},'choice':labels[0],'choice_reason':'가짜 응답 연결 시험'}
    llm.ask_json=lambda system,user,schema,**kw:answer(schema)
    sys.modules['llm']=llm
