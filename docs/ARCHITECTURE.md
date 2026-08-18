# Architecture

LLMFuzz has two entry points that share the same RAG corpus, harnesses, and AFL++ backend.

## Thesis pipeline (primary)

Used for all quantitative evaluation in the M.Sc. thesis.

```
projects/*.yaml  →  src/cli.py  →  src/pipeline.py
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
  ConstraintExtractor  SeedGenerator   AFL++ runner
  (RAG + LLM)          (RAG + LLM)     (src/afl_runner.py)
         │               │               │
         └───────────────┴───────────────┘
                         ▼
              results/<run-id>/ + reports
```

**Stages:** `index` builds or loads a FAISS store; `fuzz` extracts constraints, generates seeds, and launches AFL++; `report` aggregates coverage and trial metadata.

## Multi-agent lab path (optional)

An earlier research prototype with closed-loop crash feedback and documentation crawlers.

```
run_pipeline.py  →  AgentOrchestrator  →  AnalysisAgent / SeedGenerator / …
                           │
              src/crawlers/ (Confluence, GitLab — configure hosts in .env)
```

Configure crawler base URLs via environment variables; the shipped package replaces internal hostnames with placeholders.

## Data flow

| Component | Role |
|-----------|------|
| `data/vectorstore_projects/` | Pre-built FAISS indexes (one per target) |
| `src/rag_pipeline/` | Chunking, embedding, retrieval |
| `src/harness/*.c` | Protocol facsimiles compiled by AFL++ |
| `targets/` | Public LibreSolar snapshots; Infineon DUT is not shipped (harness facsimile only) |
| `scripts/run_local_2h_set.sh` | Optional 2-hour rerun launcher (not the historical STVR sample) |

## Offline development

Set `THESIS_LLM_ENABLED=0` or use `src/utils/mock_llm_client.py` to run the pipeline without a live LLM endpoint. Unit tests in CI use this mode.
