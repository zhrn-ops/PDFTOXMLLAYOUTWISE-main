# Phase 1 — Code audit

Snapshot: **2026-11-11 09:00 (SLST)**, commit **`612f395`**, clean tree.

Method: static reading of the cited functions plus executed probes on the current source. No production or test source was modified. Severity: **P0** data loss/security emergency; **P1** material correctness, data-integrity, or broken primary workflow; **P2** reliability, fidelity, diagnostics, security hardening, or engineering gap; **P3** maintainability/hygiene. “Confirmed” means reproduced or directly established from the executed path; “unverified” means a static concern without reproduction.

## Findings summary

| ID | Severity | Status | Area | Result |
|---|---|---|---|---|
| C01 | **P1** | **Fixed** | Load lifecycle | Failed PDF load is transactional; the previous document can no longer be exported under the new filename. |
| C02 | **P1** | **Fixed** | Headless/GUI lifecycle | A mere load is clean; headless close/replace never creates a modal. |
| C03 | **P1** | **Fixed** | Error handling | Load-error dialog is GUI-only; corrupt input returns a typed failure. |
| C04 | **P1** | **Fixed** | CLI contract | Zero-output conversion is an error and returns nonzero. |
| C05 | P2 | **Fixed** | Viewer teardown | Cleanup waits 5 s and retains ownership of a live thread. |
| C06 | P2 | **Fixed** | Tests | Two stale-API tests were repaired and pass. |
| C07 | P2 | **Open (narrowed)** | Golden comparator | Leading/trailing whitespace differences are invisible; comments/PIs *are* compared (prior report was wrong). |
| C08 | P2 | **Open** | GUI responsiveness | The Classify button still calls OpenRouter synchronously on the GUI thread (up to 3×60 s). |
| C09 | P2 | **Open (latent)** | Secrets | Plaintext OpenRouter key read/write path remains; the writer currently has no caller. |
| C10 | P2 | **Open** | Error handling | 19 broad `except Exception` handlers; classification falls back to heuristics on programming errors. |
| C11 | P2 | **Open (readiness)** | Schema validity | No authoritative ANI/CAR schema; validated export depends on a user-supplied profile. |
| C12 | P2 | **Open** | Test/repo engineering | No CI/timeout; 237 tracked `.pyc`, 2,565 tracked `node_modules` files; no `pyproject.toml`/README. |
| **N01** | P2 | **Open (new)** | Scientific markup fidelity | Non-English titles have all `sup`/`sub`/`inf` unwrapped, including Latin-script titles where the markup is meaningful. |
| **N02** | P2 | **Open (new)** | Country normalization | Common constituent/local country names (“England”, “Scotland”, “Deutschland”, “The Netherlands”) are unresolved and hard-fail strict validation. |
| **N03** | P3 | **Open (new)** | Dead code | `MainWindow._auto_classify` (≈80 lines) is unreachable and duplicates the live classification path. |

No P0 was confirmed. C01–C06 are closed with both code changes and passing regression tests.

### Remediation status (end of audit)

After this audit, the following findings were fixed and verified in the same working tree (see `05_final_engineering_review.md`):

- **C07 — fixed:** newline-bearing whitespace alone is normalized; leading spaces and lost inline tails are now detected. Six mutation tests added.
- **N02 — fixed:** UK constituent countries → `GBR`; `Deutschland` → `DEU`; `The Netherlands` → `NLD`; leading “The” tolerated. Strict unknown values still fail.
- **N03 — fixed:** `_auto_classify` removed.
- **C09 — partially fixed:** the plaintext writer is now opt-in and permission-restricted; log redaction added. The legacy read path remains for compatibility.
- **C12 — largely fixed:** `pytest-timeout`, CI, `pyproject.toml`, README, `.gitignore`, and artifact untracking added. The `gui` marker split was not implemented.

Still open and deliberately deferred: **C08** (GUI-thread classification), **C10** (typed LLM errors), **N01** (non-English title markup, needs a schema/product decision), **C11** (no authoritative schema).

---

## Closed findings (verified)

### C01 — Failed load left the previous document active (was P1)

- **Location:** `gui/main_window.py`, `_on_pdf_load_complete` (6943–6948), `_clear_document_after_load_failure` (7006+).
- **Current behavior:** the error branch sets `_last_load_error`, clears `document`, `current_xml_path`, generated paths, review state, draft keys, selection, and article state, then shows `QMessageBox.critical` only when `not self.headless`.
- **Verification:** `tests/test_cli_workflow.py::test_failed_load_clears_previous_document` and `::test_batch_two_pdfs_does_not_prompt_or_reuse_document` pass; the full suite is green.
- **Residual risk:** the clear helper must remain exhaustive when new per-document state is added; there is no shared “session reset” object enforcing it (see N03/C12 architecture note).

### C02 — A loaded-but-unedited PDF was treated as unsaved work (was P1)

- **Location:** `gui/article_drafts.py`, `workspace_is_clean` (155–166), `mark_workspace_clean` (168–170), `confirm_close_drafts` (172+).
- **Current behavior:** a document with no draft/session and no saved baseline reports clean; headless callers get `False` (refuse) instead of a modal; `Converter.convert` re-baselines after export.
- **Verification:** `test_batch_two_pdfs_does_not_prompt_or_reuse_document`, `test_close_after_load_does_not_prompt`-equivalent coverage in `test_article_drafts.py`, and the previously hanging `test_load_pdf_path_wait_parameter_completes_extraction`, `test_article_finish_drops_stale_response_on_generation_mismatch` all pass without a dialog stub.

### C03 — Load-error modal blocked headless conversion (was P1)

- **Location:** `gui/main_window.py` 6946–6947; `cli.py` `Converter.convert` 68–91.
- **Current behavior:** `headless=True` suppresses the dialog; `_load_pdf_path(wait=True)` returns the error string; `Converter` raises `RuntimeError`; `main` prints `[FAIL]` and returns 1.
- **Verification:** `test_cli_corrupt_pdf_returns_nonzero_without_dialog` passes.

### C04 — CLI reported success with zero XML (was P1)

- **Location:** `gui/main_window.py` `run_auto_pipeline` (1223–1276); `cli.py` `Converter.convert` (80–89), `main` (135–153).
- **Current behavior:** `run_auto_pipeline` returns the written `list[Path]` and exports an unsegmented PDF as one article in headless mode. `Converter.convert` raises when the list is empty after filtering to real files. `main` counts per-file failures and returns nonzero.
- **Verification:** `test_cli_converter_end_to_end`, `test_cli_main_exit_codes`, `test_converter_rejects_zero_output` pass.

### C05 — Viewer cleanup ignored a failed thread wait (was P2)

- **Location:** `gui/pdf_viewer.py`, `cleanup` (706–722).
- **Current behavior:** increments the raster generation, clears pending/queued renders, calls `quit()` and `wait(5000)`; on timeout it logs a warning and `continue`s, **retaining** thread/worker ownership. `_forget_page_render` removes only stopped threads.
- **Verification:** `test_viewer_cleanup_cancels_in_flight_raster_threads` passes. No crash was observed. A 5 s per-thread stall on application close remains possible but is bounded and non-destructive.

### C06 — Two tests used stale/nonexistent APIs (was P2)

- **Current behavior:** `test_golden_structural.py` supplies the required `bbox`; `test_process_lifecycle.py` uses the viewer’s real render/cleanup API rather than the nonexistent `set_visible_range`.
- **Verification:** both pass; no skips or xfails in the suite.

---

## Open findings

### C07 — Structural comparator hides whitespace differences (P2, narrowed)

- **Location:** `tests/test_golden_structural.py`, `assert_structural_equality` (28–40).
- **Root cause:** `norm()` applies `str.strip()` to every `text` and `tail`, so boundary whitespace is not compared. The docstring claims exact text/tail preservation; the implementation is weaker.
- **Executed probe:** comparing `<r><p>text</p></r>` with `<r><p> text</p></r>` **passed**; comparing tails `"  "` with `""` **passed**. Internal spacing (`a b` vs `a  b`) and added comments/PIs **were rejected**.
- **Correction to the previous audit:** comments and processing instructions **are** detected (child count and non-element tag mismatch), contrary to the earlier claim. The defect is whitespace-only.
- **Impact:** a golden test can pass while a space between inline elements is lost (e.g. `<italic>x</italic> y` → `<italic>x</italic>y`). That is meaningful in mixed scientific content; it weakens the regression net but does not itself corrupt output.
- **Proposed correction:** compare exact `text`/`tail`, or normalize only a documented insignificant indentation via a separate canonicalizer. Keep comments/PIs in the comparison and add mutation tests for a changed leading space, tail, comment, and PI.
- **Required regression test:** each mutation must fail the comparator; the unchanged golden must pass.

### C08 — Classify button blocks the GUI thread on network calls (P2)

- **Location:** `gui/main_window.py` 464 (`classify_btn.clicked.connect(self.classify_selected_blocks)`) → `classify_selected_blocks` 5453 → `self.openrouter_client.classify` 5515 and 5519. Client: `llm/openrouter_client.py` (`timeout=60`, `max_retries=2`).
- **Root cause:** the slot runs directly on the GUI thread and performs up to three sequential 60 s HTTP attempts (worst case ≈180 s plus connection overhead). No worker, cancellation, or disabled-button state.
- **Expected:** model work runs off the GUI thread, the action is disabled while running, and errors return via signals.
- **Actual:** the event loop is blocked; the window cannot repaint or cancel.
- **Impact:** apparent freeze / OS “not responding”; lost work if force-closed. Reliability, not data corruption.
- **Proposed correction:** reuse the existing `_ArticleFinishWorker` pattern or a `QThreadPool` task; keep the local-heuristic fallback and label its provenance.
- **Required regression test:** fake client blocks on an event; invoke the action; assert the GUI thread remains responsive and the button is disabled; release and assert assignments applied. No live service.

### C09 — Plaintext OpenRouter key path remains (P2, latent)

- **Location:** `utils/config.py`, `load_config` (37–50), `save_openrouter_settings` (55–67).
- **Root cause:** `output/openrouter_settings.json` stores `"api_key"` in plaintext with default permissions; `load_config` accepts it when `OPENROUTER_API_KEY` is absent.
- **Current exposure:** `save_openrouter_settings` has **no caller** in `pdf_to_jats/` or `tests/` (only its definition and stale bytecode). The read path is live if a file already exists.
- **Impact:** credential disclosure to other local users, backups, or screen sharing; not remotely exploitable by itself.
- **Proposed correction:** prefer the environment variable; remove the writer or gate it behind explicit opt-in with `0o600` on POSIX and a restrictive ACL on Windows; redact keys in errors/logs; warn if a key is loaded from the file.
- **Required regression test:** env precedence and redaction; if the writer is retained, permission and no-key-in-log assertions. Never embed a real key.

### C10 — Broad exception handling hides defects and silently degrades classification (P2)

- **Location:** 19 `except Exception` handlers. Representative: `gui/main_window.py` 5529 (`classify_selected_blocks`), 835 (`_auto_classify`, unreachable — see N03), `llm/primary_client.py` 32 and 39, `core/pdf_extractor.py` 231.
- **Root cause:** catch-all handlers convert programming/serialization errors into a log line and/or a heuristic fallback. In `classify_selected_blocks`, any exception from the model call falls back to `self.classifier.classify_blocks`, so a broken payload or serializer is indistinguishable from “model unavailable”.
- **Expected:** catch known transport/HTTP/shape errors; let unexpected exceptions surface (or log with `exc_info=True` and show an internal-error state).
- **Actual:** unexpected errors look like outages; the fallback can produce a plausible but unlabeled heuristic assignment.
- **Impact:** harder diagnosis and possible silent scientific misclassification; no wrong output was reproduced.
- **Proposed correction:** typed LLM errors (`LLMUnavailable`, `LLMRateLimited`, `LLMResponseError`); catch those at the UI boundary; log unexpected exceptions with stack traces; label heuristic provenance in the UI/output.
- **Required regression test:** a fake client raising `TypeError` must not be treated as unavailable; a fake transport error must still fall back and be labeled.

### C11 — No authoritative schema bundle; schema-valid claims remain impossible (P2, readiness)

- **Location:** `core/validator.py` 23–30; absent `pdf_to_jats/schemas/jats_1_4.xsd`; no `.xsd` anywhere under `pdf_to_jats/`.
- **Root cause:** the legacy default points at a JATS 1.4 schema that was never bundled, while `core/jats_generator.py` emits Elsevier ANI/CAR. Phase 2 correctly reports `SCHEMA_UNAVAILABLE` rather than treating a missing schema as success, but no publisher schema is supplied for the ANI format.
- **Verification:** `core/xml_validation.py` returns independent `WELL_FORMED` / `NOT_WELL_FORMED` / `SCHEMA_VALID` / `SCHEMA_INVALID` / `SCHEMA_UNAVAILABLE`; draft export never claims publisher validity; validated export requires `SCHEMA_VALID`. Focused tests (`test_xml_validation_export.py`) pass using temporary schemas, not a real publisher schema.
- **Impact:** the product cannot honestly claim publisher-valid XML out of the box; interoperability depends on the user’s schema bundle. This is a readiness gap, not a code regression. **This audit makes no schema-validity claim.**
- **Proposed correction:** obtain the authoritative ANI/CAR XSD with redistribution terms; pin it under `pdf_to_jats/schemas/` with provenance/checksum; run known-good and known-bad fixtures through it in CI. If redistribution is not permitted, require an explicit local profile at first validated export and document it (`docs/xml_export.md` already states the current position).
- **Required regression test:** pinned-schema `SCHEMA_VALID` / `SCHEMA_INVALID` fixtures plus the existing `SCHEMA_UNAVAILABLE` path.

### C12 — Test and repository engineering gaps (P2)

- **Evidence:** 590 tests pass in ~21 s, but there is **no CI workflow**, **no `pytest-timeout`**, **no `pyproject.toml`**, **no README**, and the `.gitignore` contains only `output/` and duplicate `.env` lines. **237 `.pyc`** and **2,565 `node_modules/` files** are tracked; `.bench/big.pdf` is tracked.
- **Root cause:** tests and features were added incrementally around a GUI application without a gated, reproducible build.
- **Impact:** regressions are not automatically gated; a future hang would block every run (the previous red baseline demonstrated this); checkout size and noise are inflated; environment setup is implicit.
- **Proposed correction:** add `pytest-timeout` and a headless CI job (`QT_QPA_PLATFORM=offscreen`, Python/Qt matrix, explicit timeout); mark GUI tests; untrack bytecode, `node_modules/`, and `.bench/`; add `pyproject.toml` and a README with the documented command. Do not delete tests to obtain green.
- **Required regression test:** CI runs the full suite; a deliberately hanging test fails via timeout rather than blocking the job.

### N01 — Non-English titles lose all scientific script markup (P2, new)

- **Location:** `core/title_order.py`, `english_titles_first` (38–52) → `remove_title_scripts` (9–35), called from `core/jats_generator.py:49` and `core/xml_correction.py:1556,1643`.
- **Root cause:** for every `titletext` whose `xml:lang` is not `ENG`/`EN`/`UND`, `remove_title_scripts` unwraps every `sup`, `sub`, and `inf` element, splicing its text into the surrounding content.
- **Verification:** executed probe on `<t>A<sup>2</sup>B<sub>3</sub>C</t>` preserved all text but produced `<t>A2B3C</t>`; nested and italic-bearing scripts were also unwrapped. `tests/test_non_english_title_scripts.py::test_generated_non_english_title_has_no_scripts[FRA]` explicitly asserts that a **French** title loses its script elements, and `test_existing_title_export_preserves_all_text_and_other_markup` asserts that only `italic` survives.
- **Expected:** scientific markup that carries meaning (charges, isotopes, oxidation states, footnote markers, formula subscripts) should survive unless the selected publisher schema forbids it.
- **Actual:** the distinction between “non-English script” and “scientifically meaningful script” is not made. A French, German, or Spanish title containing H₂O loses the subscript; a CJK title loses numeric superscript footnote markers.
- **Impact:** semantic markup loss in a title, with text preserved. Whether this is required by the ANI target is **unverified** because no authoritative schema is present (C11). It is a deliberate, tested behavior, so it must be treated as a product decision rather than silently “fixed”.
- **Proposed correction:** preserve scripts by default and unwrap only when a configured validation profile reports a concrete incompatibility, or restrict unwrapping to a documented, justified subset. If the current behavior is retained, document the semantic loss in `docs/xml_export.md` and add a Latin-script chemical-formula fixture so the decision is visible.
- **Required regression test:** a non-English title containing a formula/charge keeps its markup (if the decision changes); otherwise a test documents the expected text-only result for each language family.

### N02 — Country normalization rejects common constituent and local names (P2, new)

- **Location:** `core/country_codes.py`, `country_code` (42–44) and `normalize_country_elements` (47–74); strict callers at `core/xml_correction.py:1604,1640,1649`.
- **Root cause:** the lookup is built from ISO names/alpha-2/alpha-3 plus a fixed alias table. Common affiliation values that are not sovereign-state names or listed aliases do not resolve.
- **Executed probe:** `England`, `Scotland`, `Wales`, `Northern Ireland`, `Deutschland`, and `The Netherlands` all return `''`; `United States`, `USA`, `U.S.A.`, `Germany`, `South Korea`, `Iran`, `Türkiye`, `Russia`, and `Netherlands` resolve correctly. In strict mode, the ANI `<country>England</country>` raises `ValueError: Country 'England' needs review: select a valid three-letter country code.`
- **Expected:** common, unambiguous affiliation country values normalize to a valid three-letter code, or degrade to a review warning rather than blocking export.
- **Actual:** validated export (and strict normalization of the export copy) is blocked for typical UK and some local-name affiliations until the user manually replaces the country.
- **Impact:** workflow/interoperability friction on many real Elsevier papers; no silent wrong code is produced (the failure is loud and actionable), so this is not data corruption.
- **Proposed correction:** add aliases for the UK constituent countries → `GBR`, tolerate a leading “The”, and decide explicitly whether common exonyms (`Deutschland`) are supported. Keep the hard error for genuinely unknown values, and add a review-warning path if strict blocking proves too aggressive.
- **Required regression test:** aliases resolve to the expected codes; a genuinely unknown value still raises in strict mode and is preserved in non-strict mode.

### N03 — `_auto_classify` is unreachable duplicate logic (P3, new)

- **Location:** `gui/main_window.py` 789–~860.
- **Root cause:** the only classification connection is `classify_btn.clicked.connect(self.classify_selected_blocks)` (464). `_auto_classify` has no caller, no signal connection, and no `getattr` reference. Its body duplicates most of `classify_selected_blocks` (payload construction, OpenRouter calls, role application) with its own broad exception handlers.
- **Impact:** maintainers can edit the dead path and see no effect; the duplication multiplies review surface and the C10 exception-handler count. No runtime defect.
- **Proposed correction:** delete it, or wire it deliberately to a documented UI action and share a single implementation with `classify_selected_blocks`. Do not add a second classification pipeline.
- **Required regression test:** none required for deletion beyond the existing classification tests; if wired, add the responsiveness test from C08.

---

## Unverified risks (not counted as confirmed defects)

| ID | Risk | Why unverified | Next check |
|---|---|---|---|
| R01 | Extraction/layout accuracy on real multi-column, table-heavy, hyphenated, RTL, or scanned papers | No reviewed PDF corpus or accuracy oracle in the repo; tests are synthetic. The golden test is structural, not a corpus. | Build a licensed, reviewed corpus with block/role/reading-order labels; measure precision/recall before changing heuristics. |
| R02 | Raster performance and memory | `pdf_extractor._render_visible_page` uses a fixed `fitz.Matrix(3,3)` and `_PageRasterWorker.run` reopens the PDF per page; no benchmark was run. | Benchmark cold/warm load, pages/min, peak RSS on 50–500-page PDFs; profile before optimizing. |
| R03 | Workspace/draft restoration fidelity | Many round-trip tests pass, but there is no fuzz/property test over malformed `.jatsdraft`, partial writes, or duplicate records. | Add malformed/truncated/duplicate-record tests and a round-trip property test. |
| R04 | Live LLM/GROBID behavior | Network is denied in tests; no live service was called. Timeouts/retries are static (Ollama 120 s; OpenRouter 60 s, 2 retries). | Contract tests with recorded fixtures; opt-in live smoke test. |
| R05 | Dependency vulnerabilities | `pip check` verifies consistency only; no lockfile or CVE scan. | `pip-audit`/OSV scan with a documented exception process. |
| R06 | Residual review of the newly committed bilingual/alternate-name work | This audit reviewed the new modules and their tests and probed text preservation, country handling, and reachability; it did not exhaustively review `author_linker.py`’s 109 changed lines. | Pair-review `author_linker.py` changes with a corpus of bilingual bylines; keep the existing synthetic tests. |
| R07 | Sensitive document text in logs/errors | `PrimaryLLMClient` logs exception strings, and provider errors can include response detail; no redaction test. | Redaction test with a fake error containing a sentinel; audit log sites. |
| R08 | Workspace dirty comparison beyond tested sequences | `workspace_is_clean` is covered for load/save/switch/export, but not every edit/open/close combination. | Table-driven tests for load/edit/save/open/close/replace. |
| R09 | `english_titles_first` sorts `titletext` elements while keeping `original="y"` on the non-English title | No authoritative schema establishes whether the original-language title must remain first or be marked differently; reordering was not validated against a publisher profile. | Validate with a real ANI schema/fixture; confirm expected `original` semantics. |

## Existing protections that must be preserved

- Secure XML parsing (`resolve_entities=False`, `no_network=True`, `load_dtd=False`, `recover=False`) and local schema-path containment in `core/xml_validation.py`.
- Explicit `WELL_FORMED` / `NOT_WELL_FORMED` / `SCHEMA_VALID` / `SCHEMA_INVALID` / `SCHEMA_UNAVAILABLE`; draft export never claims publisher validity.
- Atomic writes and no-clobber publication (`core/atomic_io.py`); exact-byte revision fingerprints (`core/xml_revisions.py`).
- Mixed inline content preservation (`H<sub>2</sub>O`, adjacent italic tails), non-UTF-8 decoding, comment/PI/unknown-node preservation.
- Stale-generation guards for PDF load, article finish, and page raster results.
- Draft vs validated export separation; reviewed-block locking; source-overwrite protection.
- Headless dialog suppression and typed load/export failures.
- Autouse external-network denial in tests; offscreen Qt default.

## Audit conclusion

The application is materially healthier than the previous snapshot: the P1 lifecycle/CLI blockers are fixed, the suite is green, and the XML validation/revision core is intact. The remaining work is **not** a rewrite. In priority order it is: make the test gate trustworthy (C07, C12), decide and document scientific-markup behavior (N01), fix country alias coverage (N02), move classification off the GUI thread and type its errors (C08, C10), remove the latent secret path (C09), and settle schema readiness (C11). No production change is proposed in this phase; remediation requires explicit approval.
