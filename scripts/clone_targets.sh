#!/usr/bin/env bash
#
# clone_targets.sh — clone the three target firmware repos used by the
# thesis evaluation pipeline. Idempotent: skips repos already cloned.
#
# Usage:
#   bash scripts/clone_targets.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p targets
cd targets

declare -A REPOS=(
    [mtb-example-pwrlib-dc-optimizer]="https://github.com/Infineon/mtb-example-pwrlib-dc-optimizer"
    [bms-firmware]="https://github.com/LibreSolar/bms-firmware"
    [charge-controller-firmware]="https://github.com/LibreSolar/charge-controller-firmware"
)

for name in "${!REPOS[@]}"; do
    url="${REPOS[$name]}"
    if [[ -d "$name/.git" ]]; then
        echo "  ✓ $name already cloned, skipping"
    else
        echo "  → cloning $name from $url"
        git clone --depth 1 "$url" "$name"
    fi
done

echo ""
echo "==> Done. Targets present:"
ls -1 .
