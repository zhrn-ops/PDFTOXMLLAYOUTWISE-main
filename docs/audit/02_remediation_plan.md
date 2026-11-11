# Remediation plan (Phase 2 onward)

Snapshot: **2026-11-11 09:00 (SLST)**, commit **`612f395`**, clean tree. Based on `00_baseline_report.md` and `01_code_audit.md`. **No production or test logic was changed in Phases 0–1.**

## Current state

- The suite is **green**: 590 passed in ~21 s under offscreen Qt, no skips, no hangs.
- The previous P1 blockers (C01–C04) and C05/C06 are **fixed and covered**.
- The XML validation/revision work is committed, not uncommitted. It should be left intact.
- Open findings are engineering, fidelity, and readiness gaps: C07, C08, C09, C10, C11, C12, plus new N01, N02, N03.
- There is still no authoritative publisher schema, so **no plan step may claim schema validity** without C11.

Recommended gate order:

**1. Trustworthy test gate → 2. Scientific fidelity decisions → 3. GUI/LLM reliability → 4. Schema readiness → 5. Cleanup/packaging → later phases.**

Do not start architectural refactoring or performance work before the test gate and fidelity decisions are settled.

---

## Work package 1 (P2) — Make the regression gate trustworthy

**Findings:** C07, C12.

**Why first:** a green suite is only useful if it can detect the changes it claims to detect and can fail fast instead of hanging.

1. Make `assert_structural_equality` compare exact `text`/`tail` by default, or introduce a separately named canonicalizer for documented insignificant indentation. Keep comment/PI comparison (it already works) and state precisely what is normalized.
2. Add comparator mutation tests: changed leading space, changed tail, changed comment, changed PI must each fail; the unchanged golden must pass.
3. Add `pytest-timeout` and a `gui` marker boundary that is actually enforced.
4. Add `.github/workflows/` running `QT_QPA_PLATFORM=offscreen python -m pytest -q` with a hard timeout and a Python/PySide6 matrix.
5. Untrack `*.pyc`, `node_modules/`, and `.bench/`; extend `.gitignore` (`__pycache__/`, `*.pyc`, `.pytest_cache/`, `node_modules/`, `.bench/`, `.test-alt-review-*`). Do not delete `node_modules/` from the working tree unless the JavaScript dependency is confirmed unused and removed from `package.json`.
6. Add `pyproject.toml` (project metadata + `test` extra: `pytest`, `pytest-qt`, `pytest-timeout`) and a README with the documented headless command and supported Python/Qt versions.

**Acceptance:** comparator mutation tests pass; a deliberate `time.sleep` test fails via timeout; CI is green on a clean checkout; `git ls-files` contains no `.pyc` or `node_modules` entries.

**Risk:** removing `node_modules` from Git is safe for the Python app but may surprise Node tooling; keep the directory locally and confirm with the owner before deleting `package.json`.

---

## Work package 2 (P2) — Scientific fidelity decisions

**Findings:** N01, N02.

**Why early:** both change exported scientific content/metadata, so they need an explicit product decision and fixtures before any refactor touches the generator.

1. **N01:** decide whether non-English titles must lose `sup`/`sub`/`inf`. The current code unwraps them for every non-English language, including French/German/Spanish, where they are meaningful. Preferred: preserve markup and let schema validation report incompatibility; fallback: restrict to a documented subset and document the semantic loss. In either case, add fixtures for a Latin-script chemical formula and a CJK footnote marker.
2. **N02:** extend the alias table for UK constituent countries (`England`, `Scotland`, `Wales`, `Northern Ireland` → `GBR`), tolerate a leading “The”, and decide the policy for common exonyms (`Deutschland`). Keep hard failure only for genuinely unknown values; consider a review warning instead of blocking validated export.

**Acceptance:** the chosen behavior is asserted by tests and stated in `docs/xml_export.md`; no text is lost; the country probe cases from `01_code_audit.md` are covered by tests.

**Risk:** N01 changes output for existing drafts that were regenerated; do not retroactively rewrite corrected user XML. Apply the decision only on generation/validation, and record it as a documented behavior change.

---

## Work package 3 (P2) — GUI responsiveness, typed errors, secrets

**Findings:** C08, C10, C09.

1. Move `classify_selected_blocks` onto the existing `_ArticleFinishWorker` pattern (or a `QThreadPool` task). Disable the Classify action while running; emit typed success/error; keep the heuristic fallback only for explicit unavailability and label its provenance.
2. Introduce typed LLM errors (`LLMUnavailable`, `LLMRateLimited`, `LLMResponseError`). Catch those at the UI boundary; log unexpected exceptions with `exc_info=True`; do not convert programmer errors into heuristic assignments.
3. Prefer `OPENROUTER_API_KEY`; remove or explicitly gate `save_openrouter_settings`; restrict file permissions if retained; redact keys from logs/errors.

**Acceptance:** no synchronous network call remains in a GUI-thread slot; a fake `TypeError` from the client surfaces as an internal error, not “unavailable”; no plaintext key is written without explicit opt-in; redaction test passes.

**Risk:** classification fallback behavior is user-visible. Keep the local-first / OpenRouter-fallback order and do not change role-assignment semantics in this package.

---

## Work package 4 (P2) — Schema readiness

**Finding:** C11.

- Obtain the authoritative Elsevier ANI/CAR schema with redistribution terms; pin it under `pdf_to_jats/schemas/` with provenance and a checksum; add known-good and known-bad fixtures to CI.
- If redistribution is not permitted, keep the current explicit user-selected local profile, document it prominently, and never claim publisher validity.
- Use the pinned schema to resolve R09 (title ordering/`original` semantics) and N01 (whether scripts are allowed in `titletext`).

**Acceptance:** CI proves `SCHEMA_VALID` and `SCHEMA_INVALID` against a pinned schema, or the product explicitly requires a user-supplied schema and every report says so.

**Risk:** a publisher schema is a licensing artifact; do not invent or approximate one.

---

## Work package 5 (P3) — Cleanup and documentation integrity

**Findings:** N03, stale audit artifacts.

1. Delete `MainWindow._auto_classify` or wire it deliberately and share one implementation with `classify_selected_blocks`.
2. Regenerate `docs/audit/collection_results.txt` (it currently records 452 tests from 2026-11-09) and refresh `dependency_versions.txt` or label it as a dated inventory.
3. Keep the audit documents consistent with the code; do not commit a report that describes a baseline the tree no longer has.

**Acceptance:** no unreachable duplicate classification path; audit evidence matches `pytest --collect-only`; version inventory is dated and accurate.

---

## Later phases (per the master plan)

- **Phase 4 — regression/integration tests:** licensed corpus-driven extraction/layout tests (R01), malformed draft/revision fuzz tests (R03), recorded LLM/GROBID contract tests (R04). No live API calls in unit tests.
- **Phase 5 — architecture:** extract a conversion/session service from `MainWindow` (7,617 lines). Start with load/export orchestration and a single session-reset object replacing the ad-hoc reset lists in C01. Do not rewrite working XML/GUI components; preserve shortcuts, signals, and conversion behavior.
- **Phase 6 — performance:** benchmark before optimizing (R02). Measure cold/warm load, pages/min, peak RSS, raster behavior; only then consider caching or a shared raster service.
- **Phase 7 — failure recovery:** disk-full, permission-denied, interrupted write, schema-missing, and crash-recovery tests; verify atomic publication and draft restore.
- **Phase 8 — packaging:** lock/constraints, optional-dependency split (Docling), supported Python range (currently 3.14 is used but `requirements.txt` states no upper bound), reproducible install, release checklist.

---

## Suggested first approved step

**Work package 1 only**, plus the N03 deletion if desired. It is low-risk, does not touch scientific output, and converts the currently green-but-ungated suite into a gate that can detect whitespace/markup regressions and fail fast on hangs. Work package 2 follows separately because it requires a product decision about scientific markup.

## Constraints carried forward

- No rebuild, no dependency replacement, no invented schema, no test weakened to pass.
- Preserve secure XML parsing, atomic writes, revision fingerprints, draft/validated separation, mixed-content and encoding handling, generation guards, and the network-denial fixture.
- Never silently discard user XML corrections.
- Every fix needs the listed regression test; every claim must be executed, not inferred.

---

## Execution update (end of audit)

This plan was executed in the approved follow-up pass. Final state is recorded in `05_final_engineering_review.md`.

| Work package | Outcome |
|---|---|
| WP1 — trustworthy test gate | **Done.** Exact comparator semantics with newline-indentation normalization; 6 mutation tests; `pytest-timeout` (180 s); Windows CI; `pyproject.toml`; README; extended `.gitignore`; 237 `.pyc` and 2,565 `node_modules` entries untracked (working files intact). The `gui` marker boundary was not introduced. |
| WP2 — scientific fidelity | **Partially done.** N02 fixed (UK constituent countries, `Deutschland`, leading “The”) with 9 tests. **N01 deferred**: it requires an authoritative schema or an explicit product decision; no silent change was made. |
| WP3 — GUI/LLM reliability | **Partially done.** C09 writer is opt-in and permission-restricted; API-key/bearer log redaction added with tests. **C08 and C10 deferred** to a dedicated change set (worker extraction and typed error hierarchy). |
| WP4 — schema readiness | **Not actionable here.** Requires the licensed Elsevier ANI/CAR XSD (C11). No schema was invented; no validity claim is made. |
| WP5 — cleanup/docs | **Done.** `_auto_classify` removed; `collection_results.txt` regenerated; audit evidence reconciled with the code. |

Remaining order: **C08 → C10 → N01 decision → C11 schema → corpus (R01) → incremental architecture extraction.**
