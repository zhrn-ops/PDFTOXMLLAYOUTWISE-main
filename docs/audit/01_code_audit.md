# Phase 1 — code audit

Snapshot: **2026-11-10 14:45**. Audit-only: no production source, test source, dependency, schema, or CI file was changed. The tree contains pre-existing uncommitted Phase 2/3 work and concurrent title/alternate-name edits; those are identified separately and were not re-audited as new defects.

Severity: **P0** data loss/security emergency; **P1** material correctness, data-integrity, or broken primary workflow; **P2** reliability, diagnostics, security hardening, or engineering gap; **P3** maintainability/hygiene. “Confirmed” means reproduced or directly established from the executed code path; “unverified” means static concern without reproduction.

## Findings summary

| ID | Severity | Status | Area | One-line result |
|---|---|---|---|---|
| C01 | **P1** | Confirmed | Load lifecycle | A failed PDF load leaves the previous `Document` active; the next export can write the wrong article under the new filename. |
| C02 | **P1** | Confirmed | Headless/GUI lifecycle | A freshly loaded PDF is treated as unsaved work; opening a second PDF or closing prompts modally and hangs batch conversion and tests. |
| C03 | **P1** | Confirmed | Error handling | A corrupt PDF calls `QMessageBox.critical` from the conversion path; headless conversion blocks instead of returning an error. |
| C04 | **P1** | Confirmed | CLI contract | `Converter.convert` / `main` return success with zero XML when no article was started. |
| C05 | P2 | Code confirmed; crash unverified | Viewer teardown | `cleanup()` ignores `QThread.wait(200)` failure and clears thread references while workers may still run. |
| C06 | P2 | Confirmed | Tests | Two tests use APIs that do not exist / no longer match the model, so the suite has permanent failures and no viewer-cleanup coverage. |
| C07 | P2 | Confirmed | Golden tests | Structural comparator strips text/tails and does not compare comments/PIs, so it can pass on changes it claims to detect. |
| C08 | P2 | Confirmed | GUI responsiveness | The Classify button calls Ollama/OpenRouter synchronously on the GUI thread (120 s + 3×60 s possible). |
| C09 | P2 | Confirmed | Secrets | OpenRouter API key is read from, and a helper writes, plaintext `output/openrouter_settings.json`; no file-permission restriction. |
| C10 | P2 | Confirmed | Error handling | Nineteen broad `except Exception` handlers; classification silently switches to heuristics on programming errors and logs only a message. |
| C11 | P2 | Confirmed gap | Validation readiness | Default schema path `pdf_to_jats/schemas/jats_1_4.xsd` does not exist; no publisher schema is bundled. Status is now truthful, but no schema-valid claim is possible. |
| C12 | P2 | Confirmed | Test/repo engineering | No CI, no pytest timeout, three modal hangs, no `pyproject.toml`/README, tracked `.pyc` and `node_modules`. |

No P0 was confirmed. C01–C04 are the release blockers because they violate data integrity and the headless contract.

---

## C01 — Failed PDF load leaves the previous document active (P1)

- **Location:** `pdf_to_jats/gui/main_window.py`, `MainWindow._on_pdf_load_complete` (6923–6929); consumer `pdf_to_jats/cli.py`, `Converter.convert` (61–87).
- **Root cause:** the error branch logs and shows a dialog, then returns. It does not clear `self.document`, `self.current_pdf_path`/source path, viewer state, article state, selection, or drafts. `Converter.convert` only checks `self.window.document is None` before calling `run_auto_pipeline`, so a stale non-`None` document passes the guard.
- **Reproduction (executed):** load a valid synthetic PDF with `wait=True`, then load a corrupt `.pdf` with `wait=True` and `QMessageBox` stubbed. Result: `document is None? False`; the stale source path is still the first PDF. The load-error dialog was invoked for the corrupt input.
- **Expected:** a failed load leaves no active document, clears dependent UI/workflow state, and returns a structured failure.
- **Actual:** previous document and path remain active; the failure is only logged/modal.
- **Impact:** in a batch, a corrupt second input can cause the first article to be exported into the second PDF's output folder, with the second file's name. This is silent scientific/data-integrity corruption, not just a UI glitch.
- **Proposed correction:** make loading transactional. Capture the prior state, clear it on failure, reset the generation, and return a `LoadResult`/raise a typed error. `Converter.convert` must verify a successful load for *this* path, not merely a non-`None` document. The GUI may show a dialog in the GUI adapter only.
- **Required regression test:** new `test_failed_load_clears_previous_document`: load good PDF, attempt corrupt PDF, assert `document is None`, `current_pdf_path` empty, no XML produced for either path, and a typed failure is returned. Add a CLI batch case with one valid and one corrupt PDF; assert nonzero exit and no output under the corrupt stem.

## C02 — Loaded-but-unedited PDF is treated as unsaved work; modal prompts block batch and close (P1)

- **Location:** `pdf_to_jats/gui/main_window.py`, `_load_pdf_path` (6894–6895) and `closeEvent` (245–262, prompt at 259); `pdf_to_jats/gui/article_drafts.py`, `_workspace_text` (112–118) and `confirm_close_drafts` (158–166, question at 163).
- **Root cause:** `confirm_close_drafts` compares the current workspace JSON with `self._saved_workspace`. That baseline starts as `None` and is only populated by saving/opening a draft file. Loading a PDF creates draft/workflow content, so the comparison says “changed” even when the user has made no edit. `_load_pdf_path` calls this check whenever a document is already open, so the second PDF in a batch always prompts. `closeEvent` calls it unconditionally.
- **Reproduction (executed):** after loading one synthetic PDF, `document_loaded True`, `session False`, and `close()` produced `prompt_calls ['Save article drafts?']`. Loading a second PDF produced zero prompts on the first and one on the second. Under pytest, faulthandler ends at `article_drafts.py:163` from `main_window.py:259`.
- **Expected:** a load with no edits is clean; closing or replacing it does not prompt. In headless conversion, no modal dialog is ever created.
- **Actual:** modal Save/Discard/Cancel appears; batch conversion and three tests hang.
- **Impact:** batch CLI cannot process two PDFs; the standard test suite cannot terminate; users are prompted to save work they did not create. This is a primary-workflow blocker.
- **Proposed correction:** seed `_saved_workspace` when a document load completes successfully, or replace the JSON comparison with explicit dirty tracking that is reset on load/save/open. Add an injected dialog policy (`interactive` vs `headless`) or a workflow service that never imports `QMessageBox`. In headless mode, an unsaved workspace should be discarded only under an explicit flag, never silently.
- **Required regression test:** `test_close_after_load_does_not_prompt`; `test_second_pdf_does_not_prompt_without_edits`; `test_batch_two_pdfs_completes`; run the existing close tests without a dialog stub.

## C03 — Load-error modal blocks headless conversion (P1)

- **Location:** `pdf_to_jats/gui/main_window.py`, `_on_pdf_load_complete` (6927–6929), `QMessageBox.critical(self, "PDF Load Error", str(error))`.
- **Root cause:** the load worker delivers errors directly to a GUI slot. `_load_pdf_path(wait=True)` connects `finished` with `Qt.DirectConnection`, so the modal executes inline in the CLI thread. There is no headless error adapter.
- **Reproduction (executed):** corrupt PDF with `wait=True`; `critical_calls ['PDF Load Error']`; without the audit stub the process blocks. The CLI catch block cannot run until the dialog is dismissed.
- **Expected:** conversion returns a typed load failure; `main` prints `[FAIL] ...` and returns 1.
- **Actual:** modal blocks indefinitely in non-interactive use.
- **Impact:** any corrupt/encrypted/zero-page input stops an unattended batch; no usable exit code or per-file failure record.
- **Proposed correction:** same transactional load result as C01; GUI adapter decides whether to show a dialog. Never call `QMessageBox` from a worker completion path used by `Converter`.
- **Required regression test:** `test_cli_corrupt_pdf_returns_nonzero_without_dialog`; run with `QT_QPA_PLATFORM=offscreen` and a hard timeout; assert stderr contains `[FAIL]` and no XML is generated.

## C04 — CLI reports success with zero XML files (P1)

- **Location:** `pdf_to_jats/gui/main_window.py`, `run_auto_pipeline` (1221–1265; early return 1227–1232; generation 1253); `pdf_to_jats/cli.py`, `Converter.convert` (80–87) and `main` (135–153).
- **Root cause:** `run_auto_pipeline` returns `None` both on success and on “no article started”/“no documents to export”. `Converter.convert` checks only that a document exists, then snapshots the output folder; an empty snapshot is a valid return. `main` prints `[OK] ... 0 XML file(s)` and returns 0.
- **Reproduction (executed):** `test_cli_main_exit_codes` output: `[OK] sample_paper.pdf | 7 blocks | no review flags | 0 XML file(s)`; `main(...) == 0`. `test_cli_converter_end_to_end` gets `0` written files.
- **Expected:** a conversion that produced no XML is a failure: nonzero exit, actionable message (no article start / no exportable segment), and no success line.
- **Actual:** success exit code and success banner with zero output.
- **Impact:** automation cannot distinguish “converted” from “did nothing”; downstream systems receive silent empty results.
- **Proposed correction:** have `run_auto_pipeline` return an explicit result (paths written, skipped reason), or raise a typed `NoExportableArticleError`. `Converter.convert` must require at least one output path (unless an explicit `--allow-empty` is designed and documented). `main` should count per-file failures.
- **Required regression test:** fix the existing `test_cli_converter_end_to_end` and `test_cli_main_exit_codes`; add `test_cli_no_article_is_failure` asserting nonzero exit and no `[OK]`; keep a positive end-to-end test that starts an article and asserts one XML file.

## C05 — Viewer cleanup ignores a failed thread wait (P2; crash unverified)

- **Location:** `pdf_to_jats/gui/pdf_viewer.py`, `PDFViewer.cleanup` (702–712).
- **Root cause:** for each running render thread, `quit()` then `wait(200)` is called, but the boolean result is ignored. The method then clears `_page_render_threads` and `_page_render_workers` regardless. A worker still inside `fitz.open`/`get_pixmap` may outlive the viewer; clearing references removes the last ownership guard.
- **Reproduction:** static inspection only. The intended test (`test_viewer_cleanup_cancels_in_flight_raster_threads`) cannot run because it calls the nonexistent `set_visible_range` API (C06). No crash was reproduced in this audit.
- **Expected:** cleanup either waits until each worker stops, requests interruption and verifies exit, or leaves the thread/worker owned until `finished`; it must not clear live-thread references.
- **Actual:** fire-and-forget wait; unconditional clearing.
- **Impact:** potential `QThread: Destroyed while thread is still running`, use-after-free on viewer widgets, or a crash on application close while pages are rasterizing. Reliability risk, not a demonstrated data-corruption path.
- **Proposed correction:** connect `finished` to a cleanup that removes the thread; in `cleanup`, wait with a bounded total, log/keep ownership on timeout, and only clear when `isRunning()` is false. Avoid terminating threads that own Python locks. Consider a shared render service with cancellation.
- **Required regression test:** first repair C06; then use a deliberately slow fake raster worker, call `cleanup`, assert it returns only after `isRunning()` is false and that no `QThread` is destroyed while running. Add a close-during-render test.

## C06 — Two tests use stale/nonexistent APIs (P2)

- **Location:** `tests/test_golden_structural.py:69`; `tests/test_process_lifecycle.py:66`.
- **Root cause:** `Paragraph` has required `bbox` (`models/paragraph.py:16`); the golden test omits it. `PDFViewer` has no `set_visible_range`; `git log -S` shows the name only in the test commit, never in production. The viewer exposes `render_page` / `_render_visible_pages` instead.
- **Reproduction:** `pytest -q`; exact failures:
  - `TypeError: Paragraph.__init__() missing 1 required positional argument: 'bbox'`.
  - `AttributeError: 'PDFViewer' object has no attribute 'set_visible_range'`.
- **Expected:** tests exercise the public production contract and pass on the current tree.
- **Actual:** permanent failures unrelated to the feature under test; no usable lifecycle coverage.
- **Impact:** baseline is red; reviewers cannot distinguish new regressions from known red tests; C05 is untested.
- **Proposed correction:** add the required `bbox` to the test fixture (the production requirement is intentional). Decide whether `set_visible_range` should exist: if intended public API, implement it and test it; otherwise rewrite the test against `render_page`/the real render scheduling API. Do not add a no-op method just to satisfy the test.
- **Required regression test:** both tests pass in a normal, non-deselected run; the lifecycle test must actually exercise cleanup (see C05).

## C07 — Structural comparator normalizes away content and ignores comments/PIs (P2)

- **Location:** `tests/test_golden_structural.py`, `assert_structural_equality` (28–40).
- **Root cause:** `norm()` calls `str.strip()` on every `text` and `tail`, so leading/trailing whitespace differences are invisible. The recursion compares elements, tags, attributes, and child count/order, but not comments or processing instructions (lxml represents these as non-element nodes; `zip(node_a, node_b)` iterates children only). The XML declaration is not compared either.
- **Reproduction:** static; no deliberate whitespace/comment mutation was executed. The claim in the docstring (“exact child order”, “text, tail”) is stronger than the implementation.
- **Expected:** the comparator should state precisely what is normalized, and should compare comments/PIs if the golden contract includes them.
- **Actual:** `.strip()` hides boundary whitespace; non-element nodes are not verified.
- **Impact:** a golden test can pass while inline content spacing or comment/PI preservation changes; this weakens the scientific-XML regression net. It does not itself corrupt output.
- **Proposed correction:** compare exact `text`/`tail` by default, or normalize only documented insignificant indentation with a separate canonicalizer. Iterate all XPath nodes (`node()`), compare comment/PI targets/content, and compare the declaration where relevant. Add negative tests proving the comparator rejects a changed space/comment.
- **Required regression test:** mutation tests: altered leading space, altered tail, changed comment, changed PI must each fail the comparator; unchanged golden passes.

## C08 — Synchronous LLM call freezes the GUI (P2)

- **Location:** `pdf_to_jats/gui/main_window.py`, `classify_selected_blocks` (5444+), connected directly at 462; `llm/primary_client.py:20–44`; `llm/ollama_client.py:16,46` (120 s); `llm/openrouter_client.py:26,84–98` (60 s, 2 retries).
- **Root cause:** `classify_btn.clicked.connect(self.classify_selected_blocks)` uses a direct GUI-thread slot. The method calls `PrimaryLLMClient.classify`, which tries local Ollama, then OpenRouter with retries, all synchronously. No `QThread`/worker is used for this action.
- **Reproduction:** confirmed call graph; no live network request was made. Worst-case blocking is 120 s (Ollama) + 3×60 s (OpenRouter attempts), plus connection overhead.
- **Expected:** network/model work runs off the GUI thread; progress/cancel is available; failures return to the UI via signals.
- **Actual:** the event loop is blocked for the duration; the window cannot repaint or cancel.
- **Impact:** apparent freeze, OS “not responding”, lost user work if force-closed. Reliability/usability, not data corruption.
- **Proposed correction:** move the call to an existing worker pattern (as `_ArticleFinishWorker` does) or a `QThreadPool` task; disable the button while running; emit typed success/error. Keep local-first behavior.
- **Required regression test:** inject a fake client that blocks on an event; invoke the action, assert the GUI thread remains responsive and the button is disabled; release and assert assignments applied. No live service.

## C09 — API key stored in plaintext (P2)

- **Location:** `pdf_to_jats/utils/config.py`, `load_config` (37–46) and `save_openrouter_settings` (55–67).
- **Root cause:** the settings JSON includes `"api_key"` and is written with default filesystem permissions under `output/openrouter_settings.json`. `load_config` accepts it as a fallback to `OPENROUTER_API_KEY`. No current caller of `save_openrouter_settings` was found, so this is a latent write path rather than a confirmed active write.
- **Reproduction:** static inspection; no real key read or written.
- **Expected:** secrets come from the environment or an OS credential store; if a file is used, restrict permissions, never log it, and document the risk.
- **Actual:** plaintext key on disk; `output/` is gitignored but often backed up/shared.
- **Impact:** credential disclosure to other local users, backups, or screen-sharing; not remotely exploitable by itself.
- **Proposed correction:** prefer `OPENROUTER_API_KEY`; remove the plaintext writer or gate it behind explicit opt-in with `0o600` on POSIX and an ACL on Windows. Redact keys in errors/logs. Add a startup warning if a key is loaded from the file.
- **Required regression test:** config test asserting env precedence and redaction; writer test (if retained) asserting permissions and no key in logs. Do not embed a real key.

## C10 — Broad exception handling hides defects and silently degrades classification (P2)

- **Location:** 19 `except Exception` handlers under `pdf_to_jats/`; representative: `gui/main_window.py:833` (`_auto_classify`), `5444+` (`classify_selected_blocks`), `llm/primary_client.py:32,39`.
- **Root cause:** catch-all handlers convert programming errors, serialization bugs, and unexpected API shapes into a log line and/or heuristic fallback. `classify_selected_blocks` catches every exception from the model calls and proceeds with local heuristics, so a broken payload/serializer looks like a normal “model unavailable” event. `PrimaryLLMClient` catches everything and raises a `RuntimeError` string containing both exception texts.
- **Reproduction:** static call-path inspection. No deliberate programmer-error injection was executed.
- **Expected:** catch known transport/HTTP/JSON-shape errors; let unexpected exceptions propagate (or log with `exc_info=True` and surface a distinct internal-error state).
- **Actual:** unexpected errors are indistinguishable from expected outages; fallback may produce a wrong-but-plausible role assignment.
- **Impact:** harder diagnosis and possible silent scientific misclassification; not a confirmed wrong output in this audit.
- **Proposed correction:** define typed client errors (`LLMUnavailable`, `LLMRateLimited`, `LLMResponseError`); catch those at the UI boundary. Log unexpected exceptions with stack traces. Keep heuristic fallback only for explicit unavailability, and label its provenance in the UI/output.
- **Required regression test:** fake client raising `TypeError` must not be treated as “LLM unavailable”; assert an error state/exception and no role mutation. Fake transport error must still fall back and be labeled.

## C11 — No authoritative schema bundle; schema-valid claims remain impossible (P2 readiness gap)

- **Location:** `pdf_to_jats/core/validator.py:23–30`; absent `pdf_to_jats/schemas/jats_1_4.xsd`; no `.xsd` anywhere in the package.
- **Root cause:** the legacy default points at a JATS 1.4 schema that was never bundled. The generator emits Elsevier ANI/CAR, not JATS. Phase 2 correctly reports `SCHEMA_UNAVAILABLE` instead of treating missing schema as valid, but no publisher schema is supplied for the ANI format.
- **Reproduction:** path inspection; focused validation tests pass because they supply temporary schemas, not a real publisher schema.
- **Expected:** a reviewed, versioned ANI/CAR schema (or an explicit “no schema configured” product state) with a pinned source/checksum and CI validation.
- **Actual:** default path is dead; users must select a local schema; no schema-valid certification is possible out of the box.
- **Impact:** cannot honestly claim publisher-valid XML; interoperability depends on the user's schema. This is a product-readiness gap, not a code regression. **No finding in this audit claims schema validity.**
- **Proposed correction:** obtain the authoritative Elsevier ANI/CAR XSD with redistribution terms, pin it under `pdf_to_jats/schemas/`, add provenance/checksum, and run a real fixture through it in CI. If redistribution is not permitted, require an explicit schema path at first validated export and document it.
- **Required regression test:** CI test with the pinned schema and a known-good/known-bad fixture; assert `SCHEMA_VALID` / `SCHEMA_INVALID`; keep the `SCHEMA_UNAVAILABLE` path tested.

## C12 — Test and repository engineering gaps (P2)

- **Location:** repository root, `pytest.ini`, `.gitignore`; no `.github/`, `pyproject.toml`, or README.
- **Root cause:** tests were added incrementally around a GUI application without CI or a hard per-test timeout; build artifacts are tracked.
- **Evidence:** 586 collected; standard run hangs in three modal tests; two permanent API-drift failures; **218 tracked `.pyc`** and **2,565 tracked `node_modules/` files**; no timeout plugin/config; no CI workflow; no declared test dependencies.
- **Expected:** one command runs the suite to completion in a clean checkout; hanging/blocked tests fail fast; generated artifacts are ignored; dependencies are declared.
- **Actual:** default `pytest` does not terminate; baseline is red; environment is implicit.
- **Impact:** regressions cannot be gated; every audit/review pays the hang cost; reproducibility is poor.
- **Proposed correction:** add `pytest-timeout`, a CI matrix for Python/Qt headless, split GUI tests with an explicit `gui` marker, stop tracking bytecode/`node_modules`, add `pyproject.toml` with test extras, and document the headless command.
- **Required regression test:** CI job runs the full suite with `QT_QPA_PLATFORM=offscreen` and a timeout; a deliberately hanging test fails the job rather than blocking it.

---

## Unverified risks (not counted as confirmed defects)

| ID | Risk | Why unverified | Next check |
|---|---|---|---|
| R01 | Extraction/layout accuracy on real multi-column, table-heavy, hyphenated, RTL, or scanned papers | No reviewed PDF corpus or accuracy oracle in the repo; tests are synthetic. `test_golden_structural` is currently broken (C06) and not a corpus. | Build a licensed, reviewed corpus with expected block/role/reading-order labels; measure precision/recall before changing heuristics. |
| R02 | Raster performance and memory | `pdf_extractor._render_visible_page` uses a fixed `fitz.Matrix(3,3)` and `_PageRasterWorker.run` reopens the PDF per page; no benchmark was run. | Benchmark cold/warm load, pages/min, peak RSS on 50–500 page PDFs; profile before optimizing. Do not claim a speedup without measurement. |
| R03 | Workspace/draft restoration fidelity | Many tests pass, but no fuzz/property tests over malformed `.jatsdraft`, partial writes, or revision-history edge cases. | Add malformed/truncated/duplicate-record tests and a round-trip property test. |
| R04 | Live LLM/GROBID behavior | Network is denied in tests; no live service was called. Timeouts/retries are static. | Contract tests with recorded fixtures; opt-in live smoke test. |
| R05 | Dependency vulnerabilities | `pip check` only verifies consistency, not CVEs; no lockfile/audit. | `pip-audit`/OSV scan with a documented exception process. |
| R06 | Concurrent uncommitted feature correctness | Bilingual/alternate-name/title-language changes appeared during the audit and were not reviewed. | Review and commit them separately with their own tests; do not fold into remediation. |
| R07 | Sensitive document text in logs/errors | `PrimaryLLMClient` logs exception strings; OpenRouter errors can include response detail. Not reproduced with real content. | Redaction test with a fake error containing a sentinel; audit all log sites. |
| R08 | Workspace dirty comparison beyond the probe | C02 proves a false positive after load; other edit/save/open sequences were not exhaustively tested. | Table-driven tests for load/edit/save/open/close/replace combinations. |

## Existing protections that must be preserved

These are present and focused tests pass; remediation must not regress them:

- Secure XML parsing (`resolve_entities=False`, no network, no DTD load) and local schema-path containment in `core/xml_validation.py`.
- Explicit `WELL_FORMED` / `NOT_WELL_FORMED` / `SCHEMA_VALID` / `SCHEMA_INVALID` / `SCHEMA_UNAVAILABLE`; draft export never claims publisher validity.
- Atomic writes and no-clobber publication (`core/atomic_io.py`); exact-byte revision fingerprints (`core/xml_revisions.py`).
- Mixed inline content preservation (`H<sub>2</sub>O`, adjacent italic tails), non-UTF-8 decoding, comment/PI/unknown-node preservation.
- Stale generation guards for PDF load, article finish, and page raster results.
- Draft vs validated export separation; reviewed-block locking; source-overwrite protection.
- Autouse external-network denial in tests; offscreen Qt default.

## Prior findings resolved in the current tree

The older audit's A01–A06 are not open defects here, with one caveat:

- **A01** structured validation/export status: implemented; `tests/test_xml_validation_export.py` **36 passed**.
- **A02** encoding handling: implemented; non-UTF-8 tests pass.
- **A03** inline mixed-content serialization: implemented; focused tests pass.
- **A04** atomic/no-clobber writes: implemented; revision/export tests pass (15 in `test_xml_revision_integrity.py`).
- **A05** `_load_pdf_path(wait=True)` signature: fixed; the blocked load test's assertions pass under a dialog stub. The workflow is still unusable in a normal run because of C02.
- **A06** alphabetic/Greek script preservation: implemented; related tests pass.

## Audit conclusion

The XML core is materially stronger than the stale baseline suggested, and no P0 was found. The release blockers are lifecycle/CLI contract defects (C01–C04): they can silently associate the wrong article with an input, block unattended batches, and report success with no output. Test infrastructure (C06, C07, C12) is the second priority because it currently cannot prove the absence of regressions. No production change is proposed in this phase; remediation requires explicit approval.
