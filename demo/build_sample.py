"""가상 소비자 표본을 뽑는다.

원본: NVIDIA Nemotron-Personas-Korea (CC BY 4.0, 통계청 분포 기반 합성 인물, 만 19세 이상)
- data/drinkers.json : 술 신제품용. 성·연령대별 월간음주율(지역사회건강조사 2025)로 음주자만 추린다.
- data/adults.json   : 음료 신제품용. 성인 전체 무작위.

사용법: python3 build_sample.py [원본 parquet] [음주자 수] [성인 수]
"""
import json, random, sys
from pathlib import Path
import pyarrow.parquet as pq

ROOT = Path(__file__).parent
SRC = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data_raw/shard0.parquet")
N_DRINK = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
N_ADULT = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
KEEP = ["uuid", "persona", "culinary_persona", "family_persona", "hobbies_and_interests",
        "sex", "age", "marital_status", "family_type", "housing_type", "education_level",
        "occupation", "district", "province"]
RATES = json.loads((ROOT / "config/drink_rates.json").read_text(encoding="utf-8"))


def band(age):
    return str(min(70, max(20, age // 10 * 10)))


def tidy(r):
    r["name"] = r["persona"].split(" 씨")[0].strip()
    r["age_band"] = band(r["age"])
    return r


rows = pq.read_table(SRC, columns=KEEP).to_pylist()
rng = random.Random(20261028)
rng.shuffle(rows)

drinkers = []
for r in rows:
    if rng.random() * 100 < RATES[r["sex"]][band(r["age"])]:
        drinkers.append(tidy(dict(r)))
        if len(drinkers) == N_DRINK:
            break
adults = [tidy(dict(r)) for r in rows[-N_ADULT:]]

(ROOT / "data").mkdir(exist_ok=True)
for name, data in (("drinkers", drinkers), ("adults", adults)):
    (ROOT / f"data/{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}: {len(data)}명")
