"""Production CLI entrypoint.

Usage:
  python -m src.cli doctor
  python -m src.cli run --target /path/to/repo --protocol i2c --duration 60 --skip-fuzzing



Offline-first thesis design:
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional


from src.project_manifest import load_manifest
from src.dry_run import run_cli_dry_run
from src.run_schema import new_run_skeleton, now_utc_iso_z, validate_run_json


logger = logging.getLogger("thesis_fuzzer")


@dataclass
class DoctorResult:
    name: str
    ok: bool
    details: str


def _print_table(rows: list[DoctorResult]) -> None:
    name_w = max(len(r.name) for r in rows) if rows else 10
    print("\n" + "=" * (name_w + 35))
    print("DOCTOR CHECKS")
    print("=" * (name_w + 35))
    print(f"{'CHECK':{name_w}}  STATUS   DETAILS")
    print(f"{'-'*name_w}  ------   -------")
    for r in rows:
        status = "PASS" if r.ok else "FAIL"
        print(f"{r.name:{name_w}}  {status:6s}   {r.details}")
    print("=" * (name_w + 35))


def cmd_doctor(args: argparse.Namespace) -> int:
    rows: list[DoctorResult] = []


    # LLM enablement gate
    llm_enabled = os.getenv("THESIS_LLM_ENABLED", "1").strip() in {"1", "true", "TRUE", "yes", "YES"}
    rows.append(DoctorResult("THESIS_LLM_ENABLED", llm_enabled, "enabled" if llm_enabled else "disabled"))

    # Auth presence (any supported method)
    api_key = os.getenv("GPT4IFX_API_KEY")
    client_id = os.getenv("GPT4IFX_CLIENT_ID")
    client_secret = os.getenv("GPT4IFX_CLIENT_SECRET")
    basic_user = os.getenv("LLAMA_USER")
    basic_pass = os.getenv("LLAMA_PASSWORD")

    have_auth = bool(api_key) or (bool(client_id) and bool(client_secret)) or (bool(basic_user) and bool(basic_pass))
    auth_details = []
    if api_key:
        auth_details.append(f"bearer(len={len(api_key)})")
    if client_id and client_secret:
        auth_details.append("oauth2(client_credentials)")
    if basic_user and basic_pass:
        auth_details.append("basic->token")

    rows.append(
        DoctorResult(
            "GPT4IFX auth env",
            have_auth,
            ", ".join(auth_details) if auth_details else "NOT set (set GPT4IFX_API_KEY or GPT4IFX_CLIENT_ID/SECRET or LLAMA_USER/PASSWORD)",
        )
    )

    # optional: live probe (only if enabled + auth present)
    if llm_enabled and have_auth and not args.skip_auth_check:
        try:
            from tools.gpt4ifx_probe import _build_ssl_context, _auth_headers, _request_json

            base_url = os.getenv("GPT4IFX_BASE_URL", "https://<your-llm-endpoint>").rstrip("/")
            ca_bundle = os.getenv("GPT4IFX_CA_BUNDLE")
            ctx = _build_ssl_context(ca_bundle)
            headers = _auth_headers(base_url, ctx)

            models = _request_json("GET", f"{base_url}/models", headers=headers, ctx=ctx)
            rows.append(DoctorResult("GPT4IFX /models", True, f"ok ({len(models.get('data', models))} entries)"))

            # Tiny chat completion against a safe default model.
            # Tiny chat completion against a safe default model.
            # Prefer a model that this user is permitted to access.
            # You can override with GPT4IFX_DOCTOR_MODEL.
            model = os.getenv("GPT4IFX_DOCTOR_MODEL")
            if not model:
                # Best-effort: choose from /models_info if available.
                # Fall back to a conservative allowlist.
                try:
                    mi = _request_json("GET", f"{base_url}/models_info", headers=headers, ctx=ctx)
                    data = mi.get("data", []) if isinstance(mi, dict) else []
                    allowed = [m.get("openai_approach_name") for m in data if m.get("user_access")]
                    allowed = [x for x in allowed if isinstance(x, str) and x]
                    # Prefer non-retiring, broadly useful models.
                    pref = [
                        "gpt-5.2",
                        "gpt-5.1",
                        "gpt-5-mini",
                        "gpt-4.1",
                        "gpt-4.1-nano",
                        "claudesonnet4.6",
                        "claudesonnet4.5",
                        "llama3.3-70b",
                        "mixtral",
                        "o4-mini",
                        # retiring soon / last resort
                        "gpt-4o",
                        "gpt-4o-mini",
                        "o3-mini",
                    ]
                    model = next((m for m in pref if m in set(allowed)), None) or (allowed[0] if allowed else None)
                except Exception:
                    model = None

            if not model:
                model = "llama3.3-70b"
            payload: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": "Return exactly: OK"}],
                "temperature": 0.0,
                "stream": False,
            }
            # GPT-5* reasoning models may not accept max_tokens.
            if model.startswith("gpt-5"):
                payload["max_completion_tokens"] = 5
            else:
                payload["max_tokens"] = 5
            out = _request_json("POST", f"{base_url}/chat/completions", headers=headers, body=payload, ctx=ctx)
            msg = out["choices"][0]["message"]["content"]
            # Some models may refuse strict formatting instructions; treat any non-empty response as pass.
            ok = bool((msg or "").strip())
            rows.append(DoctorResult("GPT4IFX chat", ok, f"{model}: {msg!r}"))
        except Exception as e:
            rows.append(DoctorResult("GPT4IFX live probe", False, f"failed: {e}"))

    # vectorstore (legacy default)
    chunks = Path("data/vectorstore/chunks.pkl")
    index = Path("data/vectorstore/faiss.index")
    ok_vs = chunks.exists() and index.exists()
    rows.append(
        DoctorResult(
            "vectorstore (legacy)",
            ok_vs,
            "data/vectorstore present" if ok_vs else "missing data/vectorstore (ok if you use project rag.index_dir)",
        )
    )

    # internal docs ingest (optional, stub)
    ingester = shutil.which("thesis-doc-ingest")
    rows.append(
        DoctorResult(
            "internal docs ingest",
            bool(ingester),
            ingester or "not installed (optional)",
        )
    )

    # afl-fuzz (optional)
    afl = shutil.which("afl-fuzz")
    rows.append(DoctorResult("afl-fuzz", bool(afl), afl or "not found (optional)"))

    # demo harnesses (must not break)
    harness_dir = Path("src/harness")
    demo_bins = ["fuzz_i2c", "fuzz_pmbus", "fuzz_state"]
    missing = [h for h in demo_bins if not (harness_dir / h).exists()]
    rows.append(
        DoctorResult(
            "demo harnesses",
            not missing,
            "OK" if not missing else f"missing: {', '.join(missing)}",
        )
    )

    _print_table(rows)

    # exit code: fail if any required check failed
    required_fail = any((r.name in {"vectorstore", "demo harnesses"} and not r.ok) for r in rows)

    # If LLM is enabled, require *some* auth method to be set.
    if llm_enabled:
        required_fail = required_fail or any((r.name == "GPT4IFX auth env" and not r.ok) for r in rows)

    return 1 if required_fail else 0



def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_index(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.project)

    # Offline ingestion → build index per project
    from src.docs_ingestor import DocsIngestor
    from src.rag_pipeline.rag_pipeline import RAGPipeline

    index_dir = Path(manifest.rag.index_dir)
    corpus_dir = index_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # On --force, wipe stale corpus content before re-ingesting. Old runs may
    # have left files from a previous (possibly polluted) doc set; without
    # this the corpus only grows and the RAG index ends up noisy.
    if args.force and corpus_dir.exists():
        import shutil as _sh
        for entry in corpus_dir.iterdir():
            if entry.is_file():
                entry.unlink()
            else:
                _sh.rmtree(entry, ignore_errors=True)

    sources = [d.path for d in manifest.docs]
    ingestor = DocsIngestor(project_root=manifest.project.target_path)
    res = ingestor.ingest(sources=sources, corpus_dir=str(corpus_dir))

    logger.info("Docs ingested: %s files into %s", res.files_copied, res.corpus_dir)

    # Knowledge-base auto-update:
    # - If corpus is unchanged and index exists, skip rebuilding unless --force.
    from src.rag_pipeline.manifest import RagManifest

    if not args.force:
        try:
            mf = RagManifest.load(index_dir)
            if mf.is_up_to_date(corpus_dir=corpus_dir):
                logger.info("Index is up-to-date; skipping rebuild (use --force to rebuild)")
                return 0
        except Exception as e:
            logger.debug("RAG manifest not usable, will rebuild: %s", e)

    # For now, RAGPipeline consumes a folder of documents.
    rag = RAGPipeline(datasheet_dir=str(corpus_dir), vectorstore_dir=str(index_dir), allow_no_auth=False)

    rag.build_index(force_rebuild=True)

    # Record what we indexed (for incremental rebuild decisions next run)
    try:
        RagManifest.write(index_dir=index_dir, corpus_dir=corpus_dir)
    except Exception as e:
        logger.debug("Failed to write RAG manifest: %s", e)

    logger.info("Index ready at %s", index_dir)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run manifest-driven fuzzing pipeline.

    This is the historical `cmd_fuzz` body.
    """

    manifest = load_manifest(args.project)

    duration = int(args.duration or getattr(manifest.fuzz, "duration_seconds", 0) or 0)
    if duration <= 0:
        duration = 3600

    # results layout
    out_root = Path(args.output or "results")
    run_id = args.run_id or time.strftime("run_%Y%m%d_%H%M%S")
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)
    (out_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    # Initialize canonical run.json (schema-valid) early so later stages can attach paths.
    # IMPORTANT: do NOT write ad-hoc stub structures; always keep run.json schema-valid.
    run_json_path = out_dir / "run.json"
    if not run_json_path.exists():
        run_obj = new_run_skeleton(run_id=run_id, pipeline_name="cmd_fuzz", work_dir=str(out_dir))
        run_json_path.write_text(json.dumps(run_obj, indent=2) + "\n", encoding="utf-8")

    # Generate baseline reports early so artifact contract always has mandatory files.
    # These may be overwritten later with richer content.
    reports_dir = out_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "fuzzing_report.md").write_text(
        f"# Fuzzing report\n\nrun_id: {run_id}\n\nstatus: running\n",
        encoding="utf-8",
    )
    (reports_dir / "fuzzing_report.json").write_text(
        json.dumps({"run_id": run_id, "status": "running"}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Trial summary (baseline metadata; updated at end of run)
    # This is intentionally a flat, evaluation-friendly artifact.
    (reports_dir / "trial_summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "git_sha": None,
                "git_dirty": None,
                "target": getattr(manifest.project, "name", ""),
                "trial_seed": None,
                "duration_seconds": duration,
                "llm_calls_count": 0,
                "model_id": None,
                "decoding": {},
                "coverage_end": {},
                "coverage_curve": [],
                "unique_crashes_count": 0,
                "crash_signatures": [],
                "scenario_observed_count": 0,
                "scenario_missing_count": 0,
                "total_execs": None,
                "execs_per_sec": None,
                "created_at": now_utc_iso_z(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Record run config details for later report regeneration.
    try:
        run_obj = json.loads(run_json_path.read_text(encoding="utf-8"))
        run_obj.setdefault("pipeline", {}).setdefault("config", {})
        run_obj["pipeline"]["config"].update(
            {
                "manifest_path": str(Path(args.project).resolve()),
                "protocol": str(args.protocol or manifest.fuzz.protocol),
                "harness_path": str(harness_path) if 'harness_path' in locals() else None,
            }
        )
        run_json_path.write_text(json.dumps(run_obj, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    os.environ["THESIS_BLACKBOARD_PATH"] = str(out_dir / "blackboard.jsonl")
    try:
        from src.utils.blackboard import bb_event

        bb_event(
            "Orchestrator",
            "run_started",
            run_id=run_id,
            command="fuzz",
            protocol=args.protocol,
            duration=args.duration,
            seed_count=args.seed_count,
            output_dir=str(out_dir),
        )
    except Exception:
        pass

    # Propagate artifact directory so harness can emit scenario events.
    os.environ["THESIS_ARTIFACTS_DIR"] = str(out_dir / "artifacts")
    # Compatibility for harnesses that log directly to a file path.
    os.environ["THESIS_SCENARIO_LOG"] = str(out_dir / "artifacts" / "scenario_events.log")

    # Use adapter pattern for harness
    from src.targets_adapters import GenericExecutableHarnessAdapter

    # Optional override: select harness variant without editing manifest.
    #
    # SVC:
    #   export THESIS_SVC_TARGET=pool|db|tb
    #
    # PWRCTRL (3p3z):
    #   export THESIS_PWRCTRL_BLOCK=filter_3p3z|ac_rms_pll|mppt
    #
    # The manifest for mtb-pwrctrl is protocol-level (3p3z), so without this override
    # all runs would share the same prebuilt harness path.
    svc_target = os.environ.get("THESIS_SVC_TARGET")
    if svc_target and hasattr(manifest.fuzz, "harness_variants") and manifest.fuzz.harness_variants:
        variant = manifest.fuzz.harness_variants.get(svc_target)
        if variant and isinstance(variant, dict) and variant.get("path"):
            manifest.fuzz.harness.path = variant["path"]
            if variant.get("entrypoint"):
                manifest.fuzz.harness.entrypoint = variant["entrypoint"]

    pwrctrl_block = os.environ.get("THESIS_PWRCTRL_BLOCK")
    if pwrctrl_block and (args.protocol == "3p3z" or manifest.fuzz.protocol == "3p3z"):
        manifest.fuzz.harness.path = f"build/pwrctrl/{pwrctrl_block}/fuzz_{pwrctrl_block}"

    # If the manifest declares an afl_c_harness with a C source file, build it
    # to a binary under build/<project_name>/<stem>. This replaces the prebuilt
    # demo harness so AFL actually fuzzes the target-specific code path.
    if manifest.fuzz.harness.type == "afl_c_harness" and manifest.fuzz.harness.c_file:
        c_src = Path(manifest.fuzz.harness.c_file)
        if not c_src.is_absolute():
            c_src = (Path.cwd() / c_src).resolve()
        if not c_src.exists():
            raise SystemExit(f"harness.c_file not found: {c_src}")
        build_dir = Path("build") / manifest.project.name
        build_dir.mkdir(parents=True, exist_ok=True)
        bin_path = build_dir / c_src.stem
        # Link the shared firmware-adapters stubs so the harness's extern
        # entrypoints (e.g. dc_optimizer_process_frame, bms_process_packet,
        # charge_controller_process_i2c) resolve at link time.
        adapters_c = Path("src/harness/firmware_adapters.c")
        # Rebuild if missing or any source (wrapper *or* adapters) is newer
        # than the binary. Without checking adapters_c, edits to the widened
        # protocol surface would silently NOT make it into the binary.
        needs_build = not bin_path.exists() or c_src.stat().st_mtime > bin_path.stat().st_mtime
        if not needs_build and adapters_c.exists():
            needs_build = adapters_c.stat().st_mtime > bin_path.stat().st_mtime
        if needs_build:
            import subprocess
            cflags = [
                "-O2", "-g",
                "-I", "src/harness",
                "-I", "src/harness/stubs",
                *manifest.fuzz.harness.extra_cflags,
            ]
            extra_sources: List[str] = []
            if adapters_c.exists():
                extra_sources.append(str(adapters_c))
            cmd = ["afl-clang-fast", *cflags, str(c_src), *extra_sources, "-o", str(bin_path)]
            logger.info("Building harness: %s", " ".join(cmd))
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as e:
                raise SystemExit(f"Harness build failed (rc={e.returncode}): {' '.join(cmd)}")
            except FileNotFoundError:
                raise SystemExit("afl-clang-fast not found on PATH. Install AFL++ first.")
        manifest.fuzz.harness.path = str(bin_path)
        logger.info("Using compiled afl_c_harness binary: %s", bin_path)

    harness_path: str | None = None
    try:
        harness_adapter = GenericExecutableHarnessAdapter(harness_path=manifest.fuzz.harness.path)
        harness_path = harness_adapter.get_harness_path()
    except Exception as e:
        logger.warning("Harness path invalid (%s). Trying discovery/baseline fallback...", e)
        try:
            from src.discovery import discover_or_fallback

            dres = discover_or_fallback(
                allow_fallback=bool(getattr(manifest, "discovery", None) and manifest.discovery.allow_baseline_harness_fallback),
                out_dir=out_dir / "generated" / "baseline_harness",
            )
            if not dres.ok or not dres.harness_path:
                raise RuntimeError(dres.reason)
            harness_path = dres.harness_path
            logger.info("Using fallback harness: %s", harness_path)
        except Exception as e2:
            raise SystemExit(f"Could not resolve harness path and fallback failed: {e2}")

    # Resolve run configuration
    protocol = args.protocol or manifest.fuzz.protocol
    seed_count = args.seed_count or manifest.fuzz.seed_count
    duration = args.duration or manifest.fuzz.duration_seconds

    # Seed phase (docs index -> constraints -> seeds -> run-scoped corpus)
    # If --skip-fuzzing is set, keep this command runnable without requiring GPT/RAG.
    try:
        from src.utils.blackboard import bb_event
    except Exception:
        bb_event = None

    seeds_dir = out_dir / "seeds"
    seeds_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_fuzzing:
        # Deterministic (no-LLM) seed: still make it non-trivial so the harness can
        # exercise multiple code paths and scenario coverage can be non-zero.
        # This is important for end-to-end smoke tests.
        from src.agents.seed_generator import SeedGeneratorAgent

        sg = SeedGeneratorAgent()
        seed_bytes = sg._encode_svcs_cmdstream({"value": 16}) if protocol in {"svc_svcs_sched", "svcs", "svc"} else bytes([0x00] * 64)
        (seeds_dir / "seed_0000.bin").write_bytes(seed_bytes)
        seed_res = {
            "mode": "minimal",
            "protocol": protocol,
            "constraint_count": 0,
            "seed_count": 1,
            "seeds_dir": str(seeds_dir),
            "topics": [],
        }
    else:
        # Prefer LLM when enabled; otherwise fall back to a deterministic minimal corpus.
        # Default ON: this is the thesis's actual contribution. Set THESIS_LLM_ENABLED=0
        # explicitly only when running the no-LLM baseline configuration.
        llm_enabled = os.getenv("THESIS_LLM_ENABLED", "1").strip().lower() in {"1", "true", "yes", "y"}
        if llm_enabled:
            if bb_event:
                bb_event("SeedAgent", "seed_phase_started", run_id=run_id, mode="llm", seeds_dir=str(seeds_dir))

            from src.pipeline import run_seed_phase_llm

            seed_res = run_seed_phase_llm(
                protocol=protocol,
                manifest_path=str(Path(args.project).resolve()),
                seeds_dir=seeds_dir,
                dry_run=bool(getattr(args, "dry_run", False)),
            )

            if bb_event:
                bb_event("SeedAgent", "seed_phase_finished", run_id=run_id, mode="llm", seed_count=seed_res.get("seed_count", 0))
        else:
            from src.agents.seed_generator import SeedGeneratorAgent

            sg = SeedGeneratorAgent()
            seed_bytes = sg._encode_svcs_cmdstream({"value": 16}) if protocol in {"svc_svcs_sched", "svcs", "svc"} else bytes([0x00] * 64)
            (seeds_dir / "seed_0000.bin").write_bytes(seed_bytes)
            seed_res = {
                "mode": "minimal",
                "protocol": protocol,
                "constraint_count": 0,
                "seed_count": 1,
                "seeds_dir": str(seeds_dir),
                "topics": [],
                "llm": {"calls": 0, "model": None, "decoding": {}},
            }

    results = dict(seed_res)

    # Fail-fast guard: guided/adaptive mode must *actually* call the LLM.
    # If LLM is unavailable, we do not want a silent fallback.
    if (seed_res.get("mode") == "llm") and int((seed_res.get("llm") or {}).get("calls") or 0) == 0:
        raise SystemExit("Guided mode requested but no LLM calls were made (llm_calls_count==0). Aborting.")

    # Run AFL++ (or dry-run) using run-scoped corpus
    from src.afl_runner import AflRunner

    # If user requested CLI dry-run, never execute AFL/build.
    if bool(getattr(args, "dry_run", False)):
        afl_res = type("AflResult", (), {"__dict__": {"skipped": True, "reason": "cli_dry_run"}})()
    else:
        afl = AflRunner()
        afl_res = afl.run(
            protocol=protocol,
            duration_seconds=duration,
            results_root=str(out_root),
            run_id=run_id,
            harness_path=harness_path,
            corpus_dir=str(seeds_dir),
            dry_run=args.skip_fuzzing,
            resume=bool(getattr(args, "resume", False)),
            resume_dir=getattr(args, "resume_dir", None),
        )

    results["afl"] = afl_res.__dict__

    # Scenario coverage (best-effort)
    scenario_paths = {}
    try:
        if bb_event:
            bb_event("AnalysisAgent", "scenario_coverage_started", run_id=run_id)

        from src.analysis.scenario_coverage import compute_scenario_coverage, write_scenario_artifacts

        sc_res = compute_scenario_coverage(manifest=manifest, run_id=run_id, artifacts_dir=out_dir / "artifacts")
        paths = write_scenario_artifacts(result=sc_res, out_dir=out_dir / "reports", write_csv=True)
        scenario_paths = paths
        results["scenario"] = paths

        # Optional: HTML/JUnit exports (single-file, stakeholder-friendly)
        try:
            from src.reporters.html_xml_export import write_html_report, write_junit_xml, write_scenario_html

            run_json_path = out_dir / "run.json"
            scenario_json_path = None
            if scenario_paths and scenario_paths.get("scenario_coverage_json"):
                scenario_json_path = Path(scenario_paths["scenario_coverage_json"])

            scenario_md_path = None
            if scenario_paths and scenario_paths.get("scenario_summary_md"):
                scenario_md_path = Path(scenario_paths["scenario_summary_md"])

            html_path = out_dir / "reports" / "report.html"
            scenario_html_path = out_dir / "reports" / "scenario.html"
            junit_path = out_dir / "reports" / "report.junit.xml"

            results.setdefault("reports", {})
            results["reports"]["html"] = write_html_report(
                run_json_path=run_json_path,
                scenario_json_path=scenario_json_path,
                markdown_report_path=scenario_md_path,
                out_path=html_path,
                title=f"Thesis Fuzzer Report — {manifest.project.name} — {run_id}",
            )

            if scenario_json_path is not None:
                results["reports"]["scenario_html"] = write_scenario_html(
                    run_json_path=run_json_path,
                    scenario_json_path=scenario_json_path,
                    scenario_md_path=scenario_md_path,
                    out_path=scenario_html_path,
                    title=f"Scenario coverage — {manifest.project.name} — {run_id}",
                )

            results["reports"]["junit_xml"] = write_junit_xml(
                run_json_path=run_json_path,
                scenario_json_path=scenario_json_path,
                out_path=junit_path,
                suite_name="thesis-fuzzer",
            )
        except Exception as e:
            logger.debug("HTML/XML export skipped: %s", e)

        if bb_event:
            bb_event(
                "AnalysisAgent",
                "scenario_coverage_finished",
                run_id=run_id,
                coverage=sc_res.coverage,
                expected=sc_res.expectedCount,
                observed=sc_res.observedCount,
                artifacts=paths,
            )

    except Exception as e:
        logger.warning("Scenario coverage generation failed: %s", e)
        if bb_event:
            bb_event("AnalysisAgent", "scenario_coverage_failed", run_id=run_id, error=str(e))

    # Coverage improvement suggestions (best-effort)
    try:
        from src.agents.coverage_improvement_agent import CoverageImprovementAgent

        cov_agent = CoverageImprovementAgent()
        afl_out = Path(str(out_root)) / run_id / "afl" / protocol
        results["coverage_improvement"] = cov_agent.analyze(
            protocol=protocol,
            afl_output_dir=str(afl_out),
            harness_path=harness_path,
            target_path=str(manifest.project.target_path),
        )

        (out_dir / "reports" / "coverage_improvement.json").write_text(
            json.dumps(results["coverage_improvement"], indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Coverage improvement analysis failed: %s", e)

    # Native coverage (optional; requires instrumented build + tools)
    native_cov: dict[str, Any] = {}
    try:
        from src.analysis.native_coverage import collect_native_coverage

        # Heuristic: look for coverage artifacts near the harness.
        # This stays repo-agnostic: if nothing exists, we record "not_run".
        harness_parent = str(Path(harness_path).resolve().parent)
        cov_out_dir = str(out_dir / "coverage")
        native_res = collect_native_coverage(
            build_dir=harness_parent,
            out_dir=cov_out_dir,
            binaries=[str(Path(harness_path).resolve())],
            sources_root=str(manifest.project.target_path),
        )
        native_cov = native_res.__dict__
        native_cov["requested_mode"] = os.environ.get("THESIS_COVERAGE_MODE") or "auto"
        (out_dir / "reports" / "native_coverage.json").write_text(json.dumps(native_cov, indent=2), encoding="utf-8")
        results["native_coverage"] = native_cov
    except Exception as e:
        logger.warning("Native coverage collection skipped/failed: %s", e)

    # append durable run index (best-effort)
    try:
        from src.run_index import append_run_index

        append_run_index(
            repo_root=Path.cwd(),
            run_id=run_id,
            work_dir=out_dir,
            target=str(manifest.project.target_path),
            protocol=protocol,
            harness_path=harness_path,
            corpus_dir=str(seeds_dir),
            afl=afl_res.__dict__,
            coverage={"native": native_cov},
            scenario=scenario_paths,
            crashes={},
            index_path=out_root / "run_index.jsonl",
        )
    except Exception as e:
        logger.warning("Could not append run index: %s", e)

    # Update canonical run.json (schema-valid) with stage outputs and key metrics.
    # Keep legacy details under `extras` to avoid schema drift.
    try:
        run_obj = json.loads(run_json_path.read_text(encoding="utf-8"))
    except Exception:
        run_obj = new_run_skeleton(run_id=run_id, pipeline_name="cmd_fuzz", work_dir=str(out_dir))

    run_obj["status"] = "completed"

    # Minimal environment info (do not dump secrets)
    run_obj["environment"] = {
        "cwd": str(Path.cwd()),
        "platform": sys.platform,
    }

    # Reproducibility metadata (best-effort)
    try:
        from src.artifact_contract import enrich_run_metadata

        enrich_run_metadata(run_obj=run_obj, repo_root=Path.cwd())
    except Exception:
        pass

    # Summarize pipeline stages (high-level)
    run_obj["pipeline"]["stages"] = [
        {
            "id": "seed_phase",
            "name": "src.pipeline.run_seed_phase_llm" if not args.skip_fuzzing else "seed_minimal",
            "status": "completed",
            "startedAt": None,
            "endedAt": None,
            "outputs": [{"path": f"{out_dir}/seeds", "kind": "seeds_dir"}],
            "agents": [],
            "validation": {"status": "not_run", "validator": "run_schema.py@1.0", "checkedAt": None, "errors": []},
        },
        {
            "id": "afl",
            "name": "src.afl_runner.AflRunner.run",
            "status": "skipped" if args.skip_fuzzing else "completed",
            "startedAt": None,
            "endedAt": None,
            "outputs": [{"path": f"{out_dir}/afl/{protocol}", "kind": "afl_output"}],
            "agents": [],
            "validation": {"status": "not_run", "validator": "run_schema.py@1.0", "checkedAt": None, "errors": []},
        },
        {
            "id": "analysis",
            "name": "scenario_coverage + native_coverage + coverage_improvement",
            "status": "completed",
            "startedAt": None,
            "endedAt": None,
            "outputs": [{"path": f"{out_dir}/reports", "kind": "reports_dir"}],
            "agents": [],
            "validation": {"status": "not_run", "validator": "run_schema.py@1.0", "checkedAt": None, "errors": []},
        },
    ]

    # Record high-level outputs (non-exhaustive)
    run_obj.setdefault("extras", {})
    run_obj["extras"].update(
        {
            "mode": "fuzz",
            "project": str(Path(args.project).resolve()),
            "protocol": protocol,
            "run_id": run_id,
            "results_dir": str(out_dir),
            "harness_path": str(harness_path),
            "seed_phase": seed_res,
            "afl": afl_res.__dict__,
            "scenario": scenario_paths,
            "native_coverage": native_cov,
            "coverage": {
                "native": {
                    "status": native_cov.get("status"),
                    "mode": native_cov.get("mode"),
                    "line_percent": native_cov.get("line_percent"),
                    "branch_percent": native_cov.get("branch_percent"),
                    "function_percent": native_cov.get("function_percent"),
                    "artifacts": native_cov.get("artifacts"),
                }
            },
            "results": results,
        }
    )

    ok, errs = validate_run_json(run_obj)
    run_obj["validation"] = {
        "status": "passed" if ok else "failed",
        "validator": "run_schema.py@1.0",
        "checkedAt": now_utc_iso_z(),
        "errors": [{"path": e.path, "message": e.message} for e in errs],
    }

    # Update trial_summary.json (evaluation-friendly single file)
    try:
        ts_path = out_dir / "reports" / "trial_summary.json"
        ts = json.loads(ts_path.read_text(encoding="utf-8")) if ts_path.exists() else {}

        env = run_obj.get("environment") or {}
        ts["git_sha"] = env.get("gitCommit")
        ts["git_dirty"] = env.get("gitDirty")
        ts["duration_seconds"] = duration

        # Scenario counts from scenario_coverage.json if present
        sc_path = out_dir / "reports" / "scenario_coverage.json"
        if sc_path.exists():
            sc = json.loads(sc_path.read_text(encoding="utf-8"))
            ts["scenario_observed_count"] = int(sc.get("observedCount") or 0)
            ts["scenario_missing_count"] = int(sc.get("missingCount") or 0)

        # Coverage end (AFL + native)
        ts["coverage_end"] = {
            "afl": {
                "coverage_percent": (afl_res.__dict__ or {}).get("coverage_percent"),
                "queue_size": (afl_res.__dict__ or {}).get("queue_size"),
                "crashes_found": (afl_res.__dict__ or {}).get("crashes_found"),
            },
            "native": {
                "line_percent": native_cov.get("line_percent"),
                "branch_percent": native_cov.get("branch_percent"),
                "function_percent": native_cov.get("function_percent"),
                "status": native_cov.get("status"),
                "mode": native_cov.get("mode"),
            },
        }

        # AFL exec counts best-effort
        ts["total_execs"] = (afl_res.__dict__ or {}).get("execs_done")
        ts["execs_per_sec"] = (afl_res.__dict__ or {}).get("execs_per_sec")

        # LLM usage best-effort (agents may not populate this yet)
        llm = (run_obj.get("extras") or {}).get("llm") or {}
        if isinstance(llm, dict):
            ts["llm_calls_count"] = int(llm.get("calls") or ts.get("llm_calls_count") or 0)
            ts["model_id"] = llm.get("model") or ts.get("model_id")
            ts["decoding"] = llm.get("decoding") or ts.get("decoding") or {}

        ts_path.write_text(json.dumps(ts, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        logger.warning("Could not write trial_summary.json: %s", e)

    run_json_path.write_text(json.dumps(run_obj, indent=2, default=str) + "\n", encoding="utf-8")

    # Artifact contract validation (evaluation-grade)
    try:
        from src.artifact_contract import validate_run_artifacts

        chk = validate_run_artifacts(run_dir=out_dir)
        if chk.warnings:
            logger.warning("Artifact contract warnings (%d)", len(chk.warnings))
        if not chk.ok:
            logger.error("Artifact contract failed (%d errors)", len(chk.errors))
            for e in chk.errors[:10]:
                logger.error("- %s: %s", e.path, e.message)
            return 2
    except Exception as e:
        logger.warning("Artifact contract validation skipped: %s", e)

    logger.info("Run complete. run.json: %s", run_json_path)
    if not ok:
        logger.warning("run.json schema validation failed (%d errors)", len(errs))

    # Auto-generate dashboard (mandatory for evaluation readiness)
    try:
        from src.dashboard.static_site import generate_static_dashboard

        dash_out = generate_static_dashboard(repo_root=Path.cwd())
        logger.info("Dashboard updated: %s", dash_out)
    except Exception as e:
        logger.warning("Dashboard generation failed: %s", e)

    return 0




def cmd_loop(args: argparse.Namespace) -> int:
    """Run a closed-loop campaign (Agent 3+ controller).

    This runs the manifest-driven pipeline multiple times and writes
    `results/loop_summary.json` (or under --output).
    """

    if bool(getattr(args, "dry_run", False)):
        out_path = run_cli_dry_run(
            project_path=str(Path(args.project).resolve()),
            protocol=str(args.protocol or "i2c"),
            output_root=str(args.output or "results"),
            run_id=None,
            show_rag_content=bool(getattr(args, "show_rag_content", False)),
        )
        print(json.dumps({"dry_run": True, "dry_run_json": str(out_path)}, indent=2))
        return 0

    from src.loop_controller import LoopConfig, run_closed_loop

    cfg = LoopConfig(
        project=str(Path(args.project).resolve()),
        output=str(args.output),
        protocol=args.protocol,
        iterations=int(args.iterations),
        iter_duration_s=int(args.iter_duration),
        skip_fuzzing=bool(args.skip_fuzzing),
        stop_on_crash=bool(args.stop_on_crash),
        resume_afl=bool(getattr(args, "resume_afl", False)),
        resume_dir=getattr(args, "resume_dir", None),
    )

    summary = run_closed_loop(cfg)
    print(json.dumps({"iterations": len(summary.iterations), "output": cfg.output}, indent=2))
    return 0


def cmd_harness(args: argparse.Namespace) -> int:
    """HarnessAgent entrypoint discovery (Option A).

    - Scans the target repo from the manifest.
    - Writes `fuzz.harness.entrypoint_candidates` into the manifest.
    - User selects by setting `fuzz.harness.entrypoint` and rerunning.

    This command is intentionally non-interactive.
    """

    manifest_path = Path(args.project)
    manifest = load_manifest(str(manifest_path))
    target_repo = Path(manifest.project.target_path)

    from src.agents.harness_agent import propose_entrypoints, write_entrypoint_candidates_to_manifest

    cands = propose_entrypoints(target_repo, max_candidates=int(args.max_candidates))
    write_entrypoint_candidates_to_manifest(manifest_path=manifest_path, candidates=cands)

    logger.info("Wrote %d entrypoint candidates into %s", len(cands), manifest_path)
    logger.info("Next: set fuzz.harness.entrypoint in the manifest and rerun `bootstrap` / build step.")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Agent 0: best-effort harness bootstrap (optional).

    This command is intentionally conservative and non-invasive.
    It generates a generic harness stub and runs a basic verification loop.
    For real repos you will usually need to add link flags / init code.
    """

    from src.agents.harness_builder_agent0 import HarnessBuildSpec, build_and_verify

    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    spec = HarnessBuildSpec(
        target_repo=str(Path(args.target).resolve()),
        entrypoint=str(args.entrypoint).strip(),
        language=str(args.lang),
        build_cmd=args.build_cmd,
        include_dirs=args.include_dir,
        extra_sources=args.extra_source,
    )

    res = build_and_verify(spec=spec, out_dir=str(out_dir), timeout_s=int(args.timeout))
    print(json.dumps(res.__dict__, indent=2))
    return 0 if res.status == "completed" else 2


def cmd_report(args: argparse.Namespace) -> int:
    """Regenerate and show report paths under a results/<run_id> directory."""

    results_dir = Path(args.results)
    reports_dir = results_dir / "reports"
    artifacts_dir = results_dir / "artifacts"

    reports_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Try to reload the original manifest used for the run so scenario.signals edits
    # are picked up when regenerating reports.
    manifest_path = None
    try:
        run_json = json.loads((results_dir / "run.json").read_text(encoding="utf-8"))
        manifest_path = run_json.get("pipeline", {}).get("config", {}).get("manifest_path")
    except Exception:
        manifest_path = None

    if manifest_path:
        try:
            from src.project_manifest import load_manifest as _load_manifest
            from src.analysis.scenario_coverage import compute_scenario_coverage, write_scenario_artifacts

            m = _load_manifest(str(manifest_path))
            sc_res = compute_scenario_coverage(manifest=m, run_id=results_dir.name, artifacts_dir=artifacts_dir)
            write_scenario_artifacts(result=sc_res, out_dir=reports_dir, write_csv=True)
        except Exception as e:
            logger.warning("Scenario coverage generation failed: %s", e)

    # Best-effort HTML + JUnit exports
    try:
        from src.reporters.html_xml_export import write_html_report, write_junit_xml

        write_html_report(
            run_json_path=results_dir / "run.json",
            scenario_json_path=reports_dir / "scenario_coverage.json",
            markdown_report_path=reports_dir / "fuzzing_report.md",
            out_path=reports_dir / "report.html",
            title=f"Fuzzing report: {results_dir.name}",
        )
        write_junit_xml(
            run_json_path=results_dir / "run.json",
            scenario_json_path=reports_dir / "scenario_coverage.json",
            out_path=reports_dir / "report.junit.xml",
            suite_name="thesis-fuzzer",
        )
    except Exception:
        pass

    candidates = sorted([p for p in reports_dir.rglob("*") if p.is_file()])
    if not candidates:
        logger.warning("No report files found under %s", reports_dir)
        return 0

    logger.info("Report files under %s:", reports_dir)
    for p in candidates:
        logger.info("- %s", p)

    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from src.dashboard.static_site import generate_static_dashboard

    if getattr(args, "serve", False):
        try:
            from src.dashboard.server import serve_dashboard

            return int(serve_dashboard(repo_root=Path.cwd(), host=str(args.host), port=int(args.port)))
        except Exception as e:
            logger.error("Dashboard server failed: %s", e)
            logger.info("Tip: install optional deps: pip install -r requirements-dashboard.txt")
            return 2

    out = generate_static_dashboard(repo_root=Path.cwd())
    logger.info("Dashboard generated: %s", out)
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from src.evaluation import run_evaluation

    res = run_evaluation(
        project=str(args.project),
        output=str(args.output),
        protocol=str(args.protocol) if args.protocol else None,
        duration_s=int(args.duration),
        trials=int(args.trials),
        skip_fuzzing=bool(args.skip_fuzzing),
    )

    # Print a small summary to stdout
    print(json.dumps({"trials": len(res.trials_metrics), "results_dir": res.results_dir}, indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Statistical comparison of LLM vs baseline groups (SoK-grounded).

    Reads AFL++ plot_data from each supplied run dir, computes per-SoK
    metrics (final coverage, time-to-X%, executions, Mann-Whitney U,
    Vargha-Delaney A12) and writes a self-contained summary.
    """
    from src.eval_compare import compare_groups
    cmp = compare_groups(
        llm_globs=list(args.llm),
        baseline_globs=list(args.baseline),
        out_dir=Path(args.out),
    )
    print(f"LLM runs:      {len(cmp.llm_runs)}")
    print(f"Baseline runs: {len(cmp.baseline_runs)}")
    print(f"Outputs in:    {args.out}")
    if cmp.tests:
        print("Statistical tests:")
        for m, t in cmp.tests.items():
            marker = " *SIGNIFICANT*" if t["p_value"] < 0.05 else ""
            print(f"  {m:22s}  p={t['p_value']:.4f}  A12={t['A12_llm_vs_baseline']:.3f}"
                  f"  (n_llm={int(t['n_llm'])}, n_baseline={int(t['n_baseline'])}){marker}")
    return 0


def cmd_fuzz(args: argparse.Namespace) -> int:
    """Run manifest-driven fuzzing pipeline."""

    if bool(getattr(args, "dry_run", False)):
        out_path = run_cli_dry_run(
            project_path=str(Path(args.project).resolve()),
            protocol=str(args.protocol or "i2c"),
            output_root=str(args.output or "results"),
            run_id=getattr(args, "run_id", None),
            show_rag_content=bool(getattr(args, "show_rag_content", False)),
        )
        print(json.dumps({"dry_run": True, "dry_run_json": str(out_path)}, indent=2))
        return 0

    return cmd_run(args)

    run_id = args.run_id or time.strftime("run_%Y%m%d_%H%M%S")
    results_dir = Path("results") / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "seeds").mkdir(parents=True, exist_ok=True)
    (results_dir / "reports").mkdir(parents=True, exist_ok=True)
    (results_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    # Allow harnesses to emit scenario evidence.
    os.environ["THESIS_ARTIFACTS_DIR"] = str(results_dir / "artifacts")
    os.environ["THESIS_SCENARIO_LOG"] = str(results_dir / "artifacts" / "scenario_events.log")

    # Enable blackboard trace for multi-agent audit.
    os.environ["THESIS_BLACKBOARD_PATH"] = str(results_dir / "blackboard.jsonl")

    target = Path(args.target)
    if not target.exists():
        raise FileNotFoundError(f"Target path not found: {target}")

    protocol = args.protocol
    block = args.block

    if protocol == "3p3z" and not block:
        raise SystemExit("--block is required when --protocol=3p3z")

    # `run` is target-driven (no project), so we skip manifest-based scenario detection here.
    # Use `fuzz --project ...` for real scenario coverage.
    manifest = None

    pipeline_res: dict[str, Any] = {
        "mode": "run",
        "notes": "cmd_run avoids deprecated legacy pipeline entrypoint to avoid optional deps like requests.",
    }

    # AFL (optional)
    from src.afl_runner import AflRunner

    afl = AflRunner()

    # Harness selection: built-in demo harnesses OR mtb block harness
    harness_dir = Path("src/harness")
    if protocol == "i2c":
        harness_path = str(harness_dir / "fuzz_i2c")
    elif protocol == "pmbus":
        harness_path = str(harness_dir / "fuzz_pmbus")
    elif protocol == "state":
        harness_path = str(harness_dir / "fuzz_state")
    elif protocol == "3p3z":
        harness_path = str(results_dir / f"fuzz_{block}")
    else:
        raise SystemExit(f"Unsupported protocol: {protocol}")

    # Create run-scoped corpus (deterministic baseline)
    corpus_dir = str(results_dir / "seeds")
    Path(corpus_dir).mkdir(parents=True, exist_ok=True)
    (Path(corpus_dir) / "seed_0000.bin").write_bytes(b"\x00")

    afl_res = afl.run(
        protocol=protocol,
        duration_seconds=int(args.duration),
        results_root=str(results_dir),
        run_id=run_id,
        harness_path=harness_path,
        corpus_dir=corpus_dir,
        dry_run=bool(args.skip_fuzzing),
    )

    # Generate report from AFL outputs (if fuzzing ran) or from pipeline outputs
    report_md = results_dir / "reports" / "fuzzing_report.md"
    report_json = results_dir / "reports" / "fuzzing_report.json"

    # Prefer pipeline report if present; otherwise attempt to generate from AFL
    if not report_md.exists() or not report_json.exists():
        try:
            from src.reporters.report_generator import parse_afl_output, ReportGenerator

            afl_default = results_dir / "afl" / protocol
            if afl_default.exists():
                # constraints: if 3p3z, load from repo file; else empty
                param_constraints = {}
                if protocol == "3p3z":
                    import json as _json

                    cfg = _json.load(open("data/constraints/3p3z_parameters.json"))
                    param_constraints = {p["name"]: p for p in cfg.get("parameters", [])}

                res = parse_afl_output(str(afl_default), parameter_constraints=param_constraints, target_name=str(block or protocol))
                rg = ReportGenerator(res)
                report_md.write_text(rg.generate_markdown(include_full_details=True), encoding="utf-8")
                report_json.write_text(_json.dumps(rg.generate_summary_json(), indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Could not generate report from AFL output: %s", e)

    scenario_paths = {}
    if manifest is not None:
        try:
            from src.project_manifest import load_manifest as _load_manifest
            from src.analysis.scenario_coverage import compute_scenario_coverage, write_scenario_artifacts

            # Always reload manifest from disk so any YAML edits (e.g., adding scenarios.signals)
            # are reflected when regenerating reports.
            artifacts_dir = results_dir / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            run_manifest = manifest
            try:
                if args.project:
                    run_manifest = _load_manifest(args.project)
            except Exception:
                pass

            sc_res = compute_scenario_coverage(manifest=run_manifest, run_id=run_id, artifacts_dir=artifacts_dir)
            scenario_paths = write_scenario_artifacts(result=sc_res, out_dir=results_dir / "reports", write_csv=True)
        except Exception as e:
            logger.warning("Scenario coverage generation failed: %s", e)

    # Export convenience formats (HTML + JUnit XML) for stakeholders/CI
    try:
        from src.reporters.html_xml_export import write_html_report, write_junit_xml

        reports_dir = results_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        html_path = reports_dir / "report.html"
        junit_path = reports_dir / "report.junit.xml"

        write_html_report(
            run_json_path=results_dir / "run.json",
            scenario_json_path=reports_dir / "scenario_coverage.json",
            markdown_report_path=reports_dir / "fuzzing_report.md",
            out_path=html_path,
            title=f"Fuzzing report: {protocol}",
        )
        write_junit_xml(
            run_json_path=results_dir / "run.json",
            scenario_json_path=reports_dir / "scenario_coverage.json",
            out_path=junit_path,
            suite_name="thesis-fuzzer",
        )
    except Exception as e:
        logger.warning("HTML/XML export skipped: %s", e)

    # write strict run.json (single source of truth)
    work_dir = f"results/{run_id}"
    run_obj = new_run_skeleton(run_id=run_id, pipeline_name="src.cli run", work_dir=work_dir)
    run_obj["status"] = "completed"

    # append durable run index (best-effort)
    try:
        from src.run_index import append_run_index

        append_run_index(
            repo_root=Path.cwd(),
            run_id=run_id,
            work_dir=results_dir,
            target=str(target),
            protocol=protocol,
            harness_path=harness_path,
            corpus_dir=corpus_dir,
            afl=afl_res.__dict__,
            coverage={},
            scenario=scenario_paths,
            crashes={},
            index_path=Path("results") / "run_index.jsonl",
        )
    except Exception as e:
        logger.warning("Could not append run index: %s", e)

    # minimal environment info (do not dump secrets)
    run_obj["environment"] = {
        "cwd": str(Path.cwd()),
        "platform": sys.platform,
    }

    # Record high-level stage summaries (legacy pipeline internals are intentionally not used).
    run_obj["pipeline"]["stages"] = [
        {
            "id": "pipeline",
            "name": "src.cli cmd_run",
            "status": "completed",
            "startedAt": None,
            "endedAt": None,
            "outputs": [
                {"path": f"{work_dir}/reports/", "kind": "reports_dir"},
                {"path": f"{work_dir}/reports/scenario_coverage.json", "kind": "scenario_coverage"},
                {"path": f"{work_dir}/reports/scenario_summary.md", "kind": "scenario_summary"},
                {"path": f"{work_dir}/reports/scenario_summary.csv", "kind": "scenario_summary_csv"},
            ],
            "agents": [],
            "validation": {"status": "not_run", "validator": "run_schema.py@1.0", "checkedAt": None, "errors": []},
        },
        {
            "id": "afl",
            "name": "src.afl_runner.AflRunner.run",
            "status": "skipped" if args.skip_fuzzing else "completed",
            "startedAt": None,
            "endedAt": None,
            "outputs": [{"path": f"{work_dir}/afl/{protocol}", "kind": "afl_output"}],
            "agents": [],
            "validation": {"status": "not_run", "validator": "run_schema.py@1.0", "checkedAt": None, "errors": []},
        },
    ]

    run_obj["extras"] = {
        "target": str(target),
        "protocol": protocol,
        "block": block,
        "pipeline": pipeline_res,
        "afl": afl_res.__dict__,
        "results_dir": str(results_dir),
        "scenario": scenario_paths,
    }

    ok, errs = validate_run_json(run_obj)
    run_obj["validation"] = {
        "status": "passed" if ok else "failed",
        "validator": "run_schema.py@1.0",
        "checkedAt": now_utc_iso_z(),
        "errors": [{"path": e.path, "message": e.message} for e in errs],
    }

    run_json = results_dir / "run.json"
    run_json.write_text(json.dumps(run_obj, indent=2), encoding="utf-8")

    logger.info("Run complete: %s", run_json)
    if not ok:
        logger.warning("run.json schema validation failed (%d errors)", len(errs))
    return 0



def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="thesis-fuzzer", description="LLM-guided firmware fuzzing CLI")
    parser.add_argument("--verbose", action="store_true")

    parser.add_argument(
        "--project",
        default="project.sample.yaml",
        help="Path to project manifest YAML (default: project.sample.yaml)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    def _duration_arg(s: str) -> int:
        """Parse a duration string: '7200', '2h', '30m', '90s', '1h30m'."""
        s = str(s).strip().lower()
        if not s:
            raise argparse.ArgumentTypeError("empty duration")
        if s.isdigit():
            return int(s)
        import re
        total = 0
        matched = False
        for n, u in re.findall(r"(\d+)\s*([hms])", s):
            matched = True
            n = int(n)
            total += n * {"h": 3600, "m": 60, "s": 1}[u]
        if not matched:
            raise argparse.ArgumentTypeError(
                f"invalid duration {s!r}; use integer seconds or e.g. '2h', '30m', '1h30m'"
            )
        return total

    p_doctor = sub.add_parser("doctor", help="Check environment and dependencies")
    p_doctor.add_argument("--skip-auth-check", action="store_true", help="Skip GPT4IFX API auth test")
    p_doctor.set_defaults(func=cmd_doctor)

    p_run = sub.add_parser("run", help="Run full pipeline (constraints/seeds/fuzz/report)")
    p_run.add_argument("--target", required=True)
    p_run.add_argument("--protocol", choices=["i2c", "pmbus", "state", "3p3z"], required=True)
    # For mtb blocks, allow any block name; the pipeline can auto-generate templates.
    p_run.add_argument("--block", default=None)

    p_run.add_argument("--duration", type=_duration_arg, default=60,
                       help="Fuzz duration: integer seconds or '2h', '30m', '1h30m'")
    p_run.add_argument("--seed-count", type=int, default=100)
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--skip-fuzzing", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_index = sub.add_parser("index", help="Ingest docs and build RAG index")

    p_index.add_argument("--force", action="store_true", help="Rebuild index even if it exists")
    p_index.set_defaults(func=cmd_index)

    p_fuzz = sub.add_parser("fuzz", help="Run manifest-driven fuzzing pipeline")
    # NOTE: --project is declared on the GLOBAL parser. Do not redeclare here
    # or argparse will require it even though the global flag already supplies it.
    p_fuzz.add_argument("--output", default="results")
    p_fuzz.add_argument("--run-id", default=None)
    p_fuzz.add_argument("--duration", type=_duration_arg, default=None,
                        help="Fuzz duration: integer seconds or '2h', '30m', '1h30m'")
    p_fuzz.add_argument("--protocol", choices=["i2c", "pmbus", "3p3z"], default=None)
    p_fuzz.add_argument("--seed-count", type=int, default=None)
    p_fuzz.add_argument("--skip-fuzzing", action="store_true")
    p_fuzz.add_argument(
        "--dry-run",
        action="store_true",
        help="Run indexing+RAG+constraints+seed planning only; no build/AFL.",
    )
    p_fuzz.add_argument(
        "--show-rag-content",
        action="store_true",
        help="Include retrieved chunk content in dry_run.json (otherwise metadata only).",
    )
    p_fuzz.add_argument(
        "--resume",
        action="store_true",
        help="Resume/continue AFL session by reusing output dir (AFL -R).",
    )
    p_fuzz.add_argument(
        "--resume-dir",
        default=None,
        help="Explicit AFL output directory to reuse for resume.",
    )
    p_fuzz.set_defaults(func=cmd_fuzz)

    p_boot = sub.add_parser("bootstrap", help="Generate+verify a generic harness stub (Agent 0)")
    p_boot.add_argument("--target", required=True, help="Path to target repo")
    p_boot.add_argument("--entrypoint", required=True, help="Entrypoint function name (user-provided)")
    p_boot.add_argument("--lang", choices=["c", "cpp"], default="c")
    p_boot.add_argument("--output", required=True, help="Output directory for generated harness")
    p_boot.add_argument("--timeout", type=int, default=10)
    p_boot.add_argument("--include-dir", action="append", default=[])
    p_boot.add_argument("--extra-source", action="append", default=[])
    p_boot.add_argument("--build-cmd", nargs="+", default=None, help="Optional repo build command (tokens split)")
    p_boot.set_defaults(func=cmd_bootstrap)

    p_loop = sub.add_parser("loop", help="Run closed-loop campaign (Agent 3+ controller)")
    p_loop.add_argument("--output", default="results")
    p_loop.add_argument("--run-id", default=None, help="(unused) for compatibility")
    p_loop.add_argument("--duration", type=int, default=None, help="(unused) for compatibility")
    p_loop.add_argument("--iter-duration", type=int, default=60)
    p_loop.add_argument("--iterations", type=int, default=3)
    p_loop.add_argument("--protocol", choices=["i2c", "pmbus", "3p3z"], default=None)
    p_loop.add_argument("--skip-fuzzing", action="store_true")
    p_loop.add_argument("--stop-on-crash", action="store_true")
    p_loop.add_argument(
        "--dry-run",
        action="store_true",
        help="Run indexing+RAG+constraints+seed planning only; no build/AFL.",
    )
    p_loop.add_argument(
        "--show-rag-content",
        action="store_true",
        help="Include retrieved chunk content in dry_run.json (otherwise metadata only).",
    )
    p_loop.add_argument(
        "--resume-afl",
        action="store_true",
        help="Resume a single AFL session across loop iterations (reuse output dir).",
    )
    p_loop.add_argument(
        "--resume-dir",
        default=None,
        help="Explicit AFL output directory to reuse when --resume-afl is set.",
    )
    p_loop.set_defaults(func=cmd_loop)

    p_report = sub.add_parser("report", help="Show report paths")
    p_report.add_argument("--results", required=True)
    p_report.set_defaults(func=cmd_report)

    p_dash = sub.add_parser("dashboard", help="Generate static dashboard under results/dashboard/")
    p_dash.add_argument("--serve", action="store_true", help="Serve dashboard with Flask on http://127.0.0.1:8000")
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8000)
    p_dash.set_defaults(func=cmd_dashboard)

    p_eval = sub.add_parser("eval", help="Run repeatable evaluation trials and export metrics")
    p_eval.add_argument("--output", default="results")
    p_eval.add_argument("--protocol", choices=["i2c", "pmbus", "3p3z"], default=None)
    p_eval.add_argument("--duration", type=int, default=60)
    p_eval.add_argument("--trials", type=int, default=3)
    p_eval.add_argument("--skip-fuzzing", action="store_true")
    p_eval.set_defaults(func=cmd_eval)

    # `compare` — SoK-grounded statistical comparison of two run groups.
    # Reads AFL plot_data and computes time-to-coverage, Mann-Whitney U,
    # Vargha-Delaney A12 effect size, and emits CSV/JSON/PNG/markdown.
    p_cmp = sub.add_parser(
        "compare",
        help="Statistical comparison of LLM vs baseline campaign groups "
             "(per SoK Schloegel et al. 2024 + Klees et al. 2018)")
    p_cmp.add_argument("--llm", nargs="+", required=True,
                       help="Glob(s) for LLM run dirs (e.g. results/2h_dc_llm_*)")
    p_cmp.add_argument("--baseline", nargs="+", required=True,
                       help="Glob(s) for baseline run dirs (e.g. results/2h_dc_baseline_*)")
    p_cmp.add_argument("--out", required=True,
                       help="Output directory for CSV/JSON/PNG/markdown")
    p_cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
