"""Download pinned public NVIDIA shards, enforce 2x disk headroom and SHA256."""
import datetime, hashlib, json, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REPO='https://huggingface.co'
NAME='nvidia/Nemotron-Personas-Korea'
def get(url):
    return subprocess.check_output(['curl','-fLsS','--retry','2','--max-time','60',url])
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()
def main():
    info=json.loads(get(f'{REPO}/api/datasets/{NAME}'))
    rev=info['sha']
    files=json.loads(get(f'{REPO}/api/datasets/{NAME}/tree/{rev}?recursive=true&expand=false'))
    files=[x for x in files if x['path'].endswith('.parquet')]
    if not files: raise RuntimeError('No shards returned')
    raw=ROOT/'raw'; raw.mkdir(exist_ok=True)
    total=sum(x['size'] for x in files)
    free=shutil.disk_usage(raw).free
    # All source bytes plus conservative same-size output estimate, each with 2x headroom.
    required=2*(total+total)
    manifest={'source':f'{REPO}/datasets/{NAME}','revision':rev,'license':'CC-BY-4.0',
      'checked_at':datetime.datetime.now().astimezone().isoformat(),'shards':files,
      'raw_bytes':total,'estimated_output_bytes':total,'required_free_bytes':required,'free_bytes':free,
      'disk_pass':free>=required,'download_complete':False}
    dest=ROOT/'source_manifest.json'; dest.write_text(json.dumps(manifest,indent=2))
    if free<required: raise SystemExit('STOP: less than 2x required source+output disk space')
    print(f'{len(files)} shards; raw {total:,} bytes; free {free:,}; required {required:,}',flush=True)
    for item in files:
        p=raw/Path(item['path']).name; expected=item['lfs']['oid']
        if p.exists() and p.stat().st_size==item['size'] and sha(p)==expected:
            print('verified existing',p.name,flush=True); continue
        partial=p.with_suffix('.partial')
        subprocess.run(['curl','-fL','--retry','3','--max-time','600','-o',str(partial),f'{REPO}/datasets/{NAME}/resolve/{rev}/{item["path"]}'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if partial.stat().st_size!=item['size'] or sha(partial)!=expected:
            raise RuntimeError(f'Integrity mismatch: {p.name}')
        partial.replace(p); print('verified',p.name,flush=True)
    manifest['download_complete']=True
    manifest['completed_at']=datetime.datetime.now().astimezone().isoformat()
    dest.write_text(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
