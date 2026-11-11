# Reviewed corpus workspace

No real reviewed PDF/XML corpus is included. The templates contain deliberate
placeholders and cannot be evaluated until populated with real artifacts and
review records. See [the QA guide](../../docs/scientific_qa.md).

Keep licensed source PDFs, reviewed references, annotations, schemas, and
candidate outputs beneath their respective manifest directory. Relative paths
cannot escape that directory. Do not commit copyrighted or confidential papers
without permission. Publicly distributable fixtures belong in a separately
identified corpus release.

The executable **synthetic demonstration**, including a PDF, frozen manifest,
JATS and ANI XML, and two candidate variants, is in `tests/fixtures/qa`. It tests
the evaluator only and supplies no real conversion-accuracy evidence.
