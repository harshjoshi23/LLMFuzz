import os, glob, re, statistics
from collections import defaultdict
from scipy.stats import mannwhitneyu

def parse_run(path):
    name = os.path.basename(path)
    m = re.match(r'local_(\d+h)_(.+?)_(llm|baseline)_t(\d+)_(\d{8})_(\d{6})', name)
    if not m: return None
    _, target, arm, trial, date, time = m.groups()
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
    return {'target': target, 'arm': arm, 'ts': f'{date}_{time}', 'run_time': rt, 'e2h': e2h, 'e8h': e8h}

runs = [r for r in (parse_run(p) for p in sorted(glob.glob('results/local_*h_*'))) if r]

# Take the LAST 5 trials per (target, arm) by timestamp, restricted to ones that ran >= 7200s
b = defaultdict(list)
for r in sorted(runs, key=lambda x: x['ts']):
    if r['e2h'] is not None and r['run_time'] >= 7000:
        b[(r['target'], r['arm'])].append(r)

print("=== LAST 5 TRIALS per (target, arm) at t=7200s ===\n")
print(f"{'target':<32}  {'arm':<10}  {'N':>3}  edges@2h            range")
print("-" * 78)
trimmed = {}
for (t,a) in sorted(b.keys()):
    last5 = b[(t,a)][-5:]
    trimmed[(t,a)] = [r['e2h'] for r in last5]
    e = trimmed[(t,a)]
    m = statistics.mean(e); s = statistics.stdev(e) if len(e)>1 else 0
    print(f"{t:<32}  {a:<10}  {len(e):>3}  {m:6.1f}+/-{s:4.1f}  [{min(e)}..{max(e)}]")

def a12(x,y):
    g=sum(1 for a in x for b in y if a>b); eq=sum(1 for a in x for b in y if a==b)
    return (g+0.5*eq)/(len(x)*len(y))
def lab(a):
    d=abs(a-0.5); return "LARGE" if d>=0.21 else "medium" if d>=0.14 else "small" if d>=0.06 else "negligible"

print(f"\n=== MWU + A12 on LAST 5 trials per arm at t=7200s ===")
for tgt in sorted(set(t for (t,a) in trimmed.keys())):
    L = trimmed.get((tgt,'llm'),[]); B = trimmed.get((tgt,'baseline'),[])
    if not (L and B): continue
    u,p = mannwhitneyu(L, B, alternative='two-sided')
    A = a12(L,B)
    print(f"  {tgt}:")
    print(f"    LLM  N={len(L)} mu={statistics.mean(L):6.1f}  median={statistics.median(L):6.1f}")
    print(f"    base N={len(B)} mu={statistics.mean(B):6.1f}  median={statistics.median(B):6.1f}")
    print(f"    MWU U={u:.0f} p={p:.4g}  A12={A:.3f} ({lab(A)})\n")
