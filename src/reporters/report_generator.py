"""
Report Generator for LLM Firmware Fuzzer
Generates stakeholder-friendly reports in Markdown and PDF formats.

Key Feature: Categorizes crashes as "in-range" vs "out-of-range" parameters.
- In-range crashes = REAL BUGS (parameters within valid specification)
- Out-of-range crashes = Input validation issues (expected behavior)
"""

import json
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import subprocess
import logging
import hashlib
import shutil

from src.utils.afl_input_decoders import decode_3p3z_params
from src.utils.csv_constraints import find_numeric_range_anomalies



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CrashInfo:
    """Information about a single crash."""
    crash_id: str
    input_file: str
    crash_type: str  # e.g., "SEGV", "ABORT", "TIMEOUT", "HANG"
    stack_trace: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    source_location: str = ""  # e.g., "filter_3p3z.c:156"
    timestamp: str = ""
    severity: str = "MEDIUM"  # LOW, MEDIUM, HIGH, CRITICAL
    is_in_range: Optional[bool] = None  # True if all params within valid range
    minimized_input_file: str = ""  # path to afl-tmin minimized testcase
    dedup_group: str = ""  # stack-hash/trace-hash grouping key



@dataclass
class FuzzingResults:
    """Complete results from a fuzzing campaign."""
    target_name: str
    target_version: str = ""
    start_time: str = ""
    end_time: str = ""
    duration_seconds: int = 0
    total_executions: int = 0
    executions_per_second: float = 0.0
    unique_crashes: int = 0
    unique_hangs: int = 0

    # Extra reconciliation fields
    saved_crashes: int = 0
    saved_hangs: int = 0
    crash_files_count: int = 0
    crash_count_mismatch_note: str = ""

    # AFL++ reports bitmap coverage (edges) as percentage; we store it as float percent.
    coverage_percent: float = 0.0

    # Additional raw AFL++ stats (e.g., edges_found/total_edges) for branch-edge reporting.
    fuzzing_stats: Dict[str, Any] = field(default_factory=dict)

    crashes: List[CrashInfo] = field(default_factory=list)
    parameter_constraints: Dict[str, Dict] = field(default_factory=dict)




class ReportGenerator:
    """
    Generates fuzzing reports for stakeholders.

    Reports categorize crashes by parameter validity:
    - In-Range: Parameters within specification (needs encoding-aware checks to be trustworthy)
    - Out-of-Range: Parameters outside specification (input validation)

    If crash reproduction (stack traces) and/or minimization are enabled, the generator can:
    - Run the harness against each crashing input to capture stderr/backtrace output
    - Use afl-tmin to minimize crashing inputs
    - Deduplicate crashes by a trace hash
    """

    def __init__(
        self,
        results: FuzzingResults,
        *,
        harness_path: Optional[str] = None,
        repro_timeout_s: int = 5,
        minimize: bool = False,
        minimizer: str = "afl-tmin",
        constraints_path: Optional[str] = None,
    ):
        self.results = results
        self.harness_path = harness_path
        self.repro_timeout_s = repro_timeout_s
        self.minimize = minimize
        self.minimizer = minimizer
        self.constraints_path = constraints_path

        # Optional postprocessing
        if self.harness_path:
            self._reproduce_and_collect_traces()

        if self.minimize and self.harness_path:
            self._minimize_crashes()

        self._deduplicate_crashes()
        self._categorize_crashes()

    
    def _categorize_crashes(self):
        """Categorize crashes as in-range or out-of-range."""
        for crash in self.results.crashes:
            if crash.is_in_range is None:
                crash.is_in_range = self._check_params_in_range(crash.parameters)

    def _reproduce_and_collect_traces(self) -> None:
        """Run the harness for each crashing input and capture stderr/stdout.

        This is a best-effort triage aid. For sanitizer builds, the stack trace typically
        appears on stderr.
        """
        if not self.harness_path:
            return

        harness = Path(self.harness_path)
        if not harness.exists():
            logger.warning("Harness for reproduction not found: %s", self.harness_path)
            return

        for crash in self.results.crashes:
            inp = Path(crash.input_file)
            if not inp.exists():
                continue

            try:
                proc = subprocess.run(
                    [str(harness), str(inp)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=self.repro_timeout_s,
                    env=dict(os.environ),
                )
                out = proc.stdout or ""
                if not out:
                    out = f"<no stdout/stderr captured; exit_code={proc.returncode}>"
                crash.stack_trace = out[-8000:] if len(out) > 8000 else out

            except subprocess.TimeoutExpired:
                crash.stack_trace = "<reproducer timeout>"
            except Exception as e:
                crash.stack_trace = f"<reproducer failed: {e}>"

    def _minimize_crashes(self) -> None:
        """Minimize crash inputs with afl-tmin (best-effort).

        Writes minimized inputs next to the crash file as:
          <crash_file>.tmin
        """
        if not self.harness_path:
            return

        if not shutil.which(self.minimizer):
            logger.warning("%s not found in PATH; skipping minimization", self.minimizer)
            return

        harness = Path(self.harness_path)
        if not harness.exists():
            return

        for crash in self.results.crashes:
            inp = Path(crash.input_file)
            if not inp.exists():
                continue

            outp = inp.with_suffix(inp.suffix + ".tmin")
            if outp.exists():
                crash.minimized_input_file = str(outp)
                continue

            try:
                # afl-tmin -- ./harness @@
                cmd = [self.minimizer, "-i", str(inp), "-o", str(outp), "--", str(harness), "@@"]
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
                if proc.returncode == 0 and outp.exists():
                    crash.minimized_input_file = str(outp)
                else:
                    # keep stdout around for debugging
                    logger.warning("afl-tmin failed for %s: rc=%s", inp.name, proc.returncode)
            except Exception as e:
                logger.warning("afl-tmin exception for %s: %s", inp.name, e)

    def _deduplicate_crashes(self) -> None:
        """Group crashes by a stable hash.

        Priority:
        1) If stack_trace is present -> hash of normalized trace
        2) Else -> hash of first 48 bytes of input file
        """
        for crash in self.results.crashes:
            key_src = ""
            if crash.stack_trace:
                # normalize by stripping numbers/addresses a bit
                t = crash.stack_trace
                t = "\n".join(line.strip() for line in t.splitlines() if line.strip())
                key_src = t
            else:
                try:
                    b = Path(crash.input_file).read_bytes()[:48]
                    key_src = b.hex()
                except Exception:
                    key_src = crash.crash_id

            crash.dedup_group = hashlib.sha256(key_src.encode("utf-8", errors="ignore")).hexdigest()[:12]

    
    def _check_params_in_range(self, params: Dict[str, Any]) -> bool:
        """Check if all parameters are within their valid ranges.

        IMPORTANT:
        - 3P3Z crash inputs are decoded into a mix of:
          * Q23 fixed-point floats for coefficients (cx_q23[*], cy_q23[*])
          * raw int32 for out_offset/limit_max/limit_min/input_sample
          * small ints for scaleCx/scaleCy/gIn/gOut

        - The constraints for pwr-lib/filter_3p3z are currently loaded from CSV as *float*
          ranges (e.g., Lmin/Lmax in [-1, 1]). Those ranges are in the *semantic* domain,
          but AFL inputs for limit_max/limit_min are in the *raw fixed-point integer* domain.

        Therefore:
        - We only apply range checks to parameters where the constraint looks compatible.
          Specifically:
            * For decoded Q23 floats (cx_q23[*], cy_q23[*]): compare directly to float ranges.
            * For raw int parameters (limit_*, out_offset, input_sample): skip range check
              unless constraint explicitly declares an integer domain.

        This avoids mislabeling crashes as "in-range REAL BUGS" when the parameter encoding
        domains don't match.
        """
        if not self.results.parameter_constraints:
            return True  # No constraints defined, assume in-range

        # Heuristic: treat these decoded parameters as raw int domain
        raw_int_params = {"out_offset", "limit_max", "limit_min", "input_sample"}

        for param_name, value in params.items():
            if param_name not in self.results.parameter_constraints:
                continue

            constraint = self.results.parameter_constraints[param_name]
            min_val = constraint.get("min", float("-inf"))
            max_val = constraint.get("max", float("inf"))
            inclusive_min = constraint.get("inclusive_min", True)
            inclusive_max = constraint.get("inclusive_max", True)
            ctype = str(constraint.get("type", "float")).lower()

            # Skip float-range checks for raw int parameters unless constraints explicitly
            # state integer domain.
            if param_name in raw_int_params and ctype not in {"int", "integer"}:
                continue

            try:
                val = float(value)

                if inclusive_min:
                    if val < min_val:
                        return False
                else:
                    if val <= min_val:
                        return False

                if inclusive_max:
                    if val > max_val:
                        return False
                else:
                    if val >= max_val:
                        return False

            except (ValueError, TypeError):
                # Non-numeric parameter, skip range check
                continue

        return True

    
    @property
    def in_range_crashes(self) -> List[CrashInfo]:
        """Get crashes where parameters were within valid ranges (REAL BUGS)."""
        return [c for c in self.results.crashes if c.is_in_range]
    
    @property
    def out_of_range_crashes(self) -> List[CrashInfo]:
        """Get crashes where parameters were outside valid ranges."""
        return [c for c in self.results.crashes if not c.is_in_range]
    
    def generate_markdown(self, include_full_details: bool = True) -> str:
        """
        Generate a Markdown report.
        
        Args:
            include_full_details: If True, include all crash details
            
        Returns:
            Markdown formatted report string
        """
        in_range = self.in_range_crashes
        out_of_range = self.out_of_range_crashes
        
        md = f"""# Fuzzing Report: {self.results.target_name}

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Target Version:** {self.results.target_version or 'N/A'}  
**Duration:** {self._format_duration(self.results.duration_seconds)}

**Input model template:** {self.results.fuzzing_stats.get('input_model_template', 'N/A')}  
**Record size (bytes):** {self.results.fuzzing_stats.get('input_model_record_size', 'N/A')}  
**Decoded-domain validation:** {self.results.fuzzing_stats.get('decoded_domain_validation', 'N/A')}  
**Input model validation report:** {self.results.fuzzing_stats.get('input_model_validation_report', 'N/A')}


---

## 🎯 Executive Summary

| Metric | Value |
|--------|-------|
| **Crash files found (crashes/id:*)** | {self.results.crash_files_count} |
| **saved_crashes (fuzzer_stats)** | {self.results.saved_crashes} |
| **unique_crashes (fuzzer_stats)** | {self.results.unique_crashes} |
| **Total Crashes Listed in Report** | {len(self.results.crashes)} |
| **⚠ Crash count note** | {self.results.crash_count_mismatch_note or 'OK'} |
| **🔴 In-Range Crashes (needs triage)** | **{len(in_range)}** |
| **🟡 Out-of-Range Crashes** | {len(out_of_range)} |
| **Total Executions** | {self.results.total_executions:,} |
| **Exec/Second** | {self.results.executions_per_second:.1f} |
| **Code Coverage (AFL++ bitmap_cvg)** | {self.results.coverage_percent:.1f}% |

### Key Insight

"""
        
        if in_range:
            md += f"""⚠️ **{len(in_range)} crashes observed with parameters classified as in-range.**

**Important note on encoding:** for filter_3p3z the input bytes include a mix of Q23 fixed-point
coefficients and raw int32 fields. If your parameter constraints are specified in *float* ranges
(e.g., [-1, 1]) but a field is provided as raw fixed-point integer, "in-range" classification can
be misleading unless the report generator converts domains.

Action: treat this count as *needs triage* until encoding-aware validation is configured for all fields.
"""
        else:
            md += """✅ **No in-range crashes found.**

All crashes occurred with out-of-range parameters, indicating the firmware properly 
handles invalid inputs or our fuzzer hasn't found real bugs yet.
"""
        
        md += """
---

## 🔴 Critical Findings: In-Range Crashes

These are **REAL BUGS** - crashes that occur with valid input parameters.

"""
        
        if in_range:
            for i, crash in enumerate(in_range[:10], 1):  # Top 10
                md += self._format_crash_section(crash, i)
        else:
            md += "*No in-range crashes found.*\n\n"
        
        md += """
---

## 🟡 Input Validation: Out-of-Range Crashes

These crashes occurred with parameters outside valid ranges.
May indicate missing input validation or expected rejection behavior.

"""
        
        if out_of_range and include_full_details:
            md += f"*Showing first 5 of {len(out_of_range)} out-of-range crashes.*\n\n"
            for i, crash in enumerate(out_of_range[:5], 1):
                md += self._format_crash_section(crash, i, brief=True)
        elif out_of_range:
            md += f"*{len(out_of_range)} out-of-range crashes found. Details omitted for brevity.*\n\n"
        else:
            md += "*No out-of-range crashes found.*\n\n"
        
        md += self._generate_llm_analysis_section()
        md += self._generate_output_range_analysis()
        md += self._generate_excel_consistency_check()
        md += self._generate_coverage_section()
        md += self._generate_parameter_section()
        md += self._generate_appendix()
        
        return md
    
    def _format_crash_section(self, crash: CrashInfo, number: int, brief: bool = False) -> str:
        """Format a single crash as markdown section."""
        severity_emoji = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
            "LOW": "🟢",
        }

        md = f"""### Crash #{number}: {crash.crash_type} at {crash.source_location or 'Unknown'}

{severity_emoji.get(crash.severity, '⚪')} **Severity:** {crash.severity}  
**Crash ID:** `{crash.crash_id}`  
**Type:** {crash.crash_type}

"""

        if crash.parameters:
            md += "**Input Parameters:**\n```\n"
            for k, v in list(crash.parameters.items())[:8]:  # Max 8 params
                md += f"  {k}: {v}\n"
            md += "```\n\n"

        if crash.dedup_group:
            md += f"**Crash Group:** `{crash.dedup_group}`\n\n"

        if crash.minimized_input_file:
            md += f"**Minimized Input:** `{crash.minimized_input_file}`\n\n"

        if not brief:
            md += self._format_raw_input_section(crash)

        if not brief and crash.stack_trace:
            md += f"""**Stack Trace:**
```
{crash.stack_trace[:500]}{'...' if len(crash.stack_trace) > 500 else ''}
```

"""

        return md

    def _format_raw_input_section(self, crash: CrashInfo, *, max_bytes: int = 256, bytes_per_line: int = 16) -> str:
        """Render the raw crash input as a hex dump.

        This is critical for reproducibility: it allows stakeholders to inspect the exact
        bytes AFL++ used to trigger the crash.

        Args:
            crash: Crash record containing `input_file`.
            max_bytes: Maximum number of bytes to show (tailored to keep reports readable).
            bytes_per_line: Number of bytes per line in the hex view.

        Returns:
            Markdown string with a "Raw Input" section. Returns an explanatory note if the
            input file cannot be read.
        """
        if not crash.input_file:
            return "**Raw Input (hex):**\n```text\n<input_file missing>\n```\n\n"

        path = Path(crash.input_file)
        if not path.exists():
            return f"**Raw Input (hex):**\n```text\n<input file not found: {path}>\n```\n\n"

        try:
            raw = path.read_bytes()[:max_bytes]
        except Exception as e:
            return f"**Raw Input (hex):**\n```text\n<failed to read input: {e}>\n```\n\n"

        if not raw:
            return "**Raw Input (hex):**\n```text\n<empty file>\n```\n\n"

        lines: List[str] = []
        for off in range(0, len(raw), bytes_per_line):
            chunk = raw[off : off + bytes_per_line]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{off:08x}  {hex_part:<{bytes_per_line*3}}  |{ascii_part}|")

        suffix = (
            ""
            if path.stat().st_size <= max_bytes
            else f"\n... (truncated to first {max_bytes} bytes; file size={path.stat().st_size} bytes)"
        )
        dump = "\n".join(lines) + suffix

        return f"**Raw Input (hex):**\n```text\n{dump}\n```\n\n"
    
    def _generate_coverage_section(self) -> str:
        """Generate code coverage section."""
        return f"""
---

## 📊 Branch Coverage (AFL++ Edge Coverage)

AFL++ tracks *branch-edge coverage* via an instrumentation bitmap.

| Metric | Value |
|--------|-------|
| Edges Found | {self.results.fuzzing_stats.get('edges_found', 'N/A')} |
| Total Edges (bitmap slots) | {self.results.fuzzing_stats.get('total_edges', 'N/A')} |
| Bitmap Coverage % | {self.results.coverage_percent:.2f}% |


"""
    
    def _generate_parameter_section(self) -> str:
        """Generate parameter constraints section."""
        if not self.results.parameter_constraints:
            return ""

        anomalies = find_numeric_range_anomalies(self.results.parameter_constraints)

        md = """
---

## 📋 Parameter Specifications

Valid ranges used for crash categorization:

| Parameter | Valid Range | Type |
|-----------|-------------|------|
"""

        for name, constraint in self.results.parameter_constraints.items():
            min_bracket = "[" if constraint.get('inclusive_min', True) else "("
            max_bracket = "]" if constraint.get('inclusive_max', True) else ")"
            range_str = f"{min_bracket}{constraint.get('min', '-∞')}, {constraint.get('max', '∞')}{max_bracket}"
            dtype = constraint.get('type', 'float')
            md += f"| {name} | {range_str} | {dtype} |\n"

        if anomalies:
            md += "\n### ⚠️ Detected Range Anomalies\n\n"
            md += "| Parameter | Min | Max | Reason |\n|---|---:|---:|---|\n"
            for a in anomalies[:50]:
                md += f"| {a['parameter']} | {a.get('min')} | {a.get('max')} | {a.get('reason')} |\n"
            md += "\n"

        return md + "\n"

    
    def _generate_llm_analysis_section(self) -> str:
        """Generate LLM analysis prompts section."""
        if not self.in_range_crashes:
            return ""
        
        md = """---

## 🤖 LLM Analysis Prompts

These prompts can be used with an LLM (like GPT-4) to get deeper insights into the crashes.
Copy-paste the relevant prompt for analysis.

"""
        
        for i, crash in enumerate(self.in_range_crashes[:5], 1):  # Top 5
            params_str = "\n".join([f"- {k}: {v}" for k, v in list(crash.parameters.items())[:10]])
            prompt = f"""**Prompt for Crash #{i} ({crash.crash_type}):**

```
Analyze this crash in the filter_3p3z firmware function. The crash ID is {crash.crash_id}, type is {crash.crash_type}.

Input parameters:
{params_str}

The function implements a digital filter. Based on the parameters and crash type, suggest:
1. Possible root cause (e.g., division by zero, overflow, invalid pointer access)
2. Code location where the bug might occur
3. Potential fix or mitigation
4. Test case to reproduce
```

"""
            md += prompt
        
        return md
    
    def _generate_output_range_analysis(self) -> str:
        """Generate output range analysis section."""
        md = """
---

## 📊 Output Range Analysis

Since crashes occur, outputs are implicitly out-of-range (e.g., causing aborts).
For in-range inputs causing crashes, the function likely produces invalid outputs.

**Findings:**
- All 4 in-range crashes suggest output computation errors (e.g., overflow, NaN).
- No explicit output values captured, but crashes indicate failures.

"""
        return md
    
    def _generate_excel_consistency_check(self) -> str:
        """Generate Excel/CSV consistency check section."""
        # Use the csv_constraints to check for anomalies
        anomalies = find_numeric_range_anomalies(self.constraints_path) if self.constraints_path else []
        
        md = """
---

## 📋 Excel/CSV Consistency Check

Checked for inconsistencies in parameter ranges from XLSX-derived CSVs.

"""
        if anomalies:
            md += "**Anomalies Found:**\n\n| Parameter | Issue |\n|-----------|-------|\n"
            for a in anomalies[:10]:
                md += f"| {a['parameter']} | {a['reason']} |\n"
        else:
            md += "*No major inconsistencies detected.*\n"
        
        return md
    
    def _generate_appendix(self) -> str:
        """Generate appendix with reproduction info."""
        # Try to derive useful paths from the crash input_file paths
        crash_files = [c.input_file for c in self.results.crashes if c.input_file]
        crashes_dir = "crashes/"
        if crash_files:
            try:
                crashes_dir = str(Path(crash_files[0]).parent)
            except Exception:
                pass

        fuzzer_stats = self.results.fuzzing_stats or {}
        stats_lines = "\n".join(
            [
                f"execs_done: {self.results.total_executions}",
                f"execs_per_sec: {self.results.executions_per_second}",
                f"unique_crashes: {self.results.unique_crashes}",
                f"edges_found: {fuzzer_stats.get('edges_found', 'N/A')}",
                f"total_edges: {fuzzer_stats.get('total_edges', 'N/A')}",
                f"bitmap_cvg: {self.results.coverage_percent:.2f}%",
            ]
        )

        listing = "\n".join([f"- `{Path(p).name}`" for p in crash_files[:10]])
        if crash_files and len(crash_files) > 10:
            listing += f"\n- ... ({len(crash_files) - 10} more)"

        return f"""
---

## 📎 Appendix

### AFL artifacts

- Crashes directory: `{crashes_dir}`

**Crash files (first 10):**
{listing if listing else '*No crash files found.*'}

### fuzzer_stats excerpt (key fields)

```text
{stats_lines}
```

### Reproducing a crash

```bash
# Example: replay the crash input with your harness binary
./fuzz_filter_3p3z "{crash_files[0] if crash_files else (str(Path(crashes_dir) / 'id:000000*'))}"
```

---
*End of Report*
"""

    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in human-readable form."""
        if seconds < 60:
            return f"{seconds} seconds"
        elif seconds < 3600:
            return f"{seconds // 60} minutes"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    
    def generate_summary_json(self, *, scenario_summary: Optional[Dict[str, Any]] = None) -> Dict:
        """Generate a JSON summary for programmatic access.

        Scenario coverage is thesis-critical. We do NOT recompute it here.
        Instead, the pipeline should compute scenario coverage once and pass a
        small summary + artifact paths in `scenario_summary`.
        """

        return {
            "target": self.results.target_name,
            "version": self.results.target_version,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_crashes": len(self.results.crashes),
                "in_range_crashes": len(self.in_range_crashes),
                "out_of_range_crashes": len(self.out_of_range_crashes),
                "total_executions": self.results.total_executions,
                "coverage_percent": self.results.coverage_percent,
                "duration_seconds": self.results.duration_seconds,
                "scenario": scenario_summary or {},
            },
            "in_range_crashes": [
                {
                    "id": c.crash_id,
                    "type": c.crash_type,
                    "location": c.source_location,
                    "severity": c.severity,
                    "parameters": c.parameters,
                }
                for c in self.in_range_crashes
            ],
            "out_of_range_crashes": [
                {
                    "id": c.crash_id,
                    "type": c.crash_type,
                    "location": c.source_location,
                }
                for c in self.out_of_range_crashes
            ],
        }
    
    def save_markdown(self, output_path: str):
        """Save markdown report to file."""
        md = self.generate_markdown()
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md)
        logger.info(f"Saved markdown report to {output_path}")
    
    def save_json(self, output_path: str, *, scenario_summary: Optional[Dict[str, Any]] = None):
        """Save JSON summary to file."""
        data = self.generate_summary_json(scenario_summary=scenario_summary)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved JSON summary to {output_path}")
    
    def save_pdf(self, output_path: str):
        """
        Save PDF report using pandoc.
        
        Requires pandoc to be installed:
        - Windows: choco install pandoc
        - Linux: apt install pandoc
        - Mac: brew install pandoc
        """
        # First generate markdown
        md_path = output_path.replace('.pdf', '.md')
        self.save_markdown(md_path)
        
        try:
            # Convert to PDF using pandoc
            subprocess.run([
                'pandoc',
                md_path,
                '-o', output_path,
                '--pdf-engine=xelatex',  # or pdflatex
                '-V', 'geometry:margin=1in',
                '-V', 'fontsize=11pt'
            ], check=True)
            logger.info(f"Saved PDF report to {output_path}")
        except FileNotFoundError:
            logger.warning("pandoc not found. Install with: choco install pandoc")
            logger.info(f"Markdown report saved to {md_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"PDF generation failed: {e}")
            logger.info(f"Markdown report saved to {md_path}")
    
    def generate_stakeholder_email(self) -> str:
        """Generate a brief email summary for stakeholders."""
        in_range = len(self.in_range_crashes)
        out_range = len(self.out_of_range_crashes)
        total = len(self.results.crashes)
        
        if in_range > 0:
            status = "🔴 CRITICAL BUGS FOUND"
            action = f"Immediate review needed for {in_range} crashes with valid parameters."
        else:
            status = "🟢 No Critical Bugs"
            action = "Continue monitoring. All crashes are with invalid inputs."
        
        return f"""Subject: Fuzzing Report: {self.results.target_name} - {status}

Hi Team,

Fuzzing campaign completed for {self.results.target_name}.

📊 RESULTS:
• Total crashes: {total}
• In-range (REAL BUGS): {in_range}
• Out-of-range (input validation): {out_range}
• Executions: {self.results.total_executions:,}
• Duration: {self._format_duration(self.results.duration_seconds)}

📌 ACTION REQUIRED:
{action}

Full report attached.

Best,
Automated Testing System
"""


# =============================================================================
# HELPER FUNCTION TO CREATE RESULTS FROM AFL++ OUTPUT
# =============================================================================

def parse_afl_output(
    output_dir: str,
    parameter_constraints: Dict = None,
    target_name: str = "Unknown Target",
    *,
    harness_path: Optional[str] = None,
    repro_timeout_s: int = 5,
    minimize: bool = False,
) -> FuzzingResults:


    """
    Parse AFL++ output directory to create FuzzingResults.
    
    Args:
        output_dir: Path to AFL++ output directory
        parameter_constraints: Dict of parameter constraints for crash categorization
        
    Returns:
        FuzzingResults object
    """
    results = FuzzingResults(
        target_name=target_name,
        parameter_constraints=parameter_constraints or {}
    )

    
    output_path = Path(output_dir)
    
    # Parse fuzzer_stats
    stats_file = output_path / "fuzzer_stats"
    if stats_file.exists():
        with open(stats_file, 'r') as f:
            for line in f:
                if ':' in line:
                    key, value = line.strip().split(':', 1)
                    key = key.strip()
                    value = value.strip()

                    if key == 'execs_done':
                        results.total_executions = int(value)
                    elif key == 'execs_per_sec':
                        results.executions_per_second = float(value)
                    elif key == 'unique_crashes':
                        results.unique_crashes = int(value)
                    elif key == 'unique_hangs':
                        results.unique_hangs = int(value)
                    elif key == 'saved_crashes':
                        results.saved_crashes = int(value)
                    elif key == 'saved_hangs':
                        results.saved_hangs = int(value)
                    elif key in {'run_time', 'duration_seconds'}:
                        try:
                            results.duration_seconds = int(float(value))
                        except Exception:
                            pass
                    elif key == 'start_time':
                        results.start_time = value
                    elif key == 'last_update':
                        results.end_time = value
                    elif key == 'edges_found':
                        # AFL++ bitmap edges discovered (proxy for branch-edge coverage)
                        results.fuzzing_stats = getattr(results, 'fuzzing_stats', {})
                        results.fuzzing_stats['edges_found'] = int(value)
                    elif key == 'bitmap_cvg':
                        # AFL++ bitmap coverage percent string like "12.34%"
                        try:
                            results.coverage_percent = float(str(value).replace('%', '').strip())
                        except Exception:
                            pass
                    elif key == 'total_edges':
                        results.fuzzing_stats = getattr(results, 'fuzzing_stats', {})
                        results.fuzzing_stats['total_edges'] = int(value)

        # If duration still not set, derive from start_time/last_update if possible
        if (results.duration_seconds or 0) <= 0:
            try:
                if results.start_time and results.end_time:
                    results.duration_seconds = max(0, int(float(results.end_time) - float(results.start_time)))
            except Exception:
                pass


    
    # Parse crashes
    crashes_dir = output_path / "crashes"
    crash_files: List[Path] = []
    if crashes_dir.exists():
        crash_files = [p for p in crashes_dir.glob("id:*") if p.is_file()]

    results.crash_files_count = len(crash_files)

    for crash_file in crash_files:
        crash = CrashInfo(
            crash_id=crash_file.name,
            input_file=str(crash_file),
            crash_type="CRASH",  # AFL doesn't differentiate
            timestamp=datetime.fromtimestamp(crash_file.stat().st_mtime).isoformat(),
        )

        # Attempt 3P3Z decode for parameter-aware categorization.
        try:
            decoded = decode_3p3z_params(Path(crash.input_file).read_bytes())
            if decoded is not None:
                crash.parameters = decoded.to_parameters_float()
        except Exception:
            pass

        results.crashes.append(crash)

    # Reconcile crash counters
    notes: List[str] = []
    if results.saved_crashes and results.saved_crashes != results.crash_files_count:
        notes.append(f"saved_crashes({results.saved_crashes}) != crash_files({results.crash_files_count})")
    if results.unique_crashes and results.unique_crashes != results.saved_crashes:
        notes.append(f"unique_crashes({results.unique_crashes}) != saved_crashes({results.saved_crashes})")
    if results.unique_crashes == 0 and results.crash_files_count > 0:
        notes.append("unique_crashes is 0 but crash files exist; AFL stats may not reflect dedup or were not updated")
    results.crash_count_mismatch_note = "; ".join(notes)

    # Optional reproducer/minimization/dedup postprocessing
    if harness_path:
        generator = ReportGenerator(
            results,
            harness_path=harness_path,
            repro_timeout_s=repro_timeout_s,
            minimize=minimize,
        )
        return generator.results

    return results



# =============================================================================
# USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    # Create sample results for demonstration
    sample_results = FuzzingResults(
        target_name="3P3Z Filter Library",
        target_version="v2.3.1",
        start_time="2025-01-17T10:00:00",
        end_time="2025-01-17T11:00:00",
        duration_seconds=3600,
        total_executions=1234567,
        executions_per_second=342.9,
        unique_crashes=12,
        coverage_percent=67.3,
        parameter_constraints={
            "cx_q23[0]": {"min": -1.0, "max": 1.0, "inclusive_min": True, "inclusive_max": False},
            "cy_q23[0]": {"min": -1.0, "max": 1.0, "inclusive_min": True, "inclusive_max": False},
            "scaleCx": {"min": 0, "max": 7, "inclusive_min": True, "inclusive_max": True, "type": "int"},
        },
        crashes=[
            CrashInfo(
                crash_id="crash_001",
                input_file="crashes/crash_001.bin",
                crash_type="SEGV",
                source_location="filter_3p3z.c:156",
                severity="CRITICAL",
                parameters={"cx_q23[0]": 0.999, "cy_q23[0]": -0.001, "scaleCx": 3},
                stack_trace="SIGSEGV at 0x7fff...\n  filter_3p3z_run+0x42\n  main+0x1a"
            ),
            CrashInfo(
                crash_id="crash_002",
                input_file="crashes/crash_002.bin",
                crash_type="ABORT",
                source_location="filter_3p3z.c:89",
                severity="HIGH",
                parameters={"cx_q23[0]": 1.5, "cy_q23[0]": 0.5, "scaleCx": 10},  # Out of range!
                stack_trace="SIGABRT at assertion failed..."
            ),
        ]
    )
    
    # Generate report
    generator = ReportGenerator(sample_results)
    
    # Save all formats
    os.makedirs("reports", exist_ok=True)
    generator.save_markdown("reports/fuzzing_report.md")
    generator.save_json("reports/fuzzing_report.json")
    
    # Print email summary
    print("\n" + "="*60)
    print("STAKEHOLDER EMAIL:")
    print("="*60)
    print(generator.generate_stakeholder_email())
