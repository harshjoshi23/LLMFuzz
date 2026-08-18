#!/usr/bin/env bash
#
# run_parallel_24h_dc.sh — optional 24-hour parallel launcher (extended rerun).
#
# This is NOT the STVR primary experiment (that comparison is two hours,
# N=20 vs N=14). Use only if you want a longer local campaign.
#
# Machine assumption: 8 cores, 7.6 GB RAM. Safe parallelism is 4-6 trials.
# DO NOT raise PER_ARM above 3 (= 6 total parallel) without checking RAM.
#
# Usage:
#   bash scripts/run_parallel_24h_dc.sh                     # 3 LLM + 3 base, 24h, session 'dc24h'
#   PER_ARM=2 bash scripts/run_parallel_24h_dc.sh           # 2 LLM + 2 base (conservative)
#   SESSION=dc24h_b2 bash scripts/run_parallel_24h_dc.sh    # launch second batch in new session
#   DURATION=43200 bash scripts/run_parallel_24h_dc.sh      # override to 12h (debug)
#
# After 24h, repeat with a new SESSION name (e.g. dc24h_b2, dc24h_b3) so each
# batch's tmux session is independent. Old completed sessions are auto-killed
# only if you re-use the same SESSION name.
#
set -euo pipefail
cd "$(dirname "$0")/.."

SESSION=${SESSION:-dc24h}
PER_ARM=${PER_ARM:-3}            # 3 LLM + 3 baseline = 6 parallel trials
DURATION=${DURATION:-86400}      # 24 h = 86400 s
TARGET=${TARGET:-infineon-dc-optimizer}
STAGGER=${STAGGER:-30}           # seconds between LLM launches (avoids endpoint thundering-herd)

YAML="projects/${TARGET}.project.yaml"
[[ -f "$YAML" ]] || { echo "ERROR: $YAML not found"; exit 1; }

# Pre-load auth so the token is valid (writes GPT4IFX_API_KEY env).
# shellcheck disable=SC1091
source scripts/_load_env.sh

# Quick token sanity-check before launching 6 long-running trials.
python - <<'PY'
import os, sys
try:
    from src.utils.gpt4ifx_client import GPT4IFXClient
    c = GPT4IFXClient(); _ = c  # constructs => auth OK
    print("[preflight] TOKEN OK")
except Exception as e:
    print(f"[preflight] TOKEN FAILED: {e}", file=sys.stderr); sys.exit(1)
PY

TS=$(date +%Y%m%d_%H%M%S)
TOTAL=$((PER_ARM * 2))
HOURS=$(python -c "print(round($DURATION/3600, 1))")

mkdir -p logs

echo
echo "============================================================"
echo "  Parallel 24h DC trials"
echo "  Session   : $SESSION"
echo "  Per arm   : $PER_ARM  (total $TOTAL parallel windows)"
echo "  Duration  : ${HOURS} h per trial"
echo "  Target    : $TARGET"
echo "  Timestamp : $TS"
echo "  ETA       : trials finish ~${HOURS} h from now"
echo "============================================================"
echo

# Kill prior session of same name (idempotent re-launch)
tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -c "$PWD"

launch_window() {
    local ARM=$1 IDX=$2
    local ENABLE
    ENABLE=$([ "$ARM" = "llm" ] && echo 1 || echo 0)
    local RID="local_24h_${TARGET}_${ARM}_t${IDX}_${TS}"
    local WIN="${ARM}-t${IDX}"
    tmux new-window -t "$SESSION" -n "$WIN" -c "$PWD"
    # send-keys: load env in each window (token must be present), then run the trial,
    # then sleep so the window stays alive for inspection after completion.
    tmux send-keys -t "${SESSION}:${WIN}" \
        "source scripts/_load_env.sh && THESIS_LLM_ENABLED=${ENABLE} python -m src.cli --project ${YAML} fuzz --protocol i2c --duration ${DURATION} --run-id ${RID} 2>&1 | tee logs/${RID}.log; echo '[DONE] ${RID} at \$(date)'; exec bash" C-m
    echo "  launched window '${WIN}'  RID=${RID}"
}

# Stagger LLM launches so they don't all hit the auth endpoint at the same instant.
for I in $(seq 1 "$PER_ARM"); do
    launch_window llm "$I"
    if (( I < PER_ARM )); then sleep "$STAGGER"; fi
done

# Baseline arm launches immediately (no LLM endpoint hit -> no stagger needed)
for I in $(seq 1 "$PER_ARM"); do
    launch_window baseline "$I"
done

# Remove the empty default window 0
tmux kill-window -t "${SESSION}:0" 2>/dev/null || true

echo
echo "============================================================"
echo "  All $TOTAL trials launched in tmux session '$SESSION'"
echo "============================================================"
echo "  Inspect a window:   tmux attach -t $SESSION"
echo "                      then Ctrl-b w   to list windows"
echo "                      then Ctrl-b d   to detach"
echo "  List windows:       tmux list-windows -t $SESSION"
echo "  Tail any log:       tail -f logs/local_24h_${TARGET}_llm_t1_${TS}.log"
echo "  Free RAM check:     free -h"
echo "  Top processes:      pgrep -fa 'python -m src.cli|afl-fuzz' | head"
echo
echo "  When all 6 windows say '[DONE]', launch the next batch:"
echo "    SESSION=${SESSION%_*}_b2 bash scripts/run_parallel_24h_dc.sh"
echo
