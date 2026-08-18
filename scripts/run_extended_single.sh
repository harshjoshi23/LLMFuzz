#!/usr/bin/env bash
#
# run_extended_single.sh — optional long-budget exploration trial per target.
# Not the STVR primary comparison (that uses a two-hour budget).
#
# Usage:
#   bash scripts/run_extended_single.sh                                  # 12 h per arm per target = 72 h
#   DURATION=86400 bash scripts/run_extended_single.sh                   # 24 h per arm per target = 144 h
#   bash scripts/run_extended_single.sh infineon-dc-optimizer            # one target only
#   ARMS=llm bash scripts/run_extended_single.sh                         # one arm only
#
set -euo pipefail
cd "$(dirname "$0")/.."

DURATION=${DURATION:-43200}    # 12 h per trial (set to 86400 for 24 h)
ARMS=${ARMS:-"llm baseline"}

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
    # Auto-load from .env.local + key.txt, accept any auth method.
    # shellcheck disable=SC1091
    source "$(dirname "$0")/_load_env.sh"
fi

TS=$(date +%Y%m%d_%H%M%S)
HOURS=$(python -c "print(round($DURATION / 3600, 1))")
ARM_COUNT=$(echo "$ARMS" | wc -w)
TOTAL=$((${#TARGETS[@]} * ARM_COUNT))
EST=$(python -c "print(round($TOTAL * $DURATION / 3600, 1))")

echo "==> ${HOURS} h × ${ARM_COUNT} arm(s) × ${#TARGETS[@]} target(s) = ~${EST} h wall-clock"
echo "    Targets: ${TARGETS[*]}"
echo "    Arms   : $ARMS"
read -p "    Press Enter to continue, Ctrl-C to abort... " _

for TARGET in "${TARGETS[@]}"; do
    YAML="projects/${TARGET}.project.yaml"
    [[ -f "$YAML" ]] || continue
    for ARM in $ARMS; do
        RID="extended_${HOURS}h_${TARGET}_${ARM}_${TS}"
        echo
        echo "=== [$RID] start at $(date) ==="
        ENABLE=$([ "$ARM" = "llm" ] && echo 1 || echo 0)
        THESIS_LLM_ENABLED=$ENABLE python -m src.cli \
            --project "$YAML" \
            fuzz --protocol i2c --duration "$DURATION" \
            --run-id "$RID" 2>&1 | tee "logs/${RID}.log"
    done
done

echo
echo "==> DONE at $(date)"
echo
echo "==> Auto post-processing (idempotent):"
bash scripts/gcov_all_trials.sh || echo "[!] gcov replay had errors -- see logs above"
python scripts/scan_trials.py || true
