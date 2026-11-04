"""가상 소비자 반응을 업계 표준 신제품 계산 순서(ATAR)에 넣어 제품별 지수를 낸다.

  6개월 구매 지수 = 범주 사용자 × 인지 × 매장 취급 × 보정된 시용 × (1 + 재구매율)
  - 보정된 시용: 가상 소비자 응답의 「꼭 산다」 확률 × k5 + 「아마 산다」 확률 × k4 (그 아래는 0)
  - 범주 사용자·인지·매장 취급·재구매율·그해 분위기: AI가 아니라 config/inputs.json 의 입력값(범위)
  - 모든 값은 비관·기본·낙관 세 가지로 계산해 흔들림 폭을 함께 낸다.

결과: results/summary.json
"""
import collections, json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).parent
SCEN = ("low", "base", "high")


def rng(x, s):
    if isinstance(x, (int, float)):
        return float(x)
    return float(x[SCEN.index(s)])


def main():
    sets = json.loads((ROOT / "config/sets.json").read_text(encoding="utf-8"))
    inp = json.loads((ROOT / "config/inputs.json").read_text(encoding="utf-8"))
    summary = []
    for st in sets:
        f = ROOT / "results" / f"{st['id']}.ssr.jsonl"
        if not f.exists():
            continue
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        by = collections.defaultdict(list)
        for r in rows:
            by[r["product"]].append(r)
        n_people = len({(r["uuid"], r["rep"]) for r in rows})
        cat = inp["category"][st["category"]]
        year = inp["year_mood"].get(str(st["year"]), {"value": [1, 1, 1]})
        for prod in st["products"]:
            rs = by[prod["id"]]
            if not rs:
                continue
            P = np.array([r["pmf"] for r in rs])
            pin = inp["products"].get(prod["id"], {})
            res = {"set": st["id"], "product": prod["id"], "name": prod["real_name"], "target": prod.get("target", False),
                   "n": len(rs), "expected": round(float((P @ np.arange(1, 6)).mean()), 3),
                   "top2": round(float(P[:, 3:].sum(1).mean()), 4),
                   "choice_share": round(sum(r["chosen"] for r in rs) / n_people, 4),
                   "inputs_default": [k for k in ("awareness", "availability") if k not in pin]}
            for s in SCEN:
                k5, k4 = rng(inp["trial_discount"]["definitely"], s), rng(inp["trial_discount"]["probably"], s)
                trial = float((P[:, 4] * k5 + P[:, 3] * k4).mean())
                idx = (rng(cat["users"], s) * rng(pin.get("awareness", inp["default"]["awareness"]), s)
                       * rng(pin.get("availability", inp["default"]["availability"]), s) * trial
                       * (1 + rng(cat["repeat"], s)) * rng(year["value"], s))
                res[f"trial_{s}"] = round(trial, 4)
                res[f"index_{s}"] = round(idx, 5)
                # AI를 뺀 기준선: 시용을 모든 제품에 같은 값(0.1)으로 고정하고 입력값만으로 낸 지수
                res[f"index_noai_{s}"] = round(idx / trial * 0.1, 5) if trial > 0 else 0.0
            summary.append(res)
    (ROOT / "results/summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in summary:
        mark = "★" if r["target"] else " "
        print(f"{mark} {r['set']:<16} {r['name']:<18} 끌림 {r['top2']:.3f} 선택 {r['choice_share']:.3f} 지수 {r['index_base']:.5f} ({r['index_low']:.5f}~{r['index_high']:.5f})")
    print("다음: python3 validate.py")


if __name__ == "__main__":
    main()
