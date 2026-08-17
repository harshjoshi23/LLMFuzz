#!/usr/bin/env python3
"""
Seed Corpus Converter for AFL++

Converts Agent 1 (Constraint-Aware Seed Generator) output to AFL++ binary corpus format.
This bridges the LLM-generated seeds with the AFL++ fuzzer.

Part of: AI-Enhanced Fuzzing for Embedded Power Systems

Usage:
    python seed_corpus_converter.py --input seeds.json --output corpus/
    python seed_corpus_converter.py --generate-from-agent --output corpus/
"""

import os
import sys
import json
import struct
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents import AgentOrchestrator, Seed



class SeedCorpusConverter:
    """
    Converts JSON seed definitions to binary AFL++ corpus files.
    
    AFL++ expects:
    - One file per test case
    - Raw binary data (no JSON)
    - Files in a flat directory structure
    """
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Subdirectories for different harnesses
        self.pmbus_dir = self.output_dir / "pmbus"
        self.i2c_dir = self.output_dir / "i2c"
        self.state_dir = self.output_dir / "state"
        
        for d in [self.pmbus_dir, self.i2c_dir, self.state_dir]:
            d.mkdir(exist_ok=True)
        
        self.stats = {
            "pmbus_seeds": 0,
            "i2c_seeds": 0,
            "state_seeds": 0,
            "adc_seeds_integrated": 0,
            "total_files": 0
        }
    
    def convert_pmbus_seed(self, seed: Dict[str, Any], index: int) -> Path:
        """
        Convert a PMBus seed to binary format.
        
        PMBus harness expects:
        - Byte 0: Command code
        - Byte 1+: Data bytes (length depends on command)
        """
        cmd = seed.get("command_code", seed.get("command", 0x00))
        
        # Handle different input formats
        if isinstance(cmd, str):
            cmd = int(cmd, 16) if cmd.startswith("0x") else int(cmd)
        
        data = seed.get("data", seed.get("data_bytes", []))
        if isinstance(data, str):
            # Handle hex string like "0xABCD"
            data = [int(data[i:i+2], 16) for i in range(2, len(data), 2)]
        elif isinstance(data, int):
            # Single value - convert to bytes
            data = [(data >> 8) & 0xFF, data & 0xFF] if data > 255 else [data]
        
        # Build binary packet
        packet = bytes([cmd] + list(data)[:4])  # Max 4 data bytes + command
        
        # Write to file
        filename = f"pmbus_{index:04d}_{cmd:02x}.bin"
        filepath = self.pmbus_dir / filename
        
        with open(filepath, "wb") as f:
            f.write(packet)
        
        self.stats["pmbus_seeds"] += 1
        self.stats["total_files"] += 1
        
        return filepath
    
    def convert_i2c_seed(self, seed: Dict[str, Any], index: int) -> Path:
        """
        Convert an I2C seed to binary format.
        
        I2C harness expects sequences of 3-byte packets:
        - Byte 0: SOP (0x01) or raw data
        - Byte 1: Command byte
        - Byte 2: EOP (0x17) or raw data
        """
        PACKET_SOP = 0x01
        PACKET_EOP = 0x17
        
        packets = []
        
        # Handle different input formats
        if "transactions" in seed:
            # Multiple transactions
            for tx in seed["transactions"]:
                sop = tx.get("sop", PACKET_SOP)
                cmd = tx.get("cmd", tx.get("command", 0x00))
                eop = tx.get("eop", PACKET_EOP)
                packets.extend([sop, cmd, eop])
        elif "sequence" in seed:
            # Raw sequence
            packets = list(seed["sequence"])
        else:
            # Single transaction
            sop = seed.get("sop", PACKET_SOP)
            cmd = seed.get("cmd", seed.get("command", seed.get("data", 0x00)))
            eop = seed.get("eop", PACKET_EOP)
            
            if isinstance(cmd, str):
                cmd = int(cmd, 16) if cmd.startswith("0x") else int(cmd)
            
            packets = [sop, cmd, eop]
        
        # Convert to bytes
        binary_data = bytes(packets)
        
        # Write to file
        filename = f"i2c_{index:04d}.bin"
        filepath = self.i2c_dir / filename
        
        with open(filepath, "wb") as f:
            f.write(binary_data)
        
        self.stats["i2c_seeds"] += 1
        self.stats["total_files"] += 1
        
        return filepath
    
    def convert_state_seed(self, seed: Dict[str, Any], index: int) -> Path:
        """
        Convert a state machine seed to binary format.
        
        State harness expects:
        - Byte 0: Target state
        - Byte 1-2: VIN (fixed point 8.8)
        - Byte 3-4: VOUT (fixed point 8.8)
        - Byte 5: GPIO inputs
        - Byte 6: Delay counter
        - Byte 7: Interlock current (scaled)
        - Byte 8+: State modifiers
        """
        # Extract values with defaults
        target_state = seed.get("target_state", seed.get("state", 0))
        vin = seed.get("vin", seed.get("input_voltage", 48.0))
        vout = seed.get("vout", seed.get("output_voltage", 12.0))
        gpio = seed.get("gpio", 0x00)
        delay = seed.get("delay", 0)
        interlock = seed.get("interlock_current", 0.05)
        modifiers = seed.get("modifiers", seed.get("perturbations", []))
        
        # Convert to fixed point
        vin_fp = int(vin * 256) & 0xFFFF
        vout_fp = int(vout * 256) & 0xFFFF
        interlock_scaled = int(interlock * 1000) & 0xFF
        
        # Build binary packet
        packet = struct.pack(
            "<BHHBBB",  # Little endian: byte, uint16, uint16, byte, byte, byte
            target_state & 0xFF,
            vin_fp,
            vout_fp,
            gpio & 0xFF,
            delay & 0xFF,
            interlock_scaled
        )
        
        # Add modifiers
        if modifiers:
            packet += bytes(modifiers[:256])
        
        # Write to file
        filename = f"state_{index:04d}_s{target_state:02d}.bin"
        filepath = self.state_dir / filename
        
        with open(filepath, "wb") as f:
            f.write(packet)
        
        self.stats["state_seeds"] += 1
        self.stats["total_files"] += 1
        
        return filepath
    
    def convert_adc_seed_to_state(self, adc_seed: Dict[str, Any], index: int) -> Path:
        """
        Convert ADC seeds into state machine seeds.
        
        ADC readings affect state transitions, so we integrate them
        into the state machine corpus.
        """
        # Extract ADC values
        channel = adc_seed.get("channel", "vin")
        value = adc_seed.get("value", adc_seed.get("adc_value", 2048))
        
        if isinstance(value, str):
            value = int(value, 16) if value.startswith("0x") else int(value)
        
        # Convert ADC counts to voltage (assuming 12-bit, 3.3V reference)
        voltage = (value / 4096.0) * 3.3 * 20  # Assuming 20x voltage divider
        
        # Create state seed with this voltage
        state_seed = {
            "target_state": 5,  # STATE_CHECK_INPUT_VOLTAGE
            "vin": voltage if "vin" in channel.lower() else 48.0,
            "vout": voltage if "vout" in channel.lower() else 12.0,
            "gpio": 0x01,  # PGOOD high
            "delay": 0,
            "interlock_current": 0.05,
            "modifiers": []
        }
        
        filepath = self.convert_state_seed(state_seed, index + 10000)  # Offset index
        self.stats["adc_seeds_integrated"] += 1
        
        return filepath
    
    def convert_seeds_json(self, json_path: str) -> Dict[str, int]:
        """
        Convert a JSON file containing seeds to binary corpus.
        
        Expected JSON structure:
        {
            "pmbus_seeds": [...],
            "i2c_seeds": [...],
            "state_seeds": [...],
            "adc_seeds": [...]  # Optional
        }
        """
        with open(json_path, "r") as f:
            seeds = json.load(f)
        
        # Convert PMBus seeds
        pmbus_seeds = seeds.get("pmbus_seeds", seeds.get("pmbus", []))
        for i, seed in enumerate(pmbus_seeds):
            self.convert_pmbus_seed(seed, i)
        
        # Convert I2C seeds
        i2c_seeds = seeds.get("i2c_seeds", seeds.get("i2c", []))
        for i, seed in enumerate(i2c_seeds):
            self.convert_i2c_seed(seed, i)
        
        # Convert State seeds
        state_seeds = seeds.get("state_seeds", seeds.get("state", []))
        for i, seed in enumerate(state_seeds):
            self.convert_state_seed(seed, i)
        
        # Convert ADC seeds (integrate into state corpus)
        adc_seeds = seeds.get("adc_seeds", seeds.get("adc", []))
        for i, seed in enumerate(adc_seeds):
            self.convert_adc_seed_to_state(seed, i)
        
        return self.stats
    
    def generate_from_agent(
        self,
        protocol: str,
        count: int = 50,
        query: Optional[str] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, int]:
        """Generate seeds using the real AgentOrchestrator and write to corpus.

        This replaces the legacy week-1 Agent 1 generator.
        """

        if protocol not in {"i2c", "pmbus", "3p3z"}:
            raise ValueError(f"Unsupported protocol: {protocol}")

        orchestrator = AgentOrchestrator()

        if query is None:
            if protocol == "i2c":
                query = "I2C device address ranges, register map, transaction format, limits"
            elif protocol == "pmbus":
                query = "PMBus address ranges, supported commands, command data lengths, limits"
            else:
                query = "3P3Z filter coefficient ranges, Q format, scaling factors, stability constraints"

        constraints = orchestrator.constraint_agent.extract_constraints(query=query)
        seeds: List[Seed] = orchestrator.seed_agent.run(
            protocol=protocol,
            count=count,
            constraints=constraints,
            feedback=feedback,
        )

        if protocol == "i2c":
            for i, seed in enumerate(seeds):
                self.convert_i2c_seed({"sequence": list(seed.data)}, i)
        elif protocol == "pmbus":
            for i, seed in enumerate(seeds):
                cmd = seed.data[0] if seed.data else 0
                data = list(seed.data[1:])
                self.convert_pmbus_seed({"command": cmd, "data": data}, i)
        else:
            # 3p3z: write raw to its own directory under output_dir
            p3z_dir = self.output_dir / "3p3z"
            p3z_dir.mkdir(exist_ok=True)
            for i, seed in enumerate(seeds):
                (p3z_dir / f"3p3z_{i:04d}_{seed.category}.bin").write_bytes(seed.data)
                self.stats["total_files"] += 1

        return self.stats

    
    def _generate_state_seeds(self) -> List[Dict[str, Any]]:
        """
        Generate state machine specific seeds.
        """
        seeds = []
        
        # Normal operation sequence
        for state in range(18):  # States 0-17
            seeds.append({
                "target_state": state,
                "vin": 48.0,  # Nominal
                "vout": 12.0,  # Nominal
                "gpio": 0x01,  # PGOOD=1
                "delay": 0,
                "interlock_current": 0.05
            })
        
        # Boundary voltage conditions
        boundary_voltages = [
            (35.9, "vin_under"),    # Just under min
            (36.1, "vin_min"),      # Just over min
            (59.9, "vin_max"),      # Just under max
            (60.1, "vin_over"),     # Just over max
            (0.0, "vin_zero"),      # Zero voltage
            (100.0, "vin_extreme"), # Extreme high
        ]
        
        for vin, name in boundary_voltages:
            seeds.append({
                "target_state": 5,  # CHECK_INPUT_VOLTAGE
                "vin": vin,
                "vout": 12.0,
                "gpio": 0x01,
                "delay": 15,  # Past threshold
                "interlock_current": 0.05
            })
        
        # Output voltage boundary tests
        for vout in [10.9, 11.0, 11.4, 11.5, 12.5, 12.6, 13.0]:
            seeds.append({
                "target_state": 9,  # VERIFY_PRECHARGE
                "vin": 48.0,
                "vout": vout,
                "gpio": 0x01,
                "delay": 0,
                "interlock_current": 0.05
            })
        
        # GPIO conflict scenarios
        gpio_scenarios = [
            0x00,  # Nothing enabled
            0x01,  # PGOOD only
            0x02,  # Discharge enabled
            0x03,  # Both (conflict!)
            0xFF,  # All high (chaos)
        ]
        
        for gpio in gpio_scenarios:
            seeds.append({
                "target_state": 11,  # ENABLE_VDRV
                "vin": 48.0,
                "vout": 12.0,
                "gpio": gpio,
                "delay": 0,
                "interlock_current": 0.05
            })
        
        # Power-down sequence
        for state in [50, 51, 52, 53, 54, 55, 56]:
            seeds.append({
                "target_state": state,
                "vin": 48.0,
                "vout": 8.0,  # Dropping output
                "gpio": 0x00,
                "delay": 0,
                "interlock_current": 0.0
            })
        
        return seeds
    
    def generate_report(self) -> str:
        """Generate a summary report of the conversion."""
        report = [
            "=" * 60,
            "AFL++ Seed Corpus Conversion Report",
            "=" * 60,
            "",
            f"Output Directory: {self.output_dir}",
            "",
            "Seeds Generated:",
            f"  PMBus seeds:         {self.stats['pmbus_seeds']:4d}  -> {self.pmbus_dir}",
            f"  I2C seeds:           {self.stats['i2c_seeds']:4d}  -> {self.i2c_dir}",
            f"  State machine seeds: {self.stats['state_seeds']:4d}  -> {self.state_dir}",
            f"  ADC->State integrated: {self.stats['adc_seeds_integrated']:4d}",
            "",
            f"Total files: {self.stats['total_files']}",
            "",
            "Usage:",
            "  PMBus:  afl-fuzz -i corpus/pmbus -o findings ./fuzz_pmbus @@",
            "  I2C:    afl-fuzz -i corpus/i2c -o findings ./fuzz_i2c @@",
            "  State:  afl-fuzz -i corpus/state -o findings ./fuzz_state @@",
            "",
            "=" * 60,
        ]
        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description="Convert LLM-generated seeds to AFL++ binary corpus"
    )
    parser.add_argument(
        "--input", "-i",
        help="Input JSON file with seeds"
    )
    parser.add_argument(
        "--output", "-o",
        default="../../data/corpus",
        help="Output directory for binary corpus (default: ../../data/corpus)"
    )
    parser.add_argument(
        "--generate-from-agent", "-g",
        action="store_true",
        help="Generate seeds directly from Agent 1"
    )
    
    args = parser.parse_args()
    
    # Resolve output path
    script_dir = Path(__file__).parent
    output_dir = script_dir / args.output
    
    converter = SeedCorpusConverter(str(output_dir))
    
    if args.generate_from_agent:
        print("[*] Generating seeds from Agent 1...")
        stats = converter.generate_from_agent()
    elif args.input:
        print(f"[*] Converting seeds from {args.input}...")
        stats = converter.convert_seeds_json(args.input)
    else:
        # Default: generate from agent
        print("[*] No input specified, generating from Agent 1...")
        stats = converter.generate_from_agent()
    
    # Print report
    print(converter.generate_report())
    
    # Save stats
    stats_path = output_dir / "conversion_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"[*] Stats saved to {stats_path}")


if __name__ == "__main__":
    main()
