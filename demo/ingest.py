"""현업 자료를 실험에 바로 쓰는 설정 파일로 바꾼다.

사용법
  python3 ingest.py cards inbox/cards/<파일>.csv <이름>   → config/sets_<이름>.json
  python3 ingest.py truth inbox/truth/<파일>.csv <이름>   → config/truth_<이름>.json
  python3 ingest.py survey inbox/human_survey/<파일>.csv <이름> → config/survey_<이름>.json (사람 조사 결과, 보정 비교용)

cards CSV 열: set_id, launch, category, seen_at, sample, product_id, real_name, maker, target(1/0), 종류, 도수, 용량, 가격, 맛, 포장, 컨셉
truth CSV 열: set_id, product_id, value, basis   (value = 판매액·판매량·점유율 등 같은 단위면 무엇이든)
survey CSV 열: set_id, respondent_id, choice_product_id   (실제 사람에게 같은 진열대를 보여 주고 고른 것)
빈칸은 비워 두면 카드에 안 나온다.
"""
import csv, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
ATTRS = ["종류", "도수", "용량", "가격", "맛", "포장", "컨셉"]


def read(path):
    with open(ROOT / path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def cards(rows, name):
    sets = {}
    for r in rows:
        s = sets.setdefault(r["set_id"], {"id": r["set_id"], "launch": r.get("launch", ""), "category": r.get("category", ""),
                                          "seen_at": r.get("seen_at") or "동네 마트·편의점", "sample": r.get("sample") or "drinkers",
                                          "products": []})
        s["products"].append({"id": r["product_id"], "real_name": r.get("real_name", ""), "maker": r.get("maker", ""),
                              "target": r.get("target", "0").strip() in ("1", "true", "예"),
                              "attrs": {k: r[k].strip() for k in ATTRS if r.get(k, "").strip()}})
    out = ROOT / f"config/sets_{name}.json"
    out.write_text(json.dumps(list(sets.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def truth(rows, name):
    t = {"_source": f"inbox 현업 자료 → ingest.py ({name})"}
    for r in rows:
        s = t.setdefault(r["set_id"], {"basis": r.get("basis", ""), "grade": "현업 자료", "value": {}})
        s["value"][r["product_id"]] = float(r["value"])
    out = ROOT / f"config/truth_{name}.json"
    out.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def survey(rows, name):
    cnt = defaultdict(lambda: defaultdict(int))
    for r in rows:
        cnt[r["set_id"]][r["choice_product_id"]] += 1
    t = {"_source": f"사람 조사 ({name})"}
    for sid, c in cnt.items():
        t[sid] = {"basis": f"사람 {sum(c.values())}명 선택 수", "grade": "사람 조사", "value": dict(c)}
    out = ROOT / f"config/survey_{name}.json"
    out.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    kind, path, name = sys.argv[1:4]
    out = {"cards": cards, "truth": truth, "survey": survey}[kind](read(path), name)
    print(f"✅ {out.relative_to(ROOT)} 생성. 실험 설정(experiments/*.json)의 sets_file·truth_file 에 이 경로를 넣으면 됩니다.")
