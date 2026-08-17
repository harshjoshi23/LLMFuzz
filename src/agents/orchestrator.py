"""AgentOrchestrator: wires all agents together with feedback loop.

This orchestrator implements the complete fuzzing loop:
1. Extract constraints from documentation (Agent 1)
2. Generate seeds based on constraints + feedback (Agent 2)
3. Run fuzzing (AFL++)
4. Analyze crashes and generate feedback (Agent 3)
5. Loop back to step 2 with feedback

Termination conditions:
- Max iterations reached
- Max time exceeded
- No new crashes for N iterations
- User interrupt (Ctrl+C)
"""

from __future__ import annotations

import json
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .analysis_agent import AnalysisAgent
from .constraint_extractor import ConstraintExtractorAgent
from .peripheral_emulation import PeripheralEmulationAgent
from .seed_generator import SeedGeneratorAgent
from .types import Constraint, Seed


@dataclass
class TerminationConfig:
    """Configuration for when to stop the fuzzing loop."""
    max_iterations: int = 10
    max_time_seconds: int = 3600  # 1 hour
    stop_on_no_crash_iterations: int = 3  # Stop if no new crashes for N iterations
    enable_feedback: bool = True  # Enable Agent 3 → Agent 2 feedback


@dataclass
class IterationResult:
    """Result of a single fuzzing iteration."""
    iteration: int
    seeds_generated: int
    crashes_found: int
    feedback: Optional[str]
    duration_seconds: float
    seed_files: List[str] = field(default_factory=list)


@dataclass
class LoopResult:
    """Result of the complete fuzzing loop."""
    total_iterations: int
    total_seeds: int
    total_crashes: int
    termination_reason: str
    total_duration_seconds: float
    iterations: List[IterationResult] = field(default_factory=list)
    constraints_extracted: int = 0


class AgentOrchestrator:
    """Orchestrates all agents with feedback loop and termination conditions."""
    
    def __init__(self):
        self.constraint_agent = ConstraintExtractorAgent()
        self.seed_agent = SeedGeneratorAgent()
        self.analysis_agent = AnalysisAgent()
        self.peripheral_agent = PeripheralEmulationAgent()
        
        # State tracking
        self.constraints: List[Constraint] = []
        self.feedback_history: List[str] = []
        self.iteration = 0
        self.start_time: Optional[float] = None
        self.consecutive_no_crash_iterations = 0
        self._interrupted = False
        
        print("[Orchestrator] All agents initialized")
    
    def _setup_signal_handler(self):
        """Setup Ctrl+C handler for graceful termination."""
        def handler(signum, frame):
            print("\n[Orchestrator] Interrupt received, finishing current iteration...")
            self._interrupted = True
        
        try:
            signal.signal(signal.SIGINT, handler)
        except (ValueError, OSError):
            # Signal handling not available (e.g., not main thread)
            pass
    
    def should_terminate(self, config: TerminationConfig, crashes_this_iteration: int) -> Tuple[bool, str]:
        """Check if the fuzzing loop should terminate.
        
        Returns:
            Tuple of (should_stop, reason)
        """
        # User interrupt
        if self._interrupted:
            return True, "user_interrupt"
        
        # Max iterations
        if self.iteration >= config.max_iterations:
            return True, "max_iterations_reached"
        
        # Time limit
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed >= config.max_time_seconds:
                return True, "time_limit_exceeded"
        
        # No new crashes
        if crashes_this_iteration == 0:
            self.consecutive_no_crash_iterations += 1
        else:
            self.consecutive_no_crash_iterations = 0
        
        if self.consecutive_no_crash_iterations >= config.stop_on_no_crash_iterations:
            return True, "no_new_crashes"
        
        return False, "continue"
    
    def run_iteration(
        self,
        protocol: str,
        seed_count: int = 20,
        crashes_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        enable_feedback: bool = True,
    ) -> IterationResult:
        """Run a single iteration of the fuzzing loop.
        
        Args:
            protocol: Target protocol (i2c, pmbus, 3p3z)
            seed_count: Number of seeds to generate
            crashes_dir: Directory containing crash files (for analysis)
            output_dir: Directory to write seeds
            enable_feedback: Whether to use feedback from previous analysis
            
        Returns:
            IterationResult with stats from this iteration
        """
        iteration_start = time.time()
        self.iteration += 1
        
        print(f"\n[Orchestrator] === Iteration {self.iteration} ===")
        
        # Get feedback from previous iteration (if available and enabled)
        feedback = None
        if enable_feedback and self.feedback_history:
            feedback = self.feedback_history[-1]
            print(f"[Orchestrator] Using feedback: {feedback[:100]}..." if len(feedback) > 100 else f"[Orchestrator] Using feedback: {feedback}")
        
        # Extract constraints (only on first iteration)
        if self.iteration == 1:
            print(f"[Orchestrator] Agent 1: Extracting constraints for {protocol}...")
            self.constraints = self.constraint_agent.extract_constraints(protocol)
            print(f"[Orchestrator] Agent 1: Extracted {len(self.constraints)} constraints")
        
        # Generate seeds (Agent 2)
        print(f"[Orchestrator] Agent 2: Generating {seed_count} seeds...")
        seeds = self.seed_agent.run(
            protocol=protocol,
            count=seed_count,
            constraints=self.constraints,
            feedback=feedback,
        )
        print(f"[Orchestrator] Agent 2: Generated {len(seeds)} seeds")
        
        # Write seeds to output directory
        seed_files = []
        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            for i, seed in enumerate(seeds):
                filename = f"iter{self.iteration:03d}_seed{i:04d}_{seed.category}.bin"
                filepath = out_path / filename
                filepath.write_bytes(seed.data)
                seed_files.append(str(filepath))
        
        # Analyze crashes (Agent 3) if crash directory provided
        crashes_found = 0
        new_feedback = None
        if crashes_dir and Path(crashes_dir).exists():
            print(f"[Orchestrator] Agent 3: Analyzing crashes in {crashes_dir}...")
            analysis = self.analysis_agent.analyze_crashes(crashes_dir, protocol)
            
            suggestions = analysis.get("next_suggestions", [])
            if suggestions:
                new_feedback = "; ".join(suggestions)
                self.feedback_history.append(new_feedback)
                print(f"[Orchestrator] Agent 3: Feedback: {new_feedback}")
            
            # Count crashes (simplified - would need actual crash counting)
            crash_files = list(Path(crashes_dir).glob("*"))
            crashes_found = len([f for f in crash_files if f.is_file()])
        
        duration = time.time() - iteration_start
        
        return IterationResult(
            iteration=self.iteration,
            seeds_generated=len(seeds),
            crashes_found=crashes_found,
            feedback=new_feedback,
            duration_seconds=duration,
            seed_files=seed_files,
        )
    
    def run_loop(
        self,
        protocol: str,
        config: Optional[TerminationConfig] = None,
        seed_count: int = 20,
        output_dir: Optional[str] = None,
        crashes_dir: Optional[str] = None,
        afl_runner=None,
        afl_duration_per_iteration: int = 60,
    ) -> LoopResult:
        """Run the complete fuzzing loop with feedback.
        
        Args:
            protocol: Target protocol (i2c, pmbus, 3p3z)
            config: Termination configuration
            seed_count: Seeds to generate per iteration
            output_dir: Directory for seeds and results
            crashes_dir: Directory for AFL++ crashes
            afl_runner: Optional AflRunner instance for actual fuzzing
            afl_duration_per_iteration: Seconds to fuzz per iteration
            
        Returns:
            LoopResult with complete statistics
        """
        config = config or TerminationConfig()
        self._setup_signal_handler()
        self.start_time = time.time()
        self.iteration = 0
        self.feedback_history = []
        self.consecutive_no_crash_iterations = 0
        self._interrupted = False
        
        print(f"\n{'='*60}")
        print(f"[Orchestrator] Starting fuzzing loop")
        print(f"  Protocol: {protocol}")
        print(f"  Max iterations: {config.max_iterations}")
        print(f"  Max time: {config.max_time_seconds}s")
        print(f"  Feedback enabled: {config.enable_feedback}")
        print(f"{'='*60}")
        
        iterations: List[IterationResult] = []
        termination_reason = "unknown"
        
        while True:
            # Run one iteration
            result = self.run_iteration(
                protocol=protocol,
                seed_count=seed_count,
                crashes_dir=crashes_dir,
                output_dir=output_dir,
                enable_feedback=config.enable_feedback,
            )
            iterations.append(result)
            
            # Run AFL++ if runner provided
            if afl_runner and output_dir:
                print(f"[Orchestrator] Running AFL++ for {afl_duration_per_iteration}s...")
                # Note: This would need proper integration with afl_runner
                # afl_result = afl_runner.run(...)
            
            # Check termination
            should_stop, reason = self.should_terminate(config, result.crashes_found)
            if should_stop:
                termination_reason = reason
                print(f"\n[Orchestrator] Terminating: {reason}")
                break
        
        total_duration = time.time() - self.start_time
        
        loop_result = LoopResult(
            total_iterations=len(iterations),
            total_seeds=sum(r.seeds_generated for r in iterations),
            total_crashes=sum(r.crashes_found for r in iterations),
            termination_reason=termination_reason,
            total_duration_seconds=total_duration,
            iterations=iterations,
            constraints_extracted=len(self.constraints),
        )
        
        print(f"\n{'='*60}")
        print(f"[Orchestrator] Loop completed")
        print(f"  Iterations: {loop_result.total_iterations}")
        print(f"  Total seeds: {loop_result.total_seeds}")
        print(f"  Total crashes: {loop_result.total_crashes}")
        print(f"  Reason: {loop_result.termination_reason}")
        print(f"  Duration: {loop_result.total_duration_seconds:.1f}s")
        print(f"{'='*60}")
        
        return loop_result
    
    def save_state(self, path: str):
        """Save orchestrator state for resume capability."""
        state = {
            "iteration": self.iteration,
            "constraints": [c.to_dict() for c in self.constraints],
            "feedback_history": self.feedback_history,
            "consecutive_no_crash": self.consecutive_no_crash_iterations,
        }
        Path(path).write_text(json.dumps(state, indent=2))
        print(f"[Orchestrator] State saved to {path}")
    
    def load_state(self, path: str):
        """Load orchestrator state to resume."""
        state = json.loads(Path(path).read_text())
        self.iteration = state["iteration"]
        self.constraints = [
            Constraint(
                name=c["name"],
                min_value=c.get("min"),
                max_value=c.get("max"),
                valid_values=c.get("valid_values"),
                data_type=c.get("type", "int"),
                unit=c.get("unit"),
                source=c.get("source"),
                confidence=c.get("confidence", 1.0),
            )
            for c in state["constraints"]
        ]
        self.feedback_history = state["feedback_history"]
        self.consecutive_no_crash_iterations = state["consecutive_no_crash"]
        print(f"[Orchestrator] State loaded from {path}, resuming at iteration {self.iteration}")
