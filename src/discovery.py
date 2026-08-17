"""Generic discovery (best-effort) + baseline harness stub generation.

This is intentionally minimal.

Why:
- For *generic repos*, discovery will frequently fail without expert hints.
- The thesis pipeline must still run end-to-end for evaluation, so we provide
  a baseline harness stub that fuzzes "input plumbing" only.

Baseline harness stub behavior:
- AFL++ harness that reads @@ input file
- Emits scenario events in a generic format (optional)
- Does NOT link to / call into target repo code

Expert mode can override this by providing an explicit harness path or by
using a future harness synthesis module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DiscoveryResult:
    ok: bool
    reason: str
    harness_path: Optional[str] = None


_BASELINE_HARNESS_C = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

// Minimal AFL-compatible harness stub.
// Reads @@ input file and does nothing with it.
// This exists so the pipeline can run on unknown repos.

int main(int argc, char** argv) {
  if (argc < 2) {
    return 0;
  }

  const char* path = argv[1];
  FILE* f = fopen(path, "rb");
  if (!f) return 0;

  uint8_t buf[4096];
  size_t n = fread(buf, 1, sizeof(buf), f);
  fclose(f);

  // Trivial "checksum" to prevent compiler optimizing everything away.
  uint32_t acc = 0;
  for (size_t i = 0; i < n; i++) acc = (acc * 33u) ^ buf[i];

  if (acc == 0xDEADBEEF) {
    // unreachable but keeps acc alive
    fprintf(stderr, "magic\n");
  }

  return 0;
}
"""


def ensure_baseline_harness(*, out_dir: Path) -> str:
    """Write and build baseline harness stub under out_dir.

    Returns absolute path to built harness executable.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    c_path = out_dir / "fuzz_baseline.c"
    exe_path = out_dir / "fuzz_baseline"

    if not c_path.exists():
        c_path.write_text(_BASELINE_HARNESS_C, encoding="utf-8")

    # build (best-effort). We keep it simple to avoid requiring a build system.
    import subprocess

    subprocess.check_call([
        "cc",
        "-O2",
        "-g",
        "-o",
        str(exe_path),
        str(c_path),
    ])

    return str(exe_path)


def discover_or_fallback(*, allow_fallback: bool, out_dir: Path) -> DiscoveryResult:
    """Placeholder discovery entrypoint.

    Today: always falls back when allowed.
    Future: implement real discovery + signature extraction.
    """

    if not allow_fallback:
        return DiscoveryResult(ok=False, reason="discovery not implemented; fallback disabled")

    try:
        hp = ensure_baseline_harness(out_dir=out_dir)
        return DiscoveryResult(ok=True, reason="using baseline harness stub", harness_path=hp)
    except Exception as e:
        return DiscoveryResult(ok=False, reason=f"baseline harness build failed: {e}")
