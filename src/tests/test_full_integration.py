#!/usr/bin/env python3
"""Full Integration Test (Real Agents)

Validates the refactored agent stack in `src/agents/`:
- ConstraintExtractorAgent (RAG + LLM)
- SeedGeneratorAgent (LLM-guided seeds)
- PeripheralEmulationAgent (optional; LLM JSON response)
- AnalysisAgent (crash analysis + suggestions)

This test does not require AFL++.
"""

import sys
import tempfile
from pathlib import Path

# Ensure repo root is on sys.path so `import src.*` works when invoked as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))



def test_full_integration():
    from src.agents import AgentOrchestrator
    from src.agents import PeripheralEmulationAgent


    orch = AgentOrchestrator()

    # 1) Constraints
    constraints = orch.constraint_agent.extract_constraints("I2C slave address configuration")
    assert isinstance(constraints, list)

    # 2) Seed generation
    seeds = orch.seed_agent.run(protocol="i2c", count=5, constraints=constraints)
    assert len(seeds) > 0
    assert all(isinstance(s.data, (bytes, bytearray)) and len(s.data) > 0 for s in seeds)

    # 3) Peripheral emulation (example read)
    emu = PeripheralEmulationAgent(orch.constraint_agent)
    resp = emu.emulate_read(protocol="i2c", address=0x20, register=0x00, length=2, mode="realistic")
    assert len(resp.data) == 2

    # 4) Analysis agent on synthetic crash
    with tempfile.TemporaryDirectory() as td:
        crash_dir = Path(td)
        (crash_dir / "id:000000,sig:11,src:000000,op:havoc,rep:2").write_bytes(b"\x01\x02\x03")
        analysis = orch.analysis_agent.run(str(crash_dir))
        assert "next_suggestions" in analysis


if __name__ == "__main__":
    test_full_integration()
    print("OK")
