import os, glob, re, statistics
from collections import defaultdict
from scipy.stats import mannwhitneyu

def parse_run(path):
    name = os.path.basename(path)
    m = re.match(r'local_(\d+h)_(.+?)_(llm|baseline)_t(\d+)_\d+_\d+', name)
    if not m: return None
    _, target, arm, _ = m.groups()
    pd = os.path.join(path, 'afl', 'i2c', 'default', 'plot_data')
    fs = os.path.join(path, 'afl', 'i2c', 'default', 'fuzzer_stats')
    if not (os.path.exists(pd) and os.path.exists(fs)): return None
    e2h = e8h = None
    with open(pd) as f:
        next(f, None)
        for line in f:
            parts = line.strip().split(',')
            if len(parts) < 13: continue
            try:
                t = int(parts[0]); e = int(parts[12])
                if t >= 7200 and e2h is None: e2h = e
                if t >= 28800 and e8h is None: e8h = e
            except: continue
    with open(fs) as f:
        rt = next((int(l.split(':',1)[1].strip()) for l in f if l.startswith('run_time')), 0)
    return {'target': target, 'arm': arm, 'run_time': rt, 'e2h': e2h, 'e8h': e8h}

runs = [r for r in (parse_run(p) for p in sorted(glob.glob('results/local_*h_*'))) if r]
print(f"=== SoK comparison at t=7200s (2h budget) ===")
b = defaultdict(list)
for r in runs:
    if r['e2h'] is not None and r['run_time'] >= 7000:
        b[(r['target'], r['arm'])].append(r['e2h'])
print(f"{'target':<32}  {'arm':<10}  {'N':>3}  edges@2h  range")
print("-"*78)
for (t,a) in sorted(b.keys()):
    e = b[(t,a)]; m = statistics.mean(e); s = statistics.stdev(e) if len(e)>1 else 0
    print(f"{t:<32}  {a:<10}  {len(e):>3}  {m:6.1f}+/-{s:4.1f}  [{min(e)}..{max(e)}]")

def a12(x,y):
    g=sum(1 for a in x for b in y if a>b); eq=sum(1 for a in x for b in y if a==b)
    return (g+0.5*eq)/(len(x)*len(y))
def lab(a):
    d=abs(a-0.5); return "LARGE" if d>=0.21 else "medium" if d>=0.14 else "small" if d>=0.06 else "negligible"

print(f"\n=== MWU + A12 at t=7200s ===")
for tgt in sorted(set(t for (t,a) in b.keys())):
    L = b.get((tgt,'llm'),[]); B = b.get((tgt,'baseline'),[])
    if not (L and B): continue
    u,p = mannwhitneyu(L, B, alternative='two-sided')
    A = a12(L,B)
    print(f"{tgt}: LLM N={len(L)} mu={statistics.mean(L):.1f}  base N={len(B)} mu={statistics.mean(B):.1f}  U={u:.0f} p={p:.4g} A12={A:.3f} ({lab(A)})")

print(f"\n=== 8h saturation snapshot (point estimates) ===")
b8 = defaultdict(list)
for r in runs:
    if r['e8h'] is not None and r['run_time'] >= 28000:
        b8[(r['target'], r['arm'])].append(r['e8h'])
for (t,a) in sorted(b8.keys()):
    e = b8[(t,a)]; m = statistics.mean(e); s = statistics.stdev(e) if len(e)>1 else 0
    print(f"  {t:<32}  {a:<10}  N={len(e):>2}  edges={m:6.1f}+/-{s:4.1f}  [{min(e)}..{max(e)}]")
