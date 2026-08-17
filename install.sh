#!/usr/bin/env bash
#
# install.sh — One-shot bootstrap for thesis fuzzing framework
#
# Assumes a fresh Ubuntu 22.04 / 24.04 system (or WSL2 Ubuntu on Windows VDI).
# Installs: system deps, AFL++, python venv, all pip deps, builds harnesses.
#
# Usage:
#   bash install.sh                  # full install
#   SKIP_APT=1 bash install.sh       # skip system packages (already done)
#   SKIP_BUILD=1 bash install.sh     # skip harness build
#
set -euo pipefail
cd "$(dirname "$0")"
REPO_ROOT="$(pwd)"

echo "============================================================"
echo "  Thesis Fuzzing Framework — bootstrap"
echo "  Repo root: $REPO_ROOT"
echo "============================================================"

#-----------------------------------------------------------------
# 1. System packages (Ubuntu/Debian)
#-----------------------------------------------------------------
if [[ -z "${SKIP_APT:-}" ]]; then
    echo ""
    echo "[1/5] Installing system packages (sudo required)..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        build-essential clang llvm \
        python3 python3-venv python3-pip python3-dev \
        git curl wget ca-certificates \
        afl++ \
        libssl-dev libffi-dev \
        pkg-config
    echo "  ✅ System packages installed"
else
    echo "[1/5] Skipping apt (SKIP_APT=1)"
fi

#-----------------------------------------------------------------
# 2. Python virtual environment
#-----------------------------------------------------------------
echo ""
echo "[2/5] Creating Python virtual environment..."
if [[ ! -d .venv ]]; then
    python3 -m venv .venv
    echo "  ✅ .venv created"
else
    echo "  ℹ️  .venv already exists, reusing"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip --quiet
echo "  ✅ pip upgraded ($(python -V))"

#-----------------------------------------------------------------
# 3. Python dependencies
#-----------------------------------------------------------------
echo ""
echo "[3/5] Installing Python dependencies (this takes ~2 min)..."
pip install --quiet -r requirements.txt
echo "  ✅ Python deps installed"

#-----------------------------------------------------------------
# 4. .env.local scaffold
#-----------------------------------------------------------------
echo ""
echo "[4/5] Checking .env.local credentials file..."
if [[ ! -f .env.local ]]; then
    cat > .env.local <<'ENVEOF'
# === LLM credentials (REQUIRED) ===
# Any OpenAI-compatible Chat Completions endpoint. See .env.example.
GPT4IFX_CLIENT_ID=
GPT4IFX_CLIENT_SECRET=
GPT4IFX_BASE_URL=https://<your-llm-endpoint>

# === Optional: legacy llama gateway ===
# LLAMA_USER=DOMAIN\\username
# LLAMA_PASSWORD=password

# === Model overrides (defaults are gpt-5.2 / gpt-5.2-mini) ===
# THESIS_LLM_PRIMARY_MODEL=gpt-5.2
# THESIS_LLM_FALLBACK_MODEL=gpt-5.2-mini

# === LLM mode toggle ===
THESIS_LLM_ENABLED=1

# === TLS (corporate cert if needed) ===
# REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
# SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENVEOF
    echo "  ⚠️  .env.local SCAFFOLD created — edit it with your credentials before running fuzz commands"
else
    echo "  ✅ .env.local already exists"
fi

#-----------------------------------------------------------------
# 5. Build harnesses (gcov-instrumented + AFL-instrumented)
#-----------------------------------------------------------------
if [[ -z "${SKIP_BUILD:-}" ]]; then
    echo ""
    echo "[5/5] Building harness binaries..."
    mkdir -p build logs results data
    for target in infineon-dc-optimizer libresolar-bms libresolar-charge-controller; do
        mkdir -p "build/$target"
        # delegated to per-target build scripts if they exist
        if [[ -x "scripts/build_${target}.sh" ]]; then
            bash "scripts/build_${target}.sh" || echo "  ⚠️  ${target} build failed (non-fatal)"
        fi
    done
    # Generic AFL build using firmware_adapters.c
    if [[ -f src/harness/firmware_adapters.c ]]; then
        for target in infineon-dc-optimizer libresolar-bms libresolar-charge-controller; do
            OUT="build/$target/fuzz_$(echo $target | tr '-' '_')_protocol"
            mkdir -p "build/$target"
            AFL_QUIET=1 afl-clang-fast \
                -O2 -g \
                -DTARGET_$(echo $target | tr 'a-z-' 'A-Z_') \
                src/harness/firmware_adapters.c \
                -o "$OUT" 2>/dev/null && echo "  ✅ Built $OUT" || true
        done
    fi
    echo "  ✅ Build phase complete"
else
    echo "[5/5] Skipping harness build (SKIP_BUILD=1)"
fi

#-----------------------------------------------------------------
# Done
#-----------------------------------------------------------------
echo ""
echo "============================================================"
echo "  ✅ Bootstrap complete"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Edit .env.local with your GPT4IFX credentials"
echo "  2. Source venv:        source .venv/bin/activate"
echo "  3. Load env:           set -a; source .env.local; set +a"
echo "  4. Sanity check:       python -m src.cli doctor"
echo "  5. 5-min smoke test:   THESIS_LLM_ENABLED=1 python -m src.cli \\"
echo "                           --project projects/infineon-dc-optimizer.project.yaml \\"
echo "                           fuzz --duration 300 --protocol i2c --run-id smoke_\$(date +%H%M)"
echo "  6. Long campaign:      see docs/VM_QUICKSTART.md"
echo ""
