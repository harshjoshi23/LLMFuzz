"""Minimal HTML/XML exporters for run-scoped reports.

Goals:
- Produce *portable* artifacts for stakeholders without extra dependencies.
- Keep generation deterministic and local (reads run-scoped JSON/MD).

Outputs:
- HTML: single-file report with embedded CSS.
- XML: JUnit-style summary (useful for CI ingestion) + scenario coverage fields.

This module intentionally avoids templates/jinja to keep dependencies at zero.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def _read_json(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _esc(s: Any) -> str:
    return html.escape(str(s))


_DEFAULT_CSS = """
:root { color-scheme: light; }
body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }
pre { background: #0b1020; color: #e6edf3; padding: 12px; border-radius: 8px; overflow-x: auto; }
.card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; margin: 12px 0; }
.h { display: flex; gap: 12px; flex-wrap: wrap; }
.kpi { padding: 10px 12px; border-radius: 10px; background: #f3f4f6; }
.kpi .v { font-weight: 700; font-size: 18px; }
small { color: #6b7280; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 18px 0; }
""".strip()


def write_html_report(
    *,
    run_json_path: Path,
    scenario_json_path: Optional[Path],
    markdown_report_path: Optional[Path],
    out_path: Path,
    title: str = "Fuzzing report",
) -> str:
    """Create a single-file HTML report.

    Inputs are expected to be run-scoped artifacts.
    """

    runj = _read_json(run_json_path)
    scen = _read_json(scenario_json_path) if scenario_json_path else {}
    md = _read_text(markdown_report_path) if markdown_report_path else ""

    summary = runj.get("summary", {}) if isinstance(runj.get("summary"), dict) else {}

    # Surface requested coverage mode (edge vs branch) if present.
    requested_mode = ""
    if isinstance(runj.get("native_coverage"), dict) and runj["native_coverage"].get("requested_mode"):
        requested_mode = str(runj["native_coverage"].get("requested_mode"))
    elif isinstance(runj.get("afl"), dict) and isinstance(runj["afl"].get("coverage"), dict):
        requested_mode = str(runj["afl"]["coverage"].get("requested_mode", ""))
    if requested_mode:
        summary["coverage_mode"] = requested_mode

    # Back-compat: earlier run.json schema stores AFL result under runj["afl"].
    if not summary and isinstance(runj.get("afl"), dict):
        afl = runj.get("afl")
        summary = {
            "total_crashes": afl.get("crashes_found", ""),
            "unique_crashes": afl.get("crashes_found", ""),
            "queue_size": afl.get("queue_size", ""),
            "bitmap_coverage_percent": "",
        }
        # Try to read bitmap_cvg from fuzzer_stats if present.
        fsp = afl.get("fuzzer_stats_path")
        if isinstance(fsp, str) and fsp:
            try:
                for ln in Path(fsp).read_text(errors="ignore").splitlines():
                    if ln.startswith("bitmap_cvg"):
                        summary["bitmap_coverage_percent"] = ln.split(":", 1)[1].strip()
            except Exception:
                pass

    html_out = []
    html_out.append("<!doctype html>")
    html_out.append("<html><head><meta charset='utf-8'>")
    html_out.append(f"<title>{_esc(title)}</title>")
    html_out.append(f"<style>{_DEFAULT_CSS}</style>")
    html_out.append("</head><body>")

    html_out.append(f"<h1>{_esc(title)}</h1>")
    html_out.append(f"<small>run_id: {_esc(runj.get('run_id',''))}</small>")

    html_out.append("<div class='card'>")
    html_out.append("<div class='h'>")
    html_out.append(f"<div class='kpi'><div class='v'>{_esc(summary.get('total_crashes',''))}</div><small>crashes</small></div>")
    html_out.append(f"<div class='kpi'><div class='v'>{_esc(summary.get('unique_crashes',''))}</div><small>unique crashes</small></div>")
    html_out.append(f"<div class='kpi'><div class='v'>{_esc(summary.get('queue_size',''))}</div><small>queue size</small></div>")
    html_out.append(f"<div class='kpi'><div class='v'>{_esc(summary.get('bitmap_coverage_percent',''))}</div><small>bitmap coverage %</small></div>")
    if summary.get('coverage_mode'):
        html_out.append(f"<div class='kpi'><div class='v'>{_esc(summary.get('coverage_mode',''))}</div><small>coverage mode</small></div>")
    html_out.append("</div>")
    html_out.append("</div>")

    if scen:
        html_out.append("<div class='card'>")
        html_out.append("<h2>Scenario coverage</h2>")
        html_out.append("<div class='h'>")
        html_out.append(f"<div class='kpi'><div class='v'>{_esc(scen.get('coverage',''))}</div><small>coverage</small></div>")
        html_out.append(f"<div class='kpi'><div class='v'>{_esc(scen.get('observedCount',''))}</div><small>observed</small></div>")
        html_out.append(f"<div class='kpi'><div class='v'>{_esc(scen.get('expectedCount',''))}</div><small>expected</small></div>")
        html_out.append("</div>")
        html_out.append("</div>")

    if md.strip():
        html_out.append("<div class='card'>")
        html_out.append("<h2>Markdown report (raw)</h2>")
        html_out.append("<pre>")
        html_out.append(_esc(md))
        html_out.append("</pre>")
        html_out.append("</div>")

    html_out.append("</body></html>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(html_out) + "\n", encoding="utf-8")
    return str(out_path)


def write_scenario_html(
    *,
    run_json_path: Path,
    scenario_json_path: Path,
    scenario_md_path: Optional[Path],
    out_path: Path,
    title: str = "Scenario coverage",
) -> str:
    """Create a single-file scenario HTML view.

    This is meant to be opened directly from the dashboard (scenario.html).
    """

    runj = _read_json(run_json_path)
    scen = _read_json(scenario_json_path)
    md = _read_text(scenario_md_path) if scenario_md_path else ""

    html_out = []
    html_out.append("<!doctype html>")
    html_out.append("<html><head><meta charset='utf-8'>")
    html_out.append(f"<title>{_esc(title)}</title>")
    html_out.append(f"<style>{_DEFAULT_CSS}</style>")
    html_out.append("</head><body>")

    html_out.append(f"<h1>{_esc(title)}</h1>")
    html_out.append(f"<small>run_id: {_esc(runj.get('run_id',''))}</small>")

    html_out.append("<div class='card'>")
    html_out.append("<div class='h'>")
    html_out.append(f"<div class='kpi'><div class='v'>{_esc(scen.get('coverage',''))}</div><small>coverage</small></div>")
    html_out.append(f"<div class='kpi'><div class='v'>{_esc(scen.get('observedCount',''))}</div><small>observed</small></div>")
    html_out.append(f"<div class='kpi'><div class='v'>{_esc(scen.get('expectedCount',''))}</div><small>expected</small></div>")
    html_out.append(f"<div class='kpi'><div class='v'>{_esc(scen.get('missingCount',''))}</div><small>missing</small></div>")
    html_out.append("</div>")
    html_out.append("</div>")

    expected = scen.get("expected") if isinstance(scen.get("expected"), list) else []
    observed = scen.get("observed") if isinstance(scen.get("observed"), list) else []
    missing = scen.get("missing") if isinstance(scen.get("missing"), list) else []

    html_out.append("<div class='card'>")
    html_out.append("<h2>Observed scenarios</h2>")
    if not observed:
        html_out.append("<small>(none)</small>")
    else:
        html_out.append("<ul>")
        for s in observed:
            sid = (s.get("id") if isinstance(s, dict) else "") or ""
            desc = (s.get("description") if isinstance(s, dict) else "") or ""
            html_out.append(f"<li><code>{_esc(sid)}</code> {_esc(desc)}</li>")
        html_out.append("</ul>")
    html_out.append("</div>")

    html_out.append("<div class='card'>")
    html_out.append("<h2>Missing scenarios</h2>")
    if not missing:
        html_out.append("<small>(none)</small>")
    else:
        html_out.append("<ul>")
        for sid in missing:
            html_out.append(f"<li><code>{_esc(sid)}</code></li>")
        html_out.append("</ul>")
    html_out.append("</div>")

    if md.strip():
        html_out.append("<div class='card'>")
        html_out.append("<h2>scenario_summary.md (raw)</h2>")
        html_out.append("<pre>")
        html_out.append(_esc(md))
        html_out.append("</pre>")
        html_out.append("</div>")

    # Keep a small snippet of evidence for debugging
    ev = scen.get("evidence") if isinstance(scen.get("evidence"), dict) else {}
    if ev:
        html_out.append("<div class='card'>")
        html_out.append("<h2>Evidence (snippet)</h2>")
        html_out.append("<pre>")
        html_out.append(_esc(json.dumps(ev, indent=2, sort_keys=True)[:20000]))
        html_out.append("</pre>")
        html_out.append("</div>")

    html_out.append("</body></html>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(html_out) + "\n", encoding="utf-8")
    return str(out_path)


def write_junit_xml(
    *,
    run_json_path: Path,
    scenario_json_path: Optional[Path],
    out_path: Path,
    suite_name: str = "thesis-fuzzer",
) -> str:
    """Write a small JUnit XML summary for CI ingestion.

    We model:
    - one testsuite per run
    - a few synthetic testcases: crashes==0, scenario_coverage==1, etc.
    """

    runj = _read_json(run_json_path)
    scen = _read_json(scenario_json_path) if scenario_json_path else {}

    summary = runj.get("summary", {}) if isinstance(runj.get("summary"), dict) else {}

    # Surface requested coverage mode (edge vs branch) if present.
    requested_mode = ""
    if isinstance(runj.get("native_coverage"), dict) and runj["native_coverage"].get("requested_mode"):
        requested_mode = str(runj["native_coverage"].get("requested_mode"))
    elif isinstance(runj.get("afl"), dict) and isinstance(runj["afl"].get("coverage"), dict):
        requested_mode = str(runj["afl"]["coverage"].get("requested_mode", ""))
    if requested_mode:
        summary["coverage_mode"] = requested_mode

    # Back-compat: earlier run.json schema stores AFL result under runj["afl"].
    if not summary and isinstance(runj.get("afl"), dict):
        afl = runj.get("afl")
        summary = {
            "total_crashes": afl.get("crashes_found", ""),
            "unique_crashes": afl.get("crashes_found", ""),
            "queue_size": afl.get("queue_size", ""),
            "bitmap_coverage_percent": "",
        }
        # Try to read bitmap_cvg from fuzzer_stats if present.
        fsp = afl.get("fuzzer_stats_path")
        if isinstance(fsp, str) and fsp:
            try:
                for ln in Path(fsp).read_text(errors="ignore").splitlines():
                    if ln.startswith("bitmap_cvg"):
                        summary["bitmap_coverage_percent"] = ln.split(":", 1)[1].strip()
            except Exception:
                pass

    run_id = str(runj.get("run_id", ""))
    crashes = int(summary.get("total_crashes", 0) or 0)

    # scenario coverage is optional
    sc_cov = None
    try:
        sc_cov = float(scen.get("coverage")) if scen else None
    except Exception:
        sc_cov = None

    tests = 2 + (1 if sc_cov is not None else 0)
    failures = 0

    # testcase: no crashes
    tc1_fail = crashes > 0
    if tc1_fail:
        failures += 1

    # testcase: produced run.json
    tc2_fail = not bool(run_id)
    if tc2_fail:
        failures += 1

    sc_fail = False
    if sc_cov is not None:
        sc_fail = sc_cov < 1.0
        if sc_fail:
            failures += 1

    xml = []
    xml.append("<?xml version='1.0' encoding='UTF-8'?>")
    xml.append(
        f"<testsuite name='{_esc(suite_name)}' tests='{tests}' failures='{failures}' time='0'>"
    )
    if summary.get("coverage_mode") or summary.get("bitmap_coverage_percent"):
        xml.append("  <properties>")
        if summary.get("coverage_mode"):
            xml.append(f"    <property name='coverage_mode' value='{_esc(summary.get('coverage_mode',''))}'/>")
        if summary.get("bitmap_coverage_percent"):
            xml.append(
                f"    <property name='bitmap_coverage_percent' value='{_esc(summary.get('bitmap_coverage_percent',''))}'/>"
            )
        xml.append("  </properties>")

    xml.append(f"  <testcase classname='{_esc(suite_name)}' name='run_has_no_crashes'>")
    if tc1_fail:
        xml.append(f"    <failure message='crashes={crashes}'>crashes={crashes}</failure>")
    xml.append("  </testcase>")

    xml.append(f"  <testcase classname='{_esc(suite_name)}' name='run_has_run_id'>")
    if tc2_fail:
        xml.append("    <failure message='missing run_id'>missing run_id</failure>")
    xml.append("  </testcase>")

    if sc_cov is not None:
        xml.append(f"  <testcase classname='{_esc(suite_name)}' name='scenario_coverage_is_1_0'>")
        if sc_fail:
            xml.append(f"    <failure message='scenario_coverage={sc_cov}'>scenario_coverage={sc_cov}</failure>")
        xml.append("  </testcase>")

    xml.append("</testsuite>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(xml) + "\n", encoding="utf-8")
    return str(out_path)
