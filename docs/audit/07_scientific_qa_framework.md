# Scientific QA implementation ? 2026-11-11

The latest remediation report remains authoritative. This implementation adds an
independent offline evaluator and does not change production extraction,
classification, generation, correction, export, or GUI behavior. No Classify GUI
action was added. No commit or push was performed.

## Verification

- Baseline: `python -m pytest -q -p no:cacheprovider --basetemp .test-alt-review-qa-start`
  ? **634 passed in 24.16 seconds**.
- Final: `python -m pytest -q -p no:cacheprovider --basetemp .test-alt-review-qa-final`
  ? **733 passed in 47.01 seconds**, including **99 new deterministic QA tests**.
- Tests ran with the Windows permissions required for pytest temporary files.
- Hash comparison: **109 pre-existing Python production/test files unchanged**
  from the start of this assignment. Earlier uncommitted remediation changes and
  unrelated user files were preserved.
- Python syntax checks passed for the new QA package/tests; `git diff --check`
  passed. No live provider calls or new AI models were used.
- CLI examples: damaged synthetic evaluation returned 1 (coverage gate failure),
  exact synthetic evaluation returned 0, improvement comparison returned 0,
  regression comparison returned 1.

## Delivered capabilities

Hash-sealed versioned corpus releases, review approvals bound to reference hashes,
secure local readers, JATS/ANI adapters, deterministic conservative alignment,
reviewed split/merge and entity correspondences, strict/normalized text and token
error rates, semantic-role confusion and F1, reading-order accuracy with coverage,
author-affiliation edge metrics, exact/character-level script metrics,
mathematical-symbol diagnostics, ordered XML differences, critical categories,
per-article/aggregate/group reports, coverage gates, JSON/CSV output, compatible
run comparison, and separately supplied conversion performance records.

See `docs/scientific_qa.md` for all contracts, CLI commands, metric definitions,
review workflow and operating limits. Executable synthetic inputs are in
`tests/fixtures/qa`; generated reports are in `docs/qa_examples`.

## Known limitations and interpretation

- No real manually reviewed PDF/XML corpus was supplied. **No real-world
  scientific conversion accuracy is claimed.** Synthetic tests prove evaluator
  arithmetic and behavior only.
- Known JATS/ANI subsets are mapped; unknown fields remain coverage gaps.
  Complex tables, scanned/image-only formulas, layout geometry and algebraic
  equivalence are not fully evaluated. ANI publisher acceptance still needs an
  authoritative schema; semantic accuracy and schema validation are independent.
- Alignment is conservative, role-blind and deterministic, not a semantic model.
  Repeated/ambiguous text or names require reviewed correspondence annotations.
  Split/merge grouping requires explicit review; no production XML is repaired.
- Reading-order scores require reviewed order annotations. Without them, scores
  are unavailable. Unicode offsets are code points, not rendered glyph positions.
- Mathematical detection includes Unicode mathematical symbols and Greek letters
  plus supported/annotated formulas; Greek prose can produce conservative flags.
- Critical counts have different units and overlap. No universal composite score
  or scientific acceptance threshold is invented. CLI evaluation success means
  completed evaluation with coverage gates met, not absence of scientific errors.
- Review identities and converter build provenance are supplied records, not
  authenticated signatures. Immutable storage/version registries across corpus
  directories remain the owner's responsibility.
- Conversion time/RSS are accepted only from pinned external measurements; this
  evaluator does not measure conversion performance. Hardware/measurement
  comparability remains the benchmark owner's responsibility.
- JSON/XML size and alignment limits fail explicitly. Reports include document
  excerpts and inherit the corpus's confidentiality requirements.

## Files added or changed by this assignment

Only `README.md` was edited among pre-existing files. Everything below other than
that README is new. Pre-existing remediation modifications are not attributed to
this assignment.

- `README.md`
- `benchmarks/corpus/README.md`
- `benchmarks/corpus/manifest.template.json`
- `benchmarks/corpus/predictions.template.json`
- `docs/audit/07_scientific_qa_framework.md`
- `docs/qa_examples/README.md`
- `docs/qa_examples/improvement/comparison.csv`
- `docs/qa_examples/improvement/comparison.json`
- `docs/qa_examples/regression/comparison.csv`
- `docs/qa_examples/regression/comparison.json`
- `docs/qa_examples/synthetic-bad/aggregate.csv`
- `docs/qa_examples/synthetic-bad/articles.csv`
- `docs/qa_examples/synthetic-bad/differences.csv`
- `docs/qa_examples/synthetic-bad/report.json`
- `docs/qa_examples/synthetic-good/aggregate.csv`
- `docs/qa_examples/synthetic-good/articles.csv`
- `docs/qa_examples/synthetic-good/differences.csv`
- `docs/qa_examples/synthetic-good/report.json`
- `docs/scientific_qa.md`
- `pdf_to_jats/qa/__init__.py`
- `pdf_to_jats/qa/__main__.py`
- `pdf_to_jats/qa/adapters/__init__.py`
- `pdf_to_jats/qa/adapters/ani.py`
- `pdf_to_jats/qa/adapters/base.py`
- `pdf_to_jats/qa/adapters/jats.py`
- `pdf_to_jats/qa/alignment.py`
- `pdf_to_jats/qa/cli.py`
- `pdf_to_jats/qa/comparison.py`
- `pdf_to_jats/qa/corpus.py`
- `pdf_to_jats/qa/evaluator.py`
- `pdf_to_jats/qa/metrics.py`
- `pdf_to_jats/qa/models.py`
- `pdf_to_jats/qa/normalization.py`
- `pdf_to_jats/qa/readers.py`
- `pdf_to_jats/qa/reporting.py`
- `tests/fixtures/qa/README.md`
- `tests/fixtures/qa/annotations.json`
- `tests/fixtures/qa/candidate.jats.xml`
- `tests/fixtures/qa/manifest.draft.json`
- `tests/fixtures/qa/predictions.bad.json`
- `tests/fixtures/qa/predictions.good.json`
- `tests/fixtures/qa/reference.ani.xml`
- `tests/fixtures/qa/reference.jats.xml`
- `tests/fixtures/qa/synthetic.pdf`
- `tests/fixtures/qa/synthetic.v1.json`
- `tests/qa/test_adapters.py`
- `tests/qa/test_framework.py`
- `tests/qa/test_metrics.py`
