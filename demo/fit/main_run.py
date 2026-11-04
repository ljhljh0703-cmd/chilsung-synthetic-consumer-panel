"""Run the registered survey after the public preregistration has been verified."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from random import Random
import re
import sqlite3
import sys
from urllib.request import Request, urlopen

from metrics import evaluate
from render import response_concentration, write_report
from providers import SETTINGS, CLI_SETTINGS, Quota, Stop, answer, cli_answer, load_keys, preflight
from survey import (COMBOS, DESIGN_HASH, ORDER_SEED, POPULATION, QUESTION_HASH,
                    ROOT, one, questionnaire, sample)

REPOSITORY = "ljhljh0703-cmd/chilsung-synthetic-consumer-panel"
PUBLIC = f"https://raw.githubusercontent.com/{REPOSITORY}"
OUT = ROOT / "demo/results/FIT"
MAIN_RUN_APPROVED = False  # 18:10 정정 후 총괄 확인 및 별도 실행 승인 대기


def publication(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise Stop("공개 사전 등록 커밋 해시가 필요")
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/commits/{commit}",
                      headers={"Accept":"application/vnd.github+json"})
    try:
        with urlopen(request, timeout=20) as response:
            info = json.load(response)
        if info["sha"] != commit or info["parents"]:
            raise Stop("첫 공개 커밋 판본 불일치")
        for path, expected in (("preregistration-FIT.md", DESIGN_HASH),
                               ("research/fit-questionnaire.md", QUESTION_HASH)):
            with urlopen(f"{PUBLIC}/{commit}/{path}", timeout=20) as response:
                if sha256(response.read()).hexdigest() != expected:
                    raise Stop("공개 문서와 로컬 잠금본 불일치")
    except (OSError, ValueError, KeyError) as error:
        raise Stop(f"비로그인 공개 커밋 검증 실패 ({type(error).__name__})") from None
    return info["commit"]["committer"]["date"]


def digest(path):
    h = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS manifest (signature TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs (combo INT, repeat INT, route TEXT, generation INT,
                                    PRIMARY KEY(combo, repeat));
    CREATE TABLE IF NOT EXISTS responses (combo INT, repeat INT, person INT, answer TEXT,
                                         PRIMARY KEY(combo, repeat, person));
    CREATE TABLE IF NOT EXISTS calls (combo INT, repeat INT, generation INT, route TEXT,
                                      model TEXT, settings TEXT, status TEXT);
    """)


def run(db, people, q, keys):
    live_routes = {}
    def registered_response(combo, repeat, i, route):
        records = []
        def call(model, system, user, keyfile):
            settings = (SETTINGS if route == "api" else CLI_SETTINGS)[model]
            try:
                actual, raw = (answer if route == "api" else cli_answer)(model, system, user, keyfile)
            except Stop as error:
                records.append((None, json.dumps(settings), "quota" if isinstance(error, Quota) else "error"))
                raise
            records.append((actual, json.dumps(settings), "returned"))
            return actual, raw
        try:
            response, _ = one(q, people[i], combo, repeat, i, keys, call=call)
            return response, records, None
        except Stop as error:
            return None, records, error

    for combo, (model, _, _) in COMBOS.items():
        for repeat in range(1, 4):
            existing = db.execute("SELECT route,generation FROM runs WHERE combo=? AND repeat=?",
                                  (combo,repeat)).fetchone()
            if existing is None:
                if model not in live_routes:
                    try:
                        preflight(model, keys)
                        live_routes[model] = "api"
                    except Quota:
                        live_routes[model] = "cli"
                route, generation = live_routes[model], 1
                with db:
                    db.execute("INSERT INTO runs VALUES (?,?,?,?)",(combo,repeat,route,generation))
            else:
                route, generation = existing
                live_routes[model] = route
            order = list(range(300))
            Random(f"{ORDER_SEED}:{repeat}:people").shuffle(order)
            while True:
                done = {i for (i,) in db.execute("SELECT person FROM responses WHERE combo=? AND repeat=?",(combo,repeat))}
                remaining = [i for i in order if i not in done]
                if not remaining:
                    print(f"조합 {combo} 반복 {repeat} 완료 300/300 ({route})",flush=True)
                    break
                failure = None
                width = 4 if route == "api" else 2
                with ThreadPoolExecutor(max_workers=width) as pool:
                    for start in range(0,len(remaining),width):
                        wave = remaining[start:start+width]
                        tasks = [pool.submit(registered_response,combo,repeat,i,route) for i in wave]
                        for i, task in zip(wave,tasks):
                            response, records, error = task.result()
                            with db:
                                db.executemany("INSERT INTO calls VALUES (?,?,?,?,?,?,?)",
                                    [(combo,repeat,generation,route,*row) for row in records])
                                if error is None:
                                    db.execute("INSERT INTO responses VALUES (?,?,?,?)",
                                               (combo,repeat,i,json.dumps(response,ensure_ascii=False)))
                            if error is not None and (failure is None or not isinstance(error, Quota)):
                                failure = error
                        if start == 0 or (start//width) % 10 == 9:
                            n = db.execute("SELECT count(*) FROM responses WHERE combo=? AND repeat=?",(combo,repeat)).fetchone()[0]
                            print(f"조합 {combo} 반복 {repeat} {n}/300 ({route})",flush=True)
                        if failure:
                            break
                if isinstance(failure, Quota) and route == "api":
                    route, generation = "cli", generation+1
                    live_routes[model] = route
                    with db:
                        db.execute("DELETE FROM responses WHERE combo=? AND repeat=?",(combo,repeat))
                        db.execute("UPDATE runs SET route=?,generation=? WHERE combo=? AND repeat=?",
                                   (route,generation,combo,repeat))
                    print(f"조합 {combo} 반복 {repeat} 크레딧 한도, 로그인 경로로 처음부터 재시작",flush=True)
                elif failure:
                    raise failure
    groups = {c:[] for c in COMBOS}
    for combo in COMBOS:
        for repeat in range(1,4):
            groups[combo].append([json.loads(r) for (r,) in db.execute(
                "SELECT answer FROM responses WHERE combo=? AND repeat=? ORDER BY person",(combo,repeat))])
    results = evaluate(people,groups,q["options"])
    routes = dict(db.execute("SELECT route,count(*) FROM calls GROUP BY route").fetchall())
    kept = dict(db.execute("SELECT route,300*count(*) FROM runs GROUP BY route").fetchall())
    destination = OUT / "registered"
    concentrations = {combo: response_concentration(repeats, q["options"]) for combo, repeats in groups.items()}
    write_report(destination,results,concentrations=concentrations)
    with (destination/"report.md").open("a",encoding="utf-8") as f:
        f.write(f"\n## 호출 경로\n\n- 전체 요청 수(재요청 및 전환 전 제외분 포함) {routes}\n"
                f"- 판정 대상 응답 자리 수(형식 제외 전) {kept}\n")
    print(f"완료. 등록 보고서 {destination/'report.md'}",flush=True)


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published-prereg-commit",required=True)
    args = parser.parse_args()
    if not MAIN_RUN_APPROVED:
        raise Stop("18:10 지시: 총괄 확인 및 별도 승인 전 본 실행 금지")
    q = questionnaire()
    date = publication(args.published_prereg_commit)
    print(f"공개 사전 등록 확인 {args.published_prereg_commit} / {date}",flush=True)
    keys = load_keys()
    os.umask(0o077)
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise Stop("이미 본 실행이 진행 중") from None
        if (OUT/"registered/report.md").exists():
            raise Stop("등록 보고서가 이미 존재")
        signature = json.dumps({"commit":args.published_prereg_commit, "published_commit_at":date,
                                "population":digest(POPULATION),
                                "code":{name:digest(Path(__file__).with_name(name)) for name in
                                        ("main_run.py","survey.py","providers.py","metrics.py","render.py")}},
                               sort_keys=True)
        people = sample()
        with closing(sqlite3.connect(OUT/".checkpoint.sqlite3")) as db:
            schema(db)
            old = db.execute("SELECT signature FROM manifest").fetchone()
            if old is not None and old[0] != signature:
                raise Stop("재개 입력 또는 코드가 이전 실행과 다름")
            if old is None:
                with db:
                    db.execute("INSERT INTO manifest VALUES (?)",(signature,))
            print(f"본 실행 시작 {datetime.now(timezone.utc).isoformat()} · 15회 / 4,500건",flush=True)
            run(db,people,q,keys)


if __name__ == "__main__":
    try:
        main()
    except Stop as error:
        print(str(error),file=sys.stderr,flush=True)
        sys.exit(1)
