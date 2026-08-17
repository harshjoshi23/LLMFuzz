"""Flask server wrapper for the dashboard.

Serves the static dashboard and allows linking into run artifacts.

This is optional. If Flask isn't installed, the CLI should print a clear message.
"""

from __future__ import annotations

from pathlib import Path


def serve_dashboard(*, repo_root: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    try:
        from flask import Flask, send_from_directory
    except Exception as e:
        raise RuntimeError(
            "Flask is not installed. Install with: pip install flask\n"
            f"Import error: {e}"
        )

    # Ensure static dashboard exists
    from src.dashboard.static_site import generate_static_dashboard

    generate_static_dashboard(repo_root=repo_root)

    app = Flask(__name__)

    @app.get("/")
    def index():
        return send_from_directory(str(repo_root / "results" / "dashboard"), "index.html")

    # Serve everything under results/ to make links work.
    # Also serve direct artifact paths because the static dashboard may link
    # relative to results/dashboard (e.g. ../svcs_smoke_01/reports/report.html).
    @app.get("/results/<path:subpath>")
    def results_files(subpath: str):
        return send_from_directory(str(repo_root / "results"), subpath)

    @app.get("/<path:subpath>")
    def any_files(subpath: str):
        # Allow serving of run artifacts when users open /dashboard links.
        # This intentionally restricts to the results directory.
        results_root = (repo_root / "results").resolve()
        candidate = (results_root / subpath).resolve()
        if not str(candidate).startswith(str(results_root)):
            return ("Not Found", 404)
        if not candidate.exists() or not candidate.is_file():
            return ("Not Found", 404)
        return send_from_directory(str(candidate.parent), candidate.name)

    app.run(host=host, port=port, debug=False)
    return 0
