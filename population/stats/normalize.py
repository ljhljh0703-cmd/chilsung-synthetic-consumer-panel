"""Normalize the unmodified KOSIS CSV export, keeping only age 19..99.

The CSV was exported through the official KOSIS browser UI, not a third-party
mirror. A failed direct-download request was not used for population values.
Run: python3 population/stats/normalize.py (from project root).
"""
import collections
import csv
import datetime
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "kosis_202512_raw.csv"
PROVINCES = {
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
    "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도",
    "경상남도", "제주특별자치도",
}


def main():
    with RAW.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0][2:] == ["2025.12"] * 3, "Unexpected reference period"
    assert rows[1][2:] == ["총인구수 (명)", "남자인구수 (명)", "여자인구수 (명)"]
    seen = set()
    totals = collections.Counter()
    national = {}
    cells = collections.Counter()
    excluded = collections.Counter()
    for province, label, total, male, female in rows[2:]:
        assert (province, label) not in seen, "Duplicate source row"
        seen.add((province, label))
        total, male, female = map(int, (total, male, female))
        assert male + female == total, "Sex total mismatch"
        if province == "전국":
            national[label] = (total, male, female)
            continue
        assert province in PROVINCES, f"Unexpected geography: {province}"
        for i, value in enumerate((total, male, female)):
            totals[label, i] += value
        if label == "계":
            continue
        age = int(re.search(r"\d+", label).group())
        for sex, value in (("남자", male), ("여자", female)):
            if age < 19:
                excluded["age_0_18"] += value
            elif age >= 100:
                excluded["age_100_plus"] += value
            else:
                cells[province, sex, age // 10 * 10] += value
    for label, values in national.items():
        assert tuple(totals[label, i] for i in range(3)) == values, label
    assert len(seen) == 18 * 102
    assert len(cells) == 17 * 2 * 9
    assert sum(cells.values()) + sum(excluded.values()) == national["계"][0]
    out = ROOT / "population_cells.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["province", "sex", "age_band", "population"])
        for key in sorted(cells):
            writer.writerow([*key, cells[key]])
    source = {
        "state": "provisional",
        "gate": "gate_pending",
        "provider": "KOSIS 국가통계포털",
        "producer": "행정안전부 주민등록인구현황",
        "table_id": "DT_1B04006",
        "table_title": "행정구역(시군구)별/1세별 주민등록인구",
        "url": "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1B04006&conn_path=I2",
        "reference_period": "2025-12",
        "retrieved_at": "2026-11-04T14:03:04+09:00",
        "retrieval_method": "Official browser UI: 조회설정 > 시점 2025.12 > 조회 > 다운로드 > CSV UTF-8",
        "download_filename": "행정구역_시군구_별_1세별_주민등록인구_20261104140304.csv",
        "raw_file": RAW.name,
        "raw_bytes": RAW.stat().st_size,
        "raw_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
        "normalized_file": out.name,
        "normalized_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "normalized_cells": len(cells),
        "population_age_19_99": sum(cells.values()),
        "excluded": dict(excluded),
        "national_all_ages": national["계"][0],
        "validation": {
            "each_row_male_plus_female_equals_total": True,
            "each_age_17_provinces_sum_equals_national": True,
            "no_duplicate_province_age": True,
            "all_306_cells_positive": all(v > 0 for v in cells.values()),
        },
        "scope": "17시도 남녀 주민등록 인구 중 19~99세. band10은 19세만, band20은 20~29세, 이후 10세 구간. 전국 합계와 미성년 및 100세 이상은 가중 분모에서 제외.",
        "limitations": [
            "전체 거주인구 또는 소비자 패널이 아니며 등록 외국인은 포함하지 않는다.",
            "2025-12 고정 기준. 최신 2026-10과는 시점 및 행정구역 구성이 다르다.",
            "19~99세는 Nemotron 원본의 관측 연령 지지집합에 맞춘 범위이다. 100세 이상을 90대로 합치지 않았다.",
            "인구 가중치가 행동·취향·SNS 관계망의 대표성을 보장하지 않는다.",
        ],
    }
    (ROOT / "source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cells": len(cells), "population": sum(cells.values()), "excluded": dict(excluded)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
