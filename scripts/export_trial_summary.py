#!/usr/bin/env python3
"""Export a tiny per-trial CSV from results/{thesis,local,vm_sok}_*.

Designed to be run on every host (local laptop + Infineon VM). The CSV is
small enough to git-push (< 50 KB) so we never have to scp gigabyte tarballs
of AFL queues around.

Output: artifacts/trial_summary_<hostname>_<YYYYMMDD>.csv

Columns:
    host, src, duration_h, target, arm, trial, edges, run_time_s,
    paths_total, crashes_saved, hangs_saved, last_path_s, dir
"""
from __future__ import annotations
import csv
import glob
import os
import re
import socket
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
OUT_DIR = os.path.join(ROOT, "artifacts")
os.makedirs(OUT_DIR, exist_ok=True)

HOST = socket.gethostname()
TODAY = datetime.now().strftime("%Y%m%d")
OUT_CSV = os.path.join(OUT_DIR, f"trial_summary_{HOST}_{TODAY}.csv")

# Patterns we accept:
#   thesis_<target>_<arm>_t<n>_<ts>
#   local_<dur>h_<target>_<arm>_t<n>_<ts>
#   vm_sok_<dur>h_<target>_<arm>_t<n>_<ts>
PAT = re.compile(
    r"^(?P<src>thesis|local|vm_sok)_"
    r"(?:(?P<dur>\d+)h_)?"
    r"(?P<target>[A-Za-z0-9\-]+)_"
    r"(?P<arm>llm|baseline)_"
    r"t(?P<trial>\d+)_"
    r"(?P<ts>\d{8}_\d{6})$"
)


def parse_fuzzer_stats(path: str) -> dict:
    out: dict = {}
    try:
        with open(path) as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    out[k.strip()] = v.strip()
    except Exception as e:
        out["__error__"] = str(e)
    return out


def first_int(s: str) -> int | None:
    if not s:
        return None
    try:
        return int(s.split()[0])
    except (ValueError, IndexError):
        return None


def scan_one(d: str) -> dict | None:
    name = os.path.basename(d)
    m = PAT.match(name)
    if not m:
        return None
    # Locate fuzzer_stats (may be nested afl/<inst>/<sub>/fuzzer_stats)
    hits = glob.glob(os.path.join(d, "afl", "*", "*", "fuzzer_stats"))
    if not hits:
        hits = glob.glob(os.path.join(d, "afl", "*", "fuzzer_stats"))
    if not hits:
        return {
            "host": HOST,
            "src": m.group("src"),
            "duration_h": m.group("dur") or "",
            "target": m.group("target"),
            "arm": m.group("arm"),
            "trial": m.group("trial"),
            "edges": "",
            "run_time_s": "",
            "paths_total": "",
            "crashes_saved": "",
            "hangs_saved": "",
            "last_path_s": "",
            "dir": name,
            "status": "no_stats",
        }
    stats = parse_fuzzer_stats(hits[0])
    if "__error__" in stats:
        return {
            "host": HOST,
            "src": m.group("src"),
            "duration_h": m.group("dur") or "",
            "target": m.group("target"),
            "arm": m.group("arm"),
            "trial": m.group("trial"),
            "edges": "",
            "run_time_s": "",
            "paths_total": "",
            "crashes_saved": "",
            "hangs_saved": "",
            "last_path_s": "",
            "dir": name,
            "status": f"parse_err:{stats['__error__'][:40]}",
        }
    rt = first_int(stats.get("run_time", "0"))
    return {
        "host": HOST,
        "src": m.group("src"),
        "duration_h": m.group("dur") or "",
        "target": m.group("target"),
        "arm": m.group("arm"),
        "trial": m.group("trial"),
        "edges": first_int(stats.get("edges_found", "0")) or 0,
        "run_time_s": rt or 0,
        "paths_total": first_int(stats.get("paths_total", "0")) or 0,
        "crashes_saved": first_int(stats.get("saved_crashes",
                                              stats.get("unique_crashes", "0"))) or 0,
        "hangs_saved": first_int(stats.get("saved_hangs",
                                            stats.get("unique_hangs", "0"))) or 0,
        "last_path_s": first_int(stats.get("last_find", "0")) or 0,
        "dir": name,
        "status": "ok" if (rt or 0) > 0 else "started",
    }


def main() -> int:
    dirs = sorted(
        d for d in glob.glob(os.path.join(RESULTS, "*"))
        if os.path.isdir(d)
    )
    rows = []
    for d in dirs:
        r = scan_one(d)
        if r:
            rows.append(r)
    if not rows:
        print("[export_trial_summary] no matching trial dirs found", file=sys.stderr)
        return 1
    fields = list(rows[0].keys())
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    size_kb = os.path.getsize(OUT_CSV) / 1024
    print(f"[export_trial_summary] host={HOST}  rows={len(rows)}  "
          f"size={size_kb:.1f} KB  out={OUT_CSV}")
    # Quick per-(src,target,arm,dur) summary on stdout so the user sees
    # immediately what they exported.
    from collections import defaultdict
    bucket = defaultdict(list)
    for r in rows:
        if isinstance(r["edges"], int) and r["edges"] > 0:
            bucket[(r["src"], r["duration_h"], r["target"], r["arm"])].append(r["edges"])
    print()
    print(f"{'src':8s} {'dur':>4s} {'target':32s} {'arm':9s} {'N':>3s} "
          f"{'mean':>6s} {'min':>5s} {'max':>5s}")
    print("-" * 78)
    for key in sorted(bucket):
        edges = bucket[key]
        src, dur, tgt, arm = key
        mn = sum(edges) / len(edges)
        print(f"{src:8s} {dur:>4s} {tgt:32s} {arm:9s} {len(edges):3d} "
              f"{mn:6.1f} {min(edges):5d} {max(edges):5d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
