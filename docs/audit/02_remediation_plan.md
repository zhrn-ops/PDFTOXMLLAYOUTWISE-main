# Remediation plan (Phase 2 onward)

Snapshot: **2026-11-10 14:45**. This plan is based on `00_baseline_report.md` and `01_code_audit.md`. **No production logic was changed in Phases 0–1.** The working tree already contains earlier Phase 2/3 work plus concurrent title/alternate-name edits; this plan does not redo them and does not assume they are committed.

## Current state to account for

- The XML validation/revision/export work described in `phase_02_implementation.md` and `phase_03_implementation.md` is **already implemented in the working tree** (uncommitted). Focused suites pass: 36 `test_xml_validation_export.py`, 15 `test_xml_revision_integrity.py`, plus comment/session/draft tests.
- The tree also contains concurrent uncommitted bilingual/alternate-name/country/title-language work that appeared during the audit. Treat it as a separate change set.
- Therefore the next approved phase should **not** start by re-implementing Phase 2. It should first stabilize the uncommitted work, then fix the P1 lifecycle/CLI blockers, then harden tests.

Recommended gate order: **stabilize → P1 blockers → test infrastructure → hardening → performance/accuracy → architecture → packaging**. Do not start performance or refactoring work before C01–C04 and C06/C12 are closed.

---

## Work package 0 — Stabilize the current uncommitted change sets (approval gate)

**Goal:** a reviewable, committed baseline before remediation touches behavior.

1. Review and commit the existing Phase 2/3 XML changes as their own commit/PR.
2. Review and commit the concurrent alternate-name/title-language changes separately.
3. Confirm the full suite can be run with the documented headless command; record the three known hangs and two known failures as explicit xfails/skips **only if** work package 2 will fix them in the same release, otherwise leave them visible.

**Acceptance:** clean separation of change sets; `git status` shows only intentional files; the documented baseline command and its result are reproducible.

**Do not:** rewrite the Phase 2/3 XML code, change the ANI namespace, or alter schema/validation semantics while stabilizing.

---

## Work package 1 (P1) — Headless conversion contract and load lifecycle

**Findings:** C01, C02, C03, C04.

**Goal:** batch conversion never writes the wrong article, never blocks on a dialog, and never reports success with zero output.

**Design:** introduce a conversion-facing load/export result that is independent of `QMessageBox`.

- `LoadResult` (success, document, source path, generation, typed error) returned by `_load_pdf_path`/the worker completion path; `Converter` consumes it instead of inspecting `window.document`.
- Transactional failure: on error, clear document, source path, viewer payload, article state, selection, and draft baseline for that load; reset generation.
- Explicit export result from `run_auto_pipeline` (`written_paths`, `skipped_reason`); `Converter.convert` requires at least one written path.
- Dialog policy injected into the window (`interactive`/`headless`) or moved to a GUI adapter that the conversion path does not import.
- Seed the draft baseline on successful load, or replace JSON comparison with explicit dirty tracking reset on load/save/open, so a load with no edits is clean.

**Likely files:** `pdf_to_jats/gui/main_window.py` (`_load_pdf_path`, `_on_pdf_load_complete`, `run_auto_pipeline`, `closeEvent`), `pdf_to_jats/gui/article_drafts.py` (`_workspace_text`, `confirm_close_drafts`), `pdf_to_jats/cli.py` (`Converter.convert`, `main`). Prefer minimal extraction over a new architecture layer in this package.

**Tests (must fail before, pass after):**

- `test_failed_load_clears_previous_document` (C01).
- `test_cli_corrupt_pdf_returns_nonzero_without_dialog` (C01/C03).
- `test_close_after_load_does_not_prompt`, `test_second_pdf_does_not_prompt_without_edits` (C02).
- `test_batch_two_pdfs_completes` (C02).
- Existing `test_cli_converter_end_to_end`, `test_cli_main_exit_codes`, `test_load_pdf_path_wait_parameter_completes_extraction`, `test_article_finish_drops_stale_response_on_generation_mismatch` must pass in a normal, non-deselected run (C02/C04).
- `test_cli_no_article_is_failure` (C04).

**Acceptance:** full suite terminates without deselection or dialog stubs; batch of two valid PDFs produces two XML files; corrupt PDF produces nonzero exit and no XML; closing after a mere load never prompts.

**Risk:** draft-save semantics are user-visible. Headless mode must define what happens to genuinely unsaved edits (default: fail the batch with a clear message; never silently discard without an explicit flag).

---

## Work package 2 (P2) — Test infrastructure and golden fidelity

**Findings:** C06, C07, C12 (and prerequisite for C05 coverage).

1. Fix `tests/test_golden_structural.py` to supply required `bbox`; decide the intended `PDFViewer` visibility API and either implement it deliberately or rewrite `tests/test_process_lifecycle.py` against the real render API. Do not add a no-op method to satisfy a test.
2. Make the structural comparator exact by default; compare all XPath nodes including comments/PIs; add mutation tests that prove it rejects a changed space, tail, comment, and PI.
3. Add `pytest-timeout` and a `gui` marker; add CI (headless Qt, Python matrix, timeout). Stop tracking `.pyc` and `node_modules`; add `pyproject.toml` test extras and a README with the documented command.

**Acceptance:** `QT_QPA_PLATFORM=offscreen python -m pytest -q` terminates; a deliberately hanging test fails via timeout; comparator mutation tests pass; CI green on the stabilized baseline.

---

## Work package 3 (P2) — Shutdown/lifecycle safety

**Finding:** C05.

- Rework `PDFViewer.cleanup` so live threads/workers stay owned until `finished`, or use a bounded wait that is verified and logged on timeout.
- Add a slow-render close test using a fake worker; assert no thread is destroyed while running.
- Depends on work package 2 fixing the lifecycle test API.

**Acceptance:** close during rasterization exits cleanly under the stress test; no `QThread: Destroyed while thread is still running` warning/crash.

---

## Work package 4 (P2) — GUI responsiveness, secrets, and error semantics

**Findings:** C08, C09, C10.

- Move `classify_selected_blocks` off the GUI thread using the existing worker pattern; disable the action while running; add a fake-client responsiveness test.
- Prefer `OPENROUTER_API_KEY`; remove or gate the plaintext writer, restrict permissions, redact keys in logs; add a config/redaction test.
- Introduce typed LLM errors; catch only expected transport/parse failures; log unexpected exceptions with stack traces; keep heuristic fallback only for explicit unavailability and label its provenance.
- Add an error-injection test proving a programmer error is not silently converted into a heuristic result.

**Acceptance:** no synchronous network call remains in a GUI-thread slot; no plaintext key write without explicit opt-in; unexpected errors are visible in logs/tests.

---

## Work package 5 (P2) — Schema readiness

**Finding:** C11.

- Obtain the authoritative Elsevier ANI/CAR schema with redistribution terms; pin it under `pdf_to_jats/schemas/` with provenance/checksum; add CI valid/invalid fixture tests.
- If redistribution is not permitted, require an explicit local schema profile for validated export, document it, and keep `SCHEMA_UNAVAILABLE` truthful.

**Acceptance:** CI proves `SCHEMA_VALID`/`SCHEMA_INVALID` against a pinned schema, or the product explicitly requires a user-supplied schema and never claims validity. **No report may claim schema validity without this.**

---

## Later phases (align with the master plan)

- **Phase 4 — regression/integration tests:** corpus-driven extraction/layout tests (R01), malformed draft/revision tests (R03), recorded LLM/GROBID contract tests (R04). Use licensed or synthetic PDFs only.
- **Phase 5 — architecture/reliability:** extract a conversion service from `MainWindow`; centralize dialogs, worker lifecycles, and error types. Do not rewrite working XML/GUI components.
- **Phase 6 — performance:** benchmark before optimizing (R02). Measure cold/warm load, pages/min, peak RSS, and raster behavior; only then consider caching/shared raster services or the 3× matrix.
- **Phase 7 — failure recovery:** disk-full, permission-denied, interrupted write, schema-missing, and crash-recovery tests; verify atomic publication and draft restore.
- **Phase 8 — packaging/CI:** declared dependencies, lock/constraints, headless CI, artifact cleanup, and release checklist.

---

## Suggested first approved step

**Work package 1 only**, plus the minimal test fixes needed to run it (the existing CLI tests and the two stale-API tests). That closes all four P1 blockers and turns the suite from “hangs/red” into a usable gate. Work packages 2–5 follow in separate approvals.

## Constraints carried forward

- No rebuild, no dependency replacement, no schema invented, no test weakened to pass.
- Preserve: secure XML parsing, atomic writes, revision fingerprints, draft/validated separation, mixed-content and encoding handling, generation guards, network-denial test fixture.
- Every fix must include the listed regression test; every claim must be executed, not inferred.
