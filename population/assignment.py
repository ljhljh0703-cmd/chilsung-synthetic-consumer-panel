"""Deterministic score/rank allocation. No keyword research coefficients are reused as weights."""
from collections import defaultdict
import math
from traits import TYPES

def quotas(n,ratios):
    q={k:int(n*ratios[k]) for k in TYPES}
    for k in sorted(TYPES,key=lambda k:(-(n*ratios[k]-q[k]),TYPES.index(k)))[:n-sum(q.values())]:q[k]+=1
    return q

def adjusted_order(records,age_tilt,within_sex=False):
    if within_sex and age_tilt < 1:
        # Keep the two controls orthogonal: neutralize age within each sex.
        combined=[];scores={}
        for sex in sorted({r[4] for r in records}):
            ordered,part=adjusted_order([r for r in records if r[4]==sex],age_tilt)
            combined.extend(ordered);scores.update(part)
        return sorted(combined,key=lambda x:(-scores[x[2]],x[1])),scores
    # record = (raw_score, tie_hash, uuid, age, sex). Equal-score ties fixed by seed hash.
    ordered=sorted(records,key=lambda x:(-x[0],x[1]));n=len(ordered)
    global_ranks={r[2]:1-i/max(1,n-1) for i,r in enumerate(ordered)}
    groups=defaultdict(list)
    for r in ordered:groups[r[3]//10].append(r)
    scores={}
    for group in groups.values():
        for i,r in enumerate(group):
            within=1-i/max(1,len(group)-1)
            scores[r[2]]=age_tilt*global_ranks[r[2]]+(1-age_tilt)*within
    return sorted(ordered,key=lambda x:(-scores[x[2]],x[1])),scores

def assign(ordered,ratios):
    q=quotas(len(ordered),ratios);result={};start=0
    for t in TYPES:
        for r in ordered[start:start+q[t]]:result[r[2]]=t
        start+=q[t]
    return result

def correlation(xs,ys):
    n=len(xs)
    if n<2:return None
    mx=sum(xs)/n;my=sum(ys)/n
    xx=sum((x-mx)**2 for x in xs);yy=sum((y-my)**2 for y in ys)
    return sum((x-mx)*(y-my) for x,y in zip(xs,ys))/math.sqrt(xx*yy) if xx and yy else None
