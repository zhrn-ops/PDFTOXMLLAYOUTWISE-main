# XML validation and export

The correction workspace now provides two explicit export choices:

- **Draft Export** retains the previous **Validate & Export** workflow. It checks XML syntax, lists unresolved schema/metadata issues, and saves a provisional copy. Missing schemas and schema-invalid content do not prevent draft export; malformed XML and unresolved entities do. The dialog and completion message state that publisher validation is incomplete.
- **Validated Export** requires successful validation against an explicitly selected local schema profile. Missing entry schemas, missing imports/includes, unusable schemas, wrong format profiles, and schema-invalid XML block the write. This certifies the selected XSD checks, not additional publisher business rules.

Use **Select local schema…** to select a trusted entry `.xsd`, then choose **JATS** or **ANI**. This application generates Elsevier ANI/CAR XML; a JATS schema cannot validate that output. Place the complete schema bundle beneath the entry schema's folder. Relative includes/imports within that folder are supported; network URLs and resources outside the folder are rejected. A selected profile is retained only for the current correction window, not automatically saved into a portable draft workspace.

No authoritative publisher schema is bundled. `Template_CAR.xml` remains a template, not a schema. Obtain the correct schema bundle and business rules from the receiving team. The XML document's `schemaLocation` and external DTD declarations never cause automatic downloads.

Validation separately records:

- XML syntax: `WELL_FORMED` or `NOT_WELL_FORMED`.
- Schema status: `SCHEMA_VALID`, `SCHEMA_INVALID`, or `SCHEMA_UNAVAILABLE`.
- Semantic review issues, such as missing titles/authors and incomplete CAR metadata.

A syntactically valid document is never labeled simply “Valid” when schema validation is unavailable. Semantic warnings remain visible even after successful schema validation. Edits invalidate previous results; validated export also rechecks schema resources in case they changed since validation.

Both export choices preserve the source XML and write the completed copy using a temporary file and atomic replacement. A failed write or replacement leaves an existing destination intact. Raw XML parse errors retain the last good tree for editing but cannot export it as though it were the current edit.

Inline scientific text, including adjacent styled symbols and formula components, is preserved during correction serialization. Unicode editor text is encoded consistently as UTF-8, even when it originated from a non-UTF-8 XML declaration. Structural containers remain readable without reformatting inline content.

## Programmatic compatibility

`XmlDocumentSession.validate()` still returns the existing issue list; `validation_result` exposes the structured result for the current bytes. `save_copy(destination)` retains draft behavior after validation. Use `save_copy(destination, mode=ExportMode.VALIDATED)` for strict export after validating with a `SchemaProfile`.

`JATSGenerator.generate(document, path)` remains a draft export, now atomic and syntax-checked before publication. It accepts `mode=ExportMode.VALIDATED` and `profile=SchemaProfile(...)` for strict output. Legacy GUI generation paths remain drafts and explicitly log incomplete publisher validation.

`Validator.validate(path)` retains its issue-list interface but now reports unavailable schemas instead of returning an empty list. `Validator.validate_result(path, profile)` exposes separate dimensions. The legacy default schema path is JATS-only; ANI callers must supply an ANI profile. The desktop installation requires lxml. Standalone validator/generator draft support remains available without it, but cannot perform schema validation and rejects DTD input rather than expanding entities.
