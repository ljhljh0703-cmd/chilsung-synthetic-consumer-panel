"""실험 하나를 같은 방식으로 반복 실행하고 기록을 남긴다.

사용법: python3 run_experiment.py experiments/T1.json
  1) 실험 설정(experiments/*.json)대로 가상 소비자에게 묻는다 (끊겨도 다시 돌리면 이어서)
  2) 정답 파일이 있으면 채점한다
  3) results/<이름>/report.md 에 설정·결과·통과 기준을 한 장으로 남기고
  4) experiments/ledger.tsv 에 한 줄을 더한다 (언제·무엇을·어떤 모델로·결과)
실험 설정은 결과를 보기 전에 정하고, 돌린 뒤에는 고치지 않는다. 바꾸려면 새 이름으로 복사한다.
"""
import datetime, json, subprocess, sys
from pathlib import Path
import known_eval

ROOT = Path(__file__).parent


def main():
    spec_path = ROOT / sys.argv[1]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    dual = "--familiar-incumbents" in spec.get("flags", [])
    if dual and (not spec.get("truth_file") or spec.get("primary_metric", "usual") != "usual"):
        sys.exit("❌ 익숙한 기존 제품 실험은 정답 파일과 주 지표 usual이 필요합니다.")
    name = spec["name"]
    out = ROOT / "results" / name
    out.mkdir(parents=True, exist_ok=True)
    lock = out / "spec_locked.json"
    if lock.exists() and json.loads(lock.read_text(encoding="utf-8")) != spec:
        sys.exit(f"❌ {name} 은 이미 다른 설정으로 돌렸습니다. 설정을 바꾸려면 새 이름으로 만드세요.")
    if not lock.exists():
        lock.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")

    cmd = [sys.executable, "simulate.py", "--sets-file", spec["sets_file"], "--tag", name, "--limit", str(spec["n"])] + spec.get("flags", [])
    print("▶", " ".join(cmd), flush=True)
    execution = subprocess.run(cmd, cwd=ROOT, check=not dual)

    if dual:
        # T4 is additive: old experiments retain the original evaluator below.
        import known_eval_dual
        result = known_eval_dual.evaluate(name, spec["truth_file"], expected_n=spec["n"])
        if execution.returncode:
            result["errors"].append(f"simulate_exit:{execution.returncode}")
            result["decision"].update(status="unknown", label="확인 불가")
        (out / "known_eval_dual.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        settings = json.loads((out / "settings.json").read_text(encoding="utf-8")) if (out / "settings.json").exists() else {}
        lines = [f"# 실험 {name}", "", f"- 목적: {spec.get('goal', '')}",
                 f"- 통과 기준(사전): {spec.get('pass_rule', '')}",
                 f"- 실행: {datetime.datetime.now().isoformat(timespec='minutes')}",
                 f"- 모델: {settings.get('model', '')} · 묶음 {settings.get('batch', '')}명",
                 f"- 설정: {json.dumps(spec.get('flags', []), ensure_ascii=False)}",
                 "- 주 지표: usual(평소 구매). 보조 지표: choice(이번 선택).", ""]
        lines.extend(known_eval_dual.report_lines(result))
        (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        led = ROOT / "experiments" / "ledger.tsv"
        if not led.exists():
            led.write_text("시각\t실험\t모델\t사람수\t설정\t결과\n", encoding="utf-8")
        with led.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='minutes')}\t{name}\t{settings.get('model','')}\t{spec['n']}\t"
                    f"{' '.join(spec.get('flags', []))}\t{known_eval_dual.ledger_metric(result)}\n")
        print("\n".join(lines))
        if result["decision"]["status"] == "unknown":
            print("❌ 응답 완결성을 확인할 수 없습니다. 평가·실패 기록을 남겼으며 완료로 처리하지 않습니다.", file=sys.stderr)
            sys.exit(3)
        print(f"\n✅ {name} 실행·평가 끝 ({result['decision']['label']}) → results/{name}/report.md · experiments/ledger.tsv")
        return

    res = {}
    if spec.get("truth_file"):
        res = known_eval.evaluate(name, spec["truth_file"])
    settings = json.loads((out / "settings.json").read_text(encoding="utf-8")) if (out / "settings.json").exists() else {}

    lines = [f"# 실험 {name}", "", f"- 목적: {spec.get('goal', '')}", f"- 통과 기준(사전): {spec.get('pass_rule', '')}",
             f"- 실행: {datetime.datetime.now().isoformat(timespec='minutes')}", f"- 모델: {settings.get('model', '')} · 묶음 {settings.get('batch', '')}명",
             f"- 설정: {json.dumps(spec.get('flags', []), ensure_ascii=False)}", ""]
    ledger_metric = ""
    for k, v in res.items():
        cats = ", ".join(f"{c} {x['pair_acc']}({x['pairs']}쌍)" for c, x in v.get("by_category", {}).items())
        lines.append(f"## {k}")
        lines.append(f"- 주 지표 · 약한 제품 걸러내기: 실제 꼴찌가 낀 짝 맞힘 {v.get('weak_pair_acc')} ({v.get('weak_pairs')}쌍), 꼴찌 일치 {v.get('last_match_rate')}")
        lines.append(f"- 전체 짝 맞힘 {v['pair_acc']} ({v['pairs']}쌍) · 범주별 {cats}")
        lines.append("")
        lines.append("| 진열대 | 꼴찌 일치 | 1위 일치 | 순위 상관 | 비중 차이 평균 | 없음 비율 | 가상 비중 | 실제 비중 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for sid, x in v["shelves"].items():
            sim = ", ".join(f"{i} {s:.0%}" for i, s in x["sim"].items())
            tru = ", ".join(f"{i} {s:.0%}" for i, s in x["truth"].items())
            sp = "-" if x["spearman"] is None else f"{x['spearman']:.2f}"
            lines.append(f"| {sid} | {'O' if x.get('last_match') else 'X'} | {'O' if x['top1_match'] else 'X'} | {sp} | {x['mae_pp']}%p | {x['none_rate']:.0%} | {sim} | {tru} |")
        lines.append("")
        ledger_metric += f"{k}=약한짝{v.get('weak_pair_acc')}/전체{v['pair_acc']};"
    if not res:
        lines.append("정답 파일이 없어 채점하지 않음. 응답 원문은 같은 폴더의 jsonl.")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")

    led = ROOT / "experiments" / "ledger.tsv"
    if not led.exists():
        led.write_text("시각\t실험\t모델\t사람수\t설정\t결과\n", encoding="utf-8")
    with open(led, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now().isoformat(timespec='minutes')}\t{name}\t{settings.get('model','')}\t{spec['n']}\t"
                f"{' '.join(spec.get('flags', []))}\t{ledger_metric}\n")
    print("\n".join(lines))
    print(f"\n✅ {name} 끝 → results/{name}/report.md · experiments/ledger.tsv")


if __name__ == "__main__":
    main()
