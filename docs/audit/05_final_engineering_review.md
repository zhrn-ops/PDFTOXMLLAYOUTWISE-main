# Phase 8 — Final engineering review

Snapshot: **2026-11-11**. Baseline commit: `612f395`. Working tree: remediation changes uncommitted (source, tests, CI, packaging, docs; 2,802 build artifacts untracked from the index).

This review covers Phases 0–8. It states what was executed, what was deliberately not changed, and what remains. **No publisher-schema validity is claimed.** No authoritative ANI/CAR schema exists in this repository.

## Phase status

| Phase | Status | Result |
|---|---|---|
| 0 — Discovery / baseline | **Complete** | Clean tree; 590 tests green in 20.9 s; compile and dependency checks pass. |
| 1 — Code audit | **Complete** | Prior P1s verified fixed; C07–C12 re-verified; N01–N03 added. |
| 2 — XML validation / export | **Verified already implemented** | 51 focused tests pass; structured statuses, draft vs validated export, secure parsing, atomic writes intact. No code change needed. |
| 3 — Revision integrity | **Verified already implemented** | Revision fingerprints, correction retention, reconciliation tests pass. No code change needed. |
| 4 — Test engineering | **Complete (incremental)** | Exact comparator + 6 mutation tests; 7 country cases + 2 API tests; 4 secret/log tests; timeout gate; CI. |
| 5 — Architecture | **Minimal, deliberate** | Removed one unreachable duplicate (~82 lines). Full layered refactor deferred; rules forbid a rewrite. |
| 6 — Performance | **Measured** | `04_performance_report.md`; no optimization applied. |
| 7 — Error/observability | **Partial** | Log redaction and opt-in secret persistence added. Typed LLM errors and GUI-thread classification deferred with design. |
| 8 — Packaging / CI | **Complete** | `pyproject.toml`, README, `.gitignore`, Windows CI, artifact untracking. |

## Files modified

Production:

- `pdf_to_jats/core/country_codes.py` — UK constituent-country aliases, `Deutschland`, `The Netherlands`, and leading-“The” tolerance.
- `pdf_to_jats/gui/main_window.py` — deleted unreachable `_auto_classify` (82 lines); no live path changed.
- `pdf_to_jats/utils/config.py` — `save_openrouter_settings` no longer persists the API key unless explicitly opted in; restricted mode when it is.
- `pdf_to_jats/utils/logger.py` — API-key/bearer redaction filter applied by `configure_logging`.

Tests:

- `tests/test_golden_structural.py` — exact inline whitespace comparison with documented indentation normalization; 6 mutation tests.
- `tests/test_country_codes.py` — 7 alias cases + 2 strict-normalization tests.
- `tests/test_secret_handling.py` — **new**; 4 tests for key persistence and log redaction.

Build/CI/docs:

- `pytest.ini` — 180-second per-test timeout.
- `pyproject.toml`, `README.md`, `.github/workflows/tests.yml` — **new**.
- `.gitignore` — caches, bytecode, virtualenvs, `node_modules/`, transient workspaces.
- `.bench/audit_bench.py` — **new** benchmark script (left untracked; `.bench/` is not a package).
- `docs/audit/00`–`04`, `collection_results.txt` — refreshed.

Index changes:

- `git rm --cached` removed **237 `.pyc`** and **2,565 `node_modules/`** entries from tracking. **No working files were deleted**; `node_modules/` remains on disk and `package.json`/`package-lock.json` remain tracked.

## Bugs fixed

- **C07** — structural comparator hid lost inline spacing. Leading spaces and dropped tails are now detected; newline indentation is the only documented normalization.
- **N02** — validated export blocked on common UK/local country names. `England`, `Scotland`, `Wales`, `Northern Ireland` → `GBR`; `Deutschland` → `DEU`; `The Netherlands` → `NLD`.
- **N03** — unreachable `_auto_classify` duplicate removed.
- **C09 (partial)** — the plaintext key writer is now opt-in and permission-restricted; a redaction filter masks keys/bearer tokens in logs.

No production behavior changed for a reachable classification, generation, validation, or export path other than the country aliases.

## Tests added and executed

Added **19** test cases (609 total, up from 590):

- 6 comparator mutation/strictness tests.
- 9 country alias/strict-mode tests (7 parametrized + 2 functions).
- 4 secret-handling/redaction tests.

Executed after all changes:

```text
QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:cacheprovider
609 passed in 20.66 s
```

Focused verification:

- `tests/test_golden_structural.py` — 8 passed.
- `tests/test_country_codes.py` — 38 passed.
- `tests/test_secret_handling.py` — 4 passed.
- `tests/test_xml_validation_export.py` + `tests/test_xml_revision_integrity.py` — 51 passed.
- `python -m compileall -q pdf_to_jats tests` — exit 0 after changes.

**No test was skipped, weakened, or deleted to obtain green.** CI runs the same suite headless with a 20-minute job cap and a 180-second per-test timeout. Docling is intentionally omitted in CI, exercising the documented PyMuPDF-only fallback.

## Behavior changes (intentional, documented)

1. **Country aliases** now normalize constituent UK countries and selected local names. Genuinely unknown values still fail strict validation; `Korea` remains ambiguous and unresolved.
2. **`save_openrouter_settings`** omits `api_key` unless `include_api_key=True`. It currently has no caller, so no live GUI flow changes.
3. **Logging** redacts `sk-…` keys and `api_key`/`Authorization`/`Bearer` values.
4. **Repository tracking** no longer includes bytecode or `node_modules`; a commit is required to publish that change.
5. **Tests** now fail on a 180-second stall instead of hanging indefinitely.

## Remaining technical debt

### High priority

| Item | Why it remains | Suggested next action |
|---|---|---|
| **C08 — synchronous Classify call** | The slot performs up to 3×60 s HTTP attempts on the GUI thread. Moving it requires splitting payload/apply logic and a worker + responsiveness test; too risky to fold into an audit pass. | Extract `_classify_payload`/`_apply_classify_response`, run on `_ArticleFinishWorker`-style thread, disable the button, add a fake-client responsiveness test. |
| **C10 — broad exception handling** | 19 handlers; typed LLM errors change client APIs and fallback semantics. | Introduce `LLMUnavailable`/`LLMRateLimited`/`LLMResponseError`; catch only those at the UI boundary; log unexpected errors with `exc_info=True`. |
| **N01 — non-English title script stripping** | Removing `sup`/`sub`/`inf` for French/German/Spanish titles loses meaningful markup. Whether ANI permits it is unknown without a schema. | Get an authoritative schema, then preserve scripts by default or document the loss; add Latin-formula and CJK-footnote fixtures. |
| **C11 — schema readiness** | Requires the publisher’s licensed ANI/CAR XSD; it cannot be invented. | Obtain/pin the schema with checksum, then add CI valid/invalid fixtures. Until then validated export remains user-supplied and provisional claims are explicit. |

### Medium priority

- **R01 — no real-paper accuracy corpus.** Synthetic tests cannot prove extraction/layout accuracy. Build a licensed, reviewed corpus with block/role/reading-order labels.
- **R02 — unmeasured memory/RSS and large-document behavior.** Re-run `.bench/audit_bench.py` on 50–500-page papers with `psutil`.
- **R03 — no fuzzing of `.jatsdraft`/revision records.** Add malformed/truncated/duplicate-record tests.
- **R04 — live GROBID/LLM behavior unverified.** Add recorded-fixture contract tests; keep live calls opt-in.
- **R05 — no CVE scan.** Run `pip-audit`/OSV with a documented exception process.
- **R07 — document text in provider error strings.** Redaction now covers keys, not document content. Audit log sites; add a sentinel test.
- **R08 — workspace dirty-state matrix.** Add table-driven load/edit/save/open/close/replace tests.
- **R09 — title ordering and `original="y"` semantics.** Validate against a real ANI schema.

### Lower priority

- **Architecture (Phase 5):** `main_window.py` is still 7,535 lines and owns orchestration. Extract a conversion/session service incrementally, starting with one session-reset object to replace the ad-hoc reset lists behind C01. Preserve shortcuts, signals, and conversion behavior.
- **Packaging:** `requirements.txt` remains the runtime source of truth while `pyproject.toml` mirrors core dependencies; keep them in sync or make `pyproject.toml` authoritative. Docling is optional but still installed by `requirements.txt`.
- **Docs:** `docs/audit/dependency_versions.txt` is a dated inventory, not a lockfile.

## Verification limits

- No authoritative schema validation was performed, so no XML is certified `SCHEMA_VALID` against a publisher schema.
- No live network service was called; the test fixture denies external sockets.
- No visual/manual GUI interaction was performed; GUI behavior is covered by headless tests only.
- No memory-leak, stress, or crash-recovery campaign was run.
- The performance report covers a 12-page internal PDF, not a representative corpus.

## Final assessment

The application is stable at this commit: **609 tests pass**, the previously red P1 lifecycle/CLI defects are closed, XML validation/revision protections are intact, and the test gate can now detect inline-whitespace regressions and fail fast on hangs.

The blocking gap for production XML delivery is **not code quality**; it is the absence of an authoritative ANI/CAR schema (C11) and a reviewed real-paper accuracy corpus (R01). Until those exist, the honest position is: **draft output is well-formed and semantically checked; publisher validity is unverified.**

Recommended order for the next approved change set: **C08 → C10 → N01 decision → C11 schema → corpus (R01) → incremental architecture extraction**.
