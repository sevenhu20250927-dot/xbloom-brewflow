"""Offline paired normalized extraction, v0.1. No transport, no fitted defaults.

Run from testCoffee: PYTHONPATH=. python3 -B <this.py> V60.jsonl Origami.jsonl output.json
Output is exclusive-create; source files are read-only. See adjacent model document.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path

from xbloom_bridge.report import build_report

VERSION = "0.1"
TAUS = (5.0, 15.0, 45.0, 150.0, 450.0)
CAPACITY_RATIOS = (0.1, 1.0, 10.0)


class Series:
    def __init__(self, pairs):
        if len(pairs) < 2:
            raise ValueError("insufficient series")
        self.t, self.v = zip(*pairs)
        if any(not math.isfinite(x) for x in self.t + self.v):
            raise ValueError("nonfinite series")
        if any(not 0 < b-a <= 1 for a, b in zip(self.t, self.t[1:])):
            raise ValueError("nonpositive interval or gap > 1s")

    def at(self, t, hold=False):
        i = bisect_right(self.t, t)-1
        if i < 0:
            raise ValueError("left extrapolation")
        if i == len(self.t)-1:
            if hold or abs(t-self.t[-1]) < 1e-8:
                return self.v[-1]
            raise ValueError("right extrapolation")
        f = (t-self.t[i])/(self.t[i+1]-self.t[i])
        return self.v[i] + f*(self.v[i+1]-self.v[i])


def prepare(path):
    d = build_report(path)
    if d['recipe'].get('doseGrams', 0) <= 0 or not d['coffee'] or not d['water']:
        raise ValueError("dose or telemetry missing")
    if d['status'] in ('异常记录', '记录不完整'):
        raise ValueError("incomplete or interrupted source")
    if any(b[1] < a[1] for a,b in zip(d['water'],d['water'][1:])):
        raise ValueError("water counter regression")
    corrected, changes = [], []
    peak = 0.0
    for t,v in d['coffee']:
        peak = max(peak,v)
        corrected.append((t,peak))
        if peak > v:
            changes.append(peak-v)
    w,y = Series(d['water']),Series(corrected)
    meta = {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'recipe_sha256':d['session'].get('recipe_sha256'),
            'dose_g':d['recipe']['doseGrams'],'original_warnings':d['warnings'],
            'water_peak':w.v[-1],'last_raw_beverage_g':d['coffee'][-1][1],
            'last_model_beverage_g':y.v[-1],'end_s':y.t[-1],
            'monotone_correction_count':len(changes),
            'max_monotone_correction_g':max(changes,default=0)}
    return w,y,meta,d['recipe']


def hydraulics(w,y,start,end,max_step):
    knots=sorted({start,end,*[t for t in w.t+y.t if start<t<end]})
    cells=[]
    for left,right in zip(knots,knots[1:]):
        n=math.ceil((right-left)/max_step)
        dt=(right-left)/n
        for i in range(n):
            a=left+i*dt; b=left+(i+1)*dt; mid=(a+b)/2
            h=w.at(mid,True)-y.at(mid)
            q=(y.at(b)-y.at(a))/dt
            if h < -1e-7 or q < -1e-7:
                raise ValueError("negative liquid or outflow")
            if h <= 1e-12:
                if q > 1e-9:
                    raise ValueError("outflow without liquid")
                cells.append((dt,None,0.0))
            else:
                cells.append((dt,1/h,max(q,0.0)/h))
    return cells


def exchange(s,l,a,b,dt):
    total=s+l
    equilibrium_s=b/(a+b)*total
    s=equilibrium_s+(s-equilibrium_s)*math.exp(-(a+b)*dt)
    return s,total-s


def simulate(cells,tau,capacity,initial=1.0):
    s,l,e=initial,0.0,0.0
    max_error=0.0;minimum=0.0
    for dt,inv_h,out_rate in cells:
        if inv_h is None:
            continue
        a=1/tau; b=capacity*inv_h/tau
        s,l=exchange(s,l,a,b,dt/2)
        drained=l*(-math.expm1(-out_rate*dt))
        l-=drained; e+=drained
        s,l=exchange(s,l,a,b,dt/2)
        max_error=max(max_error,abs(s+l+e-initial))
        minimum=min(minimum,s,l,e)
    if max_error > initial*1e-9 or minimum < -initial*1e-12:
        raise ArithmeticError("mass conservation or positivity failure")
    return {'solid_remaining':s,'liquid_solute':l,'cup_solute':e,
            'net_released':initial-s,'mass_error':max_error,'minimum':minimum}


def relative(a,b):
    if a <= 1e-12:
        raise ValueError("relative denominator too small")
    return 100*(b/a-1)


def run(v60,origami):
    p=[prepare(v60),prepare(origami)]
    if p[0][3] != p[1][3]:
        raise ValueError("v0.1 paired run requires identical recipe and dose")
    start=max(s.t[0] for w,y,_,_ in p for s in (w,y))
    common_end=min(x[1].t[-1] for x in p)
    cases=[]; accuracy=[]; linearity=[]
    for window in ('common_observed','individual_record_end'):
        ends=[common_end,common_end] if window=='common_observed' else [x[1].t[-1] for x in p]
        grids={step:[hydraulics(x[0],x[1],start,end,step) for x,end in zip(p,ends)]
               for step in (0.1,0.05)}
        for tau in TAUS:
            for ratio in CAPACITY_RATIOS:
                cap=ratio*p[0][2]['dose_g']
                simulations={step:[simulate(c,tau,cap) for c in cells] for step,cells in grids.items()}
                a,b=simulations[0.05]
                cup=relative(a['cup_solute'],b['cup_solute'])
                released=relative(a['net_released'],b['net_released'])
                coarse=simulations[0.1]
                err=max(abs(cup-relative(coarse[0]['cup_solute'],coarse[1]['cup_solute'])),
                        abs(released-relative(coarse[0]['net_released'],coarse[1]['net_released'])))
                accuracy.append(err)
                doubled=[simulate(c,tau,cap,2.0) for c in grids[0.05]]
                linearity.append(abs(cup-relative(doubled[0]['cup_solute'],doubled[1]['cup_solute'])))
                cases.append({'window':window,'start_s':start,'ends_s':ends,'tau_s':tau,'capacity_g':cap,
                              'capacity_per_dose':ratio,'V60':a,'Origami':b,
                              'relative_cup_pct':cup,'relative_net_released_pct':released,
                              'relative_model_concentration_pct':relative(a['cup_solute']/p[0][1].at(ends[0]),
                                                                          b['cup_solute']/p[1][1].at(ends[1])),
                              'step_halving_max_delta_percentage_points':err})
    same=simulate(hydraulics(p[0][0],p[0][1],start,common_end,0.05),45.0,15.0)
    repeated=simulate(hydraulics(p[0][0],p[0][1],start,common_end,0.05),45.0,15.0)
    checks={'same_input_relative_cup_pct':relative(same['cup_solute'],repeated['cup_solute']),
            'shared_amplitude_scaling_max_delta_percentage_points':max(linearity),
            'step_halving_max_delta_percentage_points':max(accuracy),
            'max_conservation_error':max(c[n]['mass_error'] for c in cases for n in ('V60','Origami')),
            'minimum_state':min(c[n]['minimum'] for c in cases for n in ('V60','Origami'))}
    if max(accuracy)>0.05 or max(linearity)>1e-8 or checks['same_input_relative_cup_pct']!=0:
        raise ArithmeticError(f"numerical check failed: {checks}")
    return {'model_version':VERSION,'model_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'status':'exploratory_uncalibrated_not_measured_EY',
            'parameters_are':'prespecified illustrative grid, not physical confidence bounds',
            'inputs':dict(zip(('V60','Origami'),[x[2] for x in p])),
            'numerical_checks':checks,'cases':cases}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('v60',type=Path);parser.add_argument('origami',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result=run(args.v60,args.origami)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')
    print(json.dumps({'output':str(args.output),'numerical_checks':result['numerical_checks'],
                      'cases':len(result['cases'])},ensure_ascii=False))
