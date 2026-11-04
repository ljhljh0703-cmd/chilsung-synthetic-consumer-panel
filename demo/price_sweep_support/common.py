"""Shared helpers; no existing demo source is modified."""
import hashlib,json
from pathlib import Path
DEMO=Path(__file__).resolve().parents[1]
FIELDS=('age','sex','province','hobbies_and_interests','culinary_persona','adopter','launch_sensitivity','viral_sensitivity')

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(text,encoding='utf-8');tmp.replace(path)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def persona_text(person):
    return json.dumps({k:person[k] for k in FIELDS if k in person},ensure_ascii=False)

def readonly_json(path,value):
    path=Path(path)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))!=value:raise ValueError(f'existing file has different content: {path}')
    else:save(path,value)
