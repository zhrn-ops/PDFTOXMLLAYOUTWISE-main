# Phase 0 — Repository discovery and baseline

Audit snapshot: **2026-11-11 09:00 (SLST)**, commit **`612f395`**, branch `main`, **clean working tree** (`git status --porcelain` returned no entries).

> **Historical baseline.** This file records the pre-remediation state. Later approved phases changed source, tests, CI, and packaging; the final state and all deltas are in `05_final_engineering_review.md`.

Scope: discovery, baseline execution, and audit only. **No production application logic, test source, dependency, schema, or CI file was changed.** This report supersedes the 2026-11-10 14:45 snapshot, which was taken while the tree contained uncommitted Phase 2/3 and bilingual-author work. That work is now committed, and the previously red baseline is green.

## Environment

| Item | Observed |
|---|---|
| OS / shell | Windows, Git Bash |
| Interpreter | `C:\Python314\python.exe`, Python **3.14.2** (win32, 64-bit) |
| Qt | PySide6 **6.11.1** (Qt runtime 6.11.1) |
| PDF | PyMuPDF **1.27.2.3** |
| XML | lxml **6.0.2** |
| Optional structure | Docling **2.144.0** |
| Tests | pytest **9.0.3**, pytest-qt **4.5.0**, pluggy 1.6.0 |
| `pytest-timeout` | **Not installed** |
| Headless Qt | `QT_QPA_PLATFORM=offscreen` |
| Dependency consistency | `python -m pip check` → **No broken requirements found** (consistency check only, not a CVE scan) |
| Authoritative publisher schema | **Not present.** No `.xsd` exists under `pdf_to_jats/`; `pdf_to_jats/schemas/jats_1_4.xsd`, the legacy default in `core/validator.py`, does not exist. |

No environment installation was required. No live GROBID, Ollama, or OpenRouter call was made. The autouse `deny_external_network` fixture in `tests/conftest.py` blocks non-loopback `socket.connect`, so the executed suite could not deliberately reach public services.

## Repository inventory

- **55 Python source modules** under `pdf_to_jats/`; **20,821 LOC**.
- **50 test modules** under `tests/`; **590 tests collected**; **10,196 LOC**.
- **2,935 tracked files** total.

Entry points and modules:

| Area | Files |
|---|---|
| Desktop entry | `pdf_to_jats/main.py:main` |
| Batch entry | `pdf_to_jats/cli.py:main` (`Converter`, headless `MainWindow`) |
| Domain models | `models/document.py`, `block.py`, `paragraph.py`, `author.py`, `affiliation.py`, `segmentation.py` |
| PDF / layout | `core/pdf_extractor.py`, `layout_analyzer.py`, `paragraph_reconstructor.py`, `block_merger.py`, `block_resize.py`, `inline_script_detector.py`, `rtl_text.py`, `language.py` |
| Classification / linking | `core/semantic_classifier.py`, `auto_refiner.py`, `author_linker.py`, `parenthesized_authors.py`, `alternate_names.py`, `country_codes.py`, `grobid_client.py` |
| XML | `core/jats_generator.py` (emits **Elsevier ANI/CAR**, despite the package name), `validator.py`, `xml_validation.py`, `xml_correction.py`, `xml_revisions.py`, `draft_workspace.py`, `atomic_io.py`, `title_order.py` |
| GUI | `gui/main_window.py` (**7,617 lines**), `xml_correction_window.py` (1,970), `pdf_viewer.py` (1,200), `article_drafts.py`, `properties_panel.py`, `structure_tree.py`, `styles.py`, `grammar_review.py`, `alternate_names_dialog.py`, `xml_code_editor.py` |
| LLM / infrastructure | `llm/primary_client.py` (local Ollama first, OpenRouter fallback), `ollama_client.py`, `openrouter_client.py`, `prompts.py`, `utils/config.py`, `utils/logger.py` |

Largest modules: `main_window.py` 7,617; `xml_correction_window.py` 1,970; `core/xml_correction.py` 1,662; `core/author_linker.py` 1,493; `core/pdf_viewer` 1,200.

### Working tree and history

- `main` is 14 commits ahead of the first commit, tracking `origin/main`.
- The last commit (`612f395`) committed the bilingual/alternate-name/country/title-language feature set and **also committed its `.pyc` files** and refreshed audit documents.
- No uncommitted changes existed before the audit; none were introduced by it.

### Repository hygiene measured at the snapshot

- **237 tracked `.pyc` files** (including bytecode for modules under `pdf_to_jats/` and `tests/`).
- **2,565 tracked `node_modules/` files** from a JavaScript `@openrouter/sdk` dependency. The Python application does not import it; it is a separate Node dependency (`package.json`).
- `.bench/big.pdf` (320 KB) is tracked.
- `.gitignore` contains only `output/` and two duplicate `.env` lines. Bytecode, caches, `node_modules/`, and `.bench/` are not ignored.
- **No root `README.md`**, **no `pyproject.toml`**, **no `.github/workflows/`**, and no declared test-dependency set or lockfile.
- An empty leftover directory `.test-alt-review-20261110/` exists at the root and is untracked/empty.

## State lifecycle map (as implemented)

1. `MainWindow._load_pdf_path` runs `_PdfLoadWorker` on a `QThread` (or directly when `wait=True`, using `Qt.DirectConnection`). Extraction, classification, and auto-refinement run off the GUI thread. `_document_generation` rejects stale callbacks; the synchronous path returns `_last_load_error`.
2. `_on_pdf_load_complete` installs the `Document`, viewer payload, page sizes, and preview, then resets article workflow state. **On failure it calls `_clear_document_after_load_failure`, which sets `document = None`, clears paths, selections, drafts, and article state; the modal `QMessageBox.critical` is shown only when `headless` is false.**
3. Manual role assignment, article boundaries, and accepted paragraph operations mutate `Document` blocks and metadata. The current startup flow clears extractor-derived article segments and requires an explicit article number, except that an unsegmented PDF is exported as one article.
4. Finish Article runs LLM/GROBID enrichment on `_ArticleFinishWorker`; completion is generation-checked. XML is generated in memory and opened in `XmlCorrectionWindow`; reviewed blocks are locked.
5. Corrections live in a separate `XmlDocumentSession`, not in `Document`. Raw parse failures keep the last valid tree, mark `raw_valid=False`, and block export. Structured edits invalidate the prior issue list. Validation carries exact-byte fingerprints.
6. `ArticleDrafts` retains XML, raw editor text, PDF/source paths, dirty state, history, revision snapshots, and last validation/export provenance in `.jatsdraft` JSON. Activation reconstructs a session from revision bytes; portable validation is provenance only and never grants a fresh result.
7. Reopening an article unlocks blocks without deleting its XML draft. Regeneration compares against `generated_xml`; corrected drafts require a review decision. Rejection retains `pending_generated`; acceptance archives the previous draft.
8. Draft Export and Validated Export are distinct. Validated export requires a selected local schema profile; missing/invalid schema resources block it. Legacy `run_auto_pipeline` and `_export_article_xml` remain draft-oriented and log that publisher validation is incomplete.
9. Workspace reopening validates records before replacing live state; conversion undo history is cleared. `workspace_is_clean()` treats a programmatically loaded document with no drafts/session as clean, so a mere load does not prompt. In headless mode `confirm_close_drafts` refuses rather than showing a modal.
10. `PDFViewer.cleanup` waits up to 5 s per raster thread, logs a timeout, and **keeps ownership** of a thread that did not stop instead of clearing it.

## Executed baseline

All commands were run from the project root with `QT_QPA_PLATFORM=offscreen`.

| Command | Result |
|---|---|
| `python -m compileall -q pdf_to_jats tests` | **Exit 0**; no syntax errors |
| `python -m pip check` | **No broken requirements found** |
| `python -m pytest --collect-only -q -p no:cacheprovider` | **590 tests collected in 3.57 s** |
| `timeout 300 python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=45` | **590 passed in 20.86 s**, exit 0 |
| Repeat `-rsxX` run | **590 passed in 21.99 s**; no skips, xfails, or collection errors |

The suite now terminates normally. The 2026-11-10 report recorded three modal-blocked tests, two stale-API failures, and one CLI zero-output failure; **all six now pass** in a non-deselected run without any dialog stub or audit-only test modification.

### Warnings and import failures

- Compilation and collection produced no warnings, import failures, or missing dependencies.
- `pytest.ini` filters `DeprecationWarning` and `PendingDeprecationWarning`, so deprecation output would be suppressed even if present. This was not changed.

## Reconciliation with the previous baseline

| Previous item | Current status |
|---|---|
| 586 tests; three hangs; 3 failures | **590 tests, 0 failures, 0 hangs** |
| C01 failed load retained the previous document | **Fixed** — transactional clear; covered by `test_failed_load_clears_previous_document` |
| C02 loaded-but-unedited PDF prompted to save | **Fixed** — `workspace_is_clean`/`mark_workspace_clean` and headless refusal; covered by `test_batch_two_pdfs_does_not_prompt_or_reuse_document` |
| C03 corrupt PDF opened a modal in headless runs | **Fixed** — dialog gated by `self.headless`; covered by `test_cli_corrupt_pdf_returns_nonzero_without_dialog` |
| C04 CLI reported success with zero XML | **Fixed** — `Converter.convert` raises when no file is written; covered by `test_converter_rejects_zero_output` |
| C05 cleanup ignored a failed thread wait | **Fixed** — 5 s verified wait, ownership retained on timeout; covered by `test_viewer_cleanup_cancels_in_flight_raster_threads` |
| C06 stale test APIs | **Fixed** — the tests now use the real model/viewer APIs and pass |
| Prior audit documents described a red baseline | **Stale**; replaced by this report and refreshed `01`–`03` |

## Baseline conclusion

- **No P0 defect is open.** The four P1 release blockers from the previous audit are fixed and covered by regression tests.
- The remaining open findings are engineering and fidelity issues, not data-corruption blockers: schema/scientific-accuracy readiness, test-build hygiene, a GUI-thread LLM call, broad exception handling, and two newly confirmed content-normalization concerns (see `01_code_audit.md`).
- The XML core (structured validation statuses, atomic publication, revision fingerprints, secure parsing, mixed-content preservation) is present and its focused tests pass.
- **No claim of publisher schema validity is made.** No authoritative ANI/CAR schema is bundled, so validated export depends on a user-supplied local profile.
- Not measured in this phase: real scientific-PDF extraction accuracy, performance/memory benchmarks, dependency CVEs, live-service behavior, or schema validation against an authoritative publisher schema.
