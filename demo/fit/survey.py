"""L17 approved questionnaire and format-only live runner."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import heapq
import json
import math
from pathlib import Path
from random import Random
import re
from unicodedata import normalize
from threading import Lock
from datetime import datetime, timezone

from providers import HAIKU, TERRA, SETTINGS, CLI_SETTINGS, Quota, Stop, answer, cli_answer, load_keys, preflight

ROOT = Path(__file__).resolve().parents[2]
VAULT = ROOT.parents[1]
QUESTION = ROOT / "research/fit-questionnaire.md"
PREREG = ROOT / "preregistration-FIT.md"
POPULATION = ROOT / "population/out/population.parquet"
RETURN = VAULT / "wiki/projects/lotte-ax-2026-returns/2026-11-04-market-fit"
DESIGN_HASH = "ac04857d0983b19fe249a02722dde40f0f843700edeaa739d03120b918d500d8"
QUESTION_HASH = "7cd9e3d42d40c9ecbb41975186f4eab7bc7fc15505a34eb9eabe093de8d94a29"
SAMPLE_SEED, ORDER_SEED = 20261104, 1730
COMBOS = {1: (TERRA, 0, "A"), 2: (TERRA, 1, "A"), 3: (TERRA, 2, "A"),
          4: (HAIKU, 2, "A"), 5: (TERRA, 2, "B")}
DEMOGRAPHICS = {"age": "나이", "sex": "성별", "province": "거주 지역"}
PROFILE = {"occupation": "직업", "professional_persona": "직업 생활", "culinary_persona": "식생활",
           "family_persona": "가족 생활", "hobbies_and_interests": "취미와 관심사",
           "sports_persona": "운동", "arts_persona": "예술", "travel_persona": "여행"}
FIELDS = [*DEMOGRAPHICS, *PROFILE, "adopter"]
KEYS = {"v1", "v2", "v3_drank", "v3", "soju_cups", "beer_cups"}


def questionnaire():
    raw = QUESTION.read_bytes()
    if (sha256(raw).hexdigest() != QUESTION_HASH or
            sha256(PREREG.read_bytes()).hexdigest() != DESIGN_HASH):
        raise Stop("승인 문안 또는 17:30 정리본의 판본이 달라 중지")
    doc = raw.decode()
    if not re.search(r"^status: approved\b", doc, re.M):
        raise Stop("문항 승인 기록 미확인")
    sections = re.split(r"^## ", doc, flags=re.M)
    result = {"system": sections[1].splitlines()[1], "questions": {}, "options": {}}
    for i, v in enumerate(("v1", "v2", "v3"), 2):
        section = sections[i]
        result["questions"][v] = {a: re.search(rf"^- {a}: (.+)$", section, re.M)[1] for a in "AB"}
        result["options"][v] = re.search(r"^- 보기\(.+?\): (.+)$", section, re.M)[1].split(" / ")
    result["screen"] = dict(zip("AB", re.search(r"^- 사전 문항 A: (.+) — B: (.+)$", sections[4], re.M).groups()))
    result["schema"] = re.search(r"^JSON: (.+)$", sections[6], re.M)[1]
    return result


def redact_profile(person):
    """Use source persona only to verify the name, then drop both source fields."""
    name = normalize("NFC", person.pop("name") or "")
    source = normalize("NFC", person.pop("persona") or "")
    if not re.fullmatch(r"[가-힣]{2,5}", name) or not source.startswith(name + " 씨"):
        raise Stop("원본 페르소나 이름을 확인할 수 없어 전송 중단")
    count = 0
    for field in PROFILE:
        if isinstance(person.get(field), str):
            value = normalize("NFC", person[field])
            count += value.count(name)
            person[field] = value.replace(name, "이 사람")
    person["_name_replacements"] = count
    return person


def sample(path=POPULATION, size=300):
    """Weighted sampling without replacement using exponential arrival times."""
    import pyarrow.parquet as pq
    source = pq.ParquetFile(path)
    rng = Random(SAMPLE_SEED)
    selected = []
    for rowgroup in range(source.num_row_groups):
        scalars = source.read_row_group(rowgroup, columns=["age", "weight"])
        for i, (age, weight) in enumerate(zip(scalars["age"].to_pylist(), scalars["weight"].to_pylist())):
            if type(age) is not int:
                raise Stop("모집단 나이 형식 오류")
            if age < 19:
                continue
            if weight is None or not math.isfinite(weight) or weight <= 0:
                raise Stop("모집단 인구 가중치 오류")
            rank = -rng.expovariate(weight)
            item = (rank, rowgroup, i)
            if len(selected) < size:
                heapq.heappush(selected, item)
            elif item > selected[0]:
                heapq.heapreplace(selected, item)
    if len(selected) != size:
        raise Stop("성인 표본 수 미달")
    ranks = {(g, i): k for k, (_, g, i) in enumerate(sorted(selected, reverse=True))}
    people = [None] * size
    for group in sorted({g for g, _ in ranks}):
        offsets = [(i, k) for (g, i), k in ranks.items() if g == group]
        picked = source.read_row_group(group, columns=[*FIELDS, "name", "persona"]).take([i for i, _ in offsets]).to_pylist()
        for (_, k), person in zip(offsets, picked):
            people[k] = redact_profile(person)
    return people


def prompt(q, person, combo, repeat, index, retry=False):
    _, level, phrasing = COMBOS[combo]
    if level == 0:
        system = "당신은 한국에 사는 성인 한 명입니다."
    else:
        fields = {**DEMOGRAPHICS, **(PROFILE if level == 2 else {})}
        description = {label: person[key] for key, label in fields.items() if person.get(key) not in (None, "")}
        system = q["system"] + "\n인물 소개: " + json.dumps(description, ensure_ascii=False)
    options = q["options"]["v3"].copy()
    Random(f"{ORDER_SEED}:{repeat}:{index}").shuffle(options)
    v1, v2, v3 = [q["questions"][v][phrasing] for v in ("v1", "v2", "v3")]
    v1_opts = " / ".join(q["options"]["v1"])
    v2_opts = " / ".join(q["options"]["v2"])
    v3_opts = " / ".join(options)
    text = f"""2024년 조사 시점을 기준으로 답하세요.
V1. {v1}
보기: {v1_opts}
V2. V1이 「최근 1년간 마시지 않음」이면 묻지 않으며 v2는 「전혀 없음」입니다.
그 외에는 답하세요: {v2}
보기: {v2_opts}

2020년 조사 시점을 기준으로 답하세요.
V3 사전 문항. {q["screen"][phrasing]}
「예」이면 v3_drank=true, 「아니오」이면 false입니다.
「예」일 때만 답하세요: {v3}
보기: {v3_opts}
「아니오」이면 v3는 빈 배열입니다.
보조: 1회 평균 음주량: 소주로 몇 잔, 맥주로 몇 잔(마시는 경우만).
해당하지 않는 음주량은 null입니다.
설명과 코드 울타리 없이 JSON 객체 하나만 반환하세요. 보기 문구를 그대로 쓰세요.
{q["schema"]}"""
    if retry:
        text += "\n응답 형식만 한 번 더 확인합니다. 여섯 키를 모두 포함한 JSON 객체만 답하세요."
    return system, text


def parse(q, raw):
    def unique(items):
        obj = dict(items)
        if len(obj) != len(items):
            raise ValueError("duplicate keys")
        return obj
    def bad_constant(_):
        raise ValueError("non-finite")
    try:
        obj = json.loads(raw, object_pairs_hook=unique, parse_constant=bad_constant)
        if not isinstance(obj, dict) or obj.keys() != KEYS:
            return None
        if any(obj[v] not in q["options"][v] for v in ("v1", "v2")):
            return None
        if obj["v1"] == q["options"]["v1"][0] and obj["v2"] != q["options"]["v2"][0]:
            return None
        selected = obj["v3"]
        if (type(obj["v3_drank"]) is not bool or not isinstance(selected, list)
                or any(type(x) is not str or x not in q["options"]["v3"] for x in selected)
                or len(set(selected)) != len(selected) or obj["v3_drank"] != bool(selected)):
            return None
        for k in ("soju_cups", "beer_cups"):
            value = obj[k]
            if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or value < 0):
                return None
        return obj
    except (ValueError, OverflowError, RecursionError):
        return None


def one(q, person, combo, repeat, index, keys, call=answer):
    model = COMBOS[combo][0]
    returned = []
    for retry in (False, True):
        settings = prompt(q, person, combo, repeat, index, retry)
        actual, raw = call(model, *settings, keys)
        returned.append(actual)
        obj = parse(q, raw)
        if obj is not None:
            return obj, returned
    return None, returned


def smoke(path):
    q = questionnaire()
    keys = load_keys()
    people = sample()
    order = list(range(10))
    Random(ORDER_SEED).shuffle(order)
    groups, models, route, calls = {}, {}, {}, []
    stop = None
    lock = Lock()

    def tracked(combo, kind, generation, replacements, model, system, user, keyfile):
        with lock:
            if len(calls) >= 100:
                raise Stop("형식 시험 승인 상한 100건 도달")
            entry = {"combo": combo, "route": kind, "generation": generation, "model": None,
                     "name_replacements": replacements,
                     "settings": (SETTINGS if kind=="api" else CLI_SETTINGS)[model]}
            calls.append(entry)
        try:
            actual, raw = (answer if kind=="api" else cli_answer)(model, system, user, keyfile)
        except Quota:
            entry["status"] = "quota"
            raise
        except Stop:
            entry["status"] = "error"
            raise
        entry.update(status="returned", model=actual)
        return actual, raw

    def group(combo, kind, generation):
        valid = retries = completed = 0
        actual = Counter()
        error = None
        quota = None
        def format_only(index):
            person = people[index]
            replacements = person["_name_replacements"] if COMBOS[combo][1] == 2 else 0
            def call(*args):
                return tracked(combo, kind, generation, replacements, *args)
            obj, names = one(q, person, combo, 1, index, keys, call=call)
            return obj is not None, names
        with ThreadPoolExecutor(max_workers=5 if kind=="api" else 2) as pool:
            wave = 5 if kind=="api" else 2
            for start in range(0, len(order), wave):
                futures = [pool.submit(format_only, i) for i in order[start:start+wave]]
                for future in futures:
                    try:
                        ok, names = future.result()
                    except Quota as exc:
                        quota = exc
                    except Stop as exc:
                        error = exc
                    else:
                        completed += 1
                        valid += int(ok)
                        retries += len(names)-1
                        actual.update(names)
                if error or quota:
                    break
        return {"route":kind, "planned":10, "completed":completed, "format_valid":valid,
                "excluded":completed-valid, "excluded_rate":(completed-valid)/completed if completed else None,
                "retried":retries, "actual_models_per_response":dict(actual),
                "name_replacements_in_returned_requests":sum(
                    c["name_replacements"] for c in calls if c["combo"] == combo
                    and c["generation"] == generation and c["status"] == "returned"),
                "format_status":"partial" if completed<10 else ("pass" if valid==10 else "hold")}, error or quota

    try:
        for model in (TERRA, HAIKU):
            try:
                models[model] = preflight(model, keys)
                route[model] = "api"
            except Quota:
                models[model] = "quota"
                route[model] = "cli"
        for combo, (model, _, _) in COMBOS.items():
            kind = route[model]
            row, failure = group(combo, kind, 1)
            if isinstance(failure, Quota) and kind=="api":
                route[model] = "cli"
                print(f"조합 {combo}: API 크레딧 한도. 해당 조합을 로그인 경로로 다시 시작", flush=True)
                discarded = row
                row, failure = group(combo, "cli", 2)
                row["discarded_api"] = discarded
            groups[combo] = row
            print(f"조합 {combo} ({row['route']}): 완료 {row['completed']}/10 · 형식 유효 {row['format_valid']} · 제외 {row['excluded']} · 재요청 {row['retried']}", flush=True)
            if failure:
                raise failure
    except Stop as error:
        stop = str(error)
    result = {"state":"provisional", "gate":"gate_pending", "mode":"format-only",
              "recorded_at":datetime.now(timezone.utc).isoformat(),
              "question_sha256":QUESTION_HASH, "prereg_sha256":DESIGN_HASH,
              "model_preflight":models, "groups":groups, "calls":calls,
              "attempts_by_route":dict(Counter(c["route"] for c in calls)),
              "accepted_responses_by_route":dict(Counter({kind:sum(g["completed"] for g in groups.values() if g["route"]==kind)
                                                          for kind in ("api","cli")})),
              "stop":stop, "survey_answers_retained":False, "main_run":"not run"}
    with path.open("x") as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
        out.write("\n")
    if stop:
        raise Stop(stop)
    if any(row["format_status"]!="pass" for row in groups.values()):
        raise Stop("형식 시험에서 제외율 5% 초과 조합 발생")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("format",))
    args = parser.parse_args()
    out = RETURN / "format-evidence-1810.json"
    try:
        if out.exists():
            raise Stop("이전 형식 증거 보존: 중복 실행 금지")
        smoke(out)
    except Stop as error:
        raise SystemExit(str(error)) from None
