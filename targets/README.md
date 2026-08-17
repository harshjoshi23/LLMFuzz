# Targets

This directory holds **public** firmware snapshots used as exploratory transfer
targets.

| Directory | Upstream | License |
|-----------|----------|---------|
| `bms-firmware/` | LibreSolar BMS | MIT (upstream) |
| `charge-controller-firmware/` | LibreSolar charge controller | MIT (upstream) |

## Infineon DC optimizer (not shipped)

Infineon firmware under test is **not** redistributed in this GitHub repository.
The official Infineon code portal holds that snapshot; GitHub is not an approved
push target for that tree.

The primary statistical evaluation uses the sanitized protocol-harness facsimile:

```
src/harness/fuzz_dc_optimizer_protocol.c
```

configured by `projects/infineon-dc-optimizer.project.yaml`.
A stub directory `mtb-example-pwrlib-dc-optimizer/` exists only so the project
manifest `target_path` resolves; it contains this README pointer, not firmware.
