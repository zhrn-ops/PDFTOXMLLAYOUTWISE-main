# Prioritized remediation plan

Date: 2026-11-09. Phases 0 and 1 are complete within the documented audit limits. All items below are proposals, not implemented changes. Stop at each major phase for approval as requested.

Update: Phase 2 was implemented (see [Phase 2 implementation report](phase_02_implementation.md)). Phase 3 was approved and implemented; see [Phase 3 implementation report](phase_03_implementation.md). The original plan below is retained for traceability. Phase 4 and later still require separate approval.

## Phase 2: validation and export safety (recommended next approval)

Affected files: `core/validator.py`, `core/xml_correction.py`, `core/jats_generator.py`, `gui/xml_correction_window.py`, relevant legacy export paths in `gui/main_window.py`, and focused new tests.

1. Introduce a shared typed validation result. Keep well-formedness (`WELL_FORMED`, `NOT_WELL_FORMED`), schema (`SCHEMA_VALID`, `SCHEMA_INVALID`, `SCHEMA_UNAVAILABLE`) and semantic issues independent. Include profile/schema identity and a fingerprint of the exact XML bytes evaluated. Missing schema must never produce schema-valid status.
2. Detect/select actual JATS vs ANI/CAR profiles; require trusted local complete schema resources for publisher validation. Ignore untrusted remote schemaLocation as an instruction to fetch. A small synthetic XSD is appropriate for tests only. Obtaining the receiving team's authoritative ANI schema/rules is necessary for real validated ANI delivery, but does not block implementing truthful unavailable status.
3. Explicitly retain draft export, show unresolved issues and publisher incompleteness, and add a separate strict validated export. The existing `Validate & Export` behavior is effectively provisional; migrate it visibly rather than silently making it strict or calling it publisher-valid.
4. Centralize byte preparation and atomic publication. Cover the direct generator/legacy export paths as well as correction copies (A04). Strict export evaluates exact bytes before replacement; draft export still rejects malformed XML. Preserve source protection and overwrite decisions.
5. Treat A03 serializer text mutation as a Phase 2 integrity prerequisite: validation/export must operate on the accepted text and markup, not a reformatted scientific token stream. Add encoding-safe byte boundaries from A02 where shared validation/export requires them; complete activation/history integration in Phase 3.

Acceptance: malformed XML cannot export; missing/wrong schemas cannot pass strict export; draft XML remains available with honest status; schema success is profile-specific; edits invalidate results; mixed-content text survives; injected failures preserve existing files. Run focused tests after each small change, then all 452 baseline tests plus additions.

## Phase 3: revision/content integrity

Affected files: `core/xml_correction.py`, `gui/article_drafts.py`, `gui/xml_correction_window.py`, `core/workflow_state.py`, selected MainWindow transitions, generator script handling and tests.

- Extend existing generated/current/pending/archive records; do not replace their proven regeneration prompts. Bind last validation to an immutable revision/profile and retain export provenance.
- Resolve A02 across activation, undo/redo, JSON workspace restore and non-UTF-8 declarations. Preserve immutable original source bytes separately from the mutable saved baseline.
- Resolve A06 by preserving trustworthy alphabetic script annotations without reintroducing stale-offset formatting errors. Review scientific fixtures with explicit expected text/markup.
- Validate workspace structure before changing live state; stage/commit restoration and retain recovery on failure (R02).
- Exercise every PDF review → finish → correction → edit → validate → export → reopen → regenerate transition, including conflicts, cancellation, invalid raw edits and switching articles. Retain existing comment policy unless a change is approved.

Acceptance: no silent correction loss or encoding drift; no stale schema result applied to a changed revision; archived corrections recoverable; unsupported content remains intact.

## Phase 4: test engineering and CI

- Preserve the current 38 modules. Add explicit unit/integration/GUI/schema/scientific/recovery/benchmark markers and controlled discovery; declare pytest and pytest-qt requirements.
- Add a network-denial fixture with mocked services, CLI end-to-end regressions for A05, interrupted I/O and subprocess shutdown tests for R01/R04.
- Create reviewed golden XML/PDF fixtures for multicolumn layouts, affiliation ambiguity, numeric/alphabetic scripts, symbols/formulas, hyphenation, multiple abstracts, namespaces, tables and atypical pages. Record fixture origin/rights and expected article scope.
- Structural comparisons must preserve text, tails, order and semantic markup. Canonicalization must not erase A03-like failures. Review golden changes rather than auto-accepting regeneration.
- Add GitHub Actions only after deciding supported Python/platform versions; begin with the verified dependency combination and Windows/offscreen Qt. A passing local suite does not prove hosted CI compatibility.

## Phase 5: small architecture changes

- Repair A05 using an explicit conversion workflow/completion contract. Do not merely delete `wait=True`: async loading, article-start policy and dialog-free batch errors need handling.
- Extract revision persistence and conversion/job coordination behind existing GUI methods. Keep Qt widgets out of new domain services. Move blocking selection classification (A07) to the shared job mechanism and add generation/cancellation handling.
- Preserve shortcuts, signals, slots, explicit article eligibility, heuristic fallbacks and draft behavior. Run workflow regression tests after each extraction; no giant MainWindow rewrite.

## Phase 6: measured performance

Deferred; no performance optimization approved or performed. Use a reviewed small/medium/large PDF corpus and fixed environment to measure PDF open, text extraction, rasterization, layout/paragraph reconstruction, classification, XML generation/validation, peak process memory and service latency separately. Record cold/warm runs and distribution, not a single test-suite duration. Inspect redundant PDF opens and raster allocations only after measurement. Never trade away content/markup for speed.

## Phase 7: recovery and observability

Establish typed PDF/extraction/classification/service/XML/filesystem/cancellation errors. Add bounded, redacted diagnostics, recoverable UI messages and shutdown ownership; test delayed completion, timeouts and partial failures with mocks. Address A08 without copying real secrets into reports or fixtures.

## Phase 8: dependencies and packaging

Document Python support and startup/install instructions; separate runtime, optional Docling and test dependencies; select reproducible per-platform locking. Review JavaScript dependency ownership before any removal. Improve ignore rules and intentionally untrack generated dependencies/bytecode without deleting user work. Verify startup with spaces in paths, clean install/imports and headless tests. Run a current vulnerability review; `pip check` is not one.

## Deliverable status

- Produced: `00_baseline_report.md`, `01_code_audit.md`, this plan, `03_test_results.md`, and inventory/environment evidence.
- `04_performance_report.md` awaits the approved measurement phase; no invented baseline numbers.
- `05_final_engineering_review.md` awaits implementation and final verification; this audit is not a production-readiness certification.
- No bugs fixed, production files changed, tests rewritten, CI added, or dependencies upgraded in Phases 0–1. Remaining technical debt is enumerated in the audit. Approve Phase 2 separately before implementation.
