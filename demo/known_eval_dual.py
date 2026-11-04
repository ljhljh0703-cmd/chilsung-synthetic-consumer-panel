"""Evaluate habitual purchase (usual, primary) and current choice separately.

The numerical definitions deliberately match known_eval.py. Missing usual is
unknown, never imputed from choice. T4 requires five complete named shelves;
the predeclared decision uses usual / unweighted selection share only.
"""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import known_eval

ROOT = Path(__file__).parent
PRIMARY = "usual"
FIELDS = ("usual", "choice")
SELECTION = "이름공개·선택비율"
PASS_RULE = {"expected_shelves": 5, "last_match_min": 4, "weak_pair_acc_min": .8}


def _read_rows(path):
    rows, errors = [], []
    if not path.exists():
        return rows, ["file_missing"]
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("object required")
            rows.append(row)
        except (ValueError, TypeError):
            errors.append(f"invalid_json_line:{index}")
    return rows, errors


def _calculate(truth, rows_by_shelf, field, named, weight):
    """Same formulas, rounding and tie policy as the preserved known_eval."""
    pairs_ok = pairs = weak_ok = weak_n = 0
    cat, per = {}, {}
    for sid, t in truth.items():
        if sid.startswith("_"):
            continue
        rows = rows_by_shelf.get((sid, named), [])
        ids = list(t["value"])
        # Incomplete fields are not silently dropped from the denominator.
        if not rows or any(r.get(field) not in ids + ["없음"] for r in rows):
            continue
        if weight and not any(r.get("weekly_qty") is not None for r in rows):
            continue
        projected = [dict(r, choice=r[field]) for r in rows]
        sim = known_eval.shares(projected, ids, weight)
        tv = np.array([t["value"][i] for i in ids], float)
        tv = tv / tv.sum()
        sv = np.array([sim[i] for i in ids])
        worst = int(tv.argmin())
        c = cat.setdefault(t.get("category", "기타"), [0, 0])
        for a, b in itertools.combinations(range(len(ids)), 2):
            if tv[a] == tv[b]:
                continue
            hi, lo = (a, b) if tv[a] > tv[b] else (b, a)
            hit = 1 if sv[hi] > sv[lo] else .5 if sv[hi] == sv[lo] else 0
            pairs += 1
            pairs_ok += hit
            c[0] += hit
            c[1] += 1
            if worst in (a, b):
                weak_ok += hit
                weak_n += 1
        per[sid] = {
            "n": len(rows),
            "none_rate": round(sum(r[field] == "없음" for r in rows) / len(rows), 3),
            "top1_match": ids[int(tv.argmax())] == ids[int(sv.argmax())],
            "last_match": ids[worst] == ids[int(sv.argmin())],
            "spearman": known_eval.spearman(sv, tv),
            "mae_pp": round(float(np.abs(sv - tv).mean() * 100), 1),
            "sim": {i: round(float(sim[i]), 3) for i in ids},
            "truth": {i: round(float(x), 3) for i, x in zip(ids, tv)},
        }
    if not per:
        return None
    return {
        "pair_acc": round(pairs_ok / pairs, 3) if pairs else None, "pairs": pairs,
        "weak_pair_acc": round(weak_ok / weak_n, 3) if weak_n else None,
        "weak_pairs": weak_n,
        "last_match_rate": round(sum(x["last_match"] for x in per.values()) / len(per), 3),
        "by_category": {k: {"pair_acc": round(v[0] / v[1], 3) if v[1] else None, "pairs": v[1]} for k, v in cat.items()},
        "shelves": per,
    }


def evaluate(tag, truth_file="config/known_truth.json", expected_n=None):
    """Read-only evaluation. This function does not write or edit source results."""
    truth = json.loads((ROOT / truth_file).read_text(encoding="utf-8"))
    shelves = [sid for sid in truth if not sid.startswith("_")]
    if expected_n is not None and (type(expected_n) is not int or expected_n < 1):
        raise ValueError("expected_n must be a positive integer")
    rows_by_shelf, completeness, errors = {}, {}, []
    for sid in shelves:
        t = truth[sid]
        if not t.get("value") or any(not np.isfinite(float(v)) or float(v) < 0 for v in t["value"].values()) or sum(t["value"].values()) <= 0:
            raise ValueError("Invalid truth values: " + sid)
        ids = list(t["value"])
        for named in (False, True):
            path = ROOT / "results" / tag / f"{sid}{'_named' if named else ''}.jsonl"
            rows, read_errors = _read_rows(path)
            # Malformed files never contribute partial, apparently valid metrics.
            rows_by_shelf[sid, named] = [] if read_errors else rows
            if not named:
                continue
            issues = list(read_errors)
            uuids = [r.get("uuid") for r in rows]
            if any(not isinstance(u, str) or not u for u in uuids):
                issues.append("missing_uuid")
            if len({str(u) for u in uuids}) != len(uuids):
                issues.append("duplicate_uuid")
            if not rows:
                issues.append("empty_rows")
            if expected_n is not None and len(rows) != expected_n:
                issues.append(f"row_count:{len(rows)}!={expected_n}")
            for field in FIELDS:
                invalid = sum(r.get(field) not in ids + ["없음"] for r in rows)
                if invalid:
                    issues.append(f"{field}_missing_or_invalid:{invalid}")
            if any(r.get("named") is not True for r in rows):
                issues.append("named_flag_not_true")
            completeness[sid] = {"n": len(rows), "expected_n": expected_n, "complete": not issues, "issues": issues}
            errors.extend(f"{sid}:{issue}" for issue in issues)
    if len(shelves) != PASS_RULE["expected_shelves"]:
        errors.append(f"shelf_count:{len(shelves)}!={PASS_RULE['expected_shelves']}")
    if expected_n is None:
        errors.append("expected_n_not_declared")
    metrics = {field: {} for field in FIELDS}
    for field in FIELDS:
        for named in (False, True):
            for weight in (False, True):
                v = _calculate(truth, rows_by_shelf, field, named, weight)
                if v:
                    key = f"{'이름공개' if named else '이름가림'}·{'구매량가중' if weight else '선택비율'}"
                    metrics[field][key] = v
    primary = metrics[PRIMARY].get(SELECTION)
    last_hits = sum(x["last_match"] for x in primary["shelves"].values()) if primary else None
    weak = primary["weak_pair_acc"] if primary else None
    if errors or not primary or weak is None:
        status = "unknown"
    else:
        status = "pass" if last_hits >= PASS_RULE["last_match_min"] and weak >= PASS_RULE["weak_pair_acc_min"] else "fail"
    return {
        "primary_metric": PRIMARY, "secondary_metric": "choice", "metrics": metrics,
        "completeness": completeness, "errors": errors,
        "decision": {"status": status, "label": {"pass": "통과", "fail": "포기", "unknown": "확인 불가"}[status],
                     "metric": "usual / " + SELECTION, "last_matches": last_hits,
                     "weak_pair_acc": weak, "rule": dict(PASS_RULE)},
        "notes": ["usual 누락값을 choice로 채우지 않음.",
                  "판정에는 usual 이름공개 선택비율만 사용. choice와 구매량가중은 보조.",
                  "동률·순위상관 정의는 기존 known_eval.py와 동일. 동률에서 제품 입력 순서의 영향도 보존.",
                  "weekly_qty가 있으면 기존 계산을 두 번 제공하지만 평소 구매량을 따로 물은 값은 아님."],
    }


def report_lines(result):
    d = result["decision"]
    lines = ["## 주 판정: 평소 구매 (usual)",
             f"- 판정: {d['label']} ({d['status']})",
             f"- 사전 기준: 진열대 5개 중 꼴찌 일치 4개 이상 + 약한 제품 짝 맞힘 80% 이상.",
             f"- 꼴찌 일치: {d['last_matches']}/5 · 약한 제품 짝 맞힘: {d['weak_pair_acc']}",
             "- 이번 선택(choice)은 보조 지표이며 주 판정을 바꾸지 않음.", ""]
    if result["errors"]:
        lines += ["### 완결성 오류", *["- " + e for e in result["errors"]], ""]
    for field, label in (("usual", "주 지표 · 평소 구매"), ("choice", "보조 지표 · 이번 선택")):
        lines.append(f"## {label} ({field})")
        if not result["metrics"][field]:
            lines += ["확인 불가: 해당 응답 자료가 없음. 다른 지표로 보간하지 않음.", ""]
        for variant, value in result["metrics"][field].items():
            cats = ", ".join(f"{c} {x['pair_acc']}({x['pairs']}쌍)" for c, x in value["by_category"].items())
            lines += [f"### {variant}",
                      f"- 약한 제품 짝 맞힘 {value['weak_pair_acc']} ({value['weak_pairs']}쌍) · 꼴찌 일치 {value['last_match_rate']}",
                      f"- 전체 짝 맞힘 {value['pair_acc']} ({value['pairs']}쌍) · 범주별 {cats}", "",
                      "| 진열대 | 인원 | 꼴찌 일치 | 1위 일치 | 순위 상관 | 비중 차이 평균 | 없음 비율 | 가상 비중 | 실제 비중 |",
                      "|---|---:|---|---|---|---|---|---|---|"]
            for sid, x in value["shelves"].items():
                sim = ", ".join(f"{i} {s:.0%}" for i, s in x["sim"].items())
                tru = ", ".join(f"{i} {s:.0%}" for i, s in x["truth"].items())
                sp = "-" if x["spearman"] is None else f"{x['spearman']:.2f}"
                lines.append(f"| {sid} | {x['n']} | {'O' if x['last_match'] else 'X'} | {'O' if x['top1_match'] else 'X'} | {sp} | {x['mae_pp']}%p | {x['none_rate']:.0%} | {sim} | {tru} |")
            lines.append("")
    lines += ["## 계산 해석", *["- " + n for n in result["notes"]]]
    return lines


def ledger_metric(result):
    parts = ["주판정usual=" + result["decision"]["status"]]
    for field, label in (("usual", "주"), ("choice", "보조")):
        value = result["metrics"][field].get(SELECTION)
        parts.append(f"{label}{field}=unknown" if not value else
                     f"{label}{field}=약한짝{value['weak_pair_acc']}/꼴찌{value['last_match_rate']}/전체{value['pair_acc']}")
    return ";".join(parts) + ";"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--truth", default="config/known_truth.json")
    ap.add_argument("--expected-n", type=int)
    args = ap.parse_args()
    result = evaluate(args.tag, args.truth, args.expected_n)
    out = ROOT / "results" / args.tag
    out.mkdir(parents=True, exist_ok=True)
    (out / "known_eval_dual.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n".join(report_lines(result)))
    return 3 if result["decision"]["status"] == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
