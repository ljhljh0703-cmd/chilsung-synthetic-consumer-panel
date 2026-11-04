"""역검증: 가상 소비자 결과가 실제 시장 결과와 같은 방향인지 본다.

정답지(config/outcomes.json)는 simulate.py 가 읽지 않는다. 계산에 맞춰 넣는 값도 없다(전부 사전 입력값).
- 주 지표: 출시 6개월 판정(흥행/유지/부진, 사전 고정 기준)과의 짝 맞힘률
  : 등급이 다른 두 제품을 짝지었을 때, 등급 높은 쪽 점수가 더 높으면 맞힘. 무작위는 50%.
- 보조 지표: 출시 초기 하루 판매 속도(품목 연간 물량 대비)와의 순위 상관(스피어만)
- 기준선: 무작위, 「소주·맥주면 흥행」 규칙, 출시 분기 광고비 증가율만 쓴 규칙
- 결과 누수 검사: 이름 공개 응답(*_named)과 가린 응답의 끌림 차이
결과: results/validation.json
"""
import itertools, json, random
from pathlib import Path
import numpy as np

ROOT = Path(__file__).parent
GRADE = {"부진": 0, "유지": 1, "흥행": 2}


def pair_acc(scores, grades):
    ok = tot = 0
    for a, b in itertools.combinations(range(len(scores)), 2):
        if grades[a] == grades[b]:
            continue
        tot += 1
        hi, lo = (a, b) if grades[a] > grades[b] else (b, a)
        ok += 1 if scores[hi] > scores[lo] else 0.5 if scores[hi] == scores[lo] else 0
    return (ok / tot if tot else None), tot


def spearman(x, y):
    if len(x) < 3:
        return None
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])


def perm_p(scores, grades, observed, n=5000):
    if observed is None:
        return None
    rnd = random.Random(7)
    hits = 0
    for _ in range(n):
        s = scores[:]
        rnd.shuffle(s)
        v, _ = pair_acc(s, grades)
        hits += v >= observed
    return hits / n


def main():
    summ = json.loads((ROOT / "results/summary.json").read_text(encoding="utf-8"))
    outc = json.loads((ROOT / "config/outcomes.json").read_text(encoding="utf-8"))
    inp = json.loads((ROOT / "config/inputs.json").read_text(encoding="utf-8"))
    tg = [r for r in summ if r["target"] and r["product"] in outc and outc[r["product"]].get("grade") in GRADE
          and not outc[r["product"]].get("auxiliary")]
    grades = [GRADE[outc[r["product"]]["grade"]] for r in tg]
    report = {"n_targets": len(tg), "metrics": {}, "baselines": {}}

    for m in ("top2", "choice_share", "index_base"):
        sc = [r[m] for r in tg]
        acc, npairs = pair_acc(sc, grades)
        sp_rows = [(r[m], outc[r["product"]]["speed"]) for r in tg if outc[r["product"]].get("speed") is not None]
        report["metrics"][m] = {"pair_acc": acc, "pairs": npairs, "perm_p": perm_p(sc, grades, acc),
                                "spearman_speed": spearman([a for a, _ in sp_rows], [b for _, b in sp_rows]), "n_speed": len(sp_rows)}

    big = [1.0 if outc[r["product"]].get("category") in ("소주", "맥주") else 0.0 for r in tg]
    report["baselines"]["random"] = {"pair_acc": 0.5}
    noai = [r["index_noai_base"] for r in tg]
    report["baselines"]["inputs_only_no_ai"] = {"pair_acc": pair_acc(noai, grades)[0],
                                                "_note": "AI 응답 없이 입력값(유통·범주·분위기)만 쓴 지수. AI가 이걸 넘어야 AI가 보탠 몫이 있다"}
    report["baselines"]["soju_beer_rule"] = {"pair_acc": pair_acc(big, grades)[0]}
    ad = [inp["products"].get(r["product"], {}).get("ad_growth") for r in tg]
    if all(v is not None for v in ad):
        report["baselines"]["ad_growth_only"] = {"pair_acc": pair_acc(ad, grades)[0]}

    leaks = {}
    for r in tg:
        f = ROOT / "results" / f"{r['set']}_named.ssr.jsonl"
        if f.exists():
            rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and json.loads(l)["product"] == r["product"]]
            if rows:
                named = float(np.mean([sum(x["pmf"][3:]) for x in rows]))
                leaks[r["product"]] = {"hidden_top2": r["top2"], "named_top2": round(named, 4), "diff": round(named - r["top2"], 4)}
    report["leakage"] = leaks
    lf = ROOT / "results/leak_ask.json"
    if lf.exists():
        report["leak_ask"] = json.loads(lf.read_text(encoding="utf-8"))

    (ROOT / "results/validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
