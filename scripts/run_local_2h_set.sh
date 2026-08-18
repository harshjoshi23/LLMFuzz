#!/usr/bin/env bash
#
# run_local_2h_set.sh — optional 2-hour rerun launcher (released pipeline).
#
# Default: 3 trials × {llm,baseline} per listed target, duration 7200 s.
# This is a convenience rerun script. It is NOT the historical STVR sample
# (that paper reports N=20 documentation-grounded vs N=14 baseline on the
# primary harness). Override N_TRIALS if you want a larger local rerun.
#
# Prereqs: LLM credentials in .env.local, FAISS indexes present, .venv active.
#
# Usage:
#   bash scripts/run_local_2h_set.sh                       # all 3 targets, 3 trials each
#   bash scripts/run_local_2h_set.sh infineon-dc-optimizer # one target
#   N_TRIALS=5 bash scripts/run_local_2h_set.sh            # override trial count
#
set -euo pipefail
cd "$(dirname "$0")/.."

DURATION=${DURATION:-7200}            # 2 h per trial
N_TRIALS=${N_TRIALS:-3}

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
    # Auto-load from .env.local and key.txt, accept any auth method
    # (bearer / oauth2 / basic). Exits 1 if no auth available.
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
    [[ -f "$YAML" ]] || { echo "skip: $YAML missing"; continue; }
    for ARM in llm baseline; do
        for TRIAL in $(seq 1 $N_TRIALS); do
            RID="local_2h_${TARGET}_${ARM}_t${TRIAL}_${TS}"
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
