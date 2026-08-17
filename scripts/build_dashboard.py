#!/usr/bin/env python3
"""
build_dashboard.py — single-file cross-trial HTML dashboard.

Walks results/ and aggregates every trial's AFL final stats and gcov coverage,
emits artifacts/dashboard.html and artifacts/dashboard_assets/<trial>.png with
the AFL plot_data growth curve.

Run it any time (idempotent, safe while fuzzing is in progress):

    python scripts/build_dashboard.py
    python -m http.server 8000 --directory artifacts/
    # open http://localhost:8000/dashboard.html

What goes in the dashboard
--------------------------
A. Top-level cards:        live processes, free RAM, free disk, load
B. Per-target summary:     LLM vs baseline mean +/- std edges, gcov %,
                            Mann-Whitney p-value, Vargha-Delaney A12
C. Per-trial table:        target, arm, trial id, status, edges, gcov,
                            run-time, link to per-trial detail page,
                            link to growth-curve PNG
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List, Optional, Tuple

ROOT      = Path(__file__).resolve().parent.parent
RESULTS   = ROOT / "results"
ARTIFACTS = ROOT / "artifacts"
ASSETS    = ARTIFACTS / "dashboard_assets"
ARTIFACTS.mkdir(exist_ok=True)
ASSETS.mkdir(exist_ok=True)

# ---------- small utilities -------------------------------------------------

def read_kv_stats(path: Path) -> Dict[str, str]:
    """Parse an AFL fuzzer_stats key:value file."""
    out: Dict[str, str] = {}
    try:
        for ln in path.read_text(errors="ignore").splitlines():
            if ":" not in ln:
                continue
            k, _, v = ln.partition(":")
            out[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return out


def vargha_delaney_a12(arm_a: List[float], arm_b: List[float]) -> float:
    """A12 effect size: P(X_a > X_b) + 0.5 * P(X_a == X_b)."""
    if not arm_a or not arm_b:
        return 0.5
    greater = 0
    equal = 0
    for a in arm_a:
        for b in arm_b:
            if a > b:
                greater += 1
            elif a == b:
                equal += 1
    n = len(arm_a) * len(arm_b)
    return (greater + 0.5 * equal) / n


def a12_interpret(a12: float) -> str:
    """Vargha-Delaney effect-size class."""
    d = abs(a12 - 0.5)
    if d < 0.06:  return "negligible"
    if d < 0.14:  return "small"
    if d < 0.21:  return "medium"
    return "large"


# ---------- trial discovery -------------------------------------------------

TRIAL_NAME_RE = re.compile(
    r"^(?P<campaign>thesis|local_2h|local_8h|vm_sok|extended_\d+h|smoke"
    r"|compare_final|compare_smoke|compare_thesis)"
    r"_(?P<target>infineon-dc-optimizer|libresolar-bms|libresolar-charge-controller)"
    r"_(?P<arm>llm|baseline)"
    r"_(?P<rid>.+?)$"
)


def parse_trial_dir(d: Path) -> Optional[Dict[str, Any]]:
    """Extract metadata from a results/<rid> dir."""
    m = TRIAL_NAME_RE.match(d.name)
    if not m:
        return None

    info: Dict[str, Any] = {
        "path":     d,
        "name":     d.name,
        "campaign": m.group("campaign"),
        "target":   m.group("target"),
        "arm":      m.group("arm"),
        "rid":      m.group("rid"),
    }

    # AFL final stats (layout is afl/<protocol>/<afl-out-dir>/fuzzer_stats)
    stats: Dict[str, str] = {}
    for fs in d.glob("afl/*/*/fuzzer_stats"):
        stats = read_kv_stats(fs)
        info["fuzzer_stats_path"] = str(fs.relative_to(ROOT))
        plot = fs.parent / "plot_data"
        if plot.exists():
            info["plot_data"] = plot
        break

    info["edges"]         = int(stats.get("edges_found", 0)) if stats.get("edges_found", "").isdigit() else None
    info["paths"]         = int(stats.get("paths_total", 0)) if stats.get("paths_total", "").isdigit() else None
    info["execs_done"]    = int(stats.get("execs_done", 0)) if stats.get("execs_done", "").isdigit() else None
    info["execs_per_sec"] = float(stats.get("execs_per_sec", 0.0)) if stats.get("execs_per_sec", "0").replace(".", "", 1).isdigit() else None
    info["run_time"]      = int(stats.get("run_time", 0)) if stats.get("run_time", "").isdigit() else None
    info["last_update"]   = stats.get("last_update", "")

    # Native (gcov) coverage from replay_gcov.sh -> gcovr summary JSON.
    # Schema reminder (gcovr 5.x summary_format_version 0.6):
    #   line_percent / branch_percent / function_percent at the top level.
    # When the replay script wrote a stub ({"status":"not_run", "line_percent": null})
    # we treat it as "no data" and fall back to coverage/gcov_report.txt if present.
    info["gcov_line_pct"]      = None
    info["gcov_branch_pct"]    = None
    info["gcov_function_pct"]  = None
    info["gcov_status"]        = "missing"

    cov = d / "reports" / "native_coverage.json"
    if cov.exists():
        try:
            c = json.loads(cov.read_text())
            lp = c.get("line_percent")
            bp = c.get("branch_percent")
            fp = c.get("function_percent")
            if lp is not None:
                info["gcov_line_pct"]     = round(float(lp), 2)
            if bp is not None:
                info["gcov_branch_pct"]   = round(float(bp), 2)
            if fp is not None:
                info["gcov_function_pct"] = round(float(fp), 2)
            if c.get("status") == "not_run" or lp is None:
                info["gcov_status"] = "pending"
            else:
                info["gcov_status"] = "ok"
        except Exception:
            info["gcov_status"] = "parse_error"

    # Fallback: if JSON had no numbers, try the text summary gcovr also writes.
    if info["gcov_line_pct"] is None:
        txt = d / "coverage" / "gcov_report.txt"
        if txt.exists():
            try:
                for ln in txt.read_text(errors="ignore").splitlines():
                    # gcovr "TOTAL" line: "TOTAL  547  142  25.96%  660  176  26.67%"
                    if ln.strip().startswith("TOTAL"):
                        parts = ln.split()
                        # find percentages
                        pcts = [p for p in parts if p.endswith("%")]
                        if len(pcts) >= 1:
                            info["gcov_line_pct"]   = float(pcts[0].rstrip("%"))
                        if len(pcts) >= 2:
                            info["gcov_branch_pct"] = float(pcts[1].rstrip("%"))
                        info["gcov_status"] = "ok_from_txt"
                        break
            except Exception:
                pass

    # Is this trial alive right now?
    info["alive"] = is_trial_alive(d.name)

    # Status classification
    if info["alive"]:
        info["status"] = "RUNNING"
    elif info["run_time"] is None or info["run_time"] == 0:
        info["status"] = "NO_DATA"
    elif info["run_time"] < 600:
        info["status"] = "SHORT"
    else:
        info["status"] = "DONE"

    # Per-trial detail report
    rpt = d / "reports" / "report.html"
    info["report_html"] = str(rpt.relative_to(ROOT)) if rpt.exists() else None

    return info


_alive_cache: Optional[set] = None
def is_trial_alive(name: str) -> bool:
    """Cheap process-list scan to see if afl-fuzz is currently writing to this trial."""
    global _alive_cache
    if _alive_cache is None:
        try:
            out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=2).stdout
            _alive_cache = set(re.findall(r"results/([^/\s]+)/(?:seeds|afl/)", out))
        except Exception:
            _alive_cache = set()
    return name in _alive_cache


# ---------- per-trial growth-curve PNG -------------------------------------

def render_plot_png(trial: Dict[str, Any]) -> Optional[Path]:
    """Render edges-found vs time from AFL plot_data into a small PNG."""
    plot_data = trial.get("plot_data")
    if not plot_data or not plot_data.exists():
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    xs, ys = [], []
    for ln in plot_data.read_text().splitlines():
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split(",")
        # AFL++ plot_data columns include: relative_time, ..., edges_found
        if len(parts) < 13:
            continue
        try:
            t      = float(parts[0])
            edges  = float(parts[12])
        except ValueError:
            continue
        xs.append(t / 60.0)   # minutes
        ys.append(edges)

    if not xs:
        return None

    out = ASSETS / f"{trial['name']}.png"
    fig, ax = plt.subplots(figsize=(5, 2.2))
    color = "#0d6efd" if trial["arm"] == "llm" else "#dc3545"
    ax.plot(xs, ys, color=color, linewidth=1.2)
    ax.set_xlabel("Minutes")
    ax.set_ylabel("Edges found")
    ax.set_title(f"{trial['target']} / {trial['arm']} / {trial['rid'][:24]}",
                 fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=80)
    plt.close(fig)
    return out


# ---------- per-target aggregation -----------------------------------------

def aggregate_by_target(trials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_target: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in trials:
        if t["status"] != "DONE":
            continue
        by_target[t["target"]].append(t)

    rows = []
    for target, ts in sorted(by_target.items()):
        llm      = [x for x in ts if x["arm"] == "llm"]
        baseline = [x for x in ts if x["arm"] == "baseline"]
        edges_llm = [x["edges"] for x in llm if x["edges"] is not None]
        edges_bl  = [x["edges"] for x in baseline if x["edges"] is not None]
        gcov_llm  = [x["gcov_line_pct"]   for x in llm      if x["gcov_line_pct"]   is not None]
        gcov_bl   = [x["gcov_line_pct"]   for x in baseline if x["gcov_line_pct"]   is not None]

        row: Dict[str, Any] = {
            "target":    target,
            "n_llm":     len(edges_llm),
            "n_bl":      len(edges_bl),
            "edges_llm_mean": mean(edges_llm) if edges_llm else None,
            "edges_llm_std":  stdev(edges_llm) if len(edges_llm) > 1 else 0.0,
            "edges_bl_mean":  mean(edges_bl) if edges_bl else None,
            "edges_bl_std":   stdev(edges_bl) if len(edges_bl) > 1 else 0.0,
            "gcov_llm_mean":  mean(gcov_llm) if gcov_llm else None,
            "gcov_bl_mean":   mean(gcov_bl) if gcov_bl else None,
        }

        # Stats
        if len(edges_llm) >= 2 and len(edges_bl) >= 2:
            try:
                from scipy.stats import mannwhitneyu
                u, p = mannwhitneyu(edges_llm, edges_bl, alternative="two-sided")
                row["p"]    = p
                row["A12"]  = vargha_delaney_a12(edges_llm, edges_bl)
                row["effect"] = a12_interpret(row["A12"])
            except Exception:
                row["p"], row["A12"], row["effect"] = None, None, "?"
        else:
            row["p"], row["A12"], row["effect"] = None, None, "?"

        rows.append(row)
    return rows


# ---------- HTML render -----------------------------------------------------

def system_card() -> str:
    """Top-line system status block."""
    try:
        load = os.getloadavg()
        load_str = f"{load[0]:.2f} / {load[1]:.2f} / {load[2]:.2f}"
    except OSError:
        load_str = "n/a"
    nproc = os.cpu_count() or "?"

    free_disk = "n/a"
    try:
        du = shutil.disk_usage(ROOT)
        free_disk = f"{du.free / 1e9:.1f} GB free"
    except Exception:
        pass

    free_mem = "n/a"
    try:
        with open("/proc/meminfo") as fp:
            mem = {kv[0]: int(kv[1].split()[0]) for kv in (ln.split(":") for ln in fp)}
        free_mem = f"{mem['MemAvailable'] / 1e6:.2f} GB avail of {mem['MemTotal']/1e6:.1f} GB"
    except Exception:
        pass

    afl_count = 0
    try:
        out = subprocess.run(["pgrep", "-cf", "afl-fuzz"], capture_output=True, text=True, timeout=2).stdout.strip()
        afl_count = int(out) if out.isdigit() else 0
    except Exception:
        pass

    return f"""
    <div class="cards">
      <div class="card"><div class="big">{afl_count}</div><div>AFL processes alive</div></div>
      <div class="card"><div class="big">{nproc}</div><div>CPU cores</div></div>
      <div class="card"><div class="big">{load_str}</div><div>load (1m / 5m / 15m)</div></div>
      <div class="card"><div class="big">{free_mem}</div><div>memory</div></div>
      <div class="card"><div class="big">{free_disk}</div><div>disk</div></div>
    </div>
    """


def fmt(v: Any, dp: int = 1) -> str:
    if v is None:
        return "&mdash;"
    if isinstance(v, float):
        return f"{v:.{dp}f}"
    return str(v)


def render_html(target_rows: List[Dict[str, Any]], trials: List[Dict[str, Any]],
                refresh_seconds: int = 0) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # How many trials are in each gcov state?
    n_gcov_ok      = sum(1 for t in trials if t["gcov_status"] in ("ok", "ok_from_txt"))
    n_gcov_pending = sum(1 for t in trials if t["gcov_status"] == "pending")
    n_gcov_missing = sum(1 for t in trials if t["gcov_status"] == "missing")

    refresh_meta = ""
    refresh_note = "<em>(static snapshot — re-run the script for fresh data)</em>"
    if refresh_seconds > 0:
        refresh_meta = f'<meta http-equiv="refresh" content="{refresh_seconds}">'
        refresh_note = (f'<em>(auto-refresh every {refresh_seconds}s — '
                        f'run <code>python scripts/build_dashboard.py --watch</code> '
                        f'in another terminal to also regenerate)</em>')

    banner = ""
    if n_gcov_pending or n_gcov_missing:
        banner = f"""
        <div class="banner">
          <b>gcov coverage status:</b>
          {n_gcov_ok} trial(s) populated, {n_gcov_pending} pending (gcov replay queued),
          {n_gcov_missing} missing. Coverage 0.00 means the post-run replay hasn't fired yet;
          it runs automatically at the end of <code>run_local_*.sh</code>, or you can
          fire it now with: <code>bash scripts/gcov_all_trials.sh</code>.
        </div>
        """

    # Per-target summary table
    target_html = ["""
    <h2>Per-target summary (DONE trials only)</h2>
    <table>
      <thead><tr>
        <th>Target</th>
        <th>N (LLM / baseline)</th>
        <th>Edges LLM (mean &plusmn; std)</th>
        <th>Edges baseline (mean &plusmn; std)</th>
        <th>gcov-line% LLM</th>
        <th>gcov-line% baseline</th>
        <th>Mann-Whitney p</th>
        <th>A&#8321;&#8322;</th>
        <th>Effect</th>
      </tr></thead><tbody>
    """]
    for r in target_rows:
        sig = ""
        if r["p"] is not None and r["p"] < 0.05:
            sig = " sig"
        target_html.append(f"""<tr class='{sig}'>
            <td><b>{r['target']}</b></td>
            <td>{r['n_llm']} / {r['n_bl']}</td>
            <td>{fmt(r['edges_llm_mean'])} &plusmn; {fmt(r['edges_llm_std'])}</td>
            <td>{fmt(r['edges_bl_mean'])} &plusmn; {fmt(r['edges_bl_std'])}</td>
            <td>{fmt(r['gcov_llm_mean'], 2)}</td>
            <td>{fmt(r['gcov_bl_mean'], 2)}</td>
            <td>{fmt(r['p'], 4)}</td>
            <td>{fmt(r['A12'], 3)}</td>
            <td>{r['effect']}</td>
        </tr>""")
    target_html.append("</tbody></table>")

    # Per-trial table
    trial_html = ["""
    <h2>All trials</h2>
    <p class="note">Status: <span class="badge run">RUNNING</span> = AFL still active &middot;
       <span class="badge done">DONE</span> &ge; 600s of runtime &middot;
       <span class="badge short">SHORT</span> &lt; 600s &middot;
       <span class="badge nodata">NO_DATA</span> no fuzzer_stats yet</p>
    <table>
      <thead><tr>
        <th>Target</th>
        <th>Arm</th>
        <th>Campaign</th>
        <th>RID</th>
        <th>Status</th>
        <th>Edges</th>
        <th>gcov-line%</th>
        <th>gcov-br%</th>
        <th>Run-time (s)</th>
        <th>execs/s</th>
        <th>Details</th>
        <th>Curve</th>
      </tr></thead><tbody>
    """]
    # Sort: alive first, then most recent
    trials_sorted = sorted(trials, key=lambda x: (not x["alive"], -x["path"].stat().st_mtime))
    for t in trials_sorted:
        klass = {"RUNNING": "run", "DONE": "done", "SHORT": "short", "NO_DATA": "nodata"}.get(t["status"], "")
        rpt_link = f'<a href="../{t["report_html"]}">report</a>' if t["report_html"] else "&mdash;"
        png_path = ASSETS / f"{t['name']}.png"
        png_link = f'<a href="dashboard_assets/{t["name"]}.png">PNG</a>' if png_path.exists() else "&mdash;"

        # Distinguish "0% line coverage" from "gcov hasn't run yet"
        if t["gcov_status"] in ("ok", "ok_from_txt"):
            gcov_l = fmt(t['gcov_line_pct'], 2)
            gcov_b = fmt(t['gcov_branch_pct'], 2)
        elif t["gcov_status"] == "pending":
            gcov_l = "<span class='gpending'>pending</span>"
            gcov_b = "<span class='gpending'>pending</span>"
        else:
            gcov_l = "&mdash;"
            gcov_b = "&mdash;"

        trial_html.append(f"""<tr>
            <td>{t['target']}</td>
            <td>{t['arm']}</td>
            <td>{t['campaign']}</td>
            <td><span class='rid'>{t['rid']}</span></td>
            <td><span class='badge {klass}'>{t['status']}</span></td>
            <td>{fmt(t['edges'])}</td>
            <td>{gcov_l}</td>
            <td>{gcov_b}</td>
            <td>{fmt(t['run_time'])}</td>
            <td>{fmt(t['execs_per_sec'])}</td>
            <td>{rpt_link}</td>
            <td>{png_link}</td>
        </tr>""")
    trial_html.append("</tbody></table>")

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
{refresh_meta}
<title>Fuzzing dashboard</title>
<style>
  body {{ font: 14px/1.4 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          margin: 22px; color: #222; background: #fafafa; }}
  h1 {{ margin: 0 0 4px; }}
  h2 {{ margin-top: 32px; border-bottom: 2px solid #ddd; padding-bottom: 6px; }}
  .note {{ color: #666; font-size: 12px; }}
  .banner {{ background: #fff3cd; border: 1px solid #ffe69c; padding: 10px 14px;
             border-radius: 6px; margin: 14px 0; font-size: 13px; color: #664d03; }}
  .cards {{ display: flex; gap: 10px; margin: 14px 0; flex-wrap: wrap; }}
  .card {{ background: #fff; border: 1px solid #ddd; border-radius: 6px;
           padding: 10px 16px; min-width: 130px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
  .card .big {{ font-size: 18px; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border: 1px solid #ddd; font-size: 13px; }}
  th, td {{ padding: 6px 10px; border-bottom: 1px solid #eee; text-align: left; }}
  th {{ background: #f2f5fa; color: #333; }}
  tr.sig {{ background: #ecfdf5; }}
  td .rid {{ font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: #666; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px;
            font-size: 11px; font-weight: 600; color: #fff; }}
  .badge.run   {{ background: #0d6efd; }}
  .badge.done  {{ background: #198754; }}
  .badge.short {{ background: #ffc107; color: #333; }}
  .badge.nodata{{ background: #6c757d; }}
  .gpending    {{ color: #b08800; font-style: italic; }}
  a {{ color: #0d6efd; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  small {{ color: #666; }}
</style></head><body>

<h1>Fuzzing campaign dashboard</h1>
<small>Generated {now} &middot; <code>python scripts/build_dashboard.py</code> &middot; {refresh_note}</small>

{system_card()}

{banner}

{''.join(target_html)}

{''.join(trial_html)}

<p style="margin-top: 26px; color:#666; font-size:12px">
Generated by <code>scripts/build_dashboard.py</code>. The <em>sig</em>-highlighted target
rows have Mann-Whitney p &lt; 0.05 between LLM and baseline. A12 = Vargha-Delaney effect
size (0.5 = no difference; &gt;0.71 = large effect favouring LLM).
</p>

</body></html>
"""


# ---------- main ------------------------------------------------------------

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Build cross-trial HTML dashboard.")
    ap.add_argument("--watch", type=int, metavar="SECS", default=0,
                    help="Regenerate every SECS seconds (default: one-shot).")
    ap.add_argument("--refresh", type=int, metavar="SECS", default=0,
                    help="Embed <meta http-equiv=refresh> in the HTML so the "
                         "browser auto-reloads every SECS. Pairs well with --watch.")
    args = ap.parse_args()

    # If --watch is set without --refresh, set refresh to the same value
    refresh_seconds = args.refresh or args.watch

    def build_once() -> None:
        global _alive_cache
        _alive_cache = None  # force re-scan of ps each iteration
        trials: List[Dict[str, Any]] = []
        for d in sorted(RESULTS.iterdir()):
            if not d.is_dir():
                continue
            info = parse_trial_dir(d)
            if info is None:
                continue
            trials.append(info)
            render_plot_png(info)
        target_rows = aggregate_by_target(trials)
        html = render_html(target_rows, trials, refresh_seconds=refresh_seconds)
        out = ARTIFACTS / "dashboard.html"
        out.write_text(html, encoding="utf-8")
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] wrote {out.name}  ({len(trials)} trials, {len(target_rows)} targets)")

    if args.watch <= 0:
        build_once()
        print(f"==> serve with:  python -m http.server 8000 --directory artifacts/")
        print(f"==> open:        http://localhost:8000/dashboard.html")
        return 0

    print(f"[watch] regenerating every {args.watch}s (HTML auto-refresh: {refresh_seconds}s)")
    print(f"[watch] Ctrl-C to stop.  Serve with: python -m http.server 8000 --directory artifacts/")
    import time
    try:
        while True:
            build_once()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        print("\n[watch] stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
