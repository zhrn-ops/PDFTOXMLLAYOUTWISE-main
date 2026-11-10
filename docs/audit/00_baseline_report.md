# Phase 0 — repository baseline

Audit snapshot: **2026-11-10 14:45 (Asia/Colombo)**. Scope: discovery, baseline execution, and audit only. No production application logic, dependency, CI, or test source was changed in Phases 0–1.

> **Concurrent-change warning.** The working tree changed while this audit was running. `pdf_to_jats/core/title_order.py` and `pdf_to_jats/core/xml_correction.py` were touched at 14:35, and `tests/test_non_english_title_scripts.py` appeared at 14:36. The test count therefore grew from 579 to 586 during the audit. The findings below were re-checked against the 14:45 snapshot; the main finding areas (`main_window.py`, `cli.py`, `pdf_viewer.py`, `article_drafts.py`) were last modified before 11:39 and were not affected. Re-run the baseline before acting on it.

## Environment

| Item | Observed |
|---|---|
| OS / shell | Windows, Git Bash |
| Interpreter | `C:\Python314\python.exe`, Python **3.14.2** (win32, 64-bit) |
| Qt | PySide6 **6.11.1**, Qt runtime 6.11.1 |
| PDF | PyMuPDF **1.27.2.3** |
| XML | lxml **6.0.2** |
| Optional structure | Docling **2.144.0** |
| Tests | pytest **9.0.3**, pytest-qt **4.5.0**, pluggy 1.6.0 |
| Headless Qt | `QT_QPA_PLATFORM=offscreen` |
| Dependency consistency | `python -m pip check` → **No broken requirements found** (not a vulnerability scan) |
| Authoritative publisher schema | **Not present.** `pdf_to_jats/schemas/jats_1_4.xsd` (the legacy default in `core/validator.py`) does not exist, and no ANI/CAR XSD bundle is installed. |

No environment installation was needed. No live GROBID, Ollama, or OpenRouter call was intentionally made. The autouse `deny_external_network` fixture in `tests/conftest.py` blocks non-loopback `socket.connect`, so the executed suite did not deliberately reach public services.

## Repository inventory

- **55 Python source modules** under `pdf_to_jats/`.
- **50 test modules** under `tests/`, **586 tests collected** at the 14:45 snapshot.
- Entry points: `pdf_to_jats/main.py:main` (desktop); `pdf_to_jats/cli.py:main` (batch). `run.ps1` / `run.bat` select an interpreter; `run.ps1` prefers `C:\venvs\p313\...`, which does not exist on this machine.
- Domain models: `models/document.py`, `block.py`, `paragraph.py`, `author.py`, `affiliation.py`, `segmentation.py`.
- PDF/layout: `core/pdf_extractor.py`, `layout_analyzer.py`, `paragraph_reconstructor.py`, `block_merger.py`, `block_resize.py`, `inline_script_detector.py`, `rtl_text.py`.
- Classification/linking: `core/semantic_classifier.py`, `auto_refiner.py`, `author_linker.py`, `parenthesized_authors.py`, `alternate_names.py`, `grobid_client.py`.
- XML: `core/jats_generator.py` (emits **Elsevier ANI/CAR**, despite the `pdf_to_jats` package name), `validator.py`, `xml_validation.py`, `xml_correction.py`, `xml_revisions.py`, `draft_workspace.py`, `atomic_io.py`.
- GUI: `gui/main_window.py` (about 7,553 lines and the orchestration owner), `pdf_viewer.py`, `xml_correction_window.py`, `xml_code_editor.py`, `article_drafts.py`, `properties_panel.py`, `structure_tree.py`, `styles.py`, `grammar_review.py`, `alternate_names_dialog.py`.
- LLM/infrastructure: `llm/primary_client.py` (local Ollama first, OpenRouter fallback), `ollama_client.py`, `openrouter_client.py`, `prompts.py`, `utils/config.py`, `utils/logger.py`.

### Working tree at the snapshot

`git status --short` (excluding bytecode) showed pre-existing changes, not made by this audit:

- Modified: `core/author_linker.py`, `core/jats_generator.py`, `core/xml_correction.py`, `gui/main_window.py`, `gui/xml_correction_window.py`, `models/author.py`, and four existing tests.
- Untracked: `core/alternate_names.py`, `core/country_codes.py`, `core/country_codes.json`, `core/title_order.py`, `gui/alternate_names_dialog.py`, `tests/test_author_edit_sync.py`, `tests/test_country_codes.py`, `tests/test_manual_alternate_names.py`, `tests/test_non_english_title_scripts.py`.

These changes implement bilingual/alternate author names, title-language ordering, country-code normalization, and additional tests. They were **not** part of this audit and were not modified. The existing `docs/audit/phase_02_implementation.md` and `phase_03_implementation.md` describe earlier work already present in this tree; this report supersedes the stale 2026-11-09 baseline and audit documents.

Repository hygiene measured at the snapshot:

- **2,907 tracked files**, including **218 tracked `.pyc`** and **2,565 tracked `node_modules/` files**.
- No root `README.md`, `pyproject.toml`, `.github/workflows/`, or test-dependency declaration.
- `.gitignore` contains only `output/` and two duplicate `.env` lines.
- No authoritative `.xsd` file exists anywhere under `pdf_to_jats/`.

## State lifecycle map (as implemented)

1. `MainWindow._load_pdf_path` starts `_PdfLoadWorker` on a `QThread` (or runs it directly when `wait=True`). Extraction, classification, and auto-refinement run off the GUI thread. A `_document_generation` counter rejects stale load callbacks.
2. `_on_pdf_load_complete` installs the `Document`, viewer payload, page sizes, and optional first-page raster, then resets article workflow state. **On a load error it logs and shows a modal box but does not clear the previous document** (see finding C01).
3. Manual role assignment, article boundaries, and accepted paragraph operations mutate `Document` blocks and metadata. Legacy detector segments remain supported; the current startup flow requires an explicit article number before export.
4. Finish Article runs LLM/GROBID enrichment on `_ArticleFinishWorker`; completion is generation-checked. XML is generated in memory and opened in `XmlCorrectionWindow`; reviewed blocks are locked.
5. Corrections live in a separate `XmlDocumentSession`, not in `Document`. Raw parse failures keep the last valid tree, mark `raw_valid=False`, and block export. Structured edits invalidate the prior issue list.
6. `ArticleDrafts` retains XML, raw editor text, PDF/source paths, dirty state, history, revision snapshots, and last validation/export provenance in `.jatsdraft` JSON. Activation reconstructs a session from revision bytes; portable validation is provenance only and never grants a fresh result.
7. Reopening an article unlocks blocks without deleting its XML draft. Regeneration compares against `generated_xml`; corrected drafts require a review decision. Rejection retains `pending_generated`; acceptance archives the previous draft.
8. Draft Export and Validated Export are distinct in the correction UI. Validated export requires a selected local schema profile; missing/invalid schema resources block it. Legacy `run_auto_pipeline` and `_export_article_xml` remain draft-oriented and report publisher incompleteness.
9. Workspace reopening validates records through `stage_workspace` before replacing live state; conversion undo history is cleared. Closing prompts to save/discard/cancel when the workspace comparison says there are changes.

## Executed baseline

| Command / variant | Result |
|---|---|
| `python -m compileall -q pdf_to_jats tests` | **Exit 0**, no syntax errors printed |
| `python -m pytest -q` (default discovery) | **Never returned**; terminated by the audit's 600 s command timeout |
| `python -m pytest -q tests` (offscreen, cache disabled) | **Hangs** in `test_cli_workflow.py` and `test_process_lifecycle.py` (details below) |
| Full suite, three blocking tests deselected | **580 passed, 3 failed, 3 deselected in 27.49 s** (586 collected) |
| CLI + lifecycle files with an audit-only `QMessageBox` stub | **4 passed, 3 failed in 2.48 s**; the three blocked tests split into two passes and one failure (`converter` zero-output), and the non-blocked `test_cli_main_exit_codes` also failed |
| `python -m pip check` | No broken requirements |

The standard suite is **not a passing run**. The three deselected tests block on real modal dialogs, and two of the three failures are caused by stale test code. The audit-only `QMessageBox` stub was used solely to expose the behavior underneath; it is not a test change and is not part of the repository.

### Failures and blocked tests

| Test | Status | Evidence |
|---|---|---|
| `tests/test_golden_structural.py::test_golden_scientific_document_structure` | **Failed** | `TypeError: Paragraph.__init__() missing 1 required positional argument: 'bbox'` at test line 69. `Paragraph` has required `bbox`; the test constructs it without one. |
| `tests/test_process_lifecycle.py::test_viewer_cleanup_cancels_in_flight_raster_threads` | **Failed** | `AttributeError: 'PDFViewer' object has no attribute 'set_visible_range'` at test line 66. The viewer exposes `_render_visible_pages` / `render_page`, not this method; `git log -S` shows the test introduced the name but no production implementation. |
| `tests/test_cli_workflow.py::test_cli_main_exit_codes` | **Failed** | `main([...])` returns 0, then `out_dir.glob("*.xml")` is empty. stdout: `[OK] sample_paper.pdf \| 7 blocks \| no review flags \| 0 XML file(s)`. |
| `tests/test_cli_workflow.py::test_cli_converter_end_to_end` | **Blocked by modal close** | Under a dialog stub: `assert len(written) >= 1` fails with `0`. Without the stub: hangs in `converter.window.close()` → `article_drafts.py:163 confirm_close_drafts`. |
| `tests/test_cli_workflow.py::test_load_pdf_path_wait_parameter_completes_extraction` | **Blocked by modal close** | Faulthandler stack ends at `article_drafts.py:163 confirm_close_drafts` called by `main_window.py:259 closeEvent`. Under a dialog stub the assertions pass, so the prior `wait=True` `TypeError` is fixed, but the test still hangs in normal runs. |
| `tests/test_process_lifecycle.py::test_article_finish_drops_stale_response_on_generation_mismatch` | **Blocked by modal close** | Same `closeEvent` → `confirm_close_drafts` stack at test line 102. Under a dialog stub the stale-generation assertions pass. |

### Baseline probes (synthetic, no real documents or secrets)

| Probe | Observed | Finding |
|---|---|---|
| Load a minimal valid PDF, then close without editing | `document_loaded True`, `session False`, `prompt_calls ['Save article drafts?']` | C02 |
| Load a valid PDF, then load a second valid PDF | First load: 0 prompts; second load: 1 prompt (`Save article drafts?`) | C02; batch CLI hangs on the second input |
| Load a valid PDF, then a corrupt `.pdf` | `document is None? False`; stale `source_pdf` remains the first PDF; `QMessageBox.critical('PDF Load Error')` called | C01, C03 |
| Run the CLI `Converter` on a simple PDF with no manual article start | No exception; `0 XML file(s)`; `main` returns 0 | C04 |
| Read `PDFViewer.cleanup` | `thread.wait(200)` return ignored; thread/worker maps cleared regardless | C05 (static; crash not reproduced) |
| Inspect structural comparator | `.strip()` on text/tails; comments/PIs not compared as content | C07 |

No actual API key was read or written. No real source XML was overwritten. All probe files were created under a temporary directory inside `.audit_tmp/` and are removed before hand-off.

## Phase 2/3 work already present in this tree

The earlier phases are already implemented in the working tree (uncommitted). This audit did not re-report them as open defects:

- Structured `WELL_FORMED` / `NOT_WELL_FORMED` / `SCHEMA_VALID` / `SCHEMA_INVALID` / `SCHEMA_UNAVAILABLE` results in `core/xml_validation.py`; explicit draft vs validated export; local schema-bundle path containment; secure parsers.
- Atomic publication in `core/atomic_io.py` and exact-byte revision fingerprints in `core/xml_revisions.py`.
- Inline mixed-content serialization that leaves `H<sub>2</sub>O` and adjacent `italic` tails intact.
- ISO-8859-1/UTF-16 Unicode boundaries; alphabetic/Greek script preservation.
- 36 `tests/test_xml_validation_export.py` cases and 15 `tests/test_xml_revision_integrity.py` cases all passed in the terminating run.

Remaining limitations are documented in `01_code_audit.md`. The absence of an authoritative ANI/CAR schema means this checkout still cannot make a publisher-valid claim; the code now reports that truthfully instead of treating missing schema as success.

## Baseline conclusion

- No **P0** defect was confirmed.
- The most serious current issues are not in the XML core; they are in the **headless conversion contract** (stale document on failed load, modal dialogs during batch/close, zero-output success) and in **test infrastructure** (three hangs, two stale-API failures, no CI/timeout).
- The prior XML validation/revision work is present and its focused tests pass. It should be reviewed and committed before further changes.
- No performance benchmark, vulnerability scan, live-service test, or publisher-schema validation was executed. No production-readiness certification is claimed.
