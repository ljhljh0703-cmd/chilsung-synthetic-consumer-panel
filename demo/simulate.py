"""출시 당시 경쟁 제품들과 신제품을 나란히 가상 소비자에게 보여주고 반응을 받는다.

- 제품 이름·브랜드·제조사·광고 모델은 가리고 A·B·C·D 로만 보여준다 (결과를 기억해서 답하는 것 차단).
- 제품 순서는 사람마다 섞는다 (먼저 본 제품이 유리해지는 것 차단).
- 점수를 직접 묻지 않고, 제품마다 그 사람 말투의 자유응답을 받는다. 점수는 ssr.py 가 기준 문장과 비교해 매긴다.
- --named 를 주면 실제 이름을 보여준다. 가린 결과와 비교해 결과가 새는지 검사하는 용도다.
- 구독 로그인(Codex·Claude CLI)으로 돌릴 때는 호출 수를 줄이려고 한 번에 여러 사람(--batch)을 묻는다.
  이때 진열 순서는 묶음마다 섞는다. 각 사람은 따로 판단하라고 지시하지만, 한 번에 한 사람씩 묻는 것보다 독립성이 약하다.

사용법
  python3 simulate.py --set saero_2022 --limit 30
  python3 simulate.py                         # config/sets.json 전체
  python3 simulate.py --set saero_2022 --named --limit 200
  python3 simulate.py --dry-run --set saero_2022
  python3 simulate.py --batch 1                # 한 사람씩 (API 키로 돌릴 때 기본)
결과: results/<세트id>[_named].jsonl (끊겨도 다시 돌리면 이어서 한다)
"""
import argparse, collections, hashlib, json, random, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import llm

ROOT = Path(__file__).parent
LABELS = "ABCDEF"
ATTR_ORDER = ["종류", "도수", "용량", "가격", "맛", "포장", "컨셉"]

SYSTEM = """당신은 아래에 묘사된 한국 사람 한 명입니다. 그 사람의 나이, 사는 곳, 직업, 가족, 식습관, 지갑 사정을 그대로 가진 채로 판단하세요.
- 진열대에서 실제로 마주친 것처럼, 이 사람이 평소 마시는 것·가격 감각·건강 걱정·취향·술자리 상황으로 판단하세요.
- 이 사람에게 해당 없는 제품이면 그렇다고 솔직하게 말하세요.
- 말투는 이 사람이 친구에게 말하듯 자연스럽게 쓰세요."""


def person_schema(labels, ask_qty=False, ask_usual=False):
    per = {"type": "object", "additionalProperties": False,
           "properties": {"reaction": {"type": "string", "description": "이 제품을 보고 살지 말지, 왜 그런지 이 사람 말투로 2~3문장"},
                          "pull": {"type": "string", "description": "끌리는 점 한 가지(없으면 빈칸)"},
                          "hesitate": {"type": "string", "description": "망설여지는 점 한 가지(없으면 빈칸)"}},
           "required": ["reaction", "pull", "hesitate"]}
    props = {"products": {"type": "object", "additionalProperties": False,
                          "properties": {l: per for l in labels}, "required": list(labels)},
             "choice": {"type": "string", "enum": list(labels) + ["없음"],
                        "description": "이 중 하나만 산다면 무엇을 고를지. 아무것도 안 사면 없음"},
             "choice_reason": {"type": "string"}}
    if ask_usual:
        props["usual"] = {"type": "string", "enum": list(labels) + ["없음"],
                          "description": "평소 이 중 가장 자주 사는 제품. 평소 사는 것이 없으면 없음"}
    if ask_qty:
        props["weekly_qty"] = {"type": "integer", "minimum": 0, "maximum": 50,
                               "description": "고른 제품을 이 사람이 보통 일주일에 몇 캔·병 살지. 안 사면 0"}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def schema(labels, keys, ask_qty=False, ask_usual=False):
    if keys is None:
        return person_schema(labels, ask_qty, ask_usual)
    return {"type": "object", "additionalProperties": False,
            "properties": {"people": {"type": "object", "additionalProperties": False,
                                      "properties": {k: person_schema(labels, ask_qty, ask_usual) for k in keys}, "required": list(keys)}},
            "required": ["people"]}


def persona_text(p):
    return (f"[기본 정보] {p['name']}, {p['sex']}, {p['age']}세, {p['province']} {p['district'].split('-')[-1]} 거주, "
            f"{p['occupation']}, {p['education_level']}, {p['marital_status']}, {p['family_type']}, {p['housing_type']}\n"
            f"[어떤 사람] {p['persona']}\n[먹고 마시는 습관] {p['culinary_persona']}\n"
            f"[가족] {p['family_persona']}\n[취미] {p['hobbies_and_interests']}")


def short(v, n=30):
    v = str(v)
    if len(v) <= n:
        return v
    cut = v[:n].rsplit(" ", 1)[0].rstrip(",·")
    return cut or v[:n]


def card(prod, named, keys=None, cap=None):
    """keys: 이 키만 보여 줌(카드 길이 맞추기용). cap: 값마다 최대 글자 수."""
    lines = []
    if named:
        lines.append(f"제품명: {prod['real_name']} ({prod['maker']})")
    for k in ATTR_ORDER:
        if keys is not None and k not in keys:
            continue
        if prod["attrs"].get(k):
            lines.append(f"{k}: {short(prod['attrs'][k], cap) if cap else prod['attrs'][k]}")
    return "\n".join(lines)


def order_for(uuid, set_id, n):
    rng = random.Random(int(hashlib.md5(f"{uuid}{set_id}".encode()).hexdigest(), 16))
    idx = list(range(n))
    rng.shuffle(idx)
    return idx


OPTS = {"scene": None, "new_hint": True, "equal_cards": False, "ask_qty": False}


def familiar_system(system):
    if OPTS.get("familiar_incumbents", False):
        return system + "\n- 이 제품들을 이미 알고 있다면 평소 경험대로 답하세요."
    return system


def familiar_question():
    if OPTS.get("familiar_incumbents", False):
        return "\n평소 이 중 가장 자주 사는 것(usual)과 이번에 하나만 고른다면 무엇인지(choice)를 따로 답하세요. 평소 사는 제품이 없으면 usual은 없음입니다."
    return ""


def build_messages(group, st, named):
    """group: 사람 목록. 1명이면 예전과 같은 한 사람 질문, 여러 명이면 묶음 질문."""
    key = group[0]["uuid"] if len(group) == 1 else "batch:" + group[0]["uuid"]
    order = order_for(key, st["id"], len(st["products"]))
    labels = LABELS[: len(order)]
    keys = cap = None
    if OPTS["equal_cards"]:
        keys = set.intersection(*[{k for k, v in p["attrs"].items() if v} for p in st["products"]])
        cap = 30
    blocks = [f"[{labels[i]}]\n{card(st['products'][j], named or (OPTS.get('familiar_incumbents', False) and not st['products'][j].get('target', False)), keys, cap)}" for i, j in enumerate(order)]
    scene = OPTS["scene"] or st["seen_at"]
    has_new = any(p.get("target") for p in st["products"])
    hint = "이 중 하나는 이번에 새로 나온 제품입니다.\n\n" if (OPTS["new_hint"] and has_new) else "\n"
    qty = "\n\n고른 제품을 이 사람이 보통 일주일에 몇 캔·병 살지도 답하세요." if OPTS["ask_qty"] else ""
    shelf = (f"지금은 {st['launch']}입니다. {scene}에서 아래 제품들을 봤습니다. " + hint + "\n\n".join(blocks) + qty)
    if len(group) == 1:
        user = (f"{persona_text(group[0])}\n\n{shelf}"
                "\n\n이 사람으로서 각 제품에 반응하고, 하나만 산다면 무엇을 고를지 답하세요.")
        return familiar_system(SYSTEM), user + familiar_question(), order, labels, None
    keys = [f"P{i + 1}" for i in range(len(group))]
    people = "\n\n".join(f"<{k}>\n{persona_text(p)}\n</{k}>" for k, p in zip(keys, group))
    user = (f"아래 {len(group)}명은 서로 모르는 사람들입니다. 각자 따로 이 진열대를 봤습니다.\n\n{people}\n\n{shelf}\n\n"
            "한 사람씩 그 사람이 되어 각 제품에 반응하고, 하나만 산다면 무엇을 고를지 답하세요. "
            "다른 사람 답에 맞추거나 일부러 다르게 하지 말고, 그 사람의 생활만 보고 판단하세요.")
    return familiar_system(SYSTEM.replace("한국 사람 한 명", "한국 사람들 각각")), user + familiar_question(), order, labels, keys


def build_person_order_messages(group, st, named):
    """New opt-in path: each P alias gets its own shelf and reverse mapping.

    Returns (system, user, orders_by_person, labels, keys). UUIDs are used only
    for deterministic local ordering; the prompt contains P1/P2 aliases only.
    Duplicate permutations are expected when the number of people exceeds n!.
    """
    if not group or not 1 <= len(st["products"]) <= len(LABELS):
        raise ValueError("비어 있거나 지원 범위를 벗어난 사람/제품 목록")
    orders = [order_for(person["uuid"], st["id"], len(st["products"])) for person in group]
    labels = LABELS[:len(st["products"])]
    if len(group) == 1:
        system, user, order, labels, keys = build_messages(group, st, named)
        return system, user, [order], labels, keys
    keys = [f"P{i + 1}" for i in range(len(group))]
    blocks = []
    for key, person in zip(keys, group):
        _, user, _, _, _ = build_messages([person], st, named)
        blocks.append(f"<{key}>\n{user}\n</{key}>")
    user = (f"아래 {len(group)}명은 서로 모르는 사람들입니다. 각 사람의 카드 순서와 A·B·C 표시가 다릅니다. "
            "각자 자기 블록 안의 카드 표시만 보고 독립적으로 답하세요.\n\n" + "\n\n".join(blocks) +
            "\n\n각 사람의 답을 같은 P 표시 아래에 적으세요. 다른 사람의 카드 표시나 답에 맞추지 마세요.")
    return familiar_system(SYSTEM.replace("한국 사람 한 명", "한국 사람들 각각")), user, orders, labels, keys


def decode_answers(group, st, orders, labels, keys, answer, *, model, named, rep, familiar=False):
    """Map each person's labels back through that person's own permutation."""
    answers = [answer] if keys is None else [answer["people"][key] for key in keys]
    if len(orders) != len(group) or len(answers) != len(group):
        raise ValueError("사람 수와 응답/순서 수가 다릅니다")
    rows = []
    for person, one, order in zip(group, answers, orders):
        by_id = {st["products"][j]["id"]: one["products"][labels[i]] for i, j in enumerate(order)}
        def product_id(value):
            if familiar and value not in list(labels) + ["없음"]:
                raise ValueError("usual/choice에 카드 표시 외 값이 왔습니다")
            return st["products"][order[labels.index(value)]]["id"] if value in labels else "없음"
        row = {"uuid": person["uuid"], "rep": rep, "model": model, "named": named, "batch": len(group),
               "order": [st["products"][j]["id"] for j in order], "by_product": by_id,
               "choice": product_id(one["choice"]), "choice_reason": one["choice_reason"],
               "weekly_qty": one.get("weekly_qty")}
        if familiar:
            row["usual"] = product_id(one["usual"])
        rows.append(row)
    return rows


def resolve_people_path(value, st):
    supplied = Path(value).expanduser()
    candidates = [supplied] if supplied.is_absolute() else [ROOT / supplied, ROOT.parent / supplied]
    found = next((p.resolve() for p in candidates if p.is_file()), None)
    if found is None:
        raise FileNotFoundError(f"표본 파일을 읽을 수 없습니다: {value}")
    if st.get("sample") == "adults" or st.get("category") == "탄산":
        if found.name == "sample_beer_2000.json":
            found = found.with_name("sample_adults_2000.json")
            if not found.is_file():
                raise FileNotFoundError(f"탄산용 성인 표본을 읽을 수 없습니다: {found}")
    return found


def sample_people(value, st, limit, seed):
    path = resolve_people_path(value, st)
    raw = path.read_bytes()
    people = json.loads(raw.decode("utf-8"))
    if not isinstance(people, list) or not people:
        raise ValueError("표본 파일은 비어 있지 않은 JSON 배열이어야 합니다")
    if len({p["uuid"] for p in people}) != len(people):
        raise ValueError("표본 파일에 중복 UUID가 있습니다")
    n = len(people) if limit is None else limit
    if not 1 <= n <= len(people):
        raise ValueError("요청 인원이 표본 파일 범위를 벗어났습니다")
    selected = random.Random(seed).sample(people, n)
    def counts(values):
        return dict(sorted(collections.Counter(values).items(), key=lambda item: str(item[0])))
    l6 = path.parent == (ROOT.parent / "population/out").resolve()
    meta = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "seed": seed,
            "source_n": len(people), "selected_n": n, "selection": "random.sample without replacement",
            "selected_uuids": [p["uuid"] for p in selected], "uuid_scope": "local_only_not_sent",
            "age_distribution": counts(str(p["age"]) for p in selected),
            "age_band_distribution": counts(str(int(p["age"]) // 10 * 10) for p in selected),
            "sex_distribution": counts(str(p["sex"]) for p in selected),
            "source_kind": "L6 generated synthetic sample" if l6 else "explicit user-supplied sample; provenance unverified",
            "raw_persona_source": "NVIDIA Nemotron-Personas-Korea / CC BY 4.0" if l6 else "unknown",
            "derived_fields": {"adopter": "L6 keyword/age ranking and fixed Rogers quotas",
                               "weight": "L6 population post-stratification",
                               "drinker": "L6 monthly drinking-rate probability",
                               "launch_sensitivity,viral_sensitivity,viral_channel": "L6 reaction_values; hypothetical, basis unresolved"},
            "derived_fields_in_prompt": False}
    return selected, meta


def load_sets(path):
    """product_ids 만 적힌 진열대는 config/sets.json 의 카드를 가져다 쓴다(같은 문구 유지)."""
    base = {p["id"]: p for s in json.loads((ROOT / "config/sets.json").read_text(encoding="utf-8")) for p in s["products"]}
    sets = json.loads((ROOT / path).read_text(encoding="utf-8"))
    for s in sets:
        if "product_ids" in s:
            s["products"] = []
            inline = {q["id"]: q for q in s.get("products_inline", [])}
            for i in s["product_ids"]:
                prod = dict(inline.get(i) or base[i], target=False)
                prod["attrs"] = {**prod["attrs"], **s.get("override", {}).get(i, {})}
                s["products"].append(prod)
    return sets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--named", action="store_true")
    ap.add_argument("--workers", type=int, default=None, help="동시 호출 수 (기본: API 16, 구독 CLI 3)")
    ap.add_argument("--batch", type=int, default=None, help="한 번에 묻는 사람 수 (기본: API 1, 구독 CLI 15)")
    ap.add_argument("--reps", type=int, default=1, help="같은 사람에게 몇 번 물을지 (흔들림 측정용)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sets-file", default="config/sets.json", help="진열대 목록 파일 (기존 제품 진열대는 config/sets_known.json)")
    ap.add_argument("--tag", default="", help="결과를 results/<tag>/ 에 따로 저장 (시도별 구분)")
    ap.add_argument("--scene", default=None, help="장면 덮어쓰기. 예) 동네 마트·편의점")
    ap.add_argument("--no-new-hint", action="store_true", help="「이 중 하나는 새 제품」 문구 빼기")
    ap.add_argument("--equal-cards", action="store_true", help="모든 카드에 같은 항목만, 값은 30자 안쪽")
    ap.add_argument("--ask-qty", action="store_true", help="고른 제품을 일주일에 몇 캔·병 살지 같이 묻기")
    ap.add_argument("--per-person-order", action="store_true", help="묶음 안에서도 각 사람의 카드 순서를 따로 섞음")
    ap.add_argument("--familiar-incumbents", action="store_true", help="기존 제품명 공개, 평소 구매 usual과 이번 선택 choice를 따로 질문")
    ap.add_argument("--people", default=None, help="별도 합성 표본 JSON; L6 맥주 파일을 주면 탄산은 같은 폴더 성인 표본 사용")
    ap.add_argument("--sample-seed", type=int, default=20261104, help="--people 표본에서 무작위 선택하는 고정 난수")
    a = ap.parse_args()
    if a.scene == "동네마트·편의점":
        a.scene = "동네 마트·편의점"
    OPTS.update(scene=a.scene, new_hint=not a.no_new_hint, equal_cards=a.equal_cards, ask_qty=a.ask_qty,
                per_person_order=a.per_person_order, familiar_incumbents=a.familiar_incumbents)

    sets = load_sets(a.sets_file)
    if a.set:
        sets = [s for s in sets if s["id"] == a.set]
    cli = llm.backend() != "api"
    batch = a.batch or (15 if cli else 1)
    workers = a.workers or (3 if cli else 16)
    model = llm.model_name()
    effective_named = a.named or a.familiar_incumbents
    failures = 0
    people_cache = {}

    for st in sets:
        source_info = None
        if a.people:
            resolved = resolve_people_path(a.people, st)
            cache_key = (str(resolved), a.limit, a.sample_seed)
            if cache_key not in people_cache:
                people_cache[cache_key] = sample_people(str(resolved), st, a.limit, a.sample_seed)
            people, source_info = people_cache[cache_key]
        else:
            people = json.loads((ROOT / f"data/{st['sample']}.json").read_text(encoding="utf-8"))
            if a.limit:
                people = people[: a.limit]
        if a.dry_run:
            if a.per_person_order:
                _, user, orders, labels, _ = build_person_order_messages(people[:batch], st, a.named)
            else:
                _, user, order, labels, _ = build_messages(people[:batch], st, a.named)
                orders = [order]
            print(user)
            print("\n순서:", [[st["products"][j]["id"] for j in order] for order in orders] if a.per_person_order
                  else [st["products"][j]["id"] for j in orders[0]])
            continue
        err = llm.check()
        if err:
            sys.exit(err)
        out = ROOT / "results" / a.tag / f"{st['id']}{'_named' if effective_named else ''}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        settings_path = out.parent / "settings.json"
        settings = {"batch": batch, "model": model, "sets_file": a.sets_file, **OPTS}
        if a.people:
            previous = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
            if previous:
                for key, value in settings.items():
                    if previous.get(key) != value:
                        raise ValueError(f"이미 시작한 실행의 {key} 설정이 다릅니다. 새 tag를 쓰세요.")
            by_shelf = previous.get("sources_by_shelf", {})
            for previous_source in by_shelf.values():
                if previous_source.get("path") == source_info["path"]:
                    for key in ("sha256", "seed", "selected_n", "selected_uuids"):
                        if previous_source.get(key) != source_info[key]:
                            raise ValueError("같은 파일에서 다른 표본/판본을 기존 실행에 섞을 수 없습니다. 새 tag를 쓰세요.")
            if st["id"] in by_shelf and by_shelf[st["id"]] != source_info:
                raise ValueError("이미 시작한 진열대의 표본 파일/난수/선정 명단이 달라졌습니다. 새 tag를 쓰세요.")
            by_shelf[st["id"]] = source_info
            settings.update(people=a.people, sample_seed=a.sample_seed, named=effective_named, sources_by_shelf=by_shelf)
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")
        done = set()
        if out.exists():
            done = {(r["uuid"], r["rep"]) for r in map(json.loads, out.read_text(encoding="utf-8").splitlines()) if r}
        todo = [(p, k) for p in people for k in range(a.reps) if (p["uuid"], k) not in done]
        groups = []
        for k in range(a.reps):
            left = [p for p, kk in todo if kk == k]
            groups += [(left[i:i + batch], k) for i in range(0, len(left), batch)]
        print(f"[{st['id']}{' 이름공개' if effective_named else ''}] 남은 {len(todo)}명 · 호출 {len(groups)}번 ({model})", flush=True)
        lock = threading.Lock()

        def ask(group, k):
            if a.per_person_order:
                system, user, orders, labels, keys = build_person_order_messages(group, st, a.named)
            else:
                system, user, order, labels, keys = build_messages(group, st, a.named)
                orders = [order for _ in group]
            if any(p["uuid"] in system or p["uuid"] in user for p in group):
                raise ValueError("외부 프롬프트에 UUID가 들어가 전송을 중단합니다")
            ans = llm.ask_json(system, user, schema(labels, keys, OPTS["ask_qty"], a.familiar_incumbents))
            return decode_answers(group, st, orders, labels, keys, ans, model=model,
                                  named=effective_named, rep=k, familiar=a.familiar_incumbents)

        n_done = 0
        with open(out, "a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(ask, g, k): g for g, k in groups}
            for fu in as_completed(futs):
                try:
                    rows = fu.result()
                except Exception as e:
                    print(f"  실패 {futs[fu][0]['uuid'][:8]} 묶음: {str(e)[:300]}", flush=True)
                    failures += len(futs[fu])
                    continue
                with lock:
                    for row in rows:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                n_done += len(rows)
                print(f"  {n_done}/{len(todo)}명", flush=True)
    if not a.dry_run:
        if failures and (a.per_person_order or a.familiar_incumbents or a.people):
            sys.exit(f"새 옵션 실행에서 {failures}명 응답 실패. 부분 결과는 보존했고 성공으로 끝내지 않습니다.")
        print("다음: python3 ssr.py")


if __name__ == "__main__":
    main()
