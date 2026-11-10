# Test results — Phase 0 baseline snapshot

Snapshot: **2026-11-10 14:45**. These are executed results for the current working tree, not projected results. The tree changed during the audit (concurrent title/alternate-name edits at 14:35–14:36); the test count grew from 579 to 586. No test source was modified by this audit. An audit-only `QMessageBox` stub under `.audit_tmp/` was used to expose behavior underneath modal dialogs; it is not part of the repository.

## Commands and outcomes

| Command | Result |
|---|---|
| `python -m compileall -q pdf_to_jats tests` | Exit **0**; no syntax errors |
| `python -m pip check` | No broken requirements |
| `python -m pytest tests -q --collect-only` | **586 tests collected** |
| `QT_QPA_PLATFORM=offscreen python -m pytest -q tests -p no:cacheprovider` | **Did not terminate** (three modal-blocked tests) |
| Same, with the three blocking tests deselected | **580 passed, 3 failed, 3 deselected in 27.49 s** |
| `tests/test_cli_workflow.py` + `tests/test_process_lifecycle.py` with the audit `QMessageBox` stub | **4 passed, 3 failed in 2.48 s** |

The standard suite is **not green**. The three failures are real for this snapshot; two are stale test code, one is a CLI contract defect.

## Failures

### 1. Golden structural test — stale model fixture

```
tests/test_golden_structural.py::test_golden_scientific_document_structure
TypeError: Paragraph.__init__() missing 1 required positional argument: 'bbox'
tests/test_golden_structural.py:69
```

`Paragraph.bbox` is a required field (`pdf_to_jats/models/paragraph.py:16`); the fixture omits it. Test defect, not a production defect (C06).

### 2. Viewer cleanup test — nonexistent API

```
tests/test_process_lifecycle.py::test_viewer_cleanup_cancels_in_flight_raster_threads
AttributeError: 'PDFViewer' object has no attribute 'set_visible_range'
tests/test_process_lifecycle.py:66
```

`PDFViewer` never exposed `set_visible_range`; the name appears only in the test commit. The test therefore provides no coverage for `PDFViewer.cleanup` (C05/C06).

### 3. CLI exit code — success with zero output

```
tests/test_cli_workflow.py::test_cli_main_exit_codes
AssertionError: main(...) returned 0; out_dir.glob('*.xml') is empty
stdout: [OK] sample_paper.pdf | 7 blocks | no review flags | 0 XML file(s)
```

`tests/test_cli_workflow.py::test_cli_converter_end_to_end` fails the same way (`0` written files) when the modal close is stubbed. Root cause: `run_auto_pipeline` returns silently when no article is started, and `Converter.convert` checks only for a non-`None` document (C04).

## Modal-blocked tests (hang)

| Test | Faulthandler endpoint | Under `QMessageBox` stub |
|---|---|---|
| `test_cli_workflow.py::test_load_pdf_path_wait_parameter_completes_extraction` | `article_drafts.py:163 confirm_close_drafts` ← `main_window.py:259 closeEvent` | **Passed** — the prior `wait=True` `TypeError` is fixed; only the close prompt hangs |
| `test_cli_workflow.py::test_cli_converter_end_to_end` | Same close path | **Failed** on the zero-output assertion (C04) |
| `test_process_lifecycle.py::test_article_finish_drops_stale_response_on_generation_mismatch` | Same close path | **Passed** — stale-generation rejection works |

Root cause: a freshly loaded PDF is treated as unsaved work (`_saved_workspace` is `None`), so `closeEvent` and opening a second PDF prompt modally (C02).

## Audit probes

| Probe | Result |
|---|---|
| Load valid PDF, then close | `document_loaded True`, `session False`, prompt `['Save article drafts?']` |
| Load valid PDF, then second valid PDF | First: 0 prompts; second: 1 prompt |
| Load valid PDF, then corrupt PDF | `document is None? False`; stale source remains; `QMessageBox.critical('PDF Load Error')` called |
| CLI `Converter` on a simple PDF, no manual article start | No exception; `0 XML file(s)`; `main(...) == 0` |
| `PDFViewer.cleanup` inspection | `thread.wait(200)` result ignored; thread maps cleared unconditionally (static) |

No real API key was read or written; no live network service was contacted (the test fixture denies external sockets); no real document was overwritten. Probe files were synthetic and confined to `.audit_tmp/`.

## Passing areas (executed)

- `tests/test_xml_validation_export.py` — **36 passed** (structured well-formed/schema/unavailable results, draft vs validated export, schema-path containment).
- `tests/test_xml_revision_integrity.py` — **15 passed** (exact-byte revisions, atomic/no-clobber publication).
- Comment/PI/unknown-node preservation, inline mixed-content serialization, non-UTF-8 decoding, draft/session, author/affiliation, and country/alternate-name tests all passed in the terminating run.
- All 50 test modules import; no collection errors.

## Limitations

- No performance benchmark, vulnerability scan, live-service test, or real-publisher-schema validation was run.
- No real scientific PDF corpus was used, so extraction/layout accuracy is not measured.
- The full suite cannot be executed end-to-end without either deselecting the modal-blocked tests or supplying a dialog stub; the standard result is “does not terminate”.
- The working tree changed during the audit; re-run before acting. No production-readiness or schema-validity certification is claimed.
