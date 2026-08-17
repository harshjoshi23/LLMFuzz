#!/usr/bin/env python3
"""
Run Fuzzing Campaign - LLM-Enhanced Fuzzing Orchestrator

This script orchestrates the complete fuzzing pipeline:
1. Generate seeds using Agent 1 (LLM-based constraint extraction)
2. Convert seeds to AFL++ corpus format
3. Run AFL++ fuzzing campaign
4. Collect coverage data using Agent 3
5. Feed back to Agent 1 for improved seed generation
6. Generate final report

Part of: AI-Enhanced Fuzzing for Embedded Power Systems

Usage:
    python run_fuzzing_campaign.py --hours 4 --output results/
    python run_fuzzing_campaign.py --dry-run  # Test without actual fuzzing
"""

import os
import sys
import json
import time
import argparse
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class FuzzingCampaign:
    """
    Orchestrates the complete fuzzing campaign with LLM integration.
    """
    
    def __init__(
        self,
        output_dir: str,
        hours: float = 4.0,
        iterations: int = 3,
        parallel_instances: int = 1,
        dry_run: bool = False
    ):
        self.output_dir = Path(output_dir)
        self.hours = hours
        self.iterations = iterations
        self.parallel_instances = parallel_instances
        self.dry_run = dry_run
        
        # Create directory structure
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.corpus_dir = self.output_dir / "corpus"
        self.findings_dir = self.output_dir / "findings"
        self.reports_dir = self.output_dir / "reports"
        self.logs_dir = self.output_dir / "logs"
        
        for d in [self.corpus_dir, self.findings_dir, self.reports_dir, self.logs_dir]:
            d.mkdir(exist_ok=True)
        
        # Campaign state
        self.campaign_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = None
        self.stats = {
            "iterations_completed": 0,
            "seeds_generated": 0,
            "crashes_found": 0,
            "unique_paths": 0,
            "coverage_percentage": 0.0,
            "llm_guided_improvements": 0
        }
    
    def check_prerequisites(self) -> bool:
        """Check that required tools are available."""
        checks = []
        
        # Check for AFL++
        afl_check = shutil.which("afl-fuzz")
        if afl_check:
            checks.append(("AFL++", True, afl_check))
        else:
            checks.append(("AFL++", False, "Not found - install via WSL or Docker"))
        
        # Check for Python agents (real orchestrator)
        try:
            from src.agents import AgentOrchestrator
            checks.append(("LLM Agents (AgentOrchestrator)", True, "OK"))
        except ImportError as e:
            checks.append(("LLM Agents (AgentOrchestrator)", False, str(e)))

        # Check for harness binaries
        harness_dir = Path(__file__).parent
        for harness in ["fuzz_pmbus", "fuzz_i2c", "fuzz_state"]:
            harness_path = harness_dir / harness
            if harness_path.exists():
                checks.append((f"Harness: {harness}", True, str(harness_path)))
            else:
                checks.append((f"Harness: {harness}", False, "Not built - run build_harnesses.sh"))
        
        # Print results
        print("\n" + "=" * 60)
        print("Prerequisite Check")
        print("=" * 60)
        
        all_ok = True
        for name, status, message in checks:
            status_str = "✓" if status else "✗"
            print(f"  [{status_str}] {name}: {message}")
            if not status and "Harness" not in name:  # Harnesses are optional for dry-run
                all_ok = False
        
        print("=" * 60 + "\n")
        
        return all_ok or self.dry_run
    
    def generate_seeds(self, iteration: int) -> Dict[str, int]:
        """Generate seeds using the real LLM agents."""
        print(f"\n[Iteration {iteration}] Generating seeds with LLM agents...")

        if self.dry_run:
            print("  [DRY RUN] Would generate seeds here")
            return {"total_files": 0}

        try:
            from harness.seed_corpus_converter import SeedCorpusConverter

            corpus_iter_dir = self.corpus_dir / f"iter_{iteration:02d}"
            converter = SeedCorpusConverter(str(corpus_iter_dir))

            # Generate per protocol
            total_before = converter.stats["total_files"]
            converter.generate_from_agent(protocol="i2c", count=50)
            converter.generate_from_agent(protocol="pmbus", count=50)

            total_after = converter.stats["total_files"]
            generated = total_after - total_before

            self.stats["seeds_generated"] += generated

            print(f"  Generated {generated} seed files")
            return converter.stats

        except Exception as e:
            print(f"  [ERROR] Seed generation failed: {e}")
            return {"total_files": 0, "error": str(e)}

    
    def run_fuzzing(self, iteration: int, harness: str, duration_seconds: int) -> Dict[str, Any]:
        """Run AFL++ fuzzing for specified duration."""
        print(f"\n[Iteration {iteration}] Fuzzing {harness} for {duration_seconds}s...")
        
        if self.dry_run:
            print("  [DRY RUN] Would run fuzzing here")
            return {"status": "dry_run"}
        
        harness_path = Path(__file__).parent / harness
        if not harness_path.exists():
            print(f"  [SKIP] Harness not found: {harness_path}")
            return {"status": "skipped", "reason": "harness_not_found"}
        
        corpus_dir = self.corpus_dir / f"iter_{iteration:02d}" / harness.replace("fuzz_", "")
        findings_dir = self.findings_dir / harness / f"iter_{iteration:02d}"
        findings_dir.mkdir(parents=True, exist_ok=True)
        
        if not corpus_dir.exists() or not list(corpus_dir.iterdir()):
            print(f"  [SKIP] No corpus found: {corpus_dir}")
            return {"status": "skipped", "reason": "no_corpus"}
        
        # Build AFL++ command
        cmd = [
            "afl-fuzz",
            "-i", str(corpus_dir),
            "-o", str(findings_dir),
            "-t", "1000",  # 1 second timeout
            "-V", str(duration_seconds),  # Time limit
            "--", str(harness_path), "@@"
        ]
        
        log_file = self.logs_dir / f"{harness}_iter{iteration:02d}.log"
        
        try:
            print(f"  Running: {' '.join(cmd)}")
            
            with open(log_file, "w") as log:
                process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=str(harness_path.parent)
                )
                
                # Monitor progress
                start = time.time()
                while process.poll() is None and (time.time() - start) < duration_seconds + 60:
                    time.sleep(10)
                    # Could add progress monitoring here
                
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                
            return {"status": "completed", "log": str(log_file)}
            
        except Exception as e:
            print(f"  [ERROR] Fuzzing failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def collect_results(self, iteration: int) -> Dict[str, Any]:
        """Collect and analyze fuzzing results."""
        print(f"\n[Iteration {iteration}] Collecting results...")
        
        results = {
            "crashes": [],
            "hangs": [],
            "queue_size": 0,
            "coverage_estimate": 0.0
        }
        
        if self.dry_run:
            print("  [DRY RUN] Would collect results here")
            return results
        
        for harness in ["fuzz_pmbus", "fuzz_i2c", "fuzz_state"]:
            findings_path = self.findings_dir / harness / f"iter_{iteration:02d}"
            
            if not findings_path.exists():
                continue
            
            # Check for crashes
            crashes_dir = findings_path / "default" / "crashes"
            if crashes_dir.exists():
                crash_files = list(crashes_dir.iterdir())
                results["crashes"].extend([
                    {"harness": harness, "file": str(f)} 
                    for f in crash_files if f.name != "README.txt"
                ])
            
            # Check for hangs
            hangs_dir = findings_path / "default" / "hangs"
            if hangs_dir.exists():
                hang_files = list(hangs_dir.iterdir())
                results["hangs"].extend([
                    {"harness": harness, "file": str(f)}
                    for f in hang_files if f.name != "README.txt"
                ])
            
            # Count queue entries (unique paths)
            queue_dir = findings_path / "default" / "queue"
            if queue_dir.exists():
                results["queue_size"] += len(list(queue_dir.iterdir()))
        
        self.stats["crashes_found"] += len(results["crashes"])
        self.stats["unique_paths"] = results["queue_size"]
        
        print(f"  Crashes: {len(results['crashes'])}, Hangs: {len(results['hangs'])}, Paths: {results['queue_size']}")
        
        return results
    
    def analyze_with_oracle(self, iteration: int, results: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze crashes with the real LLM AnalysisAgent (replaces legacy oracle)."""
        print(f"\n[Iteration {iteration}] Analyzing crashes with LLM AnalysisAgent...")

        if self.dry_run:
            print("  [DRY RUN] Would analyze crashes here")
            return {"suggestions": []}

        try:
            from src.agents import AnalysisAgent, SeedGeneratorAgent, ConstraintExtractorAgent

            # Minimal wiring: analysis agent can optionally hold a ref to seed agent.
            constraint_agent = ConstraintExtractorAgent()
            seed_agent = SeedGeneratorAgent(constraint_agent)
            analysis_agent = AnalysisAgent(seed_agent)

            crash_files = [c["file"] for c in results.get("crashes", [])]
            if not crash_files:
                return {"suggestions": []}

            # Use the parent harness directory as crash_dir input.
            crash_dir = str(Path(crash_files[0]).parent)
            analysis = analysis_agent.run(crash_dir)

            self.stats["llm_guided_improvements"] += len(analysis.get("next_suggestions", []))

            print(f"  Crash files analyzed: {analysis.get('crashes_analyzed', 0)}")
            return analysis

        except Exception as e:
            print(f"  [ERROR] Analysis failed: {e}")
            return {"suggestions": [], "error": str(e)}

    
    def generate_report(self) -> str:
        """Generate final campaign report."""
        duration = datetime.now() - self.start_time if self.start_time else timedelta(0)
        
        report = [
            "=" * 70,
            "FUZZING CAMPAIGN REPORT",
            f"Campaign ID: {self.campaign_id}",
            f"Generated: {datetime.now().isoformat()}",
            "=" * 70,
            "",
            "CONFIGURATION",
            "-" * 40,
            f"  Duration: {self.hours} hours",
            f"  Iterations: {self.iterations}",
            f"  Parallel Instances: {self.parallel_instances}",
            f"  Output Directory: {self.output_dir}",
            "",
            "RESULTS SUMMARY",
            "-" * 40,
            f"  Iterations Completed: {self.stats['iterations_completed']}",
            f"  Seeds Generated: {self.stats['seeds_generated']}",
            f"  Crashes Found: {self.stats['crashes_found']}",
            f"  Unique Paths: {self.stats['unique_paths']}",
            f"  LLM-Guided Improvements: {self.stats['llm_guided_improvements']}",
            "",
            "EXECUTION",
            "-" * 40,
            f"  Actual Duration: {duration}",
            f"  Dry Run: {self.dry_run}",
            "",
        ]
        
        # Add crash details if any
        if self.stats["crashes_found"] > 0:
            report.extend([
                "CRASHES FOUND",
                "-" * 40,
            ])
            
            for harness in ["fuzz_pmbus", "fuzz_i2c", "fuzz_state"]:
                crashes_base = self.findings_dir / harness
                if crashes_base.exists():
                    for iter_dir in crashes_base.iterdir():
                        crashes_dir = iter_dir / "default" / "crashes"
                        if crashes_dir.exists():
                            for crash_file in crashes_dir.iterdir():
                                if crash_file.name != "README.txt":
                                    report.append(f"  - {harness}: {crash_file.name}")
            
            report.append("")
        
        report.extend([
            "NEXT STEPS",
            "-" * 40,
            "  1. Analyze crash files with 'afl-tmin' for minimization",
            "  2. Run crashes through debug builds for root cause",
            "  3. Document vulnerabilities found",
            "  4. Generate patches if applicable",
            "",
            "=" * 70,
        ])
        
        return "\n".join(report)
    
    def run(self):
        """Execute the complete fuzzing campaign."""
        print("\n" + "=" * 70)
        print("AI-Enhanced Fuzzing Campaign")
        print("=" * 70)
        print(f"Campaign ID: {self.campaign_id}")
        print(f"Duration: {self.hours} hours")
        print(f"Iterations: {self.iterations}")
        print(f"Output: {self.output_dir}")
        print("=" * 70)
        
        # Check prerequisites
        if not self.check_prerequisites():
            print("[FATAL] Prerequisites not met. Exiting.")
            return 1
        
        self.start_time = datetime.now()
        end_time = self.start_time + timedelta(hours=self.hours)
        
        # Calculate time per iteration and harness
        time_per_iteration = (self.hours * 3600) / self.iterations
        time_per_harness = time_per_iteration / 3  # 3 harnesses
        
        print(f"\nTime allocation: {time_per_harness:.0f}s per harness, {time_per_iteration:.0f}s per iteration")
        
        for iteration in range(1, self.iterations + 1):
            print(f"\n{'=' * 60}")
            print(f"ITERATION {iteration}/{self.iterations}")
            print(f"{'=' * 60}")
            
            # Check time remaining
            if datetime.now() >= end_time:
                print("[TIMEOUT] Campaign time limit reached")
                break
            
            # Step 1: Generate seeds
            seed_stats = self.generate_seeds(iteration)
            
            # Step 2: Run fuzzing on each harness
            for harness in ["fuzz_pmbus", "fuzz_i2c", "fuzz_state"]:
                if datetime.now() >= end_time:
                    break
                
                remaining = (end_time - datetime.now()).total_seconds()
                duration = min(int(time_per_harness), int(remaining))
                
                if duration > 0:
                    self.run_fuzzing(iteration, harness, duration)
            
            # Step 3: Collect results
            results = self.collect_results(iteration)
            
            # Step 4: Analyze with State Oracle
            analysis = self.analyze_with_oracle(iteration, results)
            
            # Step 5: Save iteration results
            iter_report = {
                "iteration": iteration,
                "seed_stats": seed_stats,
                "results": results,
                "analysis": analysis
            }
            
            report_path = self.reports_dir / f"iteration_{iteration:02d}.json"
            with open(report_path, "w") as f:
                json.dump(iter_report, f, indent=2, default=str)
            
            self.stats["iterations_completed"] = iteration
        
        # Generate final report
        report = self.generate_report()
        print("\n" + report)
        
        # Save report
        report_path = self.reports_dir / "final_report.txt"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nReport saved to: {report_path}")
        
        # Save stats
        stats_path = self.reports_dir / "campaign_stats.json"
        with open(stats_path, "w") as f:
            json.dump(self.stats, f, indent=2)
        
        return 0 if self.stats["crashes_found"] == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Run AI-enhanced fuzzing campaign"
    )
    parser.add_argument(
        "--hours", type=float, default=4.0,
        help="Campaign duration in hours (default: 4)"
    )
    parser.add_argument(
        "--iterations", type=int, default=3,
        help="Number of seed-generation iterations (default: 3)"
    )
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="Number of parallel AFL++ instances (default: 1)"
    )
    parser.add_argument(
        "--output", "-o", default="results",
        help="Output directory (default: results/)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Test campaign logic without actual fuzzing"
    )
    
    args = parser.parse_args()
    
    # Resolve output path
    script_dir = Path(__file__).parent.parent.parent  # 04_IMPLEMENTATION
    output_dir = script_dir / args.output
    
    campaign = FuzzingCampaign(
        output_dir=str(output_dir),
        hours=args.hours,
        iterations=args.iterations,
        parallel_instances=args.parallel,
        dry_run=args.dry_run
    )
    
    return campaign.run()


if __name__ == "__main__":
    sys.exit(main())
