"""기존 제품만 놓은 진열대에서 가상 소비자 선택이 실제 점유율 순서를 재현하는지 본다.
사용법: python3 known_eval.py [tag ...]   (예: python3 known_eval.py T0 T1 T2)
       python3 known_eval.py --truth config/truth_xxx.json T0   (정답 파일 바꾸기)
- 선택 비율: 「없음」을 빼고 제품별로 고른 비율
- 구매량 가중: weekly_qty 가 있으면 고른 비율 × 일주일 구매량
- 지표: 1위 일치, 진열대를 합친 짝 맞힘률(실제 더 많이 팔린 쪽을 더 많이 골랐나), 진열대별 순위 상관, 비중 차이 평균(%p)
- 주 지표(작가 결정 2026-11-04): 약한 제품 걸러내기 = 실제 꼴찌가 가상에서도 꼴찌인가(꼴찌 일치), 실제 꼴찌가 낀 짝만 본 짝 맞힘률
- 범주별(맥주·탄산) 따로도 낸다
결과: results/known_eval.json
"""
import itertools, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).parent


def spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def shares(rows, ids, weight):
    s = {i: 0.0 for i in ids}
    for r in rows:
        if r["choice"] in s:
            w = (r.get("weekly_qty") or 0) if weight else 1
            s[r["choice"]] += w
    tot = sum(s.values()) or 1
    return {i: v / tot for i, v in s.items()}


def evaluate(tag, truth_file="config/known_truth.json"):
    truth = json.loads((ROOT / truth_file).read_text(encoding="utf-8"))
    out = {}
    for named in (False, True):
        for weight in (False, True):
            pairs_ok = pairs = 0
            weak_ok = weak_n = 0
            cat = {}
            per = {}
            for sid, t in truth.items():
                if sid.startswith("_"):
                    continue
                f = ROOT / "results" / tag / f"{sid}{'_named' if named else ''}.jsonl"
                if not f.exists():
                    continue
                rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
                if not rows or (weight and not any(r.get("weekly_qty") is not None for r in rows)):
                    continue
                ids = list(t["value"])
                sim = shares(rows, ids, weight)
                tv = np.array([t["value"][i] for i in ids], float)
                tv = tv / tv.sum()
                sv = np.array([sim[i] for i in ids])
                worst = int(tv.argmin())
                c = cat.setdefault(t.get("category", "기타"), [0, 0])
                for a, b in itertools.combinations(range(len(ids)), 2):
                    if tv[a] == tv[b]:
                        continue
                    hi, lo = (a, b) if tv[a] > tv[b] else (b, a)
                    hit = 1 if sv[hi] > sv[lo] else 0.5 if sv[hi] == sv[lo] else 0
                    pairs += 1
                    pairs_ok += hit
                    c[0] += hit
                    c[1] += 1
                    if worst in (a, b):
                        weak_ok += hit
                        weak_n += 1
                per[sid] = {"n": len(rows), "none_rate": round(sum(r["choice"] == "없음" for r in rows) / len(rows), 3),
                            "top1_match": ids[int(tv.argmax())] == ids[int(sv.argmax())],
                            "last_match": ids[worst] == ids[int(sv.argmin())],
                            "spearman": spearman(sv, tv), "mae_pp": round(float(np.abs(sv - tv).mean() * 100), 1),
                            "sim": {i: round(float(sim[i]), 3) for i in ids},
                            "truth": {i: round(float(x), 3) for i, x in zip(ids, tv)}}
            if per:
                out[f"{'이름공개' if named else '이름가림'}·{'구매량가중' if weight else '선택비율'}"] = {
                    "pair_acc": round(pairs_ok / pairs, 3) if pairs else None, "pairs": pairs,
                    "weak_pair_acc": round(weak_ok / weak_n, 3) if weak_n else None, "weak_pairs": weak_n,
                    "last_match_rate": round(sum(x["last_match"] for x in per.values()) / len(per), 3),
                    "by_category": {k: {"pair_acc": round(v[0] / v[1], 3) if v[1] else None, "pairs": v[1]} for k, v in cat.items()},
                    "shelves": per}
    return out


def main():
    args = sys.argv[1:]
    truth_file = "config/known_truth.json"
    if "--truth" in args:
        i = args.index("--truth")
        truth_file = args[i + 1]
        args = args[:i] + args[i + 2:]
    tags = args or [p.name for p in (ROOT / "results").iterdir() if p.is_dir()]
    allres = {}
    for tag in tags:
        allres[tag] = evaluate(tag, truth_file)
        for k, v in allres[tag].items():
            tops = " ".join(f"{s}:1위{'O' if x['top1_match'] else 'X'}·꼴찌{'O' if x['last_match'] else 'X'}·상관{x['spearman'] if x['spearman'] is None else round(x['spearman'],2)}·차이{x['mae_pp']}%p"
                            for s, x in v["shelves"].items())
            cats = " ".join(f"{c}:{x['pair_acc']}({x['pairs']}쌍)" for c, x in v["by_category"].items())
            print(f"[{tag}] {k}  약한 제품 짝 {v['weak_pair_acc']} ({v['weak_pairs']}쌍) · 꼴찌 일치 {v['last_match_rate']} · 전체 짝 {v['pair_acc']} ({v['pairs']}쌍) · 범주 {cats}\n   {tops}")
    (ROOT / "results/known_eval.json").write_text(json.dumps(allres, ensure_ascii=False, indent=1), encoding="utf-8")
    print("-> results/known_eval.json")


if __name__ == "__main__":
    main()
