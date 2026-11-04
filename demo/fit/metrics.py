"""Offline preregistered FIT analysis. Does not call providers."""
from collections import defaultdict
from math import sqrt
from statistics import fmean, correlation, StatisticsError

V1 = {"남자": 68.2, "여자": 51.4, "전체": 59.7}
V2 = dict(zip(("남자 19~39", "남자 40~59", "남자 60+", "여자 19~39", "여자 40~59", "여자 60+", "전체"),
              (47.8, 54.6, 34.4, 37.4, 21.7, 7.0, 37.8)))
V3 = dict(zip(("맥주", "소주", "탁주(막걸리)", "과실주(와인 등)", "청주", "위스키", "약주",
               "리큐르", "일반증류주(증류식 소주 등)", "브랜디"),
              (94.6, 77.1, 52.3, 31.5, 21.7, 21.4, 14.3, 13.2, 11.9, 9.8)))
EARLY = {"innovator", "early_adopter"}
LATE = {"late_majority", "laggard"}
H4 = ("위스키", "리큐르", "과실주(와인 등)")
AGES = ("19~39", "40~59", "60+")


def band(age):
    return AGES[0 if age < 40 else 1 if age < 60 else 2]


def wilson(pct, n):
    p, z = pct / 100, 1.959963984540054
    d = 1 + z*z/n
    center = (p + z*z/(2*n)) / d
    radius = z*sqrt((p*(1-p) + z*z/(4*n))/n) / d
    return [100*max(0, center-radius), 100*min(1, center+radius)]


def estimate(samples):
    # People are reused across repeats; never pretend the denominator triples.
    if any(not group for group in samples):
        return None
    rates = [100*fmean(group) for group in samples]
    n = [len(group) for group in samples]
    avg = fmean(rates)
    return {"pct": avg, "repeat_pct": rates, "range_pct": [min(rates), max(rates)],
            "n_by_repeat": n, "ci95_pct": wilson(avg, min(n))}


def difference(a, b):
    if a is None or b is None:
        return None
    p, q = a["pct"], b["pct"]
    al, au = a["ci95_pct"]
    bl, bu = b["ci95_pct"]
    reps = [x-y for x,y in zip(a["repeat_pct"], b["repeat_pct"])]
    return {"diff_pp": p-q, "repeat_pp": reps, "range_pp": [min(reps), max(reps)],
            "ci95_pp": [p-q-sqrt((p-al)**2+(bu-q)**2), p-q+sqrt((au-p)**2+(q-bl)**2)],
            "early": a, "late": b}


def ranks(values):
    groups = defaultdict(list)
    for i, val in enumerate(values):
        groups[val].append(i)
    ordered, start = [0]*len(values), 1
    for val in sorted(groups):
        group = groups[val]
        end = start+len(group)-1
        for i in group:
            ordered[i] = (start+end)/2
        start = end+1
    return ordered


def rho(a, b):
    try:
        return correlation(ranks(a), ranks(b))
    except StatisticsError:
        return None


def compare(cells, targets):
    if any(cells[k] is None for k in targets):
        return None
    actual = {k: cells[k]["pct"] for k in targets}
    errors = [abs(actual[k]-v) for k,v in targets.items()]
    repeat_mae = [fmean(abs(cells[k]["repeat_pct"][i]-v) for k,v in targets.items()) for i in range(3)]
    r = rho(list(actual.values()), list(targets.values())) if len(targets)>1 else None
    top = sorted(actual, key=actual.get, reverse=True)
    top2 = len(top)>2 and set(top[:2]) == {"맥주", "소주"} and actual[top[1]] > actual[top[2]]
    # Bounds obtained by mapping the pointwise rate intervals through absolute errors.
    bounds = []
    for k,v in targets.items():
        lo, hi = cells[k]["ci95_pct"]
        bounds.append((0 if lo<=v<=hi else min(abs(lo-v),abs(hi-v)), max(abs(lo-v),abs(hi-v))))
    return {"cells": {k: {**cells[k], "reference_pct": v, "diff_pp": actual[k]-v,
                          "diff_ci95_pp": [x-v for x in cells[k]["ci95_pct"]]} for k,v in targets.items()},
            "mae_pp": fmean(errors), "mae_repeat_pp": repeat_mae,
            "mae_range_pp": [min(repeat_mae),max(repeat_mae)],
            "mae_pointwise_bounds_pp": [fmean(x[i] for x in bounds) for i in (0,1)],
            "max_abs_pp": max(errors), "rho": r,
            "rho_by_repeat": [rho([cells[k]["repeat_pct"][i] for k in targets],list(targets.values()))
                              for i in range(3)] if len(targets)>1 else None, "top_two_match": top2}


def verdict(series, number):
    if series is None:
        return None
    if number == 1:
        return series["max_abs_pp"] <= 10
    return (series["rho"] is not None and series["rho"] >= .8
            and series["mae_pp"] <= 10 and (number != 3 or series["top_two_match"]))


def evaluate(people, groups, options):
    """groups[combo][repeat][person index] = parsed response or None.

    Each row is aligned to the same weighted sample, independent of presentation
    order. Excluded respondents are never counted as non-drinkers.
    """
    n = len(people)
    if n != 300 or set(groups) != set(range(1,6)) or any(len(reps)!=3 or
          any(len(rep)!=n for rep in reps) for reps in groups.values()):
        raise ValueError("같은 표본 300명 × 5조합 × 3회 필요")
    out, segment = {}, {}
    for c, reps in groups.items():
        excluded = [sum(a is None for a in rep) for rep in reps]
        out[c] = {"excluded_by_repeat": excluded, "excluded_rate": sum(excluded)/(3*n),
                  "status": "hold" if sum(excluded)>.05*3*n else "eligible"}
        if out[c]["status"] == "hold":
            continue
        paired = [[(p,a) for p,a in zip(people,rep) if a is not None] for rep in reps]
        def rate(eligible, outcome):
            return estimate([[outcome(a) for p,a in rep if eligible(p,a)] for rep in paired])
        v1 = {k: rate(lambda p,a: k=="전체" or p["sex"]==k,
                       lambda a: options["v1"].index(a["v1"])>=2) for k in V1 if c!=1 or k=="전체"}
        v2 = {k: rate(lambda p,a: k=="전체" or f'{p["sex"]} {band(p["age"])}'==k,
                       lambda a: options["v2"].index(a["v2"])>=2) for k in V2 if c!=1 or k=="전체"}
        v3 = {k: rate(lambda p,a: a["v3_drank"], lambda a: k in a["v3"]) for k in V3}
        metrics = [compare(cells,{k: targets[k] for k in cells if k!="전체" or c==1})
                   for cells,targets in zip((v1,v2,v3),(V1,V2,V3))]
        out[c]["metrics"] = metrics
        out[c]["auxiliary_mean_cups_by_repeat"] = {
            k: [fmean(vals) if (vals := [a[k] for _,a in rep if a[k] is not None]) else None for rep in paired]
            for k in ("soju_cups","beer_cups")}
        if c>=3:
            detail = [verdict(x,i) for i,x in enumerate(metrics,1)]
            out[c]["rq1_by_source"] = detail
            out[c]["rq1"] = None if None in detail else all(detail)
        if c==3:
            for age in ("전체", *AGES):
                for drink in H4:
                    def in_seg(seg):
                        return rate(lambda p,a: p["adopter"] in seg and a["v3_drank"] and
                                    (age=="전체" or band(p["age"])==age), lambda a: drink in a["v3"])
                    segment[(age,drink)] = difference(in_seg(EARLY),in_seg(LATE))
    # "같은 조건의 흔들림": use the larger observed MAE range of the two compared conditions.
    rq2 = []
    for i in range(3):
        vals = [out[c].get("metrics",[None]*3)[i] for c in (1,2,3)]
        base, demo, full = vals
        if base is None or full is None:
            rq2.append(None)
            continue
        improvement = base["mae_pp"] - full["mae_pp"]
        noise = max(max(x["mae_repeat_pp"])-min(x["mae_repeat_pp"]) for x in (base,full))
        rq2.append({"supported": improvement>noise, "improvement_pp": improvement, "noise_pp": noise,
                    "monotonic": None if demo is None else base["mae_pp"]>demo["mae_pp"]>full["mae_pp"]})
    possible = sum(x is not None and x["supported"] for x in rq2)
    rq2_all = True if possible>=2 else (False if possible+rq2.count(None)<2 else None)
    verdicts = [out[c].get("rq1") for c in (3,4,5)]
    rq3 = None if None in verdicts else len(set(verdicts))==1
    h4 = {}
    for drink in H4:
        item = segment.get(("전체",drink))
        h4[drink] = None if item is None else item["diff_pp"]>max(item["repeat_pp"])-min(item["repeat_pp"])
    return {"combos": out, "rq1": out[3].get("rq1"), "rq2": rq2_all, "rq2_by_source": rq2,
            "rq3": rq3, "h4": None if None in h4.values() else all(h4.values()), "h4_by_drink": h4,
            "h4_table": [{"age":a,"drink":d,"estimate":x} for (a,d),x in segment.items()]}
