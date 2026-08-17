#!/usr/bin/env python3
"""One-shot aggregator to verify Table 6.6 gcov N's against committed data."""
import json
from pathlib import Path
from collections import defaultdict

root = Path("${REPO_ROOT}/results")
groups = defaultdict(list)

for fp in root.glob("*/reports/native_coverage.json"):
    rid = fp.parent.parent.name
    # Identify target + arm from run-id pattern
    target = None
    if "infineon-dc-optimizer" in rid:
        target = "DC"
    elif "libresolar-bms" in rid:
        target = "BMS"
    elif "libresolar-charge-controller" in rid:
        target = "CC"
    arm = "baseline" if "baseline" in rid else ("llm" if "llm" in rid else None)
    if target is None or arm is None:
        continue
    # Skip smoke / iter runs
    if "smoke" in rid or "iter" in rid or "loop_" in rid or "_llm_smoke" in rid:
        continue
    try:
        d = json.loads(fp.read_text())
    except Exception:
        continue
    # gcovr JSON has line_percent / branch_percent
    line_pct = d.get("line_percent") or d.get("lines_percent")
    branch_pct = d.get("branch_percent") or d.get("branches_percent")
    if line_pct is None:
        # try nested
        line_pct = d.get("lines", {}).get("percent") if isinstance(d.get("lines"), dict) else None
    groups[(target, arm)].append((rid, line_pct, branch_pct))

print(f"{'target':6} {'arm':10} {'N':>3}   line%(mean±sd)        branch%(mean±sd)")
print("-" * 78)
for (t, a), items in sorted(groups.items()):
    items_valid = [(rid, l, b) for rid, l, b in items if l is not None]
    n = len(items_valid)
    if n == 0:
        print(f"{t:6} {a:10} {n:>3}   (no valid line% values)")
        continue
    lines = [l for _, l, _ in items_valid]
    branches = [b for _, _, b in items_valid if b is not None]
    import statistics
    lm = statistics.mean(lines)
    ls = statistics.stdev(lines) if n > 1 else 0
    bm = statistics.mean(branches) if branches else 0
    bs = statistics.stdev(branches) if len(branches) > 1 else 0
    print(f"{t:6} {a:10} {n:>3}   {lm:5.1f} ± {ls:4.1f}            {bm:5.1f} ± {bs:4.1f}")
