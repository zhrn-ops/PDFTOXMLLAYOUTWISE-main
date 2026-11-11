# Test results — Phase 0/1 baseline

Snapshot: **2026-11-11 09:00 (SLST)**, commit **`612f395`**, clean tree. These are executed results for the current source, not projected results. No production or test source was modified during this audit.

## Commands and outcomes

| Command | Result |
|---|---|
| `python -m compileall -q pdf_to_jats tests` | **Exit 0**; no syntax errors |
| `python -m pip check` | **No broken requirements found** |
| `QT_QPA_PLATFORM=offscreen python -m pytest --collect-only -q -p no:cacheprovider` | **590 tests collected in 3.57 s** |
| `QT_QPA_PLATFORM=offscreen timeout 300 python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=45` | **590 passed in 20.86 s**, exit 0 |
| `QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:cacheprovider -rsxX` | **590 passed in 21.99 s**; no skips, xfails, or collection errors |

The suite terminates normally without deselection, dialog stubs, or audit-only fixtures. `faulthandler_timeout` was used only to surface a stall if one occurred; no test exceeded it.

Coverage of the previously open P1 findings (all committed in `tests/`):

| Finding | Regression test | Status |
|---|---|---|
| C01 | `test_cli_workflow.py::test_failed_load_clears_previous_document`, `::test_batch_two_pdfs_does_not_prompt_or_reuse_document` | Passed |
| C02 | `test_cli_workflow.py::test_batch_two_pdfs_does_not_prompt_or_reuse_document`, the previously hanging load/lifecycle tests | Passed |
| C03 | `test_cli_workflow.py::test_cli_corrupt_pdf_returns_nonzero_without_dialog` | Passed |
| C04 | `test_cli_workflow.py::test_cli_converter_end_to_end`, `::test_cli_main_exit_codes`, `::test_converter_rejects_zero_output` | Passed |
| C05 | `test_process_lifecycle.py::test_viewer_cleanup_cancels_in_flight_raster_threads` | Passed |
| C06 | `test_golden_structural.py`, `test_process_lifecycle.py` | Passed |

## Audit probes (executed, not part of the suite)

These probes used the project modules directly; they created no repository files.

### Structural comparator (C07)

| Mutation | Comparator result |
|---|---|
| Leading space changed (`text` vs ` text`) | **Passed** (difference not detected) |
| Tail whitespace `"  "` → `""` | **Passed** (difference not detected) |
| Internal double space (`a b` → `a  b`) | Rejected |
| Comment added | Rejected (child count/tag mismatch) |
| Processing instruction added | Rejected (child count/tag mismatch) |

This narrows C07 to whitespace normalization. The previous report’s claim that comments/PIs are not compared was incorrect.

### Non-English title script removal (N01)

| Input | Result |
|---|---|
| `A<sup>2</sup>B<sub>3</sub>C` | Text preserved; serialized as `A2B3C` |
| `<sup>2</sup>H<sub>2</sub>O water` | Text preserved; serialized as `2H2O water` |
| `A<sup>x<sup>y</sup>z</sup>B` | Text preserved; serialized as `AxyzB` |
| `A<sup><italic>q</italic>r</sup>B` | Text preserved; `italic` retained, `sup` removed |

No text loss was found; the loss is markup/semantics (`sup`, `sub`, `inf`).

### Country normalization (N02)

| Value | `country_code` |
|---|---|
| `United States`, `USA`, `U.S.A.` | `USA` |
| `Germany` | `DEU` |
| `South Korea`, `Korea, Republic of` | `KOR` |
| `Iran`, `Türkiye`, `Russia`, `Netherlands` | `IRN`, `TUR`, `RUS`, `NLD` |
| `England`, `Scotland`, `Wales`, `Northern Ireland` | `''` |
| `Deutschland`, `The Netherlands` | `''` |

With `strict=True`, `<country>England</country>` raises `ValueError: Country 'England' needs review: select a valid three-letter country code.`; `Germany` normalizes to `iso-code="DEU"` and removes the text.

### Dead code (N03)

`grep` over `pdf_to_jats/gui/*.py` finds `_auto_classify` only at its definition (`main_window.py:789`) and one log string inside it. The only classification connection is `classify_btn.clicked.connect(self.classify_selected_blocks)` at line 464.

## Passing areas (executed)

- `test_xml_validation_export.py` — structured well-formed/schema/unavailable results, draft vs validated export, schema-path containment, atomic-write failure preservation, mixed-content serialization, non-UTF-8 decoding.
- `test_xml_revision_integrity.py` — exact-byte revisions, atomic/no-clobber publication.
- `test_article_drafts.py` — regeneration/reconciliation, save/reopen, workspace round-trip, cancel preserves draft.
- `test_author_edit_sync.py`, `test_bilingual_authors.py`, `test_manual_alternate_names.py`, `test_country_codes.py`, `test_non_english_title_scripts.py` — newly committed feature coverage.
- `test_article_workflow.py`, `test_segmentation.py`, `test_marker_workflow.py` — article partition, deletion, finish, export scoping.
- `test_pdf_viewer_loading.py`, `test_process_lifecycle.py` — on-demand rendering, bounded cache, stale-result rejection, cleanup.
- All 50 test modules import; no collection errors.

## Limitations

- No performance benchmark, memory measurement, vulnerability scan, live-service test, or real-publisher-schema validation was run.
- No real scientific PDF corpus was used; extraction/layout accuracy on real papers is not measured (R01).
- The full suite runs headless (`QT_QPA_PLATFORM=offscreen`); it does not prove visual/interaction correctness in a displayed window.
- `pytest.ini` filters deprecation warnings, so suppressed warnings would not appear in this output.
- `docs/audit/dependency_versions.txt` is a dated environment inventory, not a lockfile or CVE result.
- No production-readiness or schema-validity certification is claimed.

---

## Final post-remediation results

After the approved remediation changes (country aliases, exact comparator, dead-code removal, secret/log hardening, test timeout), the full suite was re-run:

| Command | Result |
|---|---|
| `python -m compileall -q pdf_to_jats tests` | Exit 0 |
| `QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:cacheprovider` | **609 passed in 20.66 s**, exit 0 |
| `tests/test_golden_structural.py` | 8 passed |
| `tests/test_country_codes.py` | 38 passed |
| `tests/test_secret_handling.py` | 4 passed |
| `tests/test_xml_validation_export.py` + `tests/test_xml_revision_integrity.py` | 51 passed |

**19 tests were added** (590 → 609): 6 comparator strictness/mutation tests, 9 country alias/strict-mode cases, and 4 secret-handling/redaction tests. No test was skipped, weakened, or deleted.

CI (`.github/workflows/tests.yml`) runs the same suite headless on Windows with a 180-second per-test timeout and a 20-minute job cap. Docling is intentionally omitted there, so CI exercises the documented PyMuPDF-only fallback.
