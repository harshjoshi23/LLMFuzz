"""Time-to-Coverage milestones, computed from plot_data for every trial.
Reports time to reach 50/100/150/200 edges for each (target, arm)."""
import os, glob, re, statistics
from collections import defaultdict

def ttc(path, thresholds=(50, 100, 150, 200)):
    pd = os.path.join(path, 'afl', 'i2c', 'default', 'plot_data')
    if not os.path.exists(pd): return None
    rows = []
    with open(pd) as f:
        next(f, None)
        for line in f:
            parts = line.strip().split(',')
            if len(parts) < 13: continue
            try:
                t = int(parts[0]); e = int(parts[12])
                rows.append((t, e))
            except: continue
    if not rows: return None
    out = {}
    for thr in thresholds:
        hit = next((t for t,e in rows if e >= thr), None)
        out[thr] = hit
    out['final_edges'] = rows[-1][1]
    out['final_time']  = rows[-1][0]
    out['first_sample_t'] = rows[0][0]
    out['first_sample_edges'] = rows[0][1]
    return out

def parse_meta(path):
    name = os.path.basename(path)
    m = re.match(r'local_(\d+h)_(.+?)_(llm|baseline)_t(\d+)_\d+_\d+', name)
    return m.groups() if m else None

bucket = defaultdict(list)
for p in sorted(glob.glob('results/local_*h_*')):
    meta = parse_meta(p)
    t = ttc(p)
    if meta and t and t['final_time'] >= 7000:
        budget, target, arm, trial = meta
        bucket[(target, arm)].append(t)

print("=== TIME-TO-COVERAGE MILESTONES — median seconds to reach N edges ===\n")
print(f"{'target':<32}  {'arm':<10}  {'N':>3}  {'first(t,e)':<14}  {'t≥50':>6}  {'t≥100':>6}  {'t≥150':>6}  {'t≥200':>6}")
print('-' * 105)
for (t, a) in sorted(bucket.keys()):
    rs = bucket[(t,a)]
    def med(field):
        vals = [r[field] for r in rs if r[field] is not None]
        return f"{int(statistics.median(vals)):>5}s" if vals else "  n/a "
    fs_t = statistics.median([r['first_sample_t'] for r in rs])
    fs_e = statistics.median([r['first_sample_edges'] for r in rs])
    print(f"{t:<32}  {a:<10}  {len(rs):>3}  ({int(fs_t)}s, {int(fs_e)}e)  {med(50):>6}  {med(100):>6}  {med(150):>6}  {med(200):>6}")

print("\n=== First-sample edges (the 'one-minute' headline) ===")
for (t, a) in sorted(bucket.keys()):
    rs = bucket[(t,a)]
    fs = [r['first_sample_edges'] for r in rs]
    print(f"  {t:<32}  {a:<10}  N={len(fs):>2}  first-sample edges μ={statistics.mean(fs):6.1f}  median={statistics.median(fs):6.1f}  [{min(fs)}..{max(fs)}]")
