# Reproducibility Guide

This repository is a **sanitized public implementation** of the documentation-to-seed pipeline.
Commands below rerun the **released method**. They are **not** a claim that a rerun is
bit-identical to the historical STVR / thesis campaign.

## What the STVR manuscript reports (do not overwrite these)

Primary confirmatory comparison (sanitized DC-optimizer protocol harness):

* Arms: documentation-grounded vs one 64-byte zero-filled seed
* \(N = 20\) documentation-grounded, \(N = 14\) baseline
* Budget: **two hours**
* About **28 unique** documentation-grounded seeds per evaluated primary trial
* Final edges: \(217.8 \pm 1.8\) vs \(206.1 \pm 6.9\)
* Median time to 200 edges: 60 s (20/20) vs 4139 s (13/14) — about **69× at that milestone only**, not a general fuzzing speedup
* Coverage acceleration, not vulnerability discovery

Exact historical chat-model identifiers, some sampling settings, and some
campaign-binding YAML details could not be fully reconciled. Original per-trial
AFL++ artefacts (`plot_data`, `fuzzer_stats`, `run.json`) are **not** in this
repository. Infineon proprietary firmware and datasheets are **not** distributed.

Example project files (for example `duration_seconds: 3600`) are **defaults /
examples**. The 2-hour scripts override duration to 7200 s.

## 1. Hardware / OS

* Ubuntu 22.04 LTS or 24.04 LTS (also tested on WSL2 Ubuntu 22.04)
* x86_64, ≥ 4 cores, ≥ 8 GB RAM
* Extra disk if you run optional long campaigns (see §5)

## 2. Bootstrap

```bash
bash install.sh
source .venv/bin/activate
python -m src.cli doctor
```

Offline: `THESIS_LLM_ENABLED=0`.

## 3. Smoke test (about 3 minutes)

```bash
cp .env.example .env.local
# set your LLM endpoint in .env.local

THESIS_LLM_ENABLED=1 python -m src.cli \
    --project projects/infineon-dc-optimizer.project.yaml \
    fuzz --protocol i2c --duration 180 --run-id smoke_test
```

This checks that the released pipeline runs. It does **not** recreate the STVR
sample sizes or the reported statistics.

## 4. Optional 2-hour rerun (released scripts)

```bash
N_TRIALS=5 bash scripts/run_local_2h_set.sh infineon-dc-optimizer
```

The script uses a 2-hour (`7200` s) budget, matching the **reported** comparison
length. Trial counts you choose here are **your** rerun, not the historical
\(N{=}20/14\) sample.

## 5. Optional longer campaigns (not the STVR primary result)

Scripts such as `run_parallel_24h_dc.sh` and `scheduler_24h_dc.sh` are
**extended / example** launchers (including plans that mention N=30 or 24 h).
They are not the confirmatory experiment in the STVR manuscript.

## 6. Other targets

Replace `infineon-dc-optimizer` with `libresolar-bms` or
`libresolar-charge-controller` to exercise the public transfer harnesses.

## 7. Public release notes

* The shipped DC-optimizer FAISS index contains public corpus chunks only.
* Do not commit `key.txt`, `ca-bundle.crt`, `.env.local`, or proprietary PDFs.
* Reruns will differ: AFL++ mutation is non-deterministic, and LLM calls are
  not pinned to the historical gateway settings.
