"""Render offline FIT metrics as Korean Markdown tables and local SVG charts."""
from collections import Counter
from html import escape
from pathlib import Path


def show(value):
    return "계산 불가" if value is None else f"{value:.2f}"


def pair(values):
    return " ~ ".join(map(show, values))


def judgment(value, yes="통과", no="미달"):
    return "보류" if value is None else yes if value else no


def chart(path, combo, source, rows):
    h = 60 + 48*len(rows)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" width="720" height="{h}" viewBox="0 0 720 {h}">',
           f'<title>조합 {combo} · 자료 {source} · 응답률 비교</title>',
           f'<rect width="720" height="{h}" fill="#fff"/>',
           '<g font-family="sans-serif" fill="#172132" font-size="13">',
           f'<text x="12" y="20">조합 {combo} / V{source} · 페르소나(파랑), 기관 통계(회색), 단위 %</text>']
    for i,(label, row) in enumerate(rows.items()):
        y = 38 + 48*i
        svg.append(f'<text x="12" y="{y+18}">{escape(label)}</text>')
        for off,color,key in ((0,"#2360a3","pct"),(18,"#6c757d","reference_pct")):
            value = row[key]
            width = 4.1*value
            svg.append(f'<rect x="220" y="{y+off}" width="{width:.1f}" height="13" fill="{color}"/>')
            svg.append(f'<text x="{226+width:.1f}" y="{y+off+11}">{value:.1f}</text>')
    path.write_text("\n".join([*svg, "</g></svg>"]) + "\n", encoding="utf-8")


def response_concentration(repeats, options):
    """Return 95% concentration flags for the questions actually answered."""
    answers = [row for repeat in repeats for row in repeat if row is not None]
    v2 = [row for row in answers if row["v1"] != options["v1"][0]]
    v3 = [row for row in answers if row["v3_drank"]]
    fields = (
        ("V1 음주 빈도", Counter(row["v1"] for row in answers), len(answers)),
        ("V2 폭음 빈도", Counter(row["v2"] for row in v2), len(v2)),
        ("V3 최근 6개월 음주 여부", Counter("예" if row["v3_drank"] else "아니오" for row in answers), len(answers)),
        ("V3 주로 마신 술", Counter(option for row in v3 for option in row["v3"]), len(v3)),
    )
    return [(question, option, count, total) for question, counts, total in fields
            for option, count in counts.most_common() if total and 100*count >= 95*total]


def write_report(directory, result, *, concentrations=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    lines = ["# L17 페르소나 시장 정합성", "",
             "state: provisional · gate: gate_pending", "",
             f"- RQ1 대표성: {judgment(result['rq1'])}",
             f"- RQ2 정보 기여: {judgment(result['rq2'],'있음','입증 안 됨')}",
             f"- RQ3 판정 안정성: {judgment(result['rq3'],'안정','불일치')}",
             f"- H4 세그먼트 방향: {judgment(result['h4'],'지지','입증 안 됨')}", "",
             "95% 구간은 세 반복의 평균 비율과 가장 작은 해당 분모를 쓴 Wilson 근사입니다. "
             "같은 300명을 반복하므로 900명으로 계산하지 않습니다. 반복 범위는 별도입니다. "
             "기관 통계 자체의 조사오차는 포함하지 않습니다.", ""]
    for c,g in sorted(result["combos"].items()):
        lines.extend([f"## 조합 {c}", "",
                      f"- 제외 {sum(g['excluded_by_repeat'])}/900 ({100*g['excluded_rate']:.2f}%). "
                      f"반복별 제외: {g['excluded_by_repeat']}."])
        if concentrations is not None:
            flags = concentrations[c]
            if not flags:
                lines.append("- 응답 쏠림 95% 이상 없음.")
            for question, option, count, total in flags:
                lines.append(f"- 응답 쏠림 · {question} 「{option}」 {count}/{total} ({100*count/total:.1f}%).")
        if g["status"]=="hold":
            lines.extend(["- 제외율 5% 초과로 판정 보류.", ""])
            continue
        if "rq1_by_source" in g:
            lines.append("- 자료별 판정: " + ", ".join(f"V{i} {judgment(v)}" for i,v in enumerate(g["rq1_by_source"],1)))
        for s,m in enumerate(g["metrics"],1):
            lines.extend(["",f"### V{s}",""])
            if m is None:
                lines.append("분모가 없는 칸이 있어 계산 보류.")
                continue
            lines.extend([f"평균 절대 차이 {show(m['mae_pp'])}%p (반복 범위 {pair(m['mae_range_pp'])}). "
                          f"스피어만 {show(m['rho'])}.",
                          "", "| 항목 | 응답 % | 기관 % | 차이 %p | 반복 범위 % | 응답 95% 구간 % | 분모(회별) |",
                          "|---|---:|---:|---:|---|---|---|"])
            for k,r in m["cells"].items():
                lines.append(f"| {k} | {show(r['pct'])} | {show(r['reference_pct'])} | {show(r['diff_pp'])} | "
                             f"{pair(r['range_pct'])} | {pair(r['ci95_pct'])} | {r['n_by_repeat']} |")
            name = f"combo-{c}-v{s}.svg"
            chart(directory/name,c,s,m["cells"])
            lines.extend(["", f"![조합 {c} V{s} 기관 통계 대 페르소나]({name})"])
        aux=g["auxiliary_mean_cups_by_repeat"]
        lines.extend(["", "- 보조 음주량(회별 평균): 소주 "+", ".join(map(show,aux["soju_cups"]))+
                      "잔(기관 5.4), 맥주 "+", ".join(map(show,aux["beer_cups"]))+"잔(기관 4.4).",""])
    lines.extend(["## RQ2 자료별 비교", "", "| 자료 | 전체 서술 개선 %p | 반복 흔들림 %p | 단계별 오차 감소 | 판정 |",
                  "|---|---:|---:|---|---|"])
    for i,r in enumerate(result["rq2_by_source"],1):
        if r is None:
            lines.append(f"| V{i} | — | — | — | 보류 |")
        else:
            lines.append(f"| V{i} | {show(r['improvement_pp'])} | {show(r['noise_pp'])} | "
                         f"{judgment(r['monotonic'],'예','아니오')} | {judgment(r['supported'],'기여 있음','입증 안 됨')} |")
    lines.extend(["","## H4 연령군별 비교","",
                  "조합 3의 최근 6개월 음주자 기준. 차이는 혁신자·초기 수용자 비율에서 후기 다수·지체자 비율을 뺀 값입니다.",
                  "", "| 연령 | 주종 | 초기 % | 후기 % | 차이 %p | 반복 범위 %p | 차이 95% 구간 %p |",
                  "|---|---|---:|---:|---:|---|---|"])
    for row in result["h4_table"]:
        a,d,e=row["age"],row["drink"],row["estimate"]
        cells=("—",)*5 if e is None else (show(e["early"]["pct"]),show(e["late"]["pct"]),show(e["diff_pp"]),
                                         pair(e["range_pp"]),pair(e["ci95_pp"]))
        lines.append("| " + " | ".join((a,d,*cells)) + " |")
    lines.extend(["", "해석 범위: V3 기관 통계는 2020년 15세 이상을 포함하지만, 합성 표본은 19세 이상입니다. "
                  "기관 정답을 재현하더라도 사람과 나란히 조사한 결과나 신제품 예측력으로 해석할 수 없습니다."])
    (directory/"report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
