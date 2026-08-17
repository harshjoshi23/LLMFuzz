"""Statistical comparison of fuzzing runs (LLM-on vs baseline).

Reads AFL++ plot_data files from multiple runs, builds coverage-over-time
curves, computes the metrics recommended by:

  Schloegel et al., "SoK: Prudent Evaluation Practices for Fuzzing",
  USENIX Security 2024.
  Klees et al., "Evaluating Fuzz Testing", CCS 2018.

Outputs:
  - <out>/comparison.csv          per-trial summary
  - <out>/comparison.json         full structured results
  - <out>/timeseries_long.csv     long-form (trial, group, t_sec, edges)
  - <out>/comparison_plot.png     coverage-over-time (matplotlib, if available)
  - <out>/summary.md              human-readable summary with statistical test

CLI:
  python -m src.cli compare \\
    --llm results/2h_dc_llm_*/ \\
    --baseline results/2h_dc_baseline_*/ \\
    --out results/comparison_dc_optimizer
"""

from __future__ import annotations

import csv
import glob
import json
import math
import statistics
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# plot_data parsing
# ---------------------------------------------------------------------------

@dataclass
class PlotSample:
    t_sec: float
    cycles: int
    corpus: int
    map_pct: float            # bitmap_cvg from "map_size" column (already %)
    edges: int                # edges_found column
    execs_per_sec: float
    total_execs: int
    crashes: int


def _parse_plot_data(path: Path) -> List[PlotSample]:
    """AFL++ plot_data columns:
        relative_time, cycles_done, cur_item, corpus_count,
        pending_total, pending_favs, map_size, saved_crashes,
        saved_hangs, max_depth, execs_per_sec, total_execs, edges_found
    """
    out: List[PlotSample] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 13:
                continue
            try:
                map_pct = float(parts[6].rstrip("%"))
                out.append(PlotSample(
                    t_sec=float(parts[0]),
                    cycles=int(parts[1]),
                    corpus=int(parts[3]),
                    map_pct=map_pct,
                    edges=int(parts[12]),
                    execs_per_sec=float(parts[10]),
                    total_execs=int(parts[11]),
                    crashes=int(parts[7]),
                ))
            except (ValueError, IndexError):
                continue
    return out


def _find_plot_data(run_dir: Path) -> Optional[Path]:
    """Locate AFL plot_data inside a run dir; supports nested afl/<proto>/default/."""
    candidates = list(run_dir.rglob("plot_data"))
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Per-run derived metrics
# ---------------------------------------------------------------------------

@dataclass
class RunMetrics:
    run_id: str
    run_dir: str
    group: str

    # SoK-recommended metrics
    final_edges: int = 0
    final_map_pct: float = 0.0
    final_corpus: int = 0
    final_crashes: int = 0
    total_execs: int = 0
    duration_sec: float = 0.0
    mean_execs_per_sec: float = 0.0

    # Time-to-milestone (seconds; -1 if never reached)
    t_to_25pct: float = -1.0
    t_to_50pct: float = -1.0
    t_to_75pct_of_max: float = -1.0
    t_to_90pct_of_max: float = -1.0
    t_to_baseline_final: float = -1.0  # filled later when comparing


def _compute_run_metrics(run_dir: Path, group: str) -> Optional[RunMetrics]:
    plot = _find_plot_data(run_dir)
    if not plot:
        return None
    samples = _parse_plot_data(plot)
    if not samples:
        return None

    last = samples[-1]
    rm = RunMetrics(
        run_id=run_dir.name,
        run_dir=str(run_dir),
        group=group,
        final_edges=last.edges,
        final_map_pct=last.map_pct,
        final_corpus=last.corpus,
        final_crashes=last.crashes,
        total_execs=last.total_execs,
        duration_sec=last.t_sec,
        mean_execs_per_sec=last.total_execs / last.t_sec if last.t_sec > 0 else 0.0,
    )

    max_edges = max(s.edges for s in samples)
    for s in samples:
        if rm.t_to_25pct < 0 and s.map_pct >= 25:
            rm.t_to_25pct = s.t_sec
        if rm.t_to_50pct < 0 and s.map_pct >= 50:
            rm.t_to_50pct = s.t_sec
        if rm.t_to_75pct_of_max < 0 and s.edges >= 0.75 * max_edges:
            rm.t_to_75pct_of_max = s.t_sec
        if rm.t_to_90pct_of_max < 0 and s.edges >= 0.90 * max_edges:
            rm.t_to_90pct_of_max = s.t_sec
    return rm


# ---------------------------------------------------------------------------
# Statistical tests (no scipy dependency)
# ---------------------------------------------------------------------------

def _mann_whitney_u(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float]:
    """Two-sided Mann-Whitney U test with normal approximation.

    Returns (U, p_value). Sufficient for the small-N regime typical of
    fuzzing campaigns; for N<10 in either group, the p-value is
    approximate and should be treated as indicative.

    Recommended by SoK Schloegel et al. (Recommendation 5) and Klees et al.
    """
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0

    combined = [(v, 0) for v in a] + [(v, 1) for v in b]
    combined.sort(key=lambda x: x[0])

    # Assign ranks (average for ties)
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # ranks are 1-indexed
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1

    r1 = sum(r for r, (_, g) in zip(ranks, combined) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    u = min(u1, u2)

    mu = n1 * n2 / 2.0
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
    if sigma == 0:
        return u, 1.0
    z = (u - mu) / sigma
    # two-sided p from standard normal CDF
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return u, max(0.0, min(1.0, p))


def _vargha_delaney_a12(a: Sequence[float], b: Sequence[float]) -> float:
    """Vargha-Delaney A12 effect size: probability that a random a > random b.

    0.5 = no effect. >0.5 = a > b on average. Magnitudes:
      small: 0.56, medium: 0.64, large: 0.71  (Vargha & Delaney 2000)
    """
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return 0.5
    wins, ties = 0.0, 0.0
    for x in a:
        for y in b:
            if x > y:
                wins += 1
            elif x == y:
                ties += 1
    return (wins + 0.5 * ties) / (n1 * n2)


def _summarize(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class GroupSummary:
    group: str
    n_trials: int
    final_edges: Dict[str, float]
    final_map_pct: Dict[str, float]
    total_execs: Dict[str, float]
    duration_sec: Dict[str, float]
    t_to_25pct: Dict[str, float]
    t_to_50pct: Dict[str, float]
    t_to_75pct_of_max: Dict[str, float]


@dataclass
class Comparison:
    llm_runs: List[RunMetrics] = field(default_factory=list)
    baseline_runs: List[RunMetrics] = field(default_factory=list)
    llm_summary: Optional[GroupSummary] = None
    baseline_summary: Optional[GroupSummary] = None
    tests: Dict[str, Dict[str, float]] = field(default_factory=dict)


def _expand_globs(patterns: Sequence[str]) -> List[Path]:
    paths: List[Path] = []
    for p in patterns:
        # If the user passes a glob, expand it; if a literal dir, include directly.
        expanded = glob.glob(p)
        if expanded:
            paths.extend(Path(x) for x in expanded if Path(x).is_dir())
        elif Path(p).is_dir():
            paths.append(Path(p))
    # De-dup, sort
    return sorted(set(paths), key=str)


def compare_groups(
    *,
    llm_globs: Sequence[str],
    baseline_globs: Sequence[str],
    out_dir: Path,
) -> Comparison:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmp = Comparison()

    for d in _expand_globs(llm_globs):
        rm = _compute_run_metrics(d, "llm")
        if rm:
            cmp.llm_runs.append(rm)
    for d in _expand_globs(baseline_globs):
        rm = _compute_run_metrics(d, "baseline")
        if rm:
            cmp.baseline_runs.append(rm)

    if not cmp.llm_runs and not cmp.baseline_runs:
        raise SystemExit("No runs with plot_data found in the supplied paths.")

    # Time-to-baseline-final: how fast did each LLM run reach baseline's
    # mean final edge count? Honest "speedup" metric per SoK.
    if cmp.baseline_runs and cmp.llm_runs:
        baseline_final_mean = statistics.mean(r.final_edges for r in cmp.baseline_runs)
        for r in cmp.llm_runs:
            plot = _find_plot_data(Path(r.run_dir))
            if not plot:
                continue
            for s in _parse_plot_data(plot):
                if s.edges >= baseline_final_mean:
                    r.t_to_baseline_final = s.t_sec
                    break

    # Group-level summaries
    def _gs(group: str, runs: List[RunMetrics]) -> GroupSummary:
        return GroupSummary(
            group=group,
            n_trials=len(runs),
            final_edges=_summarize([r.final_edges for r in runs]),
            final_map_pct=_summarize([r.final_map_pct for r in runs]),
            total_execs=_summarize([float(r.total_execs) for r in runs]),
            duration_sec=_summarize([r.duration_sec for r in runs]),
            t_to_25pct=_summarize([r.t_to_25pct for r in runs if r.t_to_25pct >= 0]),
            t_to_50pct=_summarize([r.t_to_50pct for r in runs if r.t_to_50pct >= 0]),
            t_to_75pct_of_max=_summarize(
                [r.t_to_75pct_of_max for r in runs if r.t_to_75pct_of_max >= 0]),
        )

    cmp.llm_summary = _gs("llm", cmp.llm_runs)
    cmp.baseline_summary = _gs("baseline", cmp.baseline_runs)

    # Statistical tests (per Klees et al. + SoK Recommendation 5)
    if cmp.llm_runs and cmp.baseline_runs:
        for metric_name, extractor in [
            ("final_edges",      lambda r: r.final_edges),
            ("final_map_pct",    lambda r: r.final_map_pct),
            ("t_to_75pct_of_max",
                lambda r: r.t_to_75pct_of_max if r.t_to_75pct_of_max >= 0 else None),
        ]:
            a = [extractor(r) for r in cmp.llm_runs if extractor(r) is not None]
            b = [extractor(r) for r in cmp.baseline_runs if extractor(r) is not None]
            if len(a) >= 2 and len(b) >= 2:
                u, p = _mann_whitney_u(a, b)
                a12 = _vargha_delaney_a12(a, b)
                cmp.tests[metric_name] = {
                    "U": u, "p_value": p, "A12_llm_vs_baseline": a12,
                    "n_llm": len(a), "n_baseline": len(b),
                }

    _write_outputs(cmp, out_dir)
    return cmp


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_outputs(cmp: Comparison, out_dir: Path) -> None:
    # 1. Per-trial CSV
    csv_path = out_dir / "comparison.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "group", "run_id", "final_edges", "final_map_pct", "final_corpus",
            "final_crashes", "total_execs", "duration_sec", "mean_execs_per_sec",
            "t_to_25pct", "t_to_50pct", "t_to_75pct_of_max", "t_to_90pct_of_max",
            "t_to_baseline_final",
        ])
        for r in cmp.llm_runs + cmp.baseline_runs:
            w.writerow([
                r.group, r.run_id, r.final_edges, f"{r.final_map_pct:.2f}",
                r.final_corpus, r.final_crashes, r.total_execs,
                f"{r.duration_sec:.0f}", f"{r.mean_execs_per_sec:.1f}",
                f"{r.t_to_25pct:.1f}", f"{r.t_to_50pct:.1f}",
                f"{r.t_to_75pct_of_max:.1f}", f"{r.t_to_90pct_of_max:.1f}",
                f"{r.t_to_baseline_final:.1f}",
            ])

    # 2. JSON dump
    json_path = out_dir / "comparison.json"
    json_path.write_text(json.dumps({
        "llm_runs": [asdict(r) for r in cmp.llm_runs],
        "baseline_runs": [asdict(r) for r in cmp.baseline_runs],
        "llm_summary": asdict(cmp.llm_summary) if cmp.llm_summary else None,
        "baseline_summary": asdict(cmp.baseline_summary) if cmp.baseline_summary else None,
        "tests": cmp.tests,
    }, indent=2))

    # 3. Long-form time series for external plotting (R / pandas / gnuplot)
    long_path = out_dir / "timeseries_long.csv"
    with long_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group", "run_id", "t_sec", "edges", "map_pct", "corpus", "execs"])
        for r in cmp.llm_runs + cmp.baseline_runs:
            plot = _find_plot_data(Path(r.run_dir))
            if not plot:
                continue
            for s in _parse_plot_data(plot):
                w.writerow([r.group, r.run_id, f"{s.t_sec:.0f}",
                            s.edges, f"{s.map_pct:.2f}", s.corpus, s.total_execs])

    # 4. PNG plot (optional - requires matplotlib)
    try:
        _plot_timeseries(cmp, out_dir / "comparison_plot.png")
    except Exception as e:
        print(f"[compare] matplotlib plot skipped: {e}")

    # 5. Human-readable summary
    _write_markdown_summary(cmp, out_dir / "summary.md")


def _plot_timeseries(cmp: Comparison, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    for r in cmp.baseline_runs:
        plot = _find_plot_data(Path(r.run_dir))
        if not plot:
            continue
        samples = _parse_plot_data(plot)
        ax.plot([s.t_sec / 60.0 for s in samples], [s.edges for s in samples],
                color="#888", alpha=0.6, lw=1.2, label="baseline" if r is cmp.baseline_runs[0] else None)
    for r in cmp.llm_runs:
        plot = _find_plot_data(Path(r.run_dir))
        if not plot:
            continue
        samples = _parse_plot_data(plot)
        ax.plot([s.t_sec / 60.0 for s in samples], [s.edges for s in samples],
                color="#1f77b4", alpha=0.8, lw=1.5, label="llm" if r is cmp.llm_runs[0] else None)
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("Edges discovered")
    ax.set_title("Coverage over time: LLM-guided seeds vs baseline AFL++")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _write_markdown_summary(cmp: Comparison, out_path: Path) -> None:
    lines: List[str] = []
    lines.append("# Fuzzing campaign comparison\n")
    lines.append("Metrics per SoK Prudent Evaluation Practices for Fuzzing (Schloegel et al., USENIX Security 2024) ")
    lines.append("and Evaluating Fuzz Testing (Klees et al., CCS 2018).\n")

    def _fmt(d: Dict[str, float]) -> str:
        if d.get("n", 0) == 0:
            return "n=0"
        return f"n={int(d['n'])}, mean={d['mean']:.1f}, median={d['median']:.1f}, stdev={d['stdev']:.1f}, [{d['min']:.1f}..{d['max']:.1f}]"

    for label, gs in [("LLM-guided", cmp.llm_summary), ("Baseline", cmp.baseline_summary)]:
        if not gs:
            continue
        lines.append(f"## {label} ({gs.n_trials} trial{'s' if gs.n_trials != 1 else ''})\n")
        lines.append(f"- Final edges discovered: {_fmt(gs.final_edges)}")
        lines.append(f"- Final bitmap_cvg %: {_fmt(gs.final_map_pct)}")
        lines.append(f"- Total executions: {_fmt(gs.total_execs)}")
        lines.append(f"- Runtime (s): {_fmt(gs.duration_sec)}")
        lines.append(f"- Time-to-25% map: {_fmt(gs.t_to_25pct)}")
        lines.append(f"- Time-to-50% map: {_fmt(gs.t_to_50pct)}")
        lines.append(f"- Time-to-75%-of-max-edges: {_fmt(gs.t_to_75pct_of_max)}\n")

    if cmp.tests:
        lines.append("## Statistical tests (Mann-Whitney U, two-sided)\n")
        lines.append("A12 is the Vargha-Delaney effect size: 0.5 = no effect, ")
        lines.append(">0.71 = large effect favoring LLM.\n")
        lines.append("| Metric | n_llm | n_baseline | U | p-value | A12 |")
        lines.append("|---|---|---|---|---|---|")
        for m, t in cmp.tests.items():
            sig = "**" if t["p_value"] < 0.05 else ""
            lines.append(f"| {m} | {int(t['n_llm'])} | {int(t['n_baseline'])} | "
                         f"{t['U']:.1f} | {sig}{t['p_value']:.4f}{sig} | {t['A12_llm_vs_baseline']:.3f} |")
        lines.append("")

    if cmp.llm_runs and cmp.baseline_runs:
        speedups = [r.t_to_baseline_final for r in cmp.llm_runs if r.t_to_baseline_final >= 0]
        if speedups:
            baseline_dur = statistics.mean(r.duration_sec for r in cmp.baseline_runs)
            avg_speedup_t = statistics.mean(speedups)
            ratio = baseline_dur / avg_speedup_t if avg_speedup_t > 0 else float("inf")
            lines.append("## Time-to-baseline-final-coverage\n")
            lines.append(f"On average, LLM-guided runs reached the baseline's final edge count in **{avg_speedup_t:.0f} s**, ")
            lines.append(f"vs baseline mean duration of **{baseline_dur:.0f} s** — a **{ratio:.1f}× speedup**.\n")

    out_path.write_text("\n".join(lines))
