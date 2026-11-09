"""Portable immutable XML snapshots. Saved validation is provenance, not permission."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from pdf_to_jats.core.xml_validation import ValidationResult, fingerprint, secure_parser
from lxml import etree


@dataclass(frozen=True)
class XmlRevision:
    data: bytes

    @property
    def id(self) -> str:
        return fingerprint(self.data)

    def to_record(self) -> dict[str, str]:
        return {"sha256": self.id, "bytes_base64": base64.b64encode(self.data).decode("ascii")}

    @classmethod
    def from_record(cls, value: object) -> XmlRevision:
        if not isinstance(value, dict) or not isinstance(value.get("bytes_base64"), str):
            raise ValueError("Invalid XML revision record")
        try:
            data = base64.b64decode(value["bytes_base64"], validate=True)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid XML revision bytes") from exc
        revision = cls(data)
        if value.get("sha256") != revision.id:
            raise ValueError("XML revision fingerprint does not match its bytes")
        etree.fromstring(data, secure_parser())
        return revision


def validation_record(data: bytes, result: ValidationResult) -> dict[str, Any]:
    """Capture exactly what was checked, including the local schema bundle hashes."""
    if fingerprint(data) != result.fingerprint:
        raise ValueError("Validation result does not belong to this XML revision")
    profile = result.profile
    return {
        "revision": XmlRevision(data).to_record(),
        "well_formedness": result.well_formedness.value,
        "schema_status": result.schema_status.value,
        "format": result.format,
        "profile": None if profile is None else {
            "name": profile.name, "format": profile.format, "schema_path": str(profile.schema_path)},
        "schema_resources": [list(item) for item in result.schema_resources],
        "issues": [{"severity": issue.severity, "message": issue.message,
                    "line": issue.line, "column": issue.column, "field": issue.field}
                   for issue in result.issues],
    }
