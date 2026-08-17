#!/usr/bin/env bash
#
# replay_gcov.sh — Target-agnostic gcov line/branch coverage for any
# results/<run_id>/ directory produced by `python -m src.cli fuzz`.
#
# What it does:
#   1. Reads the project YAML to find the harness C source (manifest.fuzz.harness.c_file)
#   2. Compiles a SEPARATE coverage-instrumented binary with gcc --coverage
#      into build/<project>/cov/<harness_stem>_cov  (does NOT touch the AFL binary)
#   3. Replays every input in <results_dir>/afl/<proto>/default/queue/ through
#      that binary, producing .gcda files
#   4. Runs gcovr → writes
#        <results_dir>/reports/native_coverage.json   (JSON summary)
#        <results_dir>/coverage/gcov_report.html      (human-readable)
#
# Usage:
#   bash scripts/replay_gcov.sh <results_dir> [<project_yaml>]
#
# Example:
#   bash scripts/replay_gcov.sh \
#       results/thesis_infineon-dc-optimizer_llm_t1_20260531_191702 \
#       projects/infineon-dc-optimizer.project.yaml
#
# Notes:
#   • The replay runs <num queue items> sub-processes; on a 600-item queue
#     this takes 30-60 s.
#   • The gcc coverage binary is separate from the afl-clang-fast binary;
#     they share the same C sources but produce independent build artefacts.
#   • If you re-run on a fresh queue, delete build/<project>/cov/*.gcda first
#     or coverage will accumulate across runs (that's actually useful for
#     "merged corpus coverage" — left as user choice).

set -euo pipefail

RESULTS_DIR="${1:-}"
YAML="${2:-}"

if [[ -z "$RESULTS_DIR" ]]; then
    echo "usage: $0 <results_dir> [<project_yaml>]" >&2
    exit 1
fi
if [[ ! -d "$RESULTS_DIR" ]]; then
    echo "[!] not a directory: $RESULTS_DIR" >&2
    exit 1
fi

# ---- 1) infer project YAML from results dir name if not given -------------
if [[ -z "$YAML" ]]; then
    base=$(basename "$RESULTS_DIR")
    # Result dirs look like thesis_<project>_<arm>_..., smoke_<project>_..., local_8h_<project>_...
    if [[ "$base" =~ infineon-dc-optimizer ]];           then YAML="projects/infineon-dc-optimizer.project.yaml"
    elif [[ "$base" =~ libresolar-bms ]];                then YAML="projects/libresolar-bms.project.yaml"
    elif [[ "$base" =~ libresolar-charge-controller ]];  then YAML="projects/libresolar-charge-controller.project.yaml"
    else
        echo "[!] cannot infer project YAML from $base; pass it as 2nd arg" >&2
        exit 1
    fi
fi
if [[ ! -f "$YAML" ]]; then
    echo "[!] manifest not found: $YAML" >&2
    exit 1
fi

PROJECT=$(python -c "import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))['project']['name'])" "$YAML")
HARNESS_C=$(python -c "import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))['fuzz']['harness']['c_file'])" "$YAML")
STEM=$(basename "$HARNESS_C" .c)

echo "[gcov] project        : $PROJECT"
echo "[gcov] harness source : $HARNESS_C"
echo "[gcov] results dir    : $RESULTS_DIR"

# ---- 2) build the coverage binary ----------------------------------------
COV_DIR="build/${PROJECT}/cov"
mkdir -p "$COV_DIR"
COV_BIN="${COV_DIR}/${STEM}_cov"

# We want the .gcno/.gcda files to live next to the object files in COV_DIR.
# Compile sources individually so each gets its own .gcno in COV_DIR.
COV_FLAGS=(-O0 -g --coverage -fprofile-arcs -ftest-coverage
           -I src/harness -I src/harness/stubs
           -DAFL_PERSISTENT_DISABLE=1
           -fno-inline -fno-omit-frame-pointer)
# A tiny shim turns off __AFL_LOOP / __AFL_INIT macros so the harness runs
# one input from stdin then exits, which is what gcov replay needs.
SHIM_C="$COV_DIR/_afl_shim.c"
cat > "$SHIM_C" <<'EOF'
/* Replaces AFL persistent-mode macros so the harness runs once per process. */
#include <stdio.h>
#include <stdlib.h>
int __afl_persistent_loop(unsigned int max) { (void)max; static int run = 0; if (run) return 0; run = 1; return 1; }
void __afl_manual_init(void) {}
EOF

ADAPTERS_C=src/harness/firmware_adapters.c
[[ -f "$ADAPTERS_C" ]] || ADAPTERS_C=""

# Compile each source to an object so .gcno lives next to the object.
OBJS=()
for src in "$HARNESS_C" "$ADAPTERS_C" "$SHIM_C"; do
    [[ -z "$src" ]] && continue
    obj="$COV_DIR/$(basename "$src" .c).o"
    OBJS+=("$obj")
    # Use a #define to neutralize __AFL_LOOP / __AFL_INIT in source.
    gcc "${COV_FLAGS[@]}" \
        -D'__AFL_LOOP(n)=__afl_persistent_loop(n)' \
        -D'__AFL_INIT()=__afl_manual_init()' \
        -c "$src" -o "$obj"
done

# Link
gcc --coverage -o "$COV_BIN" "${OBJS[@]}" -lgcov

echo "[gcov] coverage binary: $COV_BIN"

# ---- 3) replay the AFL queue ---------------------------------------------
QUEUE_DIR=$(find "$RESULTS_DIR/afl" -mindepth 3 -maxdepth 3 -type d -name queue | head -1)
if [[ -z "$QUEUE_DIR" || ! -d "$QUEUE_DIR" ]]; then
    echo "[!] no AFL queue dir under $RESULTS_DIR/afl/*/*/queue" >&2
    exit 1
fi
QUEUE_COUNT=$(find "$QUEUE_DIR" -maxdepth 1 -type f | wc -l)
echo "[gcov] replaying $QUEUE_COUNT queue items through $COV_BIN ..."

# Wipe stale .gcda so we measure THIS run's coverage exactly
find "$COV_DIR" -name '*.gcda' -delete 2>/dev/null || true

# Replay each input. Limit to 2 KiB and 5 s per item to avoid runaway.
i=0
for inp in "$QUEUE_DIR"/*; do
    [[ -f "$inp" ]] || continue
    timeout 5 "$COV_BIN" < "$inp" > /dev/null 2>&1 || true
    i=$((i+1))
    if (( i % 100 == 0 )); then echo "  replayed $i / $QUEUE_COUNT"; fi
done
echo "[gcov] replay done ($i items)"

# ---- 4) collect the report -----------------------------------------------
REPORT_DIR="$RESULTS_DIR/coverage"
mkdir -p "$REPORT_DIR"

if ! command -v gcovr >/dev/null 2>&1; then
    echo "[!] gcovr not installed. Install: pip install gcovr" >&2
    exit 1
fi

# JSON summary → reports/native_coverage.json
mkdir -p "$RESULTS_DIR/reports"
gcovr --root . \
      --gcov-ignore-parse-errors \
      --json-summary-pretty \
      --output "$RESULTS_DIR/reports/native_coverage.json" \
      "$COV_DIR" 2>&1 | tail -5 || true

# Human report → coverage/gcov_report.html
gcovr --root . \
      --gcov-ignore-parse-errors \
      --html-details "$REPORT_DIR/gcov_report.html" \
      "$COV_DIR" 2>&1 | tail -5 || true

if [[ -f "$RESULTS_DIR/reports/native_coverage.json" ]]; then
    echo
    echo "=== native_coverage.json summary ==="
    python - <<PY
import json
d = json.load(open("$RESULTS_DIR/reports/native_coverage.json"))
print(f"  line   : {d.get('line_percent',  '?')}%  ({d.get('line_covered',  '?')}/{d.get('line_total',  '?')})")
print(f"  branch : {d.get('branch_percent','?')}%  ({d.get('branch_covered','?')}/{d.get('branch_total','?')})")
print(f"  func   : {d.get('function_percent','?')}%  ({d.get('function_covered','?')}/{d.get('function_total','?')})")
PY
    echo
    echo "HTML report: $REPORT_DIR/gcov_report.html"
fi
