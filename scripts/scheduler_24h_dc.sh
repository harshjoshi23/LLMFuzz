#!/usr/bin/env bash
#
# scheduler_24h_dc.sh — unattended chained scheduler for 24h DC batches.
#
# Each batch = 6 parallel × 24h trials (3 LLM + 3 baseline) on DC, launched via
# scripts/run_parallel_24h_dc.sh. The scheduler:
#
#   1. Waits for batch 1 (already running, ends Sun 14 Jun ~11:39 CEST) to finish.
#   2. Runs INTERIM post-processing so user has data for Sun-night uni report.
#   3. Launches batch 2 immediately after.
#   4. Loops: wait 24h for memory to free, launch next batch, do mini-postprocess.
#   5. After the final batch, runs FULL post-processing into /tmp/dc_final_*.txt.
#
# Default: 9 more batches after batch 1 = 10 batches total = N=30 LLM + N=30 baseline
# at 24h — exactly matches the kolloquium announcement.
#
# OVERRIDE: NUM_MORE_BATCHES=N bash scripts/scheduler_24h_dc.sh
#   N=2  ->  batches 2,3        -> N=9/9  total   (3-day plan)
#   N=4  ->  batches 2..5       -> N=15/15 total  (5-day plan)
#   N=9  ->  batches 2..10      -> N=30/30 total  (10-day plan — DEFAULT)
#
# Memory safety: this script waits for >= 4 GB available memory before launching
# the next batch. If a previous batch is still running, it sleeps and re-checks
# every 5 minutes. No risk of overlapping batches OOM-killing each other.
#
# Stop early: kill the scheduler tmux session (`tmux kill-session -t dcsched`).
# The currently-running batch continues; only future batches are cancelled.
#
set -uo pipefail
cd "$(dirname "$0")/.."

NUM_MORE_BATCHES=${NUM_MORE_BATCHES:-9}
START_BATCH=${START_BATCH:-2}
INITIAL_END=${INITIAL_END:-"2026-06-14 11:39:00"}     # when batch 1 ends
MIN_FREE_GB=${MIN_FREE_GB:-2}                          # require this much "available" RAM before launching next batch
                                                       # NOTE: Linux holds cache; 2 GB is what's truly free after a batch reaps

LOG="logs/scheduler_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
echo "[$(date)] === scheduler starting ===" | tee -a "$LOG"
echo "[$(date)] NUM_MORE_BATCHES=$NUM_MORE_BATCHES  START_BATCH=$START_BATCH" | tee -a "$LOG"
echo "[$(date)] will launch batches $START_BATCH .. $((START_BATCH + NUM_MORE_BATCHES - 1))" | tee -a "$LOG"
echo "[$(date)] log: $LOG" | tee -a "$LOG"

#------------------------------------------------------------------
# Helpers
#------------------------------------------------------------------
log()  { echo "[$(date)] $*" | tee -a "$LOG"; }
mem_available_gb() { free -m | awk 'NR==2 {print int($7/1024)}'; }

wait_for_memory() {
    local need=$1
    while true; do
        local have; have=$(mem_available_gb)
        if [ "$have" -ge "$need" ]; then
            log "memory OK: ${have} GB available (need ${need} GB)"
            return 0
        fi
        log "waiting for memory: ${have} GB available, need ${need} GB. sleeping 5 min."
        sleep 300
    done
}

wait_until() {
    local target_str=$1
    local target now sleepfor
    target=$(date -d "$target_str" +%s)
    now=$(date +%s)
    if [ "$target" -le "$now" ]; then
        log "target time '$target_str' already passed, continuing immediately"
        return 0
    fi
    sleepfor=$((target - now))
    log "sleeping ${sleepfor}s until $(date -d @"$target")"
    sleep "$sleepfor"
}

interim_postprocess() {
    local tag=$1
    log "interim post-processing: tag=$tag"
    bash scripts/gcov_all_trials.sh >> "$LOG" 2>&1 || log "[warn] gcov replay had errors"
    local outfile=/tmp/dc_interim_${tag}.txt
    {
        echo "=== Interim post-processing at $(date) (tag=$tag) ==="
        echo
        echo ">>> 24h-only stats <<<"
        python scripts/sok_stats_lastN.py 30 24h 2>&1 || true
        echo
        echo ">>> Combined (24h + 2h + 8h + 12h) stats <<<"
        python scripts/sok_stats_lastN.py 30 2>&1 || true
        echo
        echo ">>> TTC milestones <<<"
        python scripts/ttc_milestones.py 2>&1 || true
    } | tee "$outfile" >> "$LOG"
    log "interim results written to: $outfile"
}

#------------------------------------------------------------------
# Phase A: wait for batch 1 to finish, then interim post-processing
#------------------------------------------------------------------
wait_until "$INITIAL_END"
log "batch 1 should be ending; verifying memory freed"
sleep 600   # 10 min cushion for trials to flush + tmux cleanup
wait_for_memory "$MIN_FREE_GB"

interim_postprocess "after_batch1"
log "============================================================"
log "INTERIM REPORT READY for Sun-night uni report:"
log "  /tmp/dc_interim_after_batch1.txt"
log "============================================================"

#------------------------------------------------------------------
# Phase B: loop launching successive batches
#------------------------------------------------------------------
for B in $(seq "$START_BATCH" "$((START_BATCH + NUM_MORE_BATCHES - 1))"); do
    log "--- launching batch $B ---"
    wait_for_memory "$MIN_FREE_GB"
    SESSION="dc24h_b${B}" bash scripts/run_parallel_24h_dc.sh >> "$LOG" 2>&1 || log "[error] launch batch $B failed (continuing)"
    log "batch $B launched. will finish in ~24h."

    # If this isn't the last batch: wait 24h, do mini post-process, prepare for next
    if [ "$B" -lt "$((START_BATCH + NUM_MORE_BATCHES - 1))" ]; then
        log "sleeping 24h 30min before launching batch $((B+1))"
        sleep $((24 * 3600 + 30 * 60))
        interim_postprocess "after_batch${B}"
    fi
done

#------------------------------------------------------------------
# Phase C: wait for final batch to finish, then full post-processing
#------------------------------------------------------------------
log "all batches launched. waiting for final batch to drain (25h)"
sleep $((25 * 3600))
wait_for_memory "$MIN_FREE_GB"

log "running FINAL post-processing"
bash scripts/gcov_all_trials.sh >> "$LOG" 2>&1 || log "[warn] gcov errors"
{
    echo "=== FINAL post-processing at $(date) ==="
    echo
    echo ">>> 24h-only stats (N up to 30 per arm) <<<"
    python scripts/sok_stats_lastN.py 30 24h 2>&1 || true
    echo
    echo ">>> Combined (24h + 2h + 8h + 12h) stats <<<"
    python scripts/sok_stats_lastN.py 30 2>&1 || true
    echo
    echo ">>> TTC milestones (median seconds to N edges) <<<"
    python scripts/ttc_milestones.py 2>&1 || true
    echo
    echo ">>> gcov line/branch table <<<"
    python scripts/verify_gcov_table.py 2>&1 || true
    echo
    echo ">>> Trial inventory <<<"
    python scripts/scan_trials.py 2>&1 || true
} | tee /tmp/dc_final_n30.txt >> "$LOG"

log "============================================================"
log "SCHEDULER DONE. Final results: /tmp/dc_final_n30.txt"
log "============================================================"
echo "[$(date)] === scheduler complete ===" | tee -a "$LOG"
