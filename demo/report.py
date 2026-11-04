"""summary.json + validation.json + 응답 원문으로 결과 화면(report.html)을 만든다.
사용법: python3 report.py
"""
import collections, json
from pathlib import Path

ROOT = Path(__file__).parent
AGE = ["20", "30", "40", "50", "60", "70"]


def main():
    sets = json.loads((ROOT / "config/sets.json").read_text(encoding="utf-8"))
    summ = json.loads((ROOT / "results/summary.json").read_text(encoding="utf-8"))
    val = json.loads((ROOT / "results/validation.json").read_text(encoding="utf-8"))
    outc = json.loads((ROOT / "config/outcomes.json").read_text(encoding="utf-8"))
    out = {"validation": val, "sets": []}
    for st in sets:
        f = ROOT / "results" / f"{st['id']}.ssr.jsonl"
        if not f.exists():
            continue
        people = {p["uuid"]: p for p in json.loads((ROOT / f"data/{st['sample']}.json").read_text(encoding="utf-8"))}
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        target = next(p for p in st["products"] if p.get("target"))
        tr = [r for r in rows if r["product"] == target["id"]]
        by_age = collections.defaultdict(list)
        for r in tr:
            by_age[people[r["uuid"]]["age_band"]].append(sum(r["pmf"][3:]))
        def q(r):
            p = people[r["uuid"]]
            return {"who": f"{p['name']} · {p['age']}세 · {p['sex']} · {p['province']} · {p['occupation']}",
                    "line": r["reaction"], "pull": r["pull"], "hesitate": r["hesitate"]}
        hi = sorted(tr, key=lambda r: -sum(r["pmf"][3:]))[:4]
        lo = sorted(tr, key=lambda r: sum(r["pmf"][3:]))[:4]
        hes = collections.Counter(r["hesitate"].strip() for r in tr if r["hesitate"].strip()).most_common(6)
        prods = sorted([s for s in summ if s["set"] == st["id"]], key=lambda s: -s["choice_share"])
        out["sets"].append({
            "id": st["id"], "launch": st["launch"], "category": st["category"], "auxiliary": st.get("auxiliary", False),
            "target": target["real_name"], "target_attrs": target["attrs"],
            "products": [{"name": s["name"], "target": s["target"], "choice": s["choice_share"], "top2": s["top2"],
                          "index": [s["index_low"], s["index_base"], s["index_high"]]} for s in prods],
            "age": [{"band": a, "top2": round(sum(by_age[a]) / len(by_age[a]), 3) if by_age[a] else None, "n": len(by_age[a])} for a in AGE],
            "pos": [q(r) for r in hi], "neg": [q(r) for r in lo], "hesitate_top": hes,
            "outcome": outc.get(target["id"])})
    html = (ROOT / "report_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(out, ensure_ascii=False))
    (ROOT / "report.html").write_text(html, encoding="utf-8")
    print("-> report.html")


if __name__ == "__main__":
    main()
