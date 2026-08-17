#!/usr/bin/env python3
"""Inventory clean thesis trials per (target, arm). Run from repo root."""
import glob
import os
import re
from statistics import mean, stdev

roots = sorted(glob.glob("results/thesis_*"))
buckets = {}
all_rows = []

for r in roots:
    name = os.path.basename(r)
    m = re.match(r"thesis_(.+?)_(llm|baseline)_", name)
    if not m:
        continue
    tgt, arm = m.group(1), m.group(2)
    hits = glob.glob(os.path.join(r, "afl", "*", "*", "fuzzer_stats"))
    if not hits:
        hits = glob.glob(os.path.join(r, "afl", "*", "fuzzer_stats"))
    if not hits:
        all_rows.append((tgt, arm, None, None, name, "no_stats"))
        continue
    stats = {}
    try:
        with open(hits[0]) as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    stats[k.strip()] = v.strip()
        rt = int(stats.get("run_time", "0").split()[0])
        ed = int(stats.get("edges_found", "0").split()[0])
    except Exception as e:
        all_rows.append((tgt, arm, None, None, name, f"parse_err:{e}"))
        continue
    status = "clean" if rt >= 7000 else "short"
    all_rows.append((tgt, arm, ed, rt, name, status))
    if rt >= 7000:
        buckets.setdefault((tgt, arm), []).append(ed)

print("=" * 88)
print("CLEAN-TRIAL SUMMARY (run_time >= 7000s)")
print("=" * 88)
for (tgt, arm), edges in sorted(buckets.items()):
    m_v = mean(edges)
    s_v = stdev(edges) if len(edges) > 1 else 0.0
    print(f"  {tgt:32s} {arm:9s} N={len(edges):2d}  "
          f"mean={m_v:6.1f} +/- {s_v:4.1f}  edges={sorted(edges)}")

print()
print("=" * 88)
print("ALL TRIALS (incl. short/no-stats) per target/arm")
print("=" * 88)
# Sort with safe key: None values go to the end without breaking comparison.
all_rows.sort(key=lambda r: (r[0] or "", r[1] or "", r[2] or 0, r[3] or 0, r[4] or ""))
for tgt, arm, ed, rt, name, status in all_rows:
    print(f"  {tgt:32s} {arm:9s} {status:9s} edges={str(ed):5s} run={str(rt):6s}s  {name}")
