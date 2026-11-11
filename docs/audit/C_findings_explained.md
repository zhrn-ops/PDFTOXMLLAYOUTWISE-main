# Confirmed “C” findings — explained

Snapshot: **2026-11-11**, commit **`c8380c4`** (parent baseline `612f395`).
Scope: the confirmed code findings labelled **C01–C12** in `01_code_audit.md`.

This document is a reader-friendly reference, not a substitute for the audit evidence. It records the **final status after remediation**, so it supersedes the status column in the original findings table where the two differ.

## How to read the identifiers

- **C01–C12** — confirmed defects or readiness gaps found by the audit. These are the subject of this document.
- **N01–N03** — additional findings discovered during the audit (N02 and N03 are fixed; N01 is deferred).
- **R01–R09** — unverified risks, not confirmed defects. They are tracked in `05_final_engineering_review.md`.

**Severity:** P0 = data loss/security emergency, P1 = blocking/corrupting, P2 = significant reliability or correctness gap, P3 = maintainability.
**No P0 was found.**

## Summary

| ID | Severity | Area | Status at `c8380c4` |
|---|---|---|---|
| C01 | P1 | Load lifecycle | **Fixed** — failed load clears the previous document |
| C02 | P1 | Headless/GUI lifecycle | **Fixed** — a load alone is not unsaved work |
| C03 | P1 | Error handling | **Fixed** — load-error dialog is GUI-only |
| C04 | P1 | CLI contract | **Fixed** — zero output is a nonzero failure |
| C05 | P2 | Viewer teardown | **Fixed** — waits, then retains a live thread |
| C06 | P2 | Tests | **Fixed** — stale-API tests repaired |
| C07 | P2 | Golden comparator | **Fixed** — inline whitespace loss is detectable |
| C08 | P2 | GUI responsiveness | **Open** — Classify still blocks the GUI thread |
| C09 | P2 | Secrets | **Partially fixed** — writer gated/redacted; legacy read path remains |
| C10 | P2 | Error handling | **Open** — broad handlers still hide defects |
| C11 | P2 | Schema validity | **Open (external)** — no authoritative ANI/CAR schema |
| C12 | P2 | Test/repo engineering | **Fixed** — CI, timeout, packaging, artifact cleanup |

---

## P1 findings (all fixed)

### C01 — A failed PDF load left the previous document active

**What was wrong.** `_on_pdf_load_complete` reported the load error but did not fully reset the session. The previous `Document`, XML path, generated paths, review state, draft keys, selection, and article state could survive a failed load. A subsequent export could therefore write the **old** paper under the **new** filename.

**Why it matters.** This is a silent cross-document data-integrity failure: the user believes they are working on the PDF they just opened.

**What changed.** The failure branch now clears the document, XML paths, generated outputs, review/draft state, selection, and article state before surfacing the error. The error dialog is shown only when `not headless`.

**Verification.** `tests/test_cli_workflow.py::test_failed_load_clears_previous_document` and `::test_batch_two_pdfs_does_not_prompt_or_reuse_document`.

**Residual risk.** The clear list is hand-maintained. There is no shared “session reset” object enforcing that every newly added per-document field is cleared; that is tracked as architecture debt.

### C02 — A loaded-but-unedited PDF was treated as unsaved work

**What was wrong.** `workspace_is_clean` treated the presence of a loaded document as dirty even when no draft, edit, or saved baseline existed. Closing after a plain load prompted for confirmation; in headless/batch flows the prompt could block or hang.

**Why it matters.** Batch processing must never require interaction, and a mere load must not create phantom unsaved work.

**What changed.** A document with no draft/session and no saved baseline now reports clean. Headless callers receive `False` (refuse) instead of a modal. `Converter.convert` re-baselines after export.

**Verification.** `tests/test_article_drafts.py`, plus the previously hanging `test_load_pdf_path_wait_parameter_completes_extraction` and `test_article_finish_drops_stale_response_on_generation_mismatch`, which now complete without a dialog stub.

### C03 — The load-error dialog blocked headless conversion

**What was wrong.** A corrupt or unreadable PDF raised a `QMessageBox.critical` even when the GUI was running headless, blocking conversion.

**Why it matters.** Modal dialogs in a batch process are an availability failure; the CLI must fail with an actionable status instead.

**What changed.** `headless=True` suppresses the dialog. `_load_pdf_path(wait=True)` returns the error text, the converter raises, `main` prints `[FAIL]`, and the process exits `1`.

**Verification.** `tests/test_cli_workflow.py::test_cli_corrupt_pdf_returns_nonzero_without_dialog`.

### C04 — The CLI reported success while writing zero XML

**What was wrong.** A conversion that produced no files still returned exit code `0`, so callers could not distinguish success from silent non-production.

**Why it matters.** Automation would treat a failed paper as converted and move on.

**What changed.** Empty output after filtering to real files raises. `main` counts per-file failures and returns nonzero. In headless mode an unsegmented PDF is exported as one article rather than skipped.

**Verification.** `test_cli_converter_end_to_end`, `test_cli_main_exit_codes`, and `test_converter_rejects_zero_output`.

---

## P2 findings

### C05 — Viewer cleanup ignored a failed thread wait

**What was wrong.** `cleanup()` called `quit()` and `wait()` but ignored the wait result, then dropped its reference to a raster thread that might still be running.

**Why it matters.** Losing ownership of a live `QThread` can produce a crash or “QThread destroyed while running” during application close.

**What changed.** Cleanup invalidates the raster generation, clears queued/pending renders, calls `quit()` and `wait(5000)`. On timeout it logs a warning and **continues to retain** the thread/worker reference. `_forget_page_render` removes only stopped threads.

**Verification.** `test_viewer_cleanup_cancels_in_flight_raster_threads`.

**Residual risk.** A bounded 5-second stall per unresponsive thread on close is still possible. That is deliberate: waiting is safer than freeing a live thread.

### C06 — Two tests used stale or nonexistent APIs

**What was wrong.** `test_golden_structural.py` constructed nodes without the required `bbox`; `test_process_lifecycle.py` called a nonexistent `set_visible_range`.

**Why it matters.** Broken tests can be mistaken for product regressions, and “fixing” them by deletion would reduce coverage.

**What changed.** The golden test now supplies `bbox`; the lifecycle test uses the viewer’s real render/cleanup API.

**Verification.** Both pass; the suite has no skips or xfails.

### C07 — The structural comparator hid whitespace differences

**What was wrong.** `assert_structural_equality` normalized every `text` and `tail` with `str.strip()`. As a result:

- `<p>text</p>` and `<p> text</p>` compared **equal**;
- a dropped trailing tail (`"  "` vs `""`) compared **equal**.

The docstring promised exact text/tail preservation, so the test net was weaker than documented.

**Correction to the earlier report.** Comments and processing instructions **were** already detected (child count and non-element tag mismatch). The defect was whitespace-only.

**Why it matters.** Losing the space between inline elements (`<italic>x</italic> y` → `<italic>x</italic>y`) is a real scientific-text regression that a golden test should catch.

**What changed.** Text and tails are compared exactly, with only newline-bearing indentation normalized as documented formatting. Six mutation tests prove that a changed leading space, trailing space, comment, or PI fails.

**Verification.** `tests/test_golden_structural.py` — 8 passed.

### C08 — The Classify button blocks the GUI thread on network calls

**What was wrong.** `classify_btn.clicked` connects directly to `classify_selected_blocks`, which calls `OpenRouterClient.classify` on the GUI thread. The client uses `timeout=60` and `max_retries=2`, i.e. up to **three sequential 60-second attempts** (worst case ≈180 s plus connection overhead). There is no worker, cancellation, or disabled-button state.

**Why it matters.** The window cannot repaint or be cancelled and may be reported as “not responding”. This is a reliability and lost-work risk, not data corruption.

**Current status: open.** The fix requires splitting payload construction from result application, running the model call on a worker (the existing `_ArticleFinishWorker` pattern is the model), disabling the action while running, and returning errors by signal. That is a behaviour change large enough to need its own change set.

**Required regression test.** A fake client that blocks on an event; assert the GUI thread stays responsive and the button is disabled; release the event and assert assignments are applied. No live service.

### C09 — Plaintext OpenRouter key path

**What was wrong.** `output/openrouter_settings.json` could contain `"api_key"` in plaintext with default permissions, and `load_config` accepts that value when `OPENROUTER_API_KEY` is absent. The writer had **no caller**, so the exposure was latent rather than active; the read path is live if such a file exists.

**Why it matters.** A plaintext credential can leak through backups, shared machines, or screen sharing.

**What changed (partial).**

- `save_openrouter_settings` no longer writes `api_key` unless called with `include_api_key=True`.
- When opted in, it attempts `0o600` permissions (Windows ACLs do not map to POSIX modes).
- Logging now redacts `sk-…`, `api_key=…`, `Authorization: …`, and `Bearer …` values via `configure_logging`.

**What remains.** The legacy read path still accepts a file-stored key, and there is no warning when one is loaded. The env var should be preferred and the file path deprecated explicitly.

**Verification.** `tests/test_secret_handling.py` — 4 passed (default omission, explicit opt-in, redaction patterns, log-record filter).

### C10 — Broad exception handling hides defects and silently degrades classification

**What was wrong.** In `classify_selected_blocks`, **any** exception from the model call — including a `TypeError`, `KeyError`, or serialization bug — is caught and converted into a heuristic fallback. A programming error is therefore indistinguishable from “model unavailable”.

**Current counts.** After removing the dead `_auto_classify` path, **18** `except Exception` handlers remain:

| File | Count |
|---|---|
| `gui/main_window.py` | 13 |
| `llm/primary_client.py` | 2 |
| `core/pdf_extractor.py` | 1 |
| `gui/pdf_viewer.py` | 1 |
| `utils/logger.py` | 1 (deliberate guard around `record.getMessage()`) |

Excluding the logger’s narrow formatting guard, 17 broad handlers remain.

**Why it matters.** Failures are hard to diagnose, and the heuristic fallback can produce plausible but **unlabelled** classifications. No wrong output was reproduced, but the failure mode is silent scientific degradation.

**Current status: open.** The proposed fix is a typed hierarchy — `LLMUnavailable`, `LLMRateLimited`, `LLMResponseError` — caught only at the UI boundary, with unexpected exceptions logged using `exc_info=True` and surfaced as an internal error. Heuristic provenance must remain labelled.

**Required regression test.** A fake client raising `TypeError` must not be treated as unavailable; a fake transport error must still fall back and be labelled.

### C11 — No authoritative schema; schema-valid claims remain impossible

**What was wrong.** The generator emits **Elsevier ANI/CAR**, but no ANI/CAR XSD is bundled. The legacy default in `core/validator.py` points at `pdf_to_jats/schemas/jats_1_4.xsd`, which does not exist, and there is no `.xsd` anywhere under `pdf_to_jats/`.

**Why it matters.** The product cannot honestly claim publisher validity out of the box, and interoperability depends on a schema the user must supply. This is a **readiness gap**, not a code regression.

**What is already correct.** `core/xml_validation.py` reports independent states: `WELL_FORMED` / `NOT_WELL_FORMED` and `SCHEMA_VALID` / `SCHEMA_INVALID` / `SCHEMA_UNAVAILABLE`. Draft export never claims publisher validity. Validated export requires `SCHEMA_VALID`. A missing schema is never treated as success.

**Current status: open (external dependency).** Closing it requires the licensed ANI/CAR XSD and its redistribution terms, pinned under `pdf_to_jats/schemas/` with provenance and checksum, plus known-good/known-bad fixtures in CI. **This audit fabricates no schema and makes no publisher-validity claim.**

### C12 — Test and repository engineering gaps

**What was wrong.** At baseline there was no CI, no per-test timeout, no `pyproject.toml`, no README, and `.gitignore` covered only `output/` plus duplicate `.env` lines. The repository tracked **237 `.pyc`** files and **2,565 `node_modules/`** files.

**Why it matters.** Regressions were not automatically gated; a hanging test could block every run (the previous red baseline demonstrated exactly that); checkouts were noisy and oversized.

**What changed.**

- `pytest-timeout` with a **180-second** per-test limit.
- Headless Windows CI (`.github/workflows/tests.yml`, Python 3.12/3.13, 20-minute job cap), running compileall and the full suite.
- `pyproject.toml` with test/docling extras; README with install, run, batch, and test instructions.
- Expanded `.gitignore`; **2,802** bytecode/`node_modules` entries untracked via `git rm --cached` (working files left on disk).
- `.bench/big.pdf` remains tracked intentionally as the benchmark input.

**Not done.** The `gui` pytest-marker split was not implemented; GUI tests still run in the default suite.

**Verification.** Full suite **609 passed**; CI configuration parses; `compileall` exits 0.

---

## What “fixed” means here

A finding is marked fixed only when the **reachable behaviour** changed and a regression test covers it, or when the defect was itself in the test net. Findings that require a product decision (N01), a licensed schema (C11), or a larger dedicated change set (C08, C10) are explicitly left open rather than partially patched in a way that would disguise risk.

## Related findings, for completeness

- **N01 (open, P2):** non-English titles have `sup`/`sub`/`inf` unwrapped, so a French or German title loses chemically meaningful markup while preserving text. Whether ANI permits scripts is unknown without C11, so this needs an explicit product decision.
- **N02 (fixed, P2):** `England`, `Scotland`, `Wales`, `Northern Ireland` → `GBR`; `Deutschland` → `DEU`; leading “The” tolerated. Unknown values still fail strict validation.
- **N03 (fixed, P3):** unreachable `_auto_classify` duplicate deleted.
- **R01–R09:** unverified risks, chiefly the absence of a reviewed real-paper accuracy corpus, no RSS/leak measurement, and no live-provider contract tests.

## Bottom line

At `c8380c4`, the P1 lifecycle/CLI defects and the comparator, secret-writer, and repository-engineering gaps are closed. The remaining blocking risks are **C08** (GUI freeze during classification), **C10** (silent fallback on programming errors), and **C11** (no publisher schema). The honest product statement remains: **draft XML is well-formed and semantically checked; publisher validity is unverified.**
