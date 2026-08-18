#!/usr/bin/env bash
#
# run_local_8h_thesis.sh — optional 8-hour rerun launcher.
#
# This is NOT the STVR primary experiment (that comparison is two hours,
# N=20 vs N=14). Use only for a longer local saturation check.
#
# Default N_TRIALS=1: one 8h trial per target per arm (~48 h sequential).
# N_TRIALS=3 is ~144 h. Requires LLM credentials in .env.local.
#
# Usage:
#   bash scripts/run_local_8h_thesis.sh                       # 1 trial per arm per target (48 h)
#   N_TRIALS=3 bash scripts/run_local_8h_thesis.sh            # 3 trials per arm per target (144 h)
#   bash scripts/run_local_8h_thesis.sh infineon-dc-optimizer # only DC
#
set -euo pipefail
cd "$(dirname "$0")/.."

DURATION=${DURATION:-28800}           # 8 h per trial
N_TRIALS=${N_TRIALS:-1}

if [[ $# -gt 0 ]]; then
    TARGETS=("$@")
else
    TARGETS=(
        "infineon-dc-optimizer"
        "libresolar-bms"
        "libresolar-charge-controller"
    )
fi

if [[ -z "${GPT4IFX_API_KEY:-}" ]]; then
    # Auto-load from .env.local and key.txt, accept any auth method.
    # shellcheck disable=SC1091
    source "$(dirname "$0")/_load_env.sh"
fi

TS=$(date +%Y%m%d_%H%M%S)
TOTAL=$((${#TARGETS[@]} * 2 * N_TRIALS))
EST_HOURS=$(python -c "print(round($TOTAL * $DURATION / 3600, 1))")
echo "==> About to launch $TOTAL trials (${EST_HOURS} h wall-clock) at $(date)"
echo "    Targets : ${TARGETS[*]}"
echo "    Trials  : $N_TRIALS per arm per target"
echo "    Duration: ${DURATION}s per trial"
read -p "    Press Enter to continue, Ctrl-C to abort... " _

for TARGET in "${TARGETS[@]}"; do
    YAML="projects/${TARGET}.project.yaml"
    [[ -f "$YAML" ]] || continue
    for ARM in llm baseline; do
        for TRIAL in $(seq 1 $N_TRIALS); do
            RID="local_8h_${TARGET}_${ARM}_t${TRIAL}_${TS}"
            echo
            echo "=== [$RID] start at $(date) ==="
            ENABLE=$([ "$ARM" = "llm" ] && echo 1 || echo 0)
            THESIS_LLM_ENABLED=$ENABLE python -m src.cli \
                --project "$YAML" \
                fuzz --protocol i2c --duration "$DURATION" \
                --run-id "$RID" 2>&1 | tee "logs/${RID}.log"
        done
    done
done

echo
echo "==> ALL $TOTAL TRIALS COMPLETE at $(date)"
echo
echo "==> Auto post-processing (idempotent, ~2-5 min):"
echo "    [1/2] gcov replay on every trial -> writes reports/native_coverage.json"
bash scripts/gcov_all_trials.sh || echo "[!] gcov replay had errors -- see logs above"
echo
echo "    [2/2] trial inventory + statistics"
python scripts/scan_trials.py || true
echo
echo "==> Done. PDF figures in: artifacts/  &  reports/"
