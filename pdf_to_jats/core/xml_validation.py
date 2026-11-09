"""Independent XML syntax, local schema and semantic validation dimensions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
import re

try:
    from lxml import etree
except ModuleNotFoundError:
    etree = None

ANI_NS = "http://www.elsevier.com/xml/ani/ani"


class ValidationStatus(str, Enum):
    WELL_FORMED = "WELL_FORMED"
    NOT_WELL_FORMED = "NOT_WELL_FORMED"
    SCHEMA_VALID = "SCHEMA_VALID"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    SCHEMA_UNAVAILABLE = "SCHEMA_UNAVAILABLE"


class ExportMode(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    message: str
    line: int | None = None
    column: int | None = None
    field: str | None = None


@dataclass(frozen=True)
class SchemaProfile:
    """An explicitly chosen local XSD bundle, not an inferred publisher claim."""
    name: str
    format: str
    schema_path: Path


@dataclass(frozen=True)
class ValidationResult:
    well_formedness: ValidationStatus
    schema_status: ValidationStatus
    fingerprint: str
    format: str
    profile: SchemaProfile | None = None
    syntax_issues: tuple[ValidationIssue, ...] = ()
    schema_issues: tuple[ValidationIssue, ...] = ()
    semantic_issues: tuple[ValidationIssue, ...] = ()
    schema_resources: tuple[tuple[str, str], ...] = ()

    @property
    def issues(self) -> tuple[ValidationIssue, ...]:
        return self.syntax_issues + self.schema_issues + self.semantic_issues

    def require_export(self, mode: ExportMode) -> None:
        mode = ExportMode(mode)
        if self.well_formedness != ValidationStatus.WELL_FORMED or any(
            issue.severity == "error" for issue in self.syntax_issues
        ):
            raise ValueError("Fix XML parse/security errors before exporting: " +
                             "; ".join(issue.message for issue in self.syntax_issues))
        if mode == ExportMode.VALIDATED and self.schema_status != ValidationStatus.SCHEMA_VALID:
            raise ValueError("Validated export requires successful validation against the selected "
                             "local schema profile. " + "; ".join(i.message for i in self.schema_issues))


def fingerprint(data: bytes) -> str:
    return sha256(data).hexdigest()


def secure_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                           recover=False, remove_blank_text=False)


def unicode_xml_bytes(text: str) -> bytes:
    """Unicode editor text is UTF-8; keep the declaration consistent with bytes."""
    text = re.sub(r'^(\ufeff?<\?xml\s[^?]*?encoding\s*=\s*)([\"\']).*?\2',
                  lambda match: match[1] + match[2] + "UTF-8" + match[2], text, count=1)
    return text.encode("utf-8")


def document_format(root: etree._Element) -> str:
    name = etree.QName(root)
    if name.namespace == ANI_NS and name.localname == "units":
        return "ANI"
    if name.localname == "article":
        return "JATS"
    return "Unknown"


class _LocalSchemaResolver(etree.Resolver if etree is not None else object):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root.resolve()
        self.resources: dict[str, str] = {}

    def resolve(self, url: str, public_id: str, context):
        parsed = urlparse(url)
        # libxml supplies absolute Windows paths as well as file URIs.
        windows_path = bool(re.match(r"^[A-Za-z]:[/\\]", url))
        if not windows_path and (parsed.scheme not in {"", "file"} or parsed.netloc):
            raise OSError("Schema resources must be local files inside the selected schema folder")
        value = unquote(parsed.path) if parsed.scheme == "file" else url
        if re.match(r"^/[A-Za-z]:/", value):
            value = value[1:]
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if not path.is_relative_to(self.root):
            raise OSError("Schema resource is outside the selected schema folder")
        data = path.read_bytes()
        self.resources[str(path)] = fingerprint(data)
        tree = etree.parse(BytesIO(data), secure_parser())
        if tree.docinfo.doctype:
            raise OSError("Schema DTDs/entities are not supported; use a self-contained local XSD bundle")
        return self.resolve_string(data, context, base_url=path.as_uri())


def validate_xml(data: bytes, profile: SchemaProfile | None = None) -> ValidationResult:
    """Validate exact bytes. Never fetch the instance's schemaLocation or a DTD."""
    if etree is None:
        return _validate_without_lxml(data, profile)
    digest = fingerprint(data)
    try:
        tree = etree.parse(BytesIO(data), secure_parser())
    except (etree.XMLSyntaxError, ValueError) as exc:
        line, column = getattr(exc, "position", (None, None))
        return ValidationResult(ValidationStatus.NOT_WELL_FORMED,
                                ValidationStatus.SCHEMA_UNAVAILABLE, digest, "Unknown", profile,
                                (ValidationIssue("error", f"XML parse error: {exc}", line, column),))
    root = tree.getroot()
    family = document_format(root)
    syntax = []
    if any(isinstance(node, etree._Entity) for node in root.iter()):
        syntax.append(ValidationIssue("error", "Unresolved entities cannot be exported; replace them with explicit text"))
    semantic = []
    namespace = etree.QName(root).namespace
    def has_content(names: set[str]) -> bool:
        return any(isinstance(n.tag, str) and etree.QName(n).namespace == namespace
                   and etree.QName(n).localname in names and "".join(n.itertext()).strip()
                   for n in root.iter())
    for names, label in (({"article-title", "titletext"}, "title"),
                         ({"contrib", "author"}, "authors"), ({"abstract"}, "abstract")):
        if not has_content(names):
            semantic.append(ValidationIssue("warning", f"Missing or empty {label}", field=label))
    status = ValidationStatus.SCHEMA_UNAVAILABLE
    schema_issues = []
    resources: tuple[tuple[str, str], ...] = ()
    if profile is None:
        schema_issues.append(ValidationIssue("warning", "Schema validation unavailable: select a trusted local schema profile; publisher validation is incomplete"))
    elif family == "Unknown" or profile.format != family:
        schema_issues.append(ValidationIssue("error", f"Schema profile {profile.name} is for {profile.format}, but this document is {family}; select the matching profile"))
    else:
        try:
            path = Path(profile.schema_path).resolve()
            parser = secure_parser()
            resolver = _LocalSchemaResolver(path.parent)
            parser.resolvers.add(resolver)
            schema = etree.XMLSchema(etree.parse(str(path), parser))
            resources = tuple(sorted(resolver.resources.items()))
            if schema.error_log:
                raise ValueError("Incomplete schema bundle: " + "; ".join(
                    entry.message for entry in schema.error_log))
            status = ValidationStatus.SCHEMA_VALID if schema.validate(tree) else ValidationStatus.SCHEMA_INVALID
            schema_issues.extend(ValidationIssue("error", entry.message, entry.line, entry.column)
                                 for entry in schema.error_log)
        except (OSError, ValueError, etree.LxmlError) as exc:
            schema_issues.append(ValidationIssue("error", f"Schema unavailable: {exc}. Install the complete local XSD bundle and select its entry schema"))
    return ValidationResult(ValidationStatus.WELL_FORMED, status, digest, family, profile,
                            tuple(syntax), tuple(schema_issues), tuple(semantic), resources)


def _validate_without_lxml(data: bytes, profile: SchemaProfile | None) -> ValidationResult:
    """Retain standalone draft support; never claim schema validation without lxml."""
    import xml.etree.ElementTree as stdlib_etree

    class NoDTDBuilder(stdlib_etree.TreeBuilder):
        def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
            raise ValueError("DTD input requires the secure lxml parser; install lxml")

    digest = fingerprint(data)
    try:
        root = stdlib_etree.fromstring(data, parser=stdlib_etree.XMLParser(target=NoDTDBuilder()))
    except (stdlib_etree.ParseError, ValueError) as exc:
        return ValidationResult(ValidationStatus.NOT_WELL_FORMED, ValidationStatus.SCHEMA_UNAVAILABLE,
                                digest, "Unknown", profile,
                                (ValidationIssue("error", f"XML parse error: {exc}"),))
    name = root.tag.rsplit('}', 1)[-1]
    family = "ANI" if root.tag == f"{{{ANI_NS}}}units" else "JATS" if name == "article" else "Unknown"
    prefix = root.tag.rsplit('}', 1)[0] + '}' if root.tag.startswith('{') else ''
    semantic = []
    for names, label in (({"article-title", "titletext"}, "title"),
                         ({"contrib", "author"}, "authors"), ({"abstract"}, "abstract")):
        if not any(node.tag in {prefix + name for name in names} and ''.join(node.itertext()).strip()
                   for node in root.iter()):
            semantic.append(ValidationIssue("warning", f"Missing or empty {label}", field=label))
    return ValidationResult(ValidationStatus.WELL_FORMED, ValidationStatus.SCHEMA_UNAVAILABLE,
                            digest, family, profile, schema_issues=(ValidationIssue("warning",
                            "Schema validation unavailable: install lxml; publisher validation is incomplete"),),
                            semantic_issues=tuple(semantic))
