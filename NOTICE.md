# Release notes (sanitized GitHub tree)

This tree is the **verified** pipeline package (August 2026), not the 15 June 2026
university zip.

## Intentionally not redistributed

- Infineon firmware under test (`mtb-example-pwrlib-dc-optimizer` and related
  production sources). Infineon hosts that snapshot on their official code
  portal, which does not accept a GitHub push.
- Proprietary datasheets, Windchill exports, and internal Confluence/GitLab
  hosts. Crawler modules use placeholder URLs.
- Compiled AFL++ binaries (`fuzz_i2c`, `fuzz_pmbus`, `fuzz_state`).
- Campaign `findings/` queues (gitignored; not the unrecovered study artefacts).

## What remains (legally cleared for this sanitized release)

- Python pipeline (`src/cli.py`, RAG, agents, encoders, reporters).
- Sanitized C protocol-harness facsimiles, including
  `src/harness/fuzz_dc_optimizer_protocol.c`.
- Public LibreSolar BMS and charge-controller snapshots under `targets/`.
- Public-chunk FAISS indexes under `data/vectorstore_projects/`.
- Unit tests and CI (syntax, secrets scan, pytest with mock LLM).

Primary evaluation does **not** require the Infineon DUT tree: AFL++ is driven
from the harness facsimile listed in `projects/infineon-dc-optimizer.project.yaml`.
