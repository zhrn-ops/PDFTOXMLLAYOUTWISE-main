# Scientific PDF-to-XML quality assurance

The independent `pdf_to_jats.qa` package evaluates **existing candidate XML**
against approved reference XML. It never invokes conversion, imports the GUI,
calls a provider, changes classifications, or edits input XML. The removed
Classify GUI action remains removed. Only optional schema checks reuse the
existing read-only XML validator.

There is **no real reviewed scientific corpus bundled with this framework**.
Synthetic fixtures and example reports demonstrate evaluator behavior only.

## Install and command line

Use the existing project environment (Python 3.11+ and lxml). No additional
models, network services, or runtime dependencies are needed.

```powershell
python -m pdf_to_jats.qa --help
python -m pdf_to_jats.qa freeze corpus/manifest.draft.json corpus/corpus.v1.json
python -m pdf_to_jats.qa evaluate --manifest corpus/corpus.v1.json --predictions corpus/predictions.json --output output/qa/run-001 --formats json,csv
python -m pdf_to_jats.qa compare output/qa/run-001/report.json output/qa/run-002/report.json --output output/qa/comparison-001
```

`freeze SOURCE DESTINATION` validates the manifest, checks artifact hashes, and
publishes a canonical hash-sealed release beside the source. Destination files
cannot be overwritten. A corpus ID/version already published in the directory
cannot be reused; increment the version. Do not move artifacts independently of
the release. Keep the release and artifact hashes under version control or an
immutable artifact store. Hashes detect modification; they do not authenticate a
reviewer's identity or protect against malicious replacement of both data and
hashes. Cross-directory release registries must be enforced by the corpus owner.

`evaluate` requires `--manifest`, `--predictions`, and a **new** `--output`
directory. `--formats` accepts `json`, `csv`, or `json,csv` (default). JSON is
required for later comparison. Each article is evaluated independently; a bad
input does not prevent other articles from being evaluated. Missing candidate
entries count as failures and all supported reference content counts as missing.
Malformed/untrusted inputs have no fabricated accuracy score.

`compare BEFORE AFTER --output DIRECTORY` produces JSON and CSV changes for
every numeric metric, each article, and every critical-error category. Positive
and negative changes are interpreted using metric direction; denominator/count
changes are neutral unless they have a defined direction. Missing/undefined
values are `not_comparable`, not zero. A formerly evaluated article becoming an
input failure, or a coverage gate becoming false, is a regression.

Exit codes:

| Command | 0 | 1 | 2 |
|---|---|---|---|
| freeze | New release created | — | Invalid input or existing release |
| evaluate | All articles evaluated and coverage gates met | Article failures or insufficient coverage | Invalid run contract/output error |
| compare | Compatible comparison with no detected regression | Regression detected | Invalid/incompatible reports or output error |

Passing coverage is **not** a claim of error-free output. Critical errors and
accuracy measurements must still be reviewed. This version does not impose an
arbitrary composite score or universal scientific acceptance threshold.

## Data contracts and reproducibility

Start with `benchmarks/corpus/manifest.template.json` and
`predictions.template.json`. Placeholder hashes must be replaced. Compute hashes
with `Get-FileHash -Algorithm SHA256` (store lowercase hexadecimal) or Python's
`hashlib.sha256(path.read_bytes()).hexdigest()`.

Every corpus release records `contract_version: 1`, `corpus_id`, immutable
`manifest_version`, `kind` (`reviewed` or `synthetic`), `coverage_threshold`, and
article records. Each article has a unique `id`, PDF and reference artifact
records `{path, sha256}`, `format` (`JATS` or `ANI`), descriptive `scope`, and a
review record. Optional `language` and `category` drive report breakdowns.
Reference and candidate paths are relative to their own manifest directory.
Absolute paths, URLs, path traversal and resolved symlink escapes are rejected.

The predictions file separately records the converter's `build_id`, `commit`,
and boolean `dirty` state. Dirty builds additionally require `source_sha256`
over the converter source snapshot. These identify the build that **actually
produced** candidate XML, not the evaluator's current Git checkout. The framework
records supplied provenance; it cannot prove a caller's build claim.

Each prediction has a matching article ID, format and pinned XML artifact. Extra
or duplicate prediction IDs are rejected. Changing candidate outputs does not
change the frozen reference corpus. Multi-article ANI files require a `selector`
such as `//ani:unit[1]`. A selector must identify one element. JATS selectors may
select an `article` in a collection; namespace handling is deliberately explicit.
Use separate entries for every article and document source page ranges in scope.

Reports include corpus-release hash, candidate hashes, predictions hash,
evaluator version, a hash of evaluator Python sources, normalization policy,
converter identity, and a content-addressed `run_id`. Runs are deterministic for
identical inputs and evaluator source; no runtime timestamp contaminates scores.
Comparison verifies report integrity and refuses different corpus releases,
article sets, evaluator source/version, or normalization policy. Re-evaluate
both converter outputs with the same evaluator to compare after a framework
upgrade. Never combine incompatible scores.

## Reference review workflow

1. Obtain legally usable PDFs and record language, layout, discipline and scope.
   Include multilingual, multicolumn, table-heavy, mathematical and scanned
   examples as appropriate. A PDF extractor's output is not a reference oracle.
2. Prepare reference XML independently or manually correct a candidate while
   checking every in-scope field against the PDF. Avoid inheriting unnoticed
   converter omissions. Preserve scientific scripts, symbols and relationships.
3. Set `review.status` to `draft`, then `in_review`. Record `reference_version`.
   These states may be frozen for diagnostics but cannot produce accuracy scores.
4. Have an identified reviewer check content, article boundaries, order, author
   identities, affiliations, scripts and formulas. A second reviewer should
   adjudicate ambiguous source content. Record each ambiguity as an object with
   `question`, `resolution`, `resolved_by`, and ISO `date` (`YYYY-MM-DD`).
5. Approval requires `status: approved`, nonempty `reviewer`, ISO `date`,
   `reference_version`, and `reference_sha256` equal to the approved XML hash.
   Every recorded ambiguity must have a resolution. Review dates and identities
   are provenance supplied by the corpus owner, not authenticated signatures.
6. Hash annotations and artifacts, freeze a new corpus version, and retain old
   versions. Any reference, annotation, threshold or scope change requires a new
   release. Do not edit the frozen file or silently replace a reference.

Reference annotations are optional JSON pinned by the article's `annotations`
artifact record. Example:

```json
{
  "xml_order_reviewed": true,
  "order_pairs": [["/article/body/p[1]", "/article/body/p[2]"]]
}
```

Explicit `order_pairs` take precedence and describe a partial order. Duplicate,
self, or cyclic constraints are rejected. Otherwise `xml_order_reviewed: true`
approves XML unit order as the intended reading order. Without either declaration,
reading-order accuracy is unavailable. XML order alone does not prove PDF order.
Paths are lxml absolute element paths exposed in report differences; namespace
prefixes in pinned input documents remain part of annotation keys.

Ambiguous matching can be resolved with a prediction's pinned `alignment` JSON:

```json
{
  "reference_sha256": "64-lowercase-hex-characters",
  "candidate_sha256": "64-lowercase-hex-characters",
  "reviewer": "reviewer-id",
  "date": "2026-11-11",
  "matches": [["/article/body/p[1]", "/article/body/p[2]"]],
  "entities": {"authors": [["a1", "author9"]], "affiliations": [["f1", "aff2"]]}
}
```

For paragraph splits/merges, put `reference_groups` in reference annotations or
`candidate_groups` in the reviewed alignment. Each group has a new unique `key`,
an ordered `units` list of contiguous paths, and `separator` (`" "`, `""`, or
`"\n"`). Group members must have the same role and section. Text and script
offsets are combined explicitly. Use the group key in `matches`/`order_pairs`.
Grouping is a declared review decision, not an automatic repair of candidate XML.

Reviewed formula text outside recognized formula elements can be annotated with
`math_spans` in reference annotations and `candidate_math_spans` in a reviewed
alignment. Each entry is `{ "unit": "/article/body/p", "start": 0, "end": 3 }`;
offsets are half-open Unicode code-point offsets in the extracted unit text.
These spans include ordinary letters/digits in mathematical corruption checks.

## Metrics and coverage

| Measurement | Definition and limits |
|---|---|
| Character error rate | Exact Levenshtein `(substitutions + deletions + insertions) / reference code points`, pooled over aligned units plus missing/added units. Can exceed 1 when additions dominate. |
| Normalized character error | Same computation after NFC and whitespace collapse, separately labeled. Strict scores retain all text differences. No NFKC, case folding, diacritic removal or symbol folding. |
| Token error rate | Levenshtein over whitespace-delimited tokens; not language-specific linguistic segmentation. |
| Reading order | Concordant matched pairs / evaluated pairs; coverage is evaluated / reviewed expected pairs. Missing units never become correct pairs. |
| Semantic roles | Per-role TP/FP/FN, precision, recall, F1 and confusion counts. Unknown/missing roles are visible. Unit matching is role-blind. |
| Author–affiliation links | Edge precision/recall/F1 after unique exact normalized entity-name matching or explicit reviewed correspondences. Local IDs need not match. Duplicate-name ambiguities remain unresolved. Entity coverage is separate. |
| Scripts | Exact aligned span/type precision/recall/F1, separately for superscript and subscript; character-level script precision/recall/F1. A type flip is both FP and FN. Text-changing errors cannot receive exact script credit. |
| Mathematical symbols | Substitutions/deletions/additions involving Unicode mathematical symbols, Greek characters or characters in recognized formula spans. Reports confusion excerpts and errors/reference symbols. No algebraic-equivalence claim; Greek prose may also be flagged. |
| Structure | Ordered same-format element, attribute, text/tail, comment and PI differences. Expanded namespace names make prefix differences irrelevant. Indentation differences remain visible. Cross-format raw structures are marked incomparable. |
| Content ledger | Localized edits, missing/added units, position changes, script changes, hierarchy changes, affiliation changes and unsupported content. Position-change diagnostics alone are not reading-order errors. |

Alignment first uses reviewed one-to-one matches, then reciprocal unique
text-similarity matches at threshold 0.55. Ties/repeated ambiguous text remain
unmatched. This is conservative deterministic alignment, not a semantic model.
Automatic split/merge recovery is intentionally absent; use reviewed grouping.
Offsets use Unicode code points, not rendered glyph positions or grapheme clusters.

Text coverage is `matched supported reference characters / (all supported
reference characters + unsupported reference text characters)`. Matched means
successfully aligned and evaluated, **not correct**. Unmatched supported text
is scored as deletion; unsupported text is unscored and lowers coverage.
Author/affiliation metadata is evaluated as entities/edges rather than duplicated
into prose character totals. Reports expose unsupported text and alignment
coverage; neither is treated as correct. Empty denominators yield JSON `null`.

Default minimum text coverage is 0.95. A manifest can additionally require:

```json
"coverage_thresholds": {"authors": 1.0, "affiliations": 1.0, "reading_order": 0.95}
```

An unavailable required measurement fails its gate. Configure these only for
corpora whose scope includes those measurements. Accuracy scores remain visible
when coverage fails, but the run fails its coverage gate. Aggregates show unknown
denominators and article failures so a scored subset cannot masquerade as complete.

Critical categories are `missing_scientific_content` (deleted non-whitespace
characters from supported fields), `incorrect_author_affiliation` (missing plus
added edges), `corrupted_math_symbol` (symbol edit events), `lost_script` (missed
or wrong script spans), and `missing_section` (missing title, abstract unit or
section heading). Counts use different units and can overlap; do not sum them
into a severity score. Unsupported sections remain a coverage gap, not a claim
of successful section detection.

Aggregate reports pool numerator/denominator counts for micro rates, report
per-article macro text error rates with contributing-article counts, and pool
TP/FP/FN for F1. Nulls never contribute zero or perfect scores. Language/category
breakdowns use the same aggregation. Performance is excluded from these metrics.

## Adapter scope and schema checks

JATS support includes titles, abstract paragraphs, section headings/body
paragraphs, keywords, captions, reference content, contributor names, explicit
affiliation `xref` relationships, scripts and formula/MathML text. Supported JATS
namespaces are absent namespace or `http://jats.nlm.nih.gov`. Other namespace
profiles require an explicit adapter extension and tests.

ANI support covers the repository's ANI/common namespaces and generated
titletext, abstract/para, keyword, reference, author-group and affiliation fields.
Repeated ANI authors are reconciled by consistent `seq`. Group membership
supplies affiliation edges. Conflicting repeated identities are rejected.
Unrecognized metadata and extensions remain unsupported; publisher business
rules are not inferred. Tables, image-only equations, geometric PDF order,
complex alternative representations and full mathematical semantics are not
fully supported in this first version.

Optional `schema` records on reference/prediction entries contain `path`,
`sha256`, `format`, optional `name`, and `resources` (pinned dependency records).
All loaded XSD dependencies must be listed and hash-match. Existing validator
restrictions confine includes/imports to the selected schema folder and forbid
network retrieval. XML with a DOCTYPE or entity declarations is rejected by the
QA reader, even if another application accepts it; prepare a reviewed standalone
reference artifact rather than silently altering source XML during evaluation.

Schema results are **separate** from reference accuracy: `SCHEMA_VALID` only
describes the supplied schema check. Missing schemas are `SCHEMA_UNAVAILABLE`.
No authoritative ANI/CAR XSD is supplied, and no publisher-validity claim is made.

## Optional conversion performance

A prediction may point to a pinned `performance` JSON artifact:

```json
{
  "source": "external_conversion_benchmark",
  "pdf_sha256": "64-lowercase-hex-characters",
  "candidate_sha256": "64-lowercase-hex-characters",
  "converter": {"build_id": "release-123", "commit": "commit-id", "dirty": false},
  "measurement_method": "Isolated process; wall clock; process RSS sampled every 10 ms",
  "conversion_seconds": 1.25,
  "peak_rss_bytes": 104857600
}
```

Hashes and converter identity must match the evaluated artifacts. Measurements
must be finite and nonnegative; omitted measurements remain unavailable. State
sampling interval, process-tree inclusion, warm/cold conditions, machine and
dependency versions in the external record. Sampled RSS is not guaranteed exact
peak RSS. The evaluator does not run a converter or measure conversion time/RSS.
Performance values are per-article metadata, not scientific accuracy metrics.
Run comparison lists performance deltas only when both records have identical
measurement-method descriptions. It reports a separate
`performance_regression_detected` flag; performance does not change the
scientific-regression exit code. Matching descriptions do not prove identical
hardware or conditions, which the benchmark owner must verify.

## Outputs and synthetic examples

`report.json` contains provenance, per-article metrics, coverage, critical counts,
differences, schema results, optional performance and aggregate/group reports.
CSV output includes `articles.csv`, `aggregate.csv`, and `differences.csv`.
Nested structural differences remain in JSON. CSV cells beginning with formula
characters are escaped for spreadsheet safety; JSON retains original text.
Reports contain document excerpts, so handle them with the corpus's privacy rules.

Run the supplied demonstration without freezing it again:

```powershell
python -m pdf_to_jats.qa evaluate --manifest tests/fixtures/qa/synthetic.v1.json --predictions tests/fixtures/qa/predictions.bad.json --output output/qa/synthetic-bad
python -m pdf_to_jats.qa evaluate --manifest tests/fixtures/qa/synthetic.v1.json --predictions tests/fixtures/qa/predictions.good.json --output output/qa/synthetic-good
python -m pdf_to_jats.qa compare output/qa/synthetic-bad/report.json output/qa/synthetic-good/report.json --output output/qa/synthetic-improvement
```

The bad run intentionally fails coverage. Reversing comparison direction detects
regressions. Checked-in generated examples in `docs/qa_examples/` are explicitly
synthetic and are not evidence of scientific conversion accuracy.

## Tests and operational limits

```powershell
python -m pytest tests/qa -q
python -m pytest -q
```

The inherited test network guard remains active. Deterministic tests use tiny
synthetic inputs and hand-calculated expected values; no live APIs are required.
XML/JSON input limit is 32 MiB; hashed artifacts are bounded at 256 MiB, with XML
still subject to its smaller parser limit. Character alignment is bounded at
4 million edit cells per unequal unit pair and unit matching at 250,000 pairs.
Exceeding a limit fails the article explicitly instead of returning partial
accuracy. Use reviewed unit boundaries for long content. Coverage and alignment
limits, namespace support, ambiguous names and unreviewed reading order must
accompany any future real-corpus accuracy claim.
