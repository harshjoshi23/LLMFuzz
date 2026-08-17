"""Comparative reporting across multiple blocks.

Phase 3 component: Comparative report generator.

Input: list of dicts from scripts/multi_block_test.py
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _get_cov(metrics: Dict[str, Any]) -> Optional[float]:
    # Our report_generator JSON typically includes coverage_percent.
    # If not present, accept AFL raw stats embedded.
    if not isinstance(metrics, dict):
        return None
    if "coverage_percent" in metrics:
        try:
            return float(metrics["coverage_percent"])
        except Exception:
            return None
    # fallback: try nested
    for k in ("coverage", "bitmap_cvg"):
        if k in metrics:
            try:
                return float(str(metrics[k]).rstrip("%"))
            except Exception:
                pass
    return None


def _get_unique_crashes(metrics: Dict[str, Any]) -> Optional[int]:
    if not isinstance(metrics, dict):
        return None
    for k in ("unique_crashes", "saved_crashes"):
        if k in metrics:
            try:
                return int(metrics[k])
            except Exception:
                return None
    return None


def _get_execs_per_sec(metrics: Dict[str, Any]) -> Optional[float]:
    if not isinstance(metrics, dict):
        return None
    for k in ("executions_per_second", "execs_per_sec"):
        if k in metrics:
            try:
                return float(metrics[k])
            except Exception:
                return None
    return None


def _fmt(v: Optional[Any]) -> str:
    if v is None:
        return "-"
    return str(v)


class ComparativeReportGenerator:
    def generate(self, results: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        lines.append("# Multi-Block Fuzzing Results\n")

        lines.append("| Block | Status | Coverage | Bugs | Exec/sec | Output |")
        lines.append("|------|--------|----------|------|----------|--------|")

        total_bugs = 0
        cov_sum = 0.0
        cov_n = 0
        ok_n = 0

        for r in results:
            block = r.get("block", "?")
            ok = bool(r.get("success"))
            status = "OK" if ok else "FAIL"
            if ok:
                ok_n += 1

            metrics = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
            cov = _get_cov(metrics)
            bugs = _get_unique_crashes(metrics)
            eps = _get_execs_per_sec(metrics)

            if cov is not None:
                cov_sum += cov
                cov_n += 1
            if bugs is not None:
                total_bugs += bugs

            lines.append(
                f"| {block} | {status} | {_fmt(f'{cov:.2f}%' if cov is not None else None)} | {_fmt(bugs)} | {_fmt(f'{eps:.1f}' if eps is not None else None)} | {_fmt(r.get('output_dir'))} |"
            )

        avg_cov = (cov_sum / cov_n) if cov_n else 0.0

        lines.append("\n## Summary\n")
        lines.append(f"- Success rate: {ok_n}/{len(results)}")
        lines.append(f"- Total bugs (best-effort): {total_bugs}")
        lines.append(f"- Average coverage (best-effort): {avg_cov:.2f}%\n")

        lines.append("## Detailed Results\n")
        for r in results:
            lines.append(f"### {r.get('block','?')}\n")
            lines.append(f"- Status: {'OK' if r.get('success') else 'FAIL'}")
            lines.append(f"- Output: {r.get('output_dir','-')}")
            if r.get("last_report_json"):
                lines.append(f"- Last report JSON: {r.get('last_report_json')}")
            if r.get("metrics_error"):
                lines.append(f"- Metrics parse error: {r.get('metrics_error')}")
            lines.append("")

        return "\n".join(lines)
