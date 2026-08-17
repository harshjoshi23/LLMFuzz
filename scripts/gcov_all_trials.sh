#!/usr/bin/env bash
#
# gcov_all_trials.sh — Run scripts/replay_gcov.sh on every "clean" trial
# in results/ so every per-trial run.json gets a populated
# reports/native_coverage.json.
#
# Usage:
#   bash scripts/gcov_all_trials.sh                  # all 3 targets
#   bash scripts/gcov_all_trials.sh infineon-dc-optimizer
#
set -euo pipefail
cd "$(dirname "$0")/.."

TARGETS=("infineon-dc-optimizer" "libresolar-bms" "libresolar-charge-controller")
if [[ $# -gt 0 ]]; then TARGETS=("$@"); fi

for TARGET in "${TARGETS[@]}"; do
    YAML="projects/${TARGET}.project.yaml"
    [[ -f "$YAML" ]] || { echo "skip: $YAML missing"; continue; }
    echo
    echo "=================================================================="
    echo "  $TARGET"
    echo "=================================================================="
    for RUN in results/thesis_${TARGET}_* results/local_8h_${TARGET}_* results/vm_sok_${TARGET}_*; do
        [[ -d "$RUN" ]] || continue
        # Skip if already done in this batch (idempotent)
        if [[ -s "$RUN/reports/native_coverage.json" ]] && \
           python -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('line_percent') else 1)" \
             "$RUN/reports/native_coverage.json" 2>/dev/null; then
            echo "  ✓ $RUN already has gcov data, skipping"
            continue
        fi
        # Skip if no AFL queue (short / failed trials)
        QUEUE=$(find "$RUN/afl" -type d -name queue 2>/dev/null | head -1)
        if [[ -z "$QUEUE" ]]; then
            echo "  ⚠ $RUN has no queue/, skipping"
            continue
        fi
        echo "  → gcov on $RUN"
        bash scripts/replay_gcov.sh "$RUN" "$YAML" 2>&1 | tail -5
    done
done

# Final cross-trial summary
echo
echo "=================================================================="
echo "  CROSS-TRIAL GCOV SUMMARY"
echo "=================================================================="
python - <<'PY'
import glob, json, statistics

def collect(pat):
    out = []
    for f in sorted(glob.glob(pat)):
        try:
            d = json.load(open(f))
            lp = d.get('line_percent')
            bp = d.get('branch_percent')
            if lp is not None: out.append((lp, bp, f))
        except Exception:
            pass
    return out

for tgt in ('infineon-dc-optimizer','libresolar-bms','libresolar-charge-controller'):
    for arm in ('llm','baseline'):
        rows = collect(f"results/*{tgt}_{arm}*/reports/native_coverage.json")
        if not rows: continue
        lps = [r[0] for r in rows]
        bps = [r[1] for r in rows if r[1] is not None]
        line = f"line {statistics.mean(lps):5.1f}% +- {statistics.stdev(lps) if len(lps)>1 else 0:.1f}"
        branch = f"branch {statistics.mean(bps):5.1f}% +- {statistics.stdev(bps) if len(bps)>1 else 0:.1f}" if bps else ""
        print(f"  {tgt:<35s} {arm:<10s} N={len(rows):>2d}  {line:<22s}  {branch}")
PY
