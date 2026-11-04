"""자유응답을 기준 문장과 비교해 구매 의향 1~5의 확률로 바꾼다 (Maier 외 2025, semantic similarity rating).

응답마다: 기준 문장 세트(5문장)별로 코사인 유사도를 구하고, 최솟값을 빼서 확률로 정규화한 뒤 세트 평균을 낸다.
결과: results/<세트>.ssr.jsonl (사람×제품마다 p1~p5, 기댓값)

사용법: python3 ssr.py [--file results/saero_2022.jsonl] [--temp 1.0]
임베딩: 키 없이 맥에서 직접 돌린다(EMBED_BACKEND=local, 기본). 모델은 EMBED_MODEL (기본 nlpai-lab/KURE-v1, 한국어 검색용).
      처음 한 번 모델을 내려받는다. OpenAI API 키가 있으면 EMBED_BACKEND=api, EMBED_MODEL=text-embedding-3-small 로도 된다.
"""
import argparse, json, os
from pathlib import Path
import numpy as np
import llm

ROOT = Path(__file__).parent
EPS = 1e-3


def _writable(path):
    p = Path(path).expanduser()
    while not p.exists():
        if p.parent == p:
            return False
        p = p.parent
    return os.access(p, os.W_OK)


NEED_GB = 4  # KURE-v1 약 2.3GB + 여유


def fix_model_cache():
    """모델은 맥 본체(홈 폴더)에만 저장한다. 외장 디스크(/Volumes/...)는 작가가 USE_EXTERNAL_DISK=1 로 명시할 때만 쓴다.
    내려받기 전에 남은 용량을 확인하고, 모자라면 받지 않고 멈춘다."""
    import shutil
    home = Path.home() / ".cache" / "huggingface"
    external_ok = os.environ.get("USE_EXTERNAL_DISK") == "1"
    for var, sub in (("HF_HOME", ""), ("HF_HUB_CACHE", "hub"), ("HUGGINGFACE_HUB_CACHE", "hub"),
                     ("TRANSFORMERS_CACHE", "hub"), ("SENTENCE_TRANSFORMERS_HOME", "sentence_transformers")):
        v = os.environ.get(var)
        if v and ((v.startswith("/Volumes/") and not external_ok) or not _writable(v)):
            os.environ[var] = str(home / sub) if sub else str(home)
            print(f"모델 저장 위치를 {v} 대신 맥 본체 {os.environ[var]} 로 씀", flush=True)
    os.environ.setdefault("HF_HOME", str(home))
    target = Path(os.environ["HF_HOME"])
    already = (target / "hub" / "models--nlpai-lab--KURE-v1").exists()
    probe = target
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free / 1e9
    print(f"맥 본체 남은 용량 {free:.1f}GB (모델 {'이미 있음' if already else '약 2.3GB 내려받을 예정'})", flush=True)
    if not already and free < NEED_GB:
        raise SystemExit(f"❌ 남은 용량 {free:.1f}GB. 모델을 받으려면 {NEED_GB}GB 이상 필요해 멈춤")


class Embedder:
    def __init__(self):
        llm.load_env()
        self.kind = os.environ.get("EMBED_BACKEND", "local")
        if self.kind == "api":
            from openai import OpenAI
            self.client = OpenAI()
            self.model = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
        else:
            fix_model_cache()
            from sentence_transformers import SentenceTransformer
            self.model = os.environ.get("EMBED_MODEL", "nlpai-lab/KURE-v1")
            print(f"임베딩 모델 불러오는 중: {self.model} (처음엔 내려받기)", flush=True)
            self.st = SentenceTransformer(self.model)

    def __call__(self, texts):
        if self.kind == "api":
            r = self.client.embeddings.create(model=self.model, input=texts)
            return [np.array(d.embedding, dtype=np.float32) for d in r.data]
        return list(self.st.encode(texts, batch_size=32, convert_to_numpy=True, show_progress_bar=len(texts) > 500))


def embed(emb, texts, cache):
    need = [t for t in dict.fromkeys(texts) if t not in cache]
    for i in range(0, len(need), 256):
        chunk = need[i:i + 256]
        for t, v in zip(chunk, emb(chunk)):
            v = np.asarray(v, dtype=np.float32)
            cache[t] = v / np.linalg.norm(v)
    return np.stack([cache[t] for t in texts])


def to_pmf(resp_vec, anchor_mats, temp):
    pmfs = []
    for A in anchor_mats:
        s = A @ resp_vec
        p = s - s.min() + EPS
        p = p ** (1.0 / temp)
        pmfs.append(p / p.sum())
    return np.mean(pmfs, axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", default=None)
    ap.add_argument("--temp", type=float, default=1.0)
    a = ap.parse_args()
    emb = Embedder()
    sets = json.loads((ROOT / "config/anchors_ko.json").read_text(encoding="utf-8"))["sets"]
    cache = {}
    anchor_mats = [embed(emb, s, cache) for s in sets]

    files = [Path(f) for f in a.file] if a.file else sorted(p for p in (ROOT / "results").glob("*.jsonl") if ".ssr" not in p.name)
    for f in files:
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        texts = [v["reaction"] for r in rows for v in r["by_product"].values()]
        vecs = embed(emb, texts, cache)
        out, i = [], 0
        for r in rows:
            for pid, v in r["by_product"].items():
                pmf = to_pmf(vecs[i], anchor_mats, a.temp)
                i += 1
                out.append({"uuid": r["uuid"], "rep": r["rep"], "product": pid, "pmf": [round(float(x), 4) for x in pmf],
                            "expected": round(float(pmf @ np.arange(1, 6)), 3), "chosen": r["choice"] == pid,
                            "pull": v["pull"], "hesitate": v["hesitate"], "reaction": v["reaction"]})
        dest = f.with_name(f.stem + ".ssr.jsonl")
        dest.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
        print(f"{f.name}: {len(out)}건 -> {dest.name}")
    print("다음: python3 calc.py")


if __name__ == "__main__":
    main()
