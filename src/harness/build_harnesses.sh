#!/bin/bash
# Build AFL++ Harnesses
# Run this in WSL or Linux environment with AFL++ installed
#
# Usage: ./build_harnesses.sh
#
# Part of: AI-Enhanced Fuzzing for Embedded Power Systems

set -e

echo "=================================================="
echo "Building AFL++ Harnesses"
echo "=================================================="
echo ""

# Check for AFL++
if ! command -v afl-gcc &> /dev/null; then
    echo "[ERROR] afl-gcc not found. Please install AFL++ first."
    echo ""
    echo "Installation options:"
    echo "  1. WSL: sudo apt install afl++"
    echo "  2. Docker: docker run -it aflplusplus/aflplusplus"
    echo "  3. Source: git clone https://github.com/AFLplusplus/AFLplusplus && make"
    exit 1
fi

echo "[*] AFL++ found at: $(which afl-gcc)"
echo ""

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[*] Building standard harnesses..."

# PMBus harness
echo "  - fuzz_pmbus"
afl-gcc -O2 -o fuzz_pmbus fuzz_pmbus.c 2>&1 || echo "    [WARNING] Build failed"

# I2C harness
echo "  - fuzz_i2c"
afl-gcc -O2 -o fuzz_i2c fuzz_i2c_slave.c 2>&1 || echo "    [WARNING] Build failed"

# State machine harness
echo "  - fuzz_state"
afl-gcc -O2 -o fuzz_state fuzz_state_machine.c 2>&1 || echo "    [WARNING] Build failed"

echo ""
echo "[*] Building ASAN-instrumented harnesses..."

# Build with AddressSanitizer (better crash detection)
AFL_USE_ASAN=1 afl-gcc -o fuzz_pmbus_asan fuzz_pmbus.c 2>/dev/null || \
    echo "    [SKIP] ASAN build not available"

AFL_USE_ASAN=1 afl-gcc -o fuzz_i2c_asan fuzz_i2c_slave.c 2>/dev/null || \
    echo "    [SKIP] ASAN build not available"

AFL_USE_ASAN=1 afl-gcc -o fuzz_state_asan fuzz_state_machine.c 2>/dev/null || \
    echo "    [SKIP] ASAN build not available"

echo ""
echo "[*] Building debug harnesses (for crash analysis)..."

gcc -O0 -g -o fuzz_pmbus_debug fuzz_pmbus.c 2>&1 || echo "    [WARNING] Debug build failed"
gcc -O0 -g -o fuzz_i2c_debug fuzz_i2c_slave.c 2>&1 || echo "    [WARNING] Debug build failed"
gcc -O0 -g -o fuzz_state_debug fuzz_state_machine.c 2>&1 || echo "    [WARNING] Debug build failed"

echo ""
echo "=================================================="
echo "Build Results"
echo "=================================================="

# List built files
if ls fuzz_* 1> /dev/null 2>&1; then
    echo ""
    ls -la fuzz_* 2>/dev/null || true
    echo ""
    echo "[+] Build complete!"
else
    echo "[!] No harnesses built. Check for errors above."
fi

echo ""
echo "Next steps:"
echo "  1. Generate seed corpus: python seed_corpus_converter.py --generate-from-agent"
echo "  2. Run fuzzing: afl-fuzz -i corpus/pmbus -o findings ./fuzz_pmbus @@"
echo ""
