"""XML and content validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pdf_to_jats.core.xml_validation import SchemaProfile, ValidationResult, validate_xml

from pdf_to_jats.models.document import Document


@dataclass(slots=True)
class ValidationError:
    """Validation issue."""

    message: str


class Validator:
    """Validate XML with an explicit format/profile, plus document content."""

    def __init__(self, schema_path: Path | None = None) -> None:
        self.schema_path = schema_path

    def validate_result(self, xml_path: Path, profile: SchemaProfile | None = None) -> ValidationResult:
        """Return independent syntax/schema/semantic results for exact file bytes."""
        if profile is None and self.schema_path is not None and self.schema_path.exists():
            profile = SchemaProfile("Explicit JATS schema", "JATS", self.schema_path)
        return validate_xml(xml_path.read_bytes(), profile)

    def validate(self, xml_path: Path) -> list[ValidationError]:
        """Compatibility issue list; absence of a schema is now explicitly reported."""
        try:
            result = self.validate_result(xml_path)
        except OSError as exc:
            return [ValidationError(f"Could not read XML: {exc}")]
        return [ValidationError(issue.message) for issue in result.issues]

    def validate_document(self, document: Document) -> list[ValidationError]:
        """Validate the intermediate document before XML export."""

        errors: list[ValidationError] = []
        if not document.title.strip():
            errors.append(ValidationError("Missing title"))
        lowered_title = document.title.lower()
        if "doi:" in lowered_title or "abstract" in lowered_title and "flash talks" in lowered_title:
            errors.append(ValidationError("Title still contains DOI or section-heading noise"))
        if not document.authors:
            errors.append(ValidationError("Missing authors"))
        for author in document.authors:
            combined = f"{author.initials} {author.surname} {author.display_name}".strip()
            lowered = combined.lower()
            if not combined or not any(ch.isalpha() for ch in combined):
                errors.append(ValidationError("Invalid author entry: missing alphabetic content"))
                break
            if any(token in lowered for token in ("copyright", "published by", "all rights reserved")):
                errors.append(ValidationError("Invalid author entry: footer or copyright text detected"))
                break
            if combined.strip() in {"|", "||", "©", "®"}:
                errors.append(ValidationError("Invalid author entry: symbol-only author detected"))
                break
        if not document.affiliations:
            errors.append(ValidationError("Missing affiliations"))
        if not document.abstract.strip():
            errors.append(ValidationError("Missing abstract"))
        absn = document.abstract_number()
        if absn and absn != "ABSN" and any(ch.isspace() for ch in absn):
            errors.append(ValidationError("Abstract number contains whitespace"))
        return errors
