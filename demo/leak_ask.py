"""결과 누수 검사: AI에게 실제 제품 이름을 대고 「출시 후 어땠는지」 직접 묻는다.
맞히는 제품은 AI가 결과를 이미 알고 있다는 뜻이라 「오염」으로 표시한다.
결과: results/leak_ask.json
"""
import json
import llm
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    err = llm.check()
    if err:
        raise SystemExit(err)
    sets = json.loads((ROOT / "config/sets.json").read_text(encoding="utf-8"))
    outc = json.loads((ROOT / "config/outcomes.json").read_text(encoding="utf-8"))
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"answer": {"type": "string", "enum": ["흥행", "유지", "부진", "모름"]}, "why": {"type": "string"}},
              "required": ["answer", "why"]}
    res = {}
    for st in sets:
        for p in st["products"]:
            if not p.get("target") or p["id"] not in outc:
                continue
            q = (f"{p['maker']}의 「{p['real_name']}」({st['launch']} 출시)는 출시 후 6개월 동안 시장 반응이 어땠는지 "
                 f"알고 있는 대로 답하세요. 흥행(크게 팔림), 유지(무난), 부진(단종·전략 변경 등), 모름 중 하나로.")
            a = llm.ask_json("질문에 아는 대로 답하세요. 모르면 모름이라고 답하세요.", q, schema)
            truth = outc[p["id"]]["grade"]
            res[p["id"]] = {"answer": a["answer"], "truth": truth, "contaminated": a["answer"] == truth, "why": a["why"]}
            print(p["real_name"], a["answer"], "정답" if a["answer"] == truth else "", sep=" | ")
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/leak_ask.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
