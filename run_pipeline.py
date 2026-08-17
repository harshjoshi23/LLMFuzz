#!/usr/bin/env python3
"""
End-to-End Fuzzing Pipeline
Orchestrates the complete workflow: crawl -> seed gen -> fuzz -> report

This is the MAIN entry point for the LLM Firmware Fuzzer.

Usage:
    python run_pipeline.py --target ./middleware --duration 1h
    
    # Or with more options:
    python run_pipeline.py \
        --target ./middleware \
        --confluence-url "https://confluence.../page/123" \
        --duration 3600 \
        --output ./results
"""

import os
import sys
import json
import argparse
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.agents import AgentOrchestrator, Seed


from src.crawlers import (
    LocalRepoCrawler, 
    LocalDocumentCrawler,
    export_manual_parameters

)
from src.reporters import ReportGenerator, FuzzingResults, CrashInfo, parse_afl_output
from src.harness.harness_generator import HarnessGenerator
from src.utils.config_manager import Config, get_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FuzzingPipeline:
    """End-to-end fuzzing pipeline orchestrator.

    This pipeline is wired to the **real agents** in `src/agents/agents.py` and does
    *not* use the legacy week-1 agent prototypes.

    Loop:
      1) Extract constraints from datasheets via RAG+LLM
      2) Generate protocol-aware seeds (I2C/PMBus/3P3Z)
      3) Write seeds into `data/corpus/<protocol>/` for AFL++
      4) Run AFL++ (optional)
      5) Analyze crashes and feed back into next seed generation iteration
    """

    
    def __init__(
        self,
        target_path: str,
        output_dir: str = "results",
        config: Optional[Config] = None
    ):
        """
        Initialize the pipeline.
        
        Args:
            target_path: Path to firmware/middleware to fuzz
            output_dir: Directory for outputs (seeds, findings, reports)
            config: Configuration object (uses default if None)
        """
        self.target_path = Path(target_path)
        self.output_dir = Path(output_dir)
        self.config = config or get_config()
        
        # Create output directories
        self.seeds_dir = self.output_dir / "seeds"
        self.findings_dir = self.output_dir / "findings"
        self.reports_dir = self.output_dir / "reports"
        
        for d in [self.seeds_dir, self.findings_dir, self.reports_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # State tracking
        self.constraints = {}
        self.documentation = []
        self.seeds_generated = 0
        self.fuzzing_stats = {}
    
    def step_1_crawl_documentation(
        self,
        confluence_url: Optional[str] = None,
        local_docs_path: Optional[str] = None,
        protocol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Step 1: Extract constraints from documentation.

        Policy: **No hardcoded defaults**.

        This step may collect raw documentation chunks from the target repo and/or local
        docs path, but the *constraints* used by the pipeline must be produced by the
        real `ConstraintExtractorAgent` (RAG + LLM).
        """
        logger.info("=" * 60)
        logger.info("STEP 1: Crawling Documentation")
        logger.info("=" * 60)

        results: Dict[str, Any] = {
            "chunks_extracted": 0,
            "parameters_found": 0,
            "sources": [],
        }

        # Collect raw documentation (optional / for reporting only)
        if self.target_path.exists():
            logger.info(f"Crawling target repository: {self.target_path}")
            crawler = LocalRepoCrawler(str(self.target_path))

            doc_files = crawler.find_documentation_files()
            source_files = crawler.find_source_files()
            logger.info(f"  Found {len(doc_files)} documentation files")
            logger.info(f"  Found {len(source_files)} source files")

            chunks = crawler.extract_all_documentation()
            self.documentation.extend(chunks)
            results["chunks_extracted"] += len(chunks)
            results["sources"].append(str(self.target_path))

        if local_docs_path and Path(local_docs_path).exists():
            logger.info(f"Crawling local docs: {local_docs_path}")
            crawler = LocalRepoCrawler(str(local_docs_path))
            chunks = crawler.extract_all_documentation()
            self.documentation.extend(chunks)
            results["chunks_extracted"] += len(chunks)
            results["sources"].append(local_docs_path)

        # Derive query for constraint extraction
        protocol = (protocol or "").lower() or "unknown"
        if protocol == "i2c":
            query = "I2C device address ranges, register map, transaction format, timing and limits"
        elif protocol == "pmbus":
            query = "PMBus address ranges, supported commands, command data lengths, limits"
        elif protocol == "3p3z":
            query = "3P3Z filter coefficient ranges, Q format, scaling factors, stability constraints"
        else:
            query = "Protocol constraints: addresses, register map, frame format, numeric limits"

        # IMPORTANT: constraints must come from the real agent (RAG + LLM)
        orchestrator = AgentOrchestrator()
        constraints = orchestrator.constraint_agent.extract_constraints(topic=query)

        # Normalize into pipeline's constraints dict format
        # NOTE: agent returns List[Constraint]
        self.constraints = {}
        for c in constraints:
            self.constraints[c.name] = {
                "min": c.min_value,
                "max": c.max_value,
                "valid_values": c.valid_values,
                "type": c.data_type,
                "unit": c.unit,
                "source": c.source,
                "confidence": c.confidence,
            }


        results["parameters_found"] = len(self.constraints)

        # Save constraints
        constraints_file = self.output_dir / "constraints.json"
        with open(constraints_file, "w") as f:
            json.dump(
                {
                    "source": "rag_llm_extraction",
                    "timestamp": datetime.now().isoformat(),
                    "protocol": protocol,
                    "query": query,
                    "parameters": self.constraints,
                },
                f,
                indent=2,
            )

        logger.info(f"  Extracted {results['chunks_extracted']} documentation chunks")
        logger.info(f"  Found {results['parameters_found']} parameter constraints")
        logger.info(f"  Saved constraints to {constraints_file}")

        return results

    
    def step_2_generate_seeds(
        self,
        protocol: str,
        count: int = 100,
        topics: Optional[List[str]] = None,
        use_llm: bool = True,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Step 2: Generate fuzzing seeds using the real LLM agents.

        Notes:
        - This is intentionally *not* heuristic/random seed generation.
        - Seeds are written into the pipeline output directory *and* optionally into
          `data/corpus/<protocol>/` so AFL++ can use them as an initial corpus.
        """

        if protocol not in {"i2c", "pmbus", "3p3z"}:
            raise ValueError(f"Unsupported protocol: {protocol}")

        logger.info("=" * 60)
        logger.info("STEP 2: Generating Fuzzing Seeds (LLM + RAG)")
        logger.info("=" * 60)

        results: Dict[str, Any] = {
            "protocol": protocol,
            "seeds_generated": 0,
            "seed_files": [],
        }

        if not use_llm:
            raise RuntimeError("use_llm=False is no longer supported; legacy generation removed")

        topics = topics or [
            "I2C addressing and transactions",
            "PMBus command set and data formats",
            "3P3Z digital control loop coefficients and scaling",
        ]

        # Build per-protocol query that is used by the constraint extractor.
        if protocol == "i2c":
            query = "I2C device address ranges, register map, transaction format, limits"
        elif protocol == "pmbus":
            query = "PMBus address ranges, supported commands, command data lengths, limits"
        else:
            query = "3P3Z filter coefficient ranges, Q format, scaling factors, stability constraints"

        # Use orchestrator agents
        orchestrator = AgentOrchestrator()
        constraints = orchestrator.constraint_agent.extract_constraints(topic=query)


        # Feed constraints into seed generation
        seeds: List[Seed] = orchestrator.seed_agent.run(
            protocol=protocol,
            count=count,
            constraints=constraints,
            feedback=feedback,
        )

        # Write seeds into results/<...>/seeds and into data/corpus/<protocol>
        corpus_root = Path(self.config.paths.corpus) if hasattr(self.config, "paths") else (project_root / "data" / "corpus")
        corpus_dir = corpus_root / protocol
        corpus_dir.mkdir(parents=True, exist_ok=True)

        for i, seed in enumerate(seeds):
            name = f"seed_{i:04d}_{seed.category}.bin"

            out_file = self.seeds_dir / name
            out_file.write_bytes(seed.data)
            results["seed_files"].append(str(out_file))

            corpus_file = corpus_dir / name
            corpus_file.write_bytes(seed.data)

        results["seeds_generated"] = len(seeds)
        self.seeds_generated = len(seeds)

        logger.info(f"  Generated {len(seeds)} seeds for protocol={protocol}")
        logger.info(f"  Saved to {self.seeds_dir}/")
        logger.info(f"  AFL++ corpus: {corpus_dir}/")

        return results

    
    def step_3_build_harness(
        self,
        harness_type: str = "3p3z",
        source_files: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Step 3: Build the fuzzing harness.
        
        Args:
            harness_type: Type of harness (3p3z, pmbus, i2c)
            source_files: Additional source files to link
            
        Returns:
            Dict with build results
        """
        logger.info("="*60)
        logger.info("STEP 3: Building Fuzzing Harness")
        logger.info("="*60)
        
        results = {
            "harness_generated": False,
            "harness_compiled": False,
            "harness_path": None
        }
        
        # Generate harness code
        generator = HarnessGenerator(str(self.output_dir / "constraints.json"))
        
        if harness_type == "3p3z":
            harness_code = generator.generate_3p3z_harness()
        else:
            harness_code = generator.generate_generic_harness(
                function_name=f"fuzz_{harness_type}",
                include_path=f"{harness_type}.h"
            )
        
        # Save harness
        harness_file = self.output_dir / f"harness_{harness_type}.c"
        with open(harness_file, 'w') as f:
            f.write(harness_code)
        
        results["harness_generated"] = True
        results["harness_path"] = str(harness_file)
        
        logger.info(f"  Generated harness: {harness_file}")
        
        # Attempt compilation (requires AFL++ in PATH)
        try:
            output_binary = self.output_dir / f"fuzz_{harness_type}"
            compile_cmd = [
                "afl-clang-fast",
                str(harness_file),
                "-o", str(output_binary),
                "-lm"  # Link math library
            ]
            
            # Add source files if provided
            if source_files:
                compile_cmd.extend(source_files)
            
            logger.info(f"  Compiling: {' '.join(compile_cmd)}")
            
            # This will fail on Windows without WSL
            # subprocess.run(compile_cmd, check=True, capture_output=True)
            # results["harness_compiled"] = True
            
            logger.info("  (Compilation skipped - requires WSL with AFL++)")
            
        except Exception as e:
            logger.warning(f"  Compilation failed: {e}")
            logger.info("  Harness generated but not compiled")
        
        return results
    
    def step_4_run_fuzzing(
        self,
        duration_seconds: int = 300,
        harness_binary: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Step 4: Run AFL++ fuzzing campaign.
        
        Args:
            duration_seconds: How long to fuzz
            harness_binary: Path to compiled harness (uses existing if None)
            
        Returns:
            Dict with fuzzing results
        """
        logger.info("="*60)
        logger.info("STEP 4: Running Fuzzing Campaign")
        logger.info("="*60)
        
        results = {
            "fuzzing_ran": False,
            "duration_seconds": duration_seconds,
            "crashes_found": 0,
            "execs_total": 0
        }
        
        # Check if we can run AFL++
        if not harness_binary:
            harness_binary = str(self.output_dir / "fuzz_3p3z")
        
        if not Path(harness_binary).exists():
            logger.warning(f"  Harness binary not found: {harness_binary}")
            logger.info("  Skipping fuzzing - compile harness first")
            logger.info("  Use: wsl -e afl-clang-fast harness.c -o fuzz_target")
            return results
        
        # Build AFL++ command
        afl_cmd = [
            "wsl", "-e", "bash", "-c",
            f"AFL_SKIP_CPUFREQ=1 afl-fuzz "
            f"-i {self.seeds_dir} "
            f"-o {self.findings_dir} "
            f"-V {duration_seconds} "
            f"-- {harness_binary} @@"
        ]
        
        logger.info(f"  Running: {' '.join(afl_cmd[:3])}...")
        logger.info(f"  Duration: {duration_seconds} seconds")
        
        try:
            subprocess.run(afl_cmd, check=True, timeout=duration_seconds + 60)
            results["fuzzing_ran"] = True
            
            # Count crashes
            crashes_dir = self.findings_dir / "crashes"
            if crashes_dir.exists():
                crashes = list(crashes_dir.glob("id:*"))
                results["crashes_found"] = len(crashes)
            
        except subprocess.TimeoutExpired:
            logger.info("  Fuzzing completed (timeout)")
            results["fuzzing_ran"] = True
        except Exception as e:
            logger.error(f"  Fuzzing failed: {e}")
        
        return results
    
    def step_5_generate_report(self) -> Dict[str, Any]:
        """
        Step 5: Generate stakeholder-friendly report.
        
        Returns:
            Dict with report paths
        """
        logger.info("="*60)
        logger.info("STEP 5: Generating Report")
        logger.info("="*60)
        
        results = {
            "report_generated": False,
            "report_paths": []
        }
        
        # Parse AFL++ output
        if self.findings_dir.exists():
            fuzzing_results = parse_afl_output(
                str(self.findings_dir),
                self.constraints
            )
            fuzzing_results.target_name = str(self.target_path.name)
        else:
            # Create empty results
            fuzzing_results = FuzzingResults(
                target_name=str(self.target_path.name),
                parameter_constraints=self.constraints
            )
        
        # Generate report
        reporter = ReportGenerator(fuzzing_results)
        
        # Save markdown report
        md_path = self.reports_dir / "fuzzing_report.md"
        reporter.save_markdown(str(md_path))
        results["report_paths"].append(str(md_path))
        
        # Save JSON report
        json_path = self.reports_dir / "fuzzing_report.json"
        reporter.save_json(str(json_path))
        results["report_paths"].append(str(json_path))
        
        results["report_generated"] = True
        
        # Print summary
        logger.info(f"  In-range crashes: {len(reporter.in_range_crashes)}")
        logger.info(f"  Out-of-range crashes: {len(reporter.out_of_range_crashes)}")
        logger.info(f"  Reports saved to: {self.reports_dir}/")
        
        # Print email summary
        print("\n" + "="*60)
        print("STAKEHOLDER EMAIL SUMMARY:")
        print("="*60)
        print(reporter.generate_stakeholder_email())
        
        return results
    
    def run_full_pipeline(
        self,
        duration_seconds: int = 300,
        skip_fuzzing: bool = False,
        protocol: Optional[str] = None,
        confluence_url: Optional[str] = None,
        local_docs_path: Optional[str] = None,
    ) -> Dict[str, Any]:

        """
        Run the complete fuzzing pipeline.
        
        Args:
            duration_seconds: Fuzzing campaign duration
            skip_fuzzing: If True, skip actual fuzzing (for testing)
            
        Returns:
            Dict with all results
        """
        logger.info("="*60)
        logger.info("LLM FIRMWARE FUZZER - FULL PIPELINE")
        logger.info("="*60)
        logger.info(f"Target: {self.target_path}")
        logger.info(f"Output: {self.output_dir}")
        logger.info(f"Duration: {duration_seconds}s")
        logger.info("="*60)
        
        start_time = datetime.now()
        all_results = {}
        
        # Step 1: Crawl documentation / extract constraints (RAG + LLM)
        protocol = (protocol or getattr(self.config, "fuzzing_protocol", None) or "i2c")
        all_results["crawl"] = self.step_1_crawl_documentation(
            confluence_url=confluence_url,
            local_docs_path=local_docs_path,
            protocol=protocol,
        )

        # Step 2: Generate seeds
        all_results["seeds"] = self.step_2_generate_seeds(
            protocol=protocol,
            count=self.config.fuzzing_seed_count,
            use_llm=True,
        )


        # Step 3/4: Harness build + fuzzing run are optional and environment-dependent.
        # We keep existing harness build utilities, but prefer using prebuilt harnesses
        # in `src/harness/` when available.
        all_results["harness"] = {"skipped": True, "reason": "use src/harness binaries"}

        if not skip_fuzzing:
            all_results["fuzzing"] = self.step_4_run_fuzzing(duration_seconds)
        else:
            logger.info("STEP 4: Skipping fuzzing (--skip-fuzzing)")
            all_results["fuzzing"] = {"skipped": True}

        # Step 5: Generate report
        all_results["report"] = self.step_5_generate_report()

        
        # Summary
        end_time = datetime.now()
        all_results["summary"] = {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": (end_time - start_time).total_seconds(),
            "target": str(self.target_path),
            "output": str(self.output_dir)
        }
        
        # Save full results
        with open(self.output_dir / "pipeline_results.json", 'w') as f:
            json.dump(all_results, f, indent=2, default=str)
        
        logger.info("="*60)
        logger.info("PIPELINE COMPLETE")
        logger.info("="*60)
        
        return all_results


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="LLM Firmware Fuzzer - End-to-End Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python run_pipeline.py --target ./middleware
  
  # With Confluence documentation
  python run_pipeline.py --target ./middleware \\
      --confluence-url "https://confluence.../page/123"
  
  # Custom duration
  python run_pipeline.py --target ./middleware --duration 3600
  
  # Skip fuzzing (just generate seeds and harness)
  python run_pipeline.py --target ./middleware --skip-fuzzing
        """
    )
    
    parser.add_argument(
        "--target", "-t",
        required=True,
        help="Path to firmware/middleware directory to fuzz"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="results",
        help="Output directory (default: results)"
    )
    
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=300,
        help="Fuzzing duration in seconds (default: 300)"
    )
    
    parser.add_argument(
        "--confluence-url",
        help="Confluence page URL for documentation"
    )
    
    parser.add_argument(
        "--docs-path",
        help="Path to local documentation folder"
    )
    
    parser.add_argument(
        "--skip-fuzzing",
        action="store_true",
        help="Skip actual fuzzing (useful for testing)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    parser.add_argument(
        "--protocol", "-p",
        choices=["i2c", "pmbus", "3p3z"],
        default="i2c",
        help="Protocol to fuzz (default: i2c)"
    )

    parser.add_argument(
        "--seed-count",
        type=int,
        default=50,
        help="Number of LLM-generated seeds to create (default: 50)"
    )

    args = parser.parse_args()

    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create and run pipeline
    pipeline = FuzzingPipeline(
        target_path=args.target,
        output_dir=args.output
    )

    # Store CLI fuzz params on config (minimal surface-area change)
    pipeline.config.fuzzing_protocol = args.protocol
    pipeline.config.fuzzing_seed_count = args.seed_count

    
    results = pipeline.run_full_pipeline(
        duration_seconds=args.duration,
        skip_fuzzing=args.skip_fuzzing,
        protocol=args.protocol,
        confluence_url=args.confluence_url,
        local_docs_path=args.docs_path,
    )

    
    print(f"\nResults saved to: {args.output}/")
    print(f"  - Seeds: {args.output}/seeds/")
    print(f"  - Reports: {args.output}/reports/")


if __name__ == "__main__":
    main()
