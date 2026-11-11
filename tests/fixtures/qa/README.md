# Synthetic QA fixtures

All names, institutions, text, XML and the accompanying PDF are fabricated
solely to test the evaluator. They are not a reference corpus for real scientific
conversion accuracy. Approval identities in sample manifests mean fixture
verification only, not human review of a real article.

`reference.jats.xml` contains known scripts, symbols, sections and affiliations.
`candidate.jats.xml` deliberately loses two scripts, changes two mathematical
symbols, drops a section heading and changes an affiliation relationship.
`reference.ani.xml` exercises the repository's known ANI subset. None of these
fixtures claims publisher-schema validity.

`synthetic.pdf` visually labels its content as synthetic. Its linkage to the XML
is only for exercising input provenance. `synthetic.v1.json` is a frozen demo
manifest. `predictions.bad.json` and `predictions.good.json` compare fabricated
candidate variants. Generated examples live in `docs/qa_examples/`.
