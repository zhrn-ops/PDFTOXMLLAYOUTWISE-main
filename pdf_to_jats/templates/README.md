# CAR template reference

`Template_CAR.xml` is the user-supplied `Template_CAR.tbl`, preserved unchanged.
It is an XML template, not an authoritative schema. Empty elements and repeated
examples do not establish required fields or cardinalities.

The generator follows its major hierarchy and element order. Optional sections
are emitted only when data is supplied. Unit identifiers stay empty when absent
and are reported for review. Existing workflow defaults (`S300`, `new`, `cb`,
`ENG`, and the explicit `ABSN` fallback) are retained; the timestamp records
generation time. Numeric placeholder IDs and fabricated journal/title text are
no longer inserted.

Supported optional `Document.metadata` fields include:

- `pii`, `doi`, `ern`; `itemids` as `(value, idtype)` pairs.
- `keywords` as strings; `related_item` with `type`, `pii`, and/or `doi`.
- `grants` with `grant_id`, `acronym`, `agency`, and `agency_id`; `grant_text`.
- `publisher_copyright`, `publisher_name`, `website`.
- `journal_title`, `journal_abbrev`, `volume_title`, `issue_title`, `issn`, `srcid`.
- `isbns` with `value` and optional `type` and `length`.
- Existing `volume`, `issue`, `pages`, `publication_year`, `publication_date`;
  `article_number`, `conference_event_id`, and `report_number`.

`Document.references` is preserved as unparsed citation text under
`tail/bibliography/reference`, without inferring bibliographic details.

Supported extensions absent from this blank template remain intact to avoid
losing existing work: `ce:sup`/`ce:inf`, accepted body paragraphs, article-number
workflow identifiers, and volume/issue metadata. Issue numbers use `iss-first`,
not the supplement element.

The sample-inferred XSD is intentionally not installed as an authoritative
validation gate. The correction workspace reports well-formedness and missing
metadata, but cannot certify official ANI/CAR compliance without the receiving
team's complete schema and business rules.
