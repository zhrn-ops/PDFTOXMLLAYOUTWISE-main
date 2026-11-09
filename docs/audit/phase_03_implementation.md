# Phase 3 — implementation and verification

Date: 2026-11-09. Phase 3 was approved and implemented. Phases 4–8 have not started.

## Changes

| Files | Changes |
|---|---|
| `pdf_to_jats/core/jats_generator.py` | Resolved A06: Preserved trustworthy alphabetic and Greek subscript/superscript annotations (e.g. `Vmax`, `Km`, `kUA/L`, Greek letters) from manual, geometry, font flags, or domain lexicon sources at exact matching offsets, while strictly preventing stale-offset relocation to unrelated text. |
| `pdf_to_jats/core/xml_correction.py` | Resolved A02: Correct non-UTF-8 XML handling (ISO-8859-1, UTF-16) across `from_text`, `commit_raw`, undo/redo, and `save_copy`. Preserved immutable source bytes separately from saved baseline. Supported explicit UTF-8 and declared encoding exports. |
| `pdf_to_jats/gui/xml_correction_window.py` | Prevented stale validation pollution: Fresh extraction candidates do not inherit old validation or export records when revision fingerprint changes. Archived previous corrected drafts with complete provenance on regeneration acceptance. Retained existing regeneration review prompts. |
| `pdf_to_jats/gui/article_drafts.py` | Safeguarded workspace activation: Restoring drafts with unparsed raw edits properly marks `session.raw_valid = False` to prevent silent export of obsolete trees. |
| `pdf_to_jats/core/draft_workspace.py` | Enforced strict revision verification, schema resource provenance validation, and exact-content matching across history and draft records without encoding corruption. |
| `tests/test_xml_revision_integrity.py` (new) | 15 new regression tests covering regeneration archives, validation binding, alphabetic/Greek scripts, non-UTF-8 lifecycles, and malformed workspace recovery. |

## Defects addressed

- **A02:** Resolved across session opening, draft activation, undo/redo, workspace restoration, raw editor declaration changes, and UTF-8 exports. ISO-8859-1 and UTF-16 text with non-ASCII characters (`Café`, `α`, etc.) round-trip with zero mojibake and zero entity escaping.
- **A06:** Preserved accepted alphabetic and Greek subscript/superscript annotations in Title and Abstract (`<ce:inf>` and `<ce:sup>`), while ensuring that stale offset drift cannot relocate single letters to ordinary words.
- **R02:** Staged workspace validation guarantees that malformed JSON, corrupted revision base64, fingerprint mismatches, invalid bounding boxes (x2 < x1 or y2 < y1), and unparsed raw text cannot corrupt live workspace state or permit premature invalid export.
- **Stale Validation:** Fresh extractions no longer inherit validation results or export status from earlier revisions. Validation remains strictly bound to exact-byte SHA-256 fingerprints.

## Executed tests

Baseline test count: 488 passing.
New tests added: 15 passing in `tests/test_xml_revision_integrity.py`.
Total test count: **505 passed in 22.99 s; 0 failed, 0 errors, 0 skipped; no warnings reported**.
`python -m compileall -q pdf_to_jats tests` completed without errors.

## Remaining risks and next steps

- Stopping after Phase 3 as instructed. Phase 4 (test engineering and CI) and subsequent phases require separate approval.
- Authoritative publisher ANI/CAR schemas remain external assets to be provided by the receiving team; until supplied, publisher validation status truthfully reports unavailable.
