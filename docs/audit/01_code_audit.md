# Phase 1 — code audit

Date: 2026-11-09. Production logic unchanged. Severity: P0 critical widespread loss/security; P1 material correctness/data-integrity or broken workflow; P2 reliability/engineering gap; P3 minor maintainability. No P0 was confirmed. Findings below distinguish executed reproductions from static evidence and unverified risks. Paths are relative to the repository root.

## Confirmed findings

### A01 — P1: missing schema can look like successful validation

- **Location:** `pdf_to_jats/core/validator.py:32`, `Validator.validate`; `gui/xml_correction_window.py:1536`, `validate` / `save_copy`; `core/xml_correction.py:1059`, `validate`.
- **Root cause:** the legacy validator has no missing-schema branch. Correction validation reports schema unavailability as informational; the GUI derives `Valid` solely from error/warning counts. No structured status or enforced publisher-valid export exists. The legacy default is a JATS XSD although generation emits ANI.
- **Reproduce (executed):** validate `<article><article-title>T</article-title><contrib><name><surname>Doe</surname></name></contrib><abstract>A</abstract></article>` with an absent schema path. Legacy result is `[]`. Correction result is two info messages: well-formed and schema unavailable; the GUI status rule produces `Valid`.
- **Expected / actual:** explicitly distinguish well-formed, schema unavailable, semantic issues and publisher-valid status / no legacy error and ambiguous GUI success. Draft export itself is useful and is not inherently a defect.
- **Impact:** users or callers can mistake provisional XML for validated delivery; dropping a JATS XSD into the default path cannot certify ANI.
- **Correction:** typed independent validation dimensions, explicit profile selection, secure local schema resolution, draft vs validated export. Preserve the current draft capability with clear labeling and a migration explanation.
- **Regression:** absent/malformed schema, malformed XML, valid/invalid miniature test schema, wrong profile, ANI/JATS namespaces, unknown nodes, draft/validated policies and stale validation after edits. Test schemas must never be represented as publisher schemas.

### A02 — P1: non-UTF-8 XML is corrupted when a draft is reconstructed

- **Location:** `core/xml_correction.py:64`, `XmlDocumentSession.from_text`; `gui/article_drafts.py:activate_draft`; `gui/xml_correction_window.py:_move_history` and regeneration comparisons.
- **Root cause:** `xml_text()` returns Unicode with its original encoding declaration. `from_text()` encodes it as UTF-8 without updating the declaration, so lxml decodes those bytes using the old encoding.
- **Reproduce (executed):** create a session from ISO-8859-1 bytes containing title `Café`; call `from_text(session.xml_text(), path)`, as activation does. Title changes from `Caf\xe9` to `Caf\xc3\xa9`.
- **Expected / actual:** exact character preservation across activation/history/workspace reload / mojibake without a parse error.
- **Impact:** silent corruption of scientific symbols and contributor names. Generated UTF-8 documents do not trigger this particular input case.
- **Correction:** use an explicit Unicode/bytes boundary, normalize declarations consistently, preserve original source bytes separately, and handle encoding changes in raw commits.
- **Regression:** ISO-8859-1 and UTF-16 source open, activation, undo/redo, save/reopen, raw declaration edits, and UTF-8 export; assert Unicode content and markup, not just parse success.

### A03 — P1: serialization injects whitespace into inline scientific content

- **Location:** `core/xml_correction.py:1040`, `XmlDocumentSession.xml_text`, nested `separate_elements`.
- **Root cause:** absence of non-whitespace direct text/tails is treated as proof that a parent has element-only content. Inline children can contain all meaningful text; their adjacency remains meaningful.
- **Reproduce (executed):** serialize `<article><p><italic>H</italic><sub>2</sub><italic>O</italic></p></article>`. Paragraph itertext changes from `H2O` to `\nH\n2\nO\n`. `<italic>A</italic> <italic>B</italic>` likewise changes `A B` to `\nA\nB\n`.
- **Expected / actual:** serialization preserves inline text/tail content / new text nodes appear without any user edit.
- **Impact:** text consumers can interpret chemical formulas or mathematical tokens differently; raw and exported revisions differ from accepted content.
- **Correction:** avoid mutation for pretty printing, or restrict indentation to known element-only containers with inherited `xml:space` handling.
- **Regression:** adjacent styled chemical tokens, whitespace-only tails, MathML, comments/PIs, unknown elements and `xml:space`; compare ordered text/tails without whitespace normalization hiding changes.

### A04 — P1: generator file writes are not atomic

- **Location:** `core/jats_generator.py:31`, `JATSGenerator.generate`; consumers in `gui/main_window.py:run_auto_pipeline`, `_export_segment_document`, `_export_article_xml`.
- **Root cause:** generator uses `Path.write_bytes` directly. Legacy callers validate after writing and generally log XML errors rather than rolling back. Correction `save_copy` already uses an atomic write and must retain it.
- **Reproduce (executed with an audit-owned file and injected writer):** prefill a destination, allow the first ten bytes to be written, then raise `OSError('simulated disk full')`. Destination becomes `b'<?xml vers'` and the previous bytes are gone.
- **Expected / actual:** failure preserves prior destination and leaves no final partial export / truncated destination remains.
- **Impact:** direct API/legacy export callers can damage existing output or leave an apparently deliverable partial file. Some UI callers choose a unique filename; this reduces overwrite exposure, not partial-file exposure.
- **Correction:** build and evaluate bytes before publication, share a tested atomic writer, retain draft vs validated policy and explicit overwrite decisions.
- **Regression:** serialization failure, short/interrupted write, replace failure, existing and new targets, permission failures, and preservation of original source XML.

### A05 — P1: batch conversion calls a removed loader argument

- **Location:** `cli.py:61`, `Converter.convert`, line 81; `gui/main_window.py:6724`, `_load_pdf_path`.
- **Root cause:** CLI still calls `_load_pdf_path(..., wait=True)`; loader now accepts only `path` and returns immediately after starting a QThread. `cli.main` does not catch TypeError.
- **Reproduce (executed API call):** `MainWindow._load_pdf_path(None, 'dummy.pdf', wait=True)` raises `TypeError: ... unexpected keyword argument 'wait'` before any PDF or service work.
- **Expected / actual:** CLI waits for extraction and converts / aborts at argument binding. A live full CLI conversion was unnecessary to reproduce this mismatch and was not attempted.
- **Impact:** documented batch entry is broken for real inputs. Merely removing `wait=True` is insufficient: completion/event handling and the manual article-start gate also need a defined unattended workflow.
- **Correction:** shared conversion orchestration with explicit completion/error contracts; initially bridge current asynchronous loading safely, without hidden dialogs or invented article boundaries.
- **Regression:** real synthetic PDF through CLI with services mocked, nonzero failure exits, multiple documents, duplicate stems, article eligibility, and no success report for zero unintended outputs.

### A06 — P1: accepted alphabetic script annotations are dropped

- **Location:** `core/jats_generator.py:504`, `JATSGenerator._append_scripted_text`.
- **Root cause:** expected script text is restricted to digits and charges, even when a valid supplied run is marked as geometry-derived and its offsets exactly match.
- **Reproduce (executed):** accepted body paragraph `xn`, with `{'start': 1, 'end': 2, 'type': 'sub', 'text': 'n', 'source': 'geometry'}`. Generated XML contains zero `ce:inf` elements.
- **Expected / actual:** preserve trustworthy accepted `x` subscript `n` / output becomes ordinary `xn`. This proves loss at the generator boundary; it does not establish how frequently real PDFs create this run.
- **Impact:** alphabetic variables, symbolic superscripts and scientific indices lose meaning.
- **Correction:** distinguish untrusted inferred/stale runs from explicit or reliable matching annotations; do not simply remove all stale-offset safeguards.
- **Regression:** alphabetic and Greek indices, numeric charges, ordinary-text false positives, overlapping runs and stale offsets; verify both content and semantic markup.

### A07 — P2: selection classification blocks the GUI thread

- **Location:** `gui/main_window.py:5274`, `classify_selected_blocks`, especially calls at 5336/5340; `_auto_classify` at 773.
- **Evidence:** static call chain: GUI slot makes two synchronous `PrimaryLLMClient.classify` calls; clients use blocking urllib, timeout waits and OpenRouter retry sleeps. This is separate from the correctly threaded Finish Article path.
- **Reproduce:** substitute a deliberately slow mocked client and invoke the selection action while a QTimer measures event-loop progress. This responsiveness experiment was not run; the synchronous network call path is confirmed, its real latency is unmeasured.
- **Expected / actual:** responsive UI with cancellable work / event handler remains blocked until requests return.
- **Impact:** UI stalls can last through local timeout plus remote retries.
- **Correction:** reuse a generation-aware job coordinator with queued completion and cancellation; preserve local heuristic fallback and manual roles.
- **Regression:** delayed mocked services, cancellation, document replacement, late responses and exception recovery while a Qt timer remains active.

### A08 — P2: secrets are persisted as plaintext; error messages may contain content

- **Location:** `utils/config.py:55`, `save_openrouter_settings`; `llm/openrouter_client.py:_classify_with_model`; `core/grobid_client.py:_parse`.
- **Evidence / reproduction:** source writes the `api_key` field into `output/openrouter_settings.json`. Use a dummy key to observe the behavior; no actual settings/secret file was read. OpenRouter exceptions include raw provider response detail; GROBID empty-response errors include source text.
- **Expected / actual:** explicit credential storage policy and redacted diagnostic boundaries / plaintext file and potentially sensitive error payloads. This is confirmed storage behavior and a disclosure risk, **not evidence of an actual leak**.
- **Impact:** local backups/shared folders/logging may expose keys or document content; `output/` is ignored but filesystem confidentiality is not established.
- **Correction:** environment/OS credential storage, explicit migration choice, bounded redacted errors, atomic settings writes.
- **Regression:** dummy secrets never appear in persisted ordinary settings or logged exceptions; malformed settings and permission failures remain recoverable.

### A09 — P2: baseline reproducibility and repository hygiene gaps

- **Location:** root `.gitignore`, `requirements.txt`, `run.ps1`, `run.bat`, tracked `node_modules/` and `__pycache__/`; absent root README, pytest configuration, Python package metadata and `.github/workflows`.
- **Root cause:** only output/.env ignored, broad runtime ranges, optional Docling in the main install set, no declared test dependencies or Python support matrix. Startup preference points to a machine-specific environment.
- **Reproduce (executed):** `git ls-files` counts 182 bytecode files and 2,565 dependency files; compile/tests modify tracked bytecode. Plain `python -m pytest -q` traverses an inaccessible scratch directory. No `pip check` conflicts were found.
- **Expected / actual:** clean checkout installs and tests predictably / environmental drift and test-discovery/access obstacles. Access restrictions themselves are environment failures, not production code bugs.
- **Correction:** documented Python matrix, test/runtime/optional dependency sets, per-platform lock strategy, scoped pytest discovery and CI; untrack generated assets deliberately after verifying ownership/use.
- **Regression:** fresh environment install, headless suite, launch smoke test from paths containing spaces, and clean-tree verification after tests. No dependency removal during audit.

## Existing protections to preserve

- XML correction uses `resolve_entities=False`, `no_network=True`, `load_dtd=False`, `recover=False`; the external-entity regression passed. Source overwrite is forbidden; correction copies use same-directory temporary files, flush/fsync and replace.
- Generated/current/pending XML and archived corrections are already distinguished. Regeneration prompts and revision archives, draft switching, malformed raw text retention, workspace round-trip and validation invalidation have passing regressions. Do not rebuild these features as if absent.
- Comments present in input and unknown nodes are covered by tests. The raw editor intentionally refuses newly added comments; that is an existing tested policy, not an accidental deletion finding. Any change needs an explicit compatibility decision.
- Author linking retains ambiguity issues rather than inventing all-to-all links. Paragraph proposals are distinct from accepted body paragraphs. Current tests preserve numeric scripts, Unicode/RTL text, author order and article boundaries.
- PDF load and page raster callbacks reject stale generations. Viewer pages are materialized near the viewport and have an explicit cache target. These are not unbounded-cache findings.

## Unverified risks and remaining audit work

| ID / priority | Exact area, concern and next reproduction | Expected behavior / possible impact / proposed verification |
|---|---|---|
| R01 / P1 | `MainWindow.closeEvent` checks article-finish thread but not PDF load or viewer raster workers; no viewer close cleanup found | Subprocess test closing during blocked extraction/rasterization must exit safely and preserve draft data. Native lifetime crash is plausible but **not reproduced**; add shutdown/cancellation ownership before asserting a crash defect |
| R02 / P2 | `ArticleDrafts.open_drafts`, `decode_workflow`, `MainWindow.restore_workflow` incompletely validate nested workspace state and restore incrementally | Fuzz malformed version-1 records, missing state, invalid segment fields and unavailable PDFs. Expect actionable error and original workspace intact. Potential partial restoration; exact damaging case not reproduced |
| R03 / P2 | `Validator.validate` uses default etree parsers, unlike hardened correction/GROBID paths | Run entity/DTD/internal expansion fixtures for both lxml and fallback configurations; make parser policy explicit. Do **not** claim confirmed XXE merely from default parser use |
| R04 / P2 | `_ArticleFinishWorker` completion has no document-generation token; UI busy guards are relied upon | Attempt programmatic/new-document state changes during a mocked finish request. Expect old responses ignored. Stale result race is not established by normal UI tests |
| R05 / P2 | `_PageRasterWorker.run`, `_PdfLoadWorker.run`, `_extract_docling_structure` reopen PDFs/create converters and perform advisory extraction | Profile representative large PDFs before caching/concurrency changes. No demonstrated performance regression or memory leak. The 96 MiB cache accounting does not cover all label/overlay/in-flight raster allocations |
| R06 / P2 | `PDFExtractor._order_page_blocks`, `ParagraphReconstructor._columns`, `SemanticClassifier.classify_blocks`, `AuthorLinker.link_from_texts`, `InlineScriptDetector.detect` use geometry/lexical heuristics | Reviewed corpus must include varied page sizes, columns, line-break hyphens, equations, tables, multiple abstracts and multilingual names. Heuristic misclassification is a risk; no additional real-document accuracy defect quantified here |
| R07 / P2 | `PrimaryLLMClient.classify`, Ollama/OpenRouter/GROBID clients | Mock timeout, transport loss, non-object JSON, partial parsing and fallback failures. No common cancellation/error taxonomy; broad fallback catches can obscure programming failures. Production service reliability not tested live |
| R08 / P2 | Requirement ranges / transitive dependencies | No advisory database or vulnerability scan was performed. No claim that dependencies are vulnerability-free; perform a current, source-backed scan against the eventual supported lockfiles in Phase 8 |
| R09 / P3 | `MainWindow` 7,377 lines, private GUI methods used by CLI; `ArticleDrafts` mixin owns filesystem and domain state | Incrementally extract workflow, revision and job services after integrity regressions. Maintainability burden is confirmed; wholesale rewrite is not justified |

No optimization, security exploit claim, or scientific correction is justified solely by these unverified risks.
