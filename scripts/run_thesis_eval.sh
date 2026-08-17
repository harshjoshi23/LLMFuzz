#!/usr/bin/env bash
#
# run_thesis_eval.sh — thesis evaluation campaign (SoK-graded)
#
# Runs N trials × M targets × 2 modes (LLM + baseline), computes
# per-target Mann-Whitney U / Vargha-Delaney A12 comparison.
#
# SoK grading (Schloegel et al. USENIX Sec'24 + Klees et al. CCS'18):
#
#   TIER 1 — Thesis presentation / Infineon internal submission
#     TRIALS=3  DURATION=7200   (3 trials × 2h)  ~18h serial, 3 targets
#     Defensible minimum. Shows trend, not full convergence.
#
#   TIER 2 — Thesis document (submitted in 1 week)
#     TRIALS=5  DURATION=14400  (5 trials × 4h)  ~60h serial, 3 targets
#     Recommended. p-values meaningful. Covers plateau region.
#
#   TIER 3 — Journal / external publication (post-thesis)
#     TRIALS=10 DURATION=43200  (10 trials × 12h) ~360h serial, 3 targets
#     Full SoK compliance. Run on VM in parallel.
#
# Usage:
#   bash scripts/run_thesis_eval.sh                                 # Tier 1 defaults
#   TRIALS=5  DURATION=14400 bash scripts/run_thesis_eval.sh        # Tier 2 (4h)
#   TRIALS=10 DURATION=43200 bash scripts/run_thesis_eval.sh        # Tier 3 (12h)
#   TARGETS="infineon-dc-optimizer" bash scripts/run_thesis_eval.sh # one target only
#
# Outputs (per target):
#   results/thesis_<target>_baseline_t<N>_<ts>/
#   results/thesis_<target>_llm_t<N>_<ts>/
#   results/compare_thesis_<target>/
#       summary.md, comparison.csv, comparison.json, comparison_plot.png

set -euo pipefail
cd "$(dirname "$0")/.."

TRIALS=${TRIALS:-3}
DURATION=${DURATION:-7200}

if [[ -n "${TARGETS:-}" ]]; then
    read -ra TARGETS <<< "$TARGETS"
else
    TARGETS=(
        "infineon-dc-optimizer"
        "libresolar-bms"
        "libresolar-charge-controller"
    )
fi

mkdir -p logs

TOTAL_RUNS=$(( TRIALS * ${#TARGETS[@]} * 2 ))
WALL_H=$(( TOTAL_RUNS * DURATION / 3600 ))

echo "=== thesis-eval campaign ==="
echo "  trials per group : $TRIALS"
echo "  duration per run : ${DURATION}s ($((DURATION/3600))h $(( (DURATION%3600)/60 ))m)"
echo "  targets          : ${TARGETS[*]}"
echo "  total runs       : $TOTAL_RUNS"
echo "  est. wall-clock  : ${WALL_H}h (serial)"
echo

# ---------------------------------------------------------------------------
# Pre-flight doctor check
# ---------------------------------------------------------------------------
.venv/bin/python -m src.cli doctor

# ---------------------------------------------------------------------------
# Build RAG indices (only if missing — force with: rm -rf data/vectorstore_projects/<target>)
# ---------------------------------------------------------------------------
for TARGET in "${TARGETS[@]}"; do
    YAML="projects/${TARGET}.project.yaml"
    if [[ ! -d "data/vectorstore_projects/${TARGET}" ]]; then
        echo "--- indexing RAG for ${TARGET} ---"
        .venv/bin/python -m src.cli --project "$YAML" index
    fi
done

# ---------------------------------------------------------------------------
# Per-target campaign
# ---------------------------------------------------------------------------
for TARGET in "${TARGETS[@]}"; do
    YAML="projects/${TARGET}.project.yaml"
    if [[ ! -f "$YAML" ]]; then
        echo "WARN: $YAML not found, skipping"
        continue
    fi

    echo
    echo "============================================================"
    echo "  $TARGET"
    echo "============================================================"

    for TRIAL in $(seq 1 "$TRIALS"); do
        TS=$(date +%Y%m%d_%H%M%S)

        echo
        echo ">>> [$TARGET] trial $TRIAL/$TRIALS — BASELINE"
        rm -rf "build/${TARGET}"
        LOG="logs/${TARGET}_baseline_t${TRIAL}_${TS}.log"
        THESIS_LLM_ENABLED=0 .venv/bin/python -m src.cli \
            --project "$YAML" \
            fuzz --duration "$DURATION" --protocol i2c \
            --run-id "thesis_${TARGET}_baseline_t${TRIAL}_${TS}" \
            > "$LOG" 2>&1 \
            || echo "WARN: baseline trial $TRIAL exited non-zero, see $LOG"

        echo ">>> [$TARGET] trial $TRIAL/$TRIALS — LLM"
        rm -rf "build/${TARGET}"
        LOG="logs/${TARGET}_llm_t${TRIAL}_${TS}.log"
        THESIS_LLM_ENABLED=1 .venv/bin/python -m src.cli \
            --project "$YAML" \
            fuzz --duration "$DURATION" --protocol i2c \
            --run-id "thesis_${TARGET}_llm_t${TRIAL}_${TS}" \
            > "$LOG" 2>&1 \
            || echo "WARN: llm trial $TRIAL exited non-zero, see $LOG"
    done

    # Per-target statistical comparison
    echo
    echo ">>> [$TARGET] computing comparison ..."
    .venv/bin/python -m src.cli compare \
        --llm      "results/thesis_${TARGET}_llm_t*" \
        --baseline "results/thesis_${TARGET}_baseline_t*" \
        --out      "results/compare_thesis_${TARGET}" \
    || echo "WARN: compare failed for $TARGET (need ≥2 runs per group)"
done

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
echo
echo "============================================================"
echo "  CAMPAIGN COMPLETE"
echo "============================================================"
for TARGET in "${TARGETS[@]}"; do
    SUMMARY="results/compare_thesis_${TARGET}/summary.md"
    if [[ -f "$SUMMARY" ]]; then
        echo
        echo "============= $TARGET ============="
        cat "$SUMMARY"
    fi
done

echo
echo "Dashboard: results/dashboard/index.html"
echo "Per-target comparison artifacts: results/compare_thesis_<target>/"
