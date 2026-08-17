# Reproducibility Guide

Exact commands to reproduce the evaluation protocol described in the M.Sc. thesis
(*Retrieval Augmented LLM Seed Generation for Coverage-Guided Fuzzing of Embedded
Power-Conversion Firmware*, FAU, 2026).

## 1. Hardware / OS requirements

* Ubuntu 22.04 LTS or 24.04 LTS (also tested on WSL2 Ubuntu 22.04)
* x86_64, ≥ 4 cores, ≥ 8 GB RAM
* ≥ 10 GB free disk for a full N=30 × 24 h evaluation per target

## 2. One-shot bootstrap

```bash
bash install.sh                         # apt + AFL++ + venv + pip + harness build
source .venv/bin/activate
python -m src.cli doctor                # all checks green
```

The bootstrap takes ~5 minutes on a typical machine. Offline checks pass with
`THESIS_LLM_ENABLED=0` (no LLM endpoint required for `doctor` structure checks).

## 3. Smoke test (3 minutes)

```bash
cp .env.example .env.local
# edit .env.local — set your LLM endpoint credentials

THESIS_LLM_ENABLED=1 python -m src.cli \
    --project projects/infineon-dc-optimizer.project.yaml \
    fuzz --protocol i2c --duration 180 --run-id smoke_test

grep -E "edges_found|run_time|execs_per_sec" \
    results/smoke_test/afl/i2c/default/fuzzer_stats
```

You should see ~200 edges found in well under 60 seconds (LLM arm).

## 4. Full SoK evaluation — 2-hour primary sample

```bash
N_TRIALS=5 bash scripts/run_local_2h_set.sh infineon-dc-optimizer
# ≈ 20 hours wall-clock on a single host (5 trials × 2 arms × 2 h)
```

Output: `results/local_2h_infineon-dc-optimizer_{llm,baseline}_tN_TS/`.

## 5. Full SoK evaluation — 24-hour extended

```bash
# Each batch is 6 parallel trials (3 LLM + 3 baseline) × 24 h
SESSION=batch1 bash scripts/run_parallel_24h_dc.sh

# Or use the auto-scheduler for N batches end-to-end (default 10 batches = N=30)
NUM_MORE_BATCHES=9 bash scripts/scheduler_24h_dc.sh
```

## 6. Post-processing and statistics

```bash
# Replay gcov on every trial (idempotent)
bash scripts/gcov_all_trials.sh

# Head-to-head MWU + A12 stats over the last N trials per arm
python scripts/sok_stats_lastN.py 30          # combined budgets
python scripts/sok_stats_lastN.py 30 24h      # 24h-only subset

# Time-to-coverage milestones
python scripts/ttc_milestones.py

# gcov line/branch coverage table
python scripts/verify_gcov_table.py
```

## 7. Other targets

Replace `infineon-dc-optimizer` with `libresolar-bms` or
`libresolar-charge-controller` in step 4 to evaluate the other targets.

## 8. Expected resource usage (per concurrent trial)

* CPU: 1 core for AFL++ + fractional core for LLM agent
* RAM: ~150 MB resident
* Disk: ~5 MB after gcov post-processing
* Network: bounded LLM API call rate (~1–5 calls/sec during early fuzzing)

## 9. Determinism caveats

* AFL++ uses non-deterministic mutation scheduling. Re-running yields
  similar but not identical edge counts. The SoK protocol uses N=30
  trials to make per-arm variance estimable.
* LLM responses are non-deterministic at temperature > 0. The seed-
  generation agent uses temperature 0.7; constraint extraction uses 0.0.

## 10. Public release notes

* The shipped **DC Optimizer FAISS index** contains three public corpus
  chunks. Proprietary Windchill / internal PDF exports were removed; run
  `python -m src.cli index` with your own documentation to expand coverage.
* Configure LLM endpoints via `.env.local`; never commit `key.txt`,
  `ca-bundle.crt`, or proprietary datasheets.
