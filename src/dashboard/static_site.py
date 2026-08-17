"""Static dashboard generator (single HTML file).

Writes: results/dashboard/index.html

No external dependencies.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import List

from src.dashboard.model import RunRow, load_runs


def _esc(s: object) -> str:
    return html.escape(str(s))


_CSS = """
:root { color-scheme: light; --bg:#ffffff; --muted:#6b7280; --border:#e5e7eb; --head:#0f172a; --card:#ffffff; --card2:#f8fafc; --ok:#16a34a; --warn:#f59e0b; --bad:#ef4444; }

* { box-sizing: border-box; }
body {
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
  margin: 18px;
  background: var(--bg);
  color: #111827;
}
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }

.container { max-width: 1200px; margin: 0 auto; }

.header { display:flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h1 { margin: 0; font-size: 20px; color: var(--head); }
.small { color: var(--muted); font-size: 12px; }

.row { display:flex; gap: 10px; flex-wrap: wrap; align-items: center; }

.card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
  margin: 12px 0;
  background: var(--card);
  box-shadow: 0 1px 2px rgba(15,23,42,0.04);
}

.kpis { display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; }
@media (max-width: 900px){ .kpis { grid-template-columns: repeat(2, minmax(0,1fr)); } }
@media (max-width: 520px){ .kpis { grid-template-columns: 1fr; } }

.kpi { background: var(--card2); padding: 10px 12px; border-radius: 12px; border:1px solid var(--border); }
.kpi .label { color: var(--muted); font-size: 12px; }
.kpi .value { font-size: 18px; font-weight: 700; }

.toolbar { display:flex; gap: 10px; flex-wrap: wrap; align-items: center; justify-content: space-between; }

input, select {
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 10px;
  background: #fff;
  min-width: 240px;
}
select { min-width: 200px; }

.table-wrap { overflow-x: auto; border-radius: 12px; border: 1px solid var(--border); }
.table { width: 100%; border-collapse: collapse; min-width: 980px; }
.table th, .table td { border-bottom: 1px solid var(--border); padding: 10px 10px; text-align: left; vertical-align: top; }
.table th { background: #f8fafc; position: sticky; top: 0; z-index: 1; font-size: 12px; color: #334155; text-transform: uppercase; letter-spacing: .04em; }
.table tr:hover td { background: #fafafa; }

.badge { padding: 2px 8px; border-radius: 999px; background: #eef2ff; border: 1px solid #e0e7ff; font-size: 12px; }

.btn { display:inline-block; padding: 6px 10px; border:1px solid #d1d5db; border-radius: 10px; text-decoration:none; color: inherit; background:#fff; }
.btn.secondary { background:#f8fafc; }
.btn.disabled { opacity: 0.45; cursor: not-allowed; pointer-events: none; }
.right-align { justify-content: flex-end; }

.right { text-align: right; }
.mono { font-variant-numeric: tabular-nums; font-feature-settings: 'tnum'; }
.pagedOut { display: none !important; }

.status { padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); font-size: 12px; display:inline-block; }
.status.ok { background: rgba(22,163,74,0.10); border-color: rgba(22,163,74,0.25); color: #14532d; }
.status.warn { background: rgba(245,158,11,0.12); border-color: rgba(245,158,11,0.30); color: #7c2d12; }
.status.bad { background: rgba(239,68,68,0.10); border-color: rgba(239,68,68,0.28); color: #7f1d1d; }
.pill.good { background: #dcfce7; color: #14532d; border-color:#bbf7d0; }
.pill.warn { background: #fef9c3; color: #713f12; border-color:#fde68a; }
.pill.bad  { background: #fee2e2; color: #7f1d1d; border-color:#fecaca; }
""".strip()


_JS = r"""
function $(id){ return document.getElementById(id); }

function _hiddenSet(){
  try {
    return new Set(JSON.parse(localStorage.getItem('thesis_fuzzer.hidden_run_ids') || '[]'));
  } catch (e) {
    return new Set();
  }
}

function isHidden(runId){
  return _hiddenSet().has(runId);
}

function hideSelected(){
  const boxes = document.querySelectorAll("input[data-runid]:checked");
  if (!boxes.length) { alert('Select at least one run to hide'); return; }
  const s = _hiddenSet();
  for (const b of boxes){
    const id = b.getAttribute('data-runid');
    if (id) s.add(id);
  }
  localStorage.setItem('thesis_fuzzer.hidden_run_ids', JSON.stringify(Array.from(s)));
  applyFilters();
}

let _page = 1;

function _getPageSize(){
  const sel = $('pageSize');
  const v = sel ? parseInt(sel.value || '25', 10) : 25;
  return isNaN(v) ? 25 : v;
}

function _visibleRows(){
  return Array.from(document.querySelectorAll('tr[data-run]'))
    .filter(tr => tr.style.display !== 'none');
}

function _renderPage(){
  const rows = _visibleRows();
  const pageSize = _getPageSize();
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  _page = Math.min(Math.max(1, _page), totalPages);

  // hide all, then show slice
  for (const tr of rows) tr.classList.add('pagedOut');
  const start = (_page - 1) * pageSize;
  const end = start + pageSize;
  for (const tr of rows.slice(start, end)) tr.classList.remove('pagedOut');

  const info = $('pageInfo');
  if (info) info.textContent = `page ${_page}/${totalPages} • ${rows.length} rows`;
}

function nextPage(){ _page++; _renderPage(); }
function prevPage(){ _page--; _renderPage(); }

function applyFilters(){
  const q = ($('q').value || '').toLowerCase();
  const fw = $('fw').value;
  const h = $('harness').value;
  const st = $('status').value;

  const rows = document.querySelectorAll('tr[data-run]');
  for (const tr of rows){
    const hay = (tr.getAttribute('data-hay') || '').toLowerCase();
    const fwVal = tr.getAttribute('data-fw') || '';
    const hVal = tr.getAttribute('data-harness') || '';
    const stVal = tr.getAttribute('data-status') || '';
    const runId = tr.getAttribute('data-runid') || '';

    let ok = true;
    if (q && !hay.includes(q)) ok = false;
    if (fw && fw !== fwVal) ok = false;
    if (h && h !== hVal) ok = false;
    if (st && st !== stVal) ok = false;
    if (runId && isHidden(runId)) ok = false;

    tr.style.display = ok ? '' : 'none';
    tr.classList.remove('pagedOut');
  }

  _page = 1;
  _renderPage();
}

function populateOptions(){
  const fws = new Set();
  const hs = new Set();
  const sts = new Set();

  const rows = document.querySelectorAll('tr[data-run]');
  for (const tr of rows){
    const fw = tr.getAttribute('data-fw') || '';
    const h = tr.getAttribute('data-harness') || '';
    const st = tr.getAttribute('data-status') || '';
    if (fw) fws.add(fw);
    if (h) hs.add(h);
    if (st) sts.add(st);
  }

  function fill(selId, values){
    const sel = $(selId);
    const sorted = Array.from(values).sort();
    for (const v of sorted){
      const opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      sel.appendChild(opt);
    }
  }

  fill('fw', fws);
  fill('harness', hs);
  fill('status', sts);
}

window.addEventListener('DOMContentLoaded', () => {
  populateOptions();
  applyFilters();
});
"""


def render_index(runs: List[RunRow], *, repo_root: Path) -> str:
    html_out = []
    html_out.append("<!doctype html><html><head><meta charset='utf-8'>")
    html_out.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    html_out.append("<title>Thesis Fuzzer Dashboard</title>")
    # NOTE: No auto-refresh by default. It causes flicker for large tables.
    # If you want auto-refresh while serving, add it back behind a flag.
    html_out.append(f"<style>{_CSS}</style>")
    html_out.append("</head><body>")

    total_runs = len(runs)
    total_crashes = sum(int(r.total_crashes or 0) for r in runs)
    def _avg(vals: list[float]) -> float:
        xs = [v for v in vals if v is not None and v >= 0.0]
        return (sum(xs) / len(xs)) if xs else 0.0

    avg_bitmap = _avg([float(r.bitmap_coverage_percent) for r in runs]) if runs else 0.0
    avg_scen = _avg([float(r.scenario_coverage) for r in runs]) if runs else 0.0

    html_out.append("<div class='container'>")
    html_out.append("<div class='header'>")
    html_out.append("<div>")
    html_out.append("<h1>Thesis Fuzzer Dashboard</h1>")
    html_out.append("<div class='small'>Source: results/run_index.jsonl</div>")
    html_out.append("</div>")
    html_out.append("<div class='small'>Hide runs: select rows + click <b>Hide selected</b> (stored in your browser only).</div>")
    html_out.append("</div>")

    html_out.append("<div class='card'>")
    html_out.append("<div class='kpis'>")
    html_out.append(f"<div class='kpi'><div class='label'>Runs</div><div class='value mono'>{_esc(total_runs)}</div></div>")
    html_out.append(f"<div class='kpi'><div class='label'>Total crashes</div><div class='value mono'>{_esc(total_crashes)}</div></div>")
    html_out.append(f"<div class='kpi'><div class='label'>Avg bitmap %</div><div class='value mono'>{_esc(round(avg_bitmap, 2))}</div></div>")
    html_out.append(f"<div class='kpi'><div class='label'>Avg scenario %</div><div class='value mono'>{_esc(round(avg_scen * 100.0, 2))}</div></div>")
    html_out.append("</div>")
    html_out.append("</div>")

    # Per-firmware rollups (more actionable than global averages)
    fw_stats = {}
    for r in runs:
        fw = r.target or "(unknown)"
        s = fw_stats.setdefault(fw, {"runs": 0, "crashes": 0, "sum_bitmap": 0.0, "sum_scen": 0.0})
        s["runs"] += 1
        s["crashes"] += int(r.total_crashes or 0)
        s["sum_bitmap"] += float(r.bitmap_coverage_percent) if float(r.bitmap_coverage_percent) >= 0.0 else 0.0
        s["sum_scen"] += float(r.scenario_coverage) if float(r.scenario_coverage) >= 0.0 else 0.0

    html_out.append("<div class='card'>")
    html_out.append("<div class='h2'>Firmware overview</div>")
    html_out.append("<div class='table-wrap'>")
    html_out.append("<table class='table'>")
    html_out.append("<thead><tr><th>firmware</th><th class='right'>runs</th><th class='right'>crashes</th><th class='right'>avg bitmap %</th><th class='right'>avg scenario %</th></tr></thead>")
    html_out.append("<tbody>")
    for fw in sorted(fw_stats.keys()):
        s = fw_stats[fw]
        runs_n = s["runs"]
        avg_b = (s["sum_bitmap"] / runs_n) if runs_n else 0.0
        avg_sc = (s["sum_scen"] / runs_n) if runs_n else 0.0
        html_out.append(
            "<tr><td><span class='badge'>%s</span></td><td class='right mono'>%d</td><td class='right mono'>%d</td><td class='right mono'>%.2f</td><td class='right mono'>%.2f</td></tr>"
            % (_esc(fw), runs_n, s["crashes"], avg_b, (avg_sc * 100.0))
        )
    html_out.append("</tbody></table>")
    html_out.append("</div>")
    html_out.append("</div>")

    html_out.append("<div class='card'>")
    html_out.append("<div class='toolbar'>")
    html_out.append("<div class='row'>")
    html_out.append("<label class='small'>Search</label>")
    html_out.append("<input id='q' oninput='applyFilters()' placeholder='run_id / firmware / harness' />")
    html_out.append("</div>")

    html_out.append("<div class='row'>")
    html_out.append("<label class='small'>Firmware</label>")
    html_out.append("<select id='fw' onchange='applyFilters()'><option value=''>All</option></select>")
    html_out.append("</div>")

    html_out.append("<div class='row'>")
    html_out.append("<label class='small'>Harness</label>")
    html_out.append("<select id='harness' onchange='applyFilters()'><option value=''>All</option></select>")
    html_out.append("</div>")

    html_out.append("<div class='row'>")
    html_out.append("<label class='small'>Status</label>")
    html_out.append("<select id='status' onchange='applyFilters()'><option value=''>All</option></select>")
    html_out.append("</div>")

    html_out.append("<div class='row right-align'>")
    html_out.append("<button class='btn secondary' onclick='hideSelected()'>Hide selected</button>")
    html_out.append("</div>")
    html_out.append("</div>")
    html_out.append("</div>")

    html_out.append("<div class='table-wrap'>")

    # pagination controls (reduces horizontal scrolling pain)
    html_out.append("<div class='row' style='justify-content:space-between; align-items:center; margin: 10px 0;'>")
    html_out.append("<div>")
    html_out.append("<span class='small'>Rows per page</span>")
    html_out.append("<select id='pageSize' onchange='applyFilters()'>")
    html_out.append("<option value='10'>10</option><option value='25' selected>25</option><option value='50'>50</option><option value='100'>100</option>")
    html_out.append("</select>")
    html_out.append("</div>")
    html_out.append("<div>")
    html_out.append("<button class='btn secondary' onclick='prevPage()'>Prev</button>")
    html_out.append("<span class='small mono' id='pageInfo' style='padding:0 8px;'>page</span>")
    html_out.append("<button class='btn secondary' onclick='nextPage()'>Next</button>")
    html_out.append("</div>")
    html_out.append("</div>")

    html_out.append("<table class='table'>")
    html_out.append(
        "<thead><tr><th></th><th>run_id</th><th>firmware</th><th>harness</th><th>status</th><th class='right'>bitmap %</th><th class='right'>scenario %</th><th class='right'>queue</th><th class='right'>crashes</th><th>links</th></tr></thead>"
    )
    html_out.append("<tbody id='runsTbody'>")

    def scen_pill(sc: float) -> str:
        if sc < 0.0:
            return "<span class='pill mono' title='not available'>—</span>"
        if sc >= 0.5:
            cls = "good"
        elif sc > 0.0:
            cls = "warn"
        else:
            cls = "bad"
        return f"<span class='pill {cls} mono' title='{_esc(round(sc*100.0,2))}%'>{_esc(round(sc * 100.0, 2))}%</span>"

    def bitmap_pill(bm: float) -> str:
        if bm < 0.0:
            return "<span class='pill mono' title='not available'>—</span>"
        if bm >= 20.0:
            cls = "good"
        elif bm > 0.0:
            cls = "warn"
        else:
            cls = "bad"
        return f"<span class='pill {cls} mono' title='{_esc(round(bm,2))}%'>{_esc(round(bm, 2))}%</span>"

    def _rel(repo_root: Path, p: str) -> str:
        """Return a link URL that works when serving either:
        - repo root (so /results/... exists), OR
        - results/dashboard as the web root (common during local preview).

        We prefer links relative to `results/dashboard` because users often run:
          python -m http.server --directory results/dashboard
        """
        if not p:
            return ""
        try:
            abs_p = Path(p).resolve()
            # First preference: relative to results/dashboard (for local preview)
            dash_root = (repo_root / "results" / "dashboard").resolve()
            try:
                return _esc(abs_p.relative_to(dash_root))
            except Exception:
                pass
            # Fallback: relative to repo root (for serving repo root)
            try:
                return _esc(abs_p.relative_to(repo_root.resolve()))
            except Exception:
                pass
            return _esc(str(abs_p))
        except Exception:
            return _esc(p)

    for r in runs:
        hay = f"{r.run_id} {r.target} {r.harness} {r.status}".strip()
        links = []

        def link(label: str, path: str) -> str:
            if not path:
                return f"<span class='btn disabled' title='not available'>{_esc(label)}</span>"
            return f"<a class='btn' href='{_rel(repo_root, path)}'>{_esc(label)}</a>"

        # Always render the same link set so the table is stable; disable when missing.
        links.append(link("report.html", r.report_html))
        links.append(link("report.json", r.report_json))
        links.append(link("scenario.json", r.scenario_json))
        links.append(link("scenario.html", r.scenario_html or r.scenario_md))

        html_out.append(
            "<tr data-run='1' data-runid='%s' data-fw='%s' data-harness='%s' data-status='%s' data-hay='%s'>"
            % (_esc(r.run_id), _esc(r.target), _esc(r.harness), _esc(r.status), _esc(hay))
        )
        html_out.append(
            "<td class='right mono'><input type='checkbox' data-runid='%s' aria-label='select %s'></td>"
            % (_esc(r.run_id), _esc(r.run_id))
        )
        # run_id links to report.html when present, otherwise to run.json, otherwise plain
        if r.report_html:
            html_out.append(f"<td><a href='{_rel(repo_root, r.report_html)}'><code>{_esc(r.run_id)}</code></a></td>")
        elif r.report_json:
            html_out.append(f"<td><a href='{_rel(repo_root, r.report_json)}'><code>{_esc(r.run_id)}</code></a></td>")
        else:
            html_out.append(f"<td><code>{_esc(r.run_id)}</code></td>")
        html_out.append(f"<td>{_esc(r.target)}</td>")
        html_out.append(f"<td><span class='badge'>{_esc(r.harness)}</span></td>")
        st = (r.status or '').lower()
        st_cls = 'ok' if ('complete' in st or 'ok' in st or 'done' in st) else ('bad' if ('fail' in st or 'error' in st) else 'warn')
        html_out.append(f"<td><span class='status {st_cls}'>{_esc(r.status or 'unknown')}</span></td>")
        html_out.append(f"<td class='right'>{bitmap_pill(float(r.bitmap_coverage_percent))}</td>")
        html_out.append(f"<td class='right'>{scen_pill(float(r.scenario_coverage))}</td>")
        html_out.append(f"<td class='right mono'>{_esc(r.queue_size)}</td>")
        html_out.append(f"<td class='right mono'>{_esc(r.total_crashes)}</td>")
        html_out.append(f"<td>{' '.join(links) if links else '<span class=small>no reports</span>'}</td>")
        html_out.append("</tr>")

    html_out.append("</tbody></table>")
    html_out.append("</div>")

    html_out.append(f"<script>{_JS}</script>")
    html_out.append("</div>")
    html_out.append("</body></html>")
    return "\n".join(html_out) + "\n"


def generate_static_dashboard(*, repo_root: Path) -> str:
    runs = load_runs(repo_root)
    out_dir = repo_root / "results" / "dashboard"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(render_index(runs, repo_root=repo_root), encoding="utf-8")
    return str(out_path)
