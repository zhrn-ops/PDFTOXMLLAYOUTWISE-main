"""Safe, in-memory editing primitives for XML correction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tempfile

from lxml import etree
from pdf_to_jats.core.inline_script_detector import (
    join_text_and_runs,
    normalize_inline_runs,
    preserve_matching_runs,
)

ANI_CE_NS = "http://www.elsevier.com/xml/ani/common"


def normalize_organization(value: str) -> str:
    """Return an organization name without comma separators or stray spaces.

    Editors often paste values such as ``", Dept. of Internal Medicine "``;
    the XML should keep ``"Dept. of Internal Medicine"`` instead.
    """
    return " ".join(str(value or "").replace(",", "").split())


@dataclass
class Issue:
    severity: str
    message: str
    line: int | None = None
    column: int | None = None
    field: str | None = None


class XmlDocumentSession:
    """Keep source bytes and only commit successfully parsed XML edits."""

    def __init__(
        self,
        path: Path,
        source: bytes,
        *,
        source_path: Path | None = None,
    ) -> None:
        self.path = path
        self.source_path = source_path
        self.source_bytes = source
        self.parser = etree.XMLParser(resolve_entities=False, no_network=True,
                                      load_dtd=False, recover=False, remove_blank_text=False)
        self.tree = etree.ElementTree(etree.fromstring(source, self.parser))
        self.original_bytes = source
        self.encoding = self.tree.docinfo.encoding or "UTF-8"
        self.xml_declaration = self.tree.docinfo.xml_version
        self.dirty = False
        self.validation: list[Issue] = []
        self.raw_valid = True
        self.profile = self._profile()

    @classmethod
    def open(cls, path: Path) -> "XmlDocumentSession":
        return cls(path, path.read_bytes(), source_path=path)

    @classmethod
    def from_text(cls, text: str, label_path: Path) -> "XmlDocumentSession":
        """Create a correction session for XML that has not been saved yet."""

        return cls(label_path, text.encode("utf-8"))

    def _profile(self) -> str:
        root = self.tree.getroot()
        if etree.QName(root).namespace == "http://www.elsevier.com/xml/ani/ani":
            return "ANI"
        if etree.QName(root).localname == "article":
            return "JATS"
        return "Unknown"

    def _find(self, names: tuple[str, ...]):
        # Prefer the profile's canonical metadata location, avoiding unrelated
        # titles/abstracts in references and body sections.
        local_root = etree.QName(self.tree.getroot()).localname
        preferred = ("article-title", "abstract") if local_root == "article" else ("titletext", "abstract")
        for wanted in preferred:
            if wanted in names:
                for node in self.tree.iter():
                    if etree.QName(node).localname == wanted:
                        return node
        for node in self.tree.iter():
            if etree.QName(node).localname in names:
                return node
        return None

    def title_node(self):
        return self._find(("titletext", "article-title"))

    def abstract_node(self):
        return self._find(("abstract", "abstracts"))

    def title(self) -> str:
        node = self.title_node()
        return "" if node is None else " ".join("".join(node.itertext()).split())

    def abstract(self) -> str:
        node = self.abstract_node()
        if node is None:
            return ""
        # Preserve inner formatting; display a readable textual editing view.
        paragraphs = [" ".join("".join(p.itertext()).split()) for p in node.iter() if etree.QName(p).localname in {"p", "para"}]
        return "\n\n".join(paragraphs) or " ".join("".join(node.itertext()).split())

    def authors(self):
        names = {"author", "contrib"}
        authors = []
        for node in self.tree.iter():
            if not isinstance(node.tag, str) or etree.QName(node).localname not in names:
                continue
            if not self._author_name_parts(node):
                continue
            # Bibliography authors are citation data, not article contributors;
            # including them here duplicated people and shifted author indices.
            if any(etree.QName(parent).localname in {"ref-authors", "reference"}
                   for parent in node.iterancestors()):
                continue
            authors.append(node)
        return authors

    @staticmethod
    def _author_name_parts(node):
        """Read direct ANI name fields or fields inside a JATS name wrapper."""

        parts = []
        for child in node:
            if not isinstance(child.tag, str):
                continue
            candidates = list(child) if etree.QName(child).localname == "name" else [child]
            parts.extend(
                part for part in candidates
                if isinstance(part.tag, str)
                and etree.QName(part).localname in {
                    "string-name", "surname", "given-name", "given-names", "initials"
                }
            )
        return parts

    @staticmethod
    def author_name(node) -> str:
        parts = [" ".join("".join(c.itertext()).split()) for c in XmlDocumentSession._author_name_parts(node)]
        return " ".join(part for part in parts if part)

    @staticmethod
    def _affiliation_label(node) -> str:
        """Prefer the verbatim ce:source-text, falling back to all inner text."""
        for child in node:
            if isinstance(child.tag, str) and etree.QName(child).localname == "source-text":
                text = " ".join("".join(child.itertext()).split())
                if text:
                    return text
        # Skip numbered JATS labels so they do not run into the name
        # ("1University A"); keep every other piece of the affiliation text.
        chunks = [node.text or ""]
        for child in node:
            if isinstance(child.tag, str) and etree.QName(child).localname == "label":
                chunks.append(child.tail or "")
            else:
                chunks.append("".join(child.itertext()))
                chunks.append(child.tail or "")
        return " ".join(" ".join(chunks).split())

    def affiliation_groups(self):
        """Return ``(label, author_indices, affiliation_nodes, container)``.

        Every author affiliation the document holds is represented exactly
        once, so the correction UI can offer each of them for editing:
        affiliations attached to ANI author groups, JATS ``aff`` elements linked
        by xref, and orphaned affiliations in source metadata. Correspondence
        affiliations are not listed here because the corresponding-author tab
        owns them. ``container`` is the element to extend when a group has no
        affiliation yet (an ANI ``author-group``), otherwise the affiliation
        itself.
        """
        authors = self.authors()
        groups: list[tuple[str, list[int], list, object]] = []
        assigned: set[int] = set()
        covered: set[int] = set()
        for group in self.tree.iter():
            if not isinstance(group.tag, str) or etree.QName(group).localname != "author-group":
                continue
            indices = [i for i, author in enumerate(authors) if author.getparent() is group]
            affiliations = [child for child in group if isinstance(child.tag, str)
                            and etree.QName(child).localname == "affiliation"]
            label = "; ".join(self._affiliation_label(aff) for aff in affiliations)
            groups.append((label or "No affiliation specified", indices, affiliations, group))
            assigned.update(indices)
            covered.update(id(aff) for aff in affiliations)
        # JATS stores links as xref/rid rather than structural author groups.
        for aff in self.tree.iter():
            if not isinstance(aff.tag, str) or etree.QName(aff).localname != "aff":
                continue
            identifier = aff.get("id")
            indices = [i for i, author in enumerate(authors) if identifier and any(
                isinstance(ref.tag, str) and etree.QName(ref).localname == "xref"
                and ref.get("ref-type") == "aff" and identifier in ref.get("rid", "").split()
                for ref in author.iter()
            )]
            groups.append((self._affiliation_label(aff), indices, [aff], aff))
            assigned.update(indices)
            covered.add(id(aff))
        # Orphaned affiliations outside author groups. Correspondence entries
        # keep their own affiliations in the corresponding-author tab instead
        # of showing them a second time as normal affiliations.
        for aff in self.tree.iter():
            if not isinstance(aff.tag, str) or etree.QName(aff).localname != "affiliation":
                continue
            if id(aff) in covered:
                continue
            if any(etree.QName(parent).localname == "correspondence"
                   for parent in aff.iterancestors()):
                covered.add(id(aff))
                continue
            groups.append((self._affiliation_label(aff), [], [aff], aff))
            covered.add(id(aff))
        unassigned = [i for i in range(len(authors)) if i not in assigned]
        if unassigned:
            groups.append(("No affiliation linked", unassigned, [], None))
        return groups

    def author_affiliation_groups(self):
        """Return affiliation labels and author indices using XML relationships."""
        return [(label, indices) for label, indices, _nodes, _container in self.affiliation_groups()]

    def affiliations(self):
        return [" ".join("".join(node.itertext()).split()) for node in self.tree.iter()
                if isinstance(node.tag, str) and etree.QName(node).localname in {"affiliation", "aff"}]

    def correspondence(self):
        """Return ``(person, details, affiliations)`` for the corresponding author.

        ``details`` lists ``(field, value)`` pairs in document order so repeated
        fields are all shown. ``affiliations`` holds the affiliation nodes of
        the correspondence entry, falling back to the affiliations of the
        author group whose surname matches the correspondence person.
        """
        for node in self.tree.iter():
            if not isinstance(node.tag, str) or etree.QName(node).localname != "correspondence":
                continue
            person = next(
                (child for child in node
                 if isinstance(child.tag, str) and etree.QName(child).localname == "person"),
                None,
            )
            details = [
                (etree.QName(child).localname, " ".join("".join(child.itertext()).split()))
                for child in (person if person is not None else [])
                if isinstance(child.tag, str)
            ]
            affiliations = [
                child for child in node
                if isinstance(child.tag, str)
                and etree.QName(child).localname in {"affiliation", "aff"}
            ]
            if not affiliations and person is not None:
                affiliations = self._person_affiliations(person)
            return person, [(field, value) for field, value in details if value], affiliations
        return None, [], []

    def _person_affiliations(self, person):
        """Affiliations of the author group matching a correspondence person."""

        def surname(node) -> str:
            return next(
                (" ".join("".join(child.itertext()).split()).casefold()
                 for child in XmlDocumentSession._author_name_parts(node)
                 if etree.QName(child).localname == "surname"),
                "",
            )

        wanted = surname(person)
        if not wanted:
            return []
        for author in self.authors():
            if surname(author) != wanted:
                continue
            group = author.getparent()
            if group is None or etree.QName(group).localname != "author-group":
                continue
            affiliations = [
                child for child in group
                if isinstance(child.tag, str)
                and etree.QName(child).localname in {"affiliation", "aff"}
            ]
            if affiliations:
                return affiliations
        return []

    AFFILIATION_FIELDS = ('organization', 'address-part', 'city', 'state',
                          'postal-code', 'country', 'source-text')

    def affiliation_form(self, node):
        """Every editable affiliation field, including repeated organizations.

        Fields the document does not carry are returned empty so the user can
        fill in the complete affiliation structure instead of only the values
        that already exist.
        """
        if etree.QName(node).localname not in {'affiliation', 'author-group'}:
            raise ValueError("This form supports ANI affiliations; edit other XML profiles in Raw XML")
        fields = {'affiliation-instance-id': node.get('affiliation-instance-id', '')}
        for tag in self.AFFILIATION_FIELDS:
            ns = ANI_CE_NS if tag == 'source-text' else etree.QName(node).namespace
            children = node.findall(f'{{{ns}}}{tag}' if ns else tag)
            for index, child in enumerate(children or [None]):
                key = tag if index == 0 else f'{tag}:{index + 1}'
                fields[key] = ''.join(child.itertext()) if child is not None else ''
                if tag == 'country':
                    fields[key + '@iso-code'] = child.get('iso-code', '') if child is not None else ''
        return fields

    def set_affiliation_form(self, node, values):
        """Apply the form, treating its organizations as the final list.

        The form may add organizations, and removing an entry there means the
        corresponding ``<organization>`` is dropped from the XML, so the
        organization keys must describe one contiguous ordered list.
        """
        old = self.affiliation_form(node)
        # Organization names are stored without commas, so normalize whatever
        # the editor sent before deciding whether the form actually changed.
        values = {
            key: normalize_organization(value) if key.partition(":")[0] == "organization" else value
            for key, value in values.items()
        }
        # The form may append further organization entries; every other field
        # is fixed by the document and must not be introduced by the caller.
        for key in set(values) - set(old):
            tag, _, ordinal = key.partition(':')
            if tag != 'organization' or not ordinal.isdigit() or int(ordinal) < 2:
                raise ValueError("Affiliation fields changed; reopen the editor")
        organization_keys = [key for key in values if key.partition(':')[0] == 'organization']
        ordinals = sorted(int(key.partition(':')[2] or '1') for key in organization_keys)
        if ordinals != list(range(1, len(organization_keys) + 1)):
            raise ValueError("Affiliation fields changed; reopen the editor")
        if old == values:
            return False
        # Validate all changes before touching XML, preserving nested markup.
        for key, value in values.items():
            if value == old.get(key, '') or key == 'affiliation-instance-id' or '@' in key:
                continue
            tag, _, ordinal = key.partition(':')
            ns = ANI_CE_NS if tag == 'source-text' else etree.QName(node).namespace
            children = node.findall(f'{{{ns}}}{tag}' if ns else tag)
            index = int(ordinal or '1') - 1
            if index < len(children) and len(children[index]):
                raise ValueError(f"{tag} contains inline markup; use Raw XML to preserve it")
        if etree.QName(node).localname == 'author-group':
            ns = etree.QName(node).namespace
            node = etree.SubElement(node, f'{{{ns}}}affiliation' if ns else 'affiliation')
        # Anything the form no longer lists at the end of the organization
        # sequence was removed by the user.
        ns = etree.QName(node).namespace
        qname = f'{{{ns}}}organization' if ns else 'organization'
        organizations = node.findall(qname)
        for child in organizations[len(organization_keys):]:
            node.remove(child)
        if values['affiliation-instance-id'] != old['affiliation-instance-id']:
            node.set('affiliation-instance-id', values['affiliation-instance-id'])
        for key, value in values.items():
            if key == 'affiliation-instance-id' or '@' in key:
                continue
            tag, _, ordinal = key.partition(':')
            iso_key = key + '@iso-code'
            if value == old.get(key, '') and values.get(iso_key) == old.get(iso_key):
                continue
            ns = ANI_CE_NS if tag == 'source-text' else etree.QName(node).namespace
            qname = f'{{{ns}}}{tag}' if ns else tag
            children = node.findall(qname)
            index = int(ordinal or '1') - 1
            if index < len(children):
                child = children[index]
            elif value == '' and not values.get(iso_key):
                # Leave absent optional fields out of the XML rather than
                # writing empty elements the user never filled in.
                continue
            else:
                child = etree.Element(qname)
                rank = self.AFFILIATION_FIELDS.index(tag)
                position = next((i for i, existing in enumerate(node)
                    if isinstance(existing.tag, str) and etree.QName(existing).localname in self.AFFILIATION_FIELDS
                    and self.AFFILIATION_FIELDS.index(etree.QName(existing).localname) > rank), len(node))
                node.insert(position, child)
            if value != old.get(key, ''):
                child.text = value
            if iso_key in values and values[iso_key] != old.get(iso_key):
                child.set('iso-code', values[iso_key])
        self.dirty = True
        self.validation = []
        return True

    def keywords(self):
        return [node for node in self.tree.iter() if isinstance(node.tag, str) and etree.QName(node).localname in {"keyword", "keywd", "kwd", "author-keyword"}]

    def _set_text(self, node, value: str, *, preserve_scripts: bool = False) -> None:
        if preserve_scripts:
            old_text, old_runs = self._text_and_script_runs(node)
            self._write_scripted_text(
                node,
                value,
                preserve_matching_runs(old_text, value, old_runs),
            )
            self.dirty = True
            self.validation = []
            return
        # Keep a leaf's attributes/namespaces and avoid destroying mixed markup.
        if len(node):
            for child in list(node):
                node.remove(child)
        node.text = value
        self.dirty = True
        self.validation = []

    def apply_script(self, field: str, start: int, end: int, tag: str) -> None:
        """Apply or clear scripts in a selection, retaining paragraph boundaries."""
        if tag not in {"sup", "inf", "normal"} or field not in {"title", "abstract"}:
            raise ValueError("Unsupported formatting action")
        node = self.title_node() if field == "title" else self.abstract_node()
        if node is None:
            raise ValueError("No editable field found")
        allowed = {"p", "para", "abstract", "abstracts", "sup", "inf", "sub"}
        if any(etree.QName(child).localname not in allowed for child in node.iter() if child is not node):
            raise ValueError("This field contains formatting that cannot safely be changed here")
        text, _ = self._text_and_script_runs(node)
        if not 0 <= start < end <= len(text):
            raise ValueError("Select some text first")
        paragraphs = [child for child in node.iter() if child is not node and etree.QName(child).localname in {"p", "para"}]
        offset = 0
        for target in paragraphs or [node]:
            value, runs = self._text_and_script_runs(target)
            left, right = max(0, start - offset), min(len(value), end - offset)
            if left < right:
                preserved = []
                for run in runs:
                    a, b = int(run["start"]), int(run["end"])
                    for lo, hi in ((a, min(b, left)), (max(a, right), b)):
                        if lo < hi:
                            preserved.append(dict(run, start=lo, end=hi, text=value[lo:hi]))
                ns = ANI_CE_NS if self.profile == "ANI" else etree.QName(target).namespace
                if tag != "normal":
                    preserved.append({"start": left, "end": right, "text": value[left:right],
                                      "type": "sup" if tag == "sup" else "sub",
                                      "qname": f"{{{ns}}}{tag}" if ns else tag})
                self._write_scripted_text(target, value, preserved)
            offset += len(value) + 2
        self.dirty = True
        self.validation = []

    def set_title(self, value: str) -> None:
        node = self.title_node()
        if node is None:
            raise ValueError("This XML profile has no safely mapped title element")
        self._set_text(node, value, preserve_scripts=True)

    def set_abstract(self, value: str) -> None:
        node = self.abstract_node()
        if node is None:
            raise ValueError("This XML profile has no safely mapped abstract element")
        # Replace only content for the simple single-text abstract representation.
        allowed = {"p", "para", "abstract", "abstracts", "sup", "sub", "inf"}
        if any(etree.QName(child).localname not in allowed for child in node.iter() if child is not node):
            raise ValueError("Formatted abstract cannot be safely replaced in this document")
        old_text, old_runs = self._text_and_script_runs(node)
        mapped_runs = preserve_matching_runs(old_text, value, old_runs)
        if self.profile == "JATS":
            self._write_scripted_text(node, value, mapped_runs)
        else:
            paragraph_node = next(
                (child for child in node if etree.QName(child).localname in {"p", "para"}),
                None,
            )
            paragraph_tag = paragraph_node.tag if paragraph_node is not None else f"{{{ANI_CE_NS}}}para"
            for child in list(node):
                node.remove(child)
            node.text = None
            lines = value.splitlines(keepends=True) or [value]
            offset = 0
            for line_with_ending in lines:
                line = line_with_ending.rstrip("\r\n")
                paragraph = etree.SubElement(node, paragraph_tag)
                line_runs = []
                line_end = offset + len(line)
                for run in mapped_runs:
                    if offset <= int(run["start"]) and int(run["end"]) <= line_end:
                        item = dict(run)
                        item["start"] = int(run["start"]) - offset
                        item["end"] = int(run["end"]) - offset
                        line_runs.append(item)
                self._write_scripted_text(paragraph, line, line_runs)
                offset += len(line_with_ending)
        self.dirty = True
        self.validation = []

    def _text_and_script_runs(self, node) -> tuple[str, list[dict[str, object]]]:
        """Read a field as plain text plus offsets for existing inline scripts."""

        def read_element(element):
            chunks: list[str] = []
            runs: list[dict[str, object]] = []
            length = 0

            def append(value, kind=None, qname=None):
                nonlocal length
                if not value:
                    return
                start = length
                chunks.append(value)
                length += len(value)
                if kind:
                    runs.append({"start": start, "end": length, "type": kind, "text": value, "qname": qname})

            def walk(current, inherited_kind=None, inherited_qname=None):
                append(current.text, inherited_kind, inherited_qname)
                for child in current:
                    local = etree.QName(child).localname
                    if local == "sup":
                        child_kind = "sup"
                    elif local in {"sub", "inf"}:
                        child_kind = "sub"
                    else:
                        child_kind = inherited_kind
                    child_qname = child.tag if local in {"sup", "sub", "inf"} else inherited_qname
                    walk(child, child_kind, child_qname)
                    append(child.tail, inherited_kind, inherited_qname)

            walk(element)
            return "".join(chunks), runs

        paragraph_nodes = [
            child for child in node.iter()
            if child is not node and etree.QName(child).localname in {"p", "para"}
        ]
        if paragraph_nodes:
            parts = []
            for paragraph in paragraph_nodes:
                raw_text, raw_runs = read_element(paragraph)
                parts.append(normalize_inline_runs(raw_text, raw_runs))
            return join_text_and_runs(parts, "\n\n")
        raw_text, raw_runs = read_element(node)
        return normalize_inline_runs(raw_text, raw_runs)

    def _write_scripted_text(self, node, value: str, runs: list[dict[str, object]]) -> None:
        """Replace field contents while preserving only verified script runs."""

        namespace = etree.QName(node).namespace
        default_namespace = ANI_CE_NS if self.profile == "ANI" else namespace
        valid = []
        for run in runs:
            try:
                start, end = int(run["start"]), int(run["end"])
                kind = str(run["type"])
            except (KeyError, TypeError, ValueError):
                continue
            if kind not in {"sup", "sub"} or not (0 <= start < end <= len(value)):
                continue
            expected = str(run.get("text", value[start:end]))
            if value[start:end] != expected:
                continue
            qname = run.get("qname")
            if not qname:
                local = "inf" if self.profile == "ANI" and kind == "sub" else kind
                qname = f"{{{default_namespace}}}{local}" if default_namespace else local
            valid.append((start, end, str(qname)))
        valid.sort()

        for child in list(node):
            node.remove(child)
        node.text = None
        cursor = 0
        previous = None
        for start, end, qname in valid:
            if start < cursor:
                continue
            plain = value[cursor:start]
            if previous is None:
                node.text = (node.text or "") + plain
            else:
                previous.tail = (previous.tail or "") + plain
            previous = etree.SubElement(node, qname)
            previous.text = value[start:end]
            cursor = end
        tail = value[cursor:]
        if previous is None:
            node.text = tail
        else:
            previous.tail = (previous.tail or "") + tail

    def set_author_name(self, index: int, value: str) -> None:
        node = self.authors()[index]
        if value == self.author_name(node):
            return
        parts = self._author_name_parts(node)
        target = next((c for c in parts if etree.QName(c).localname == "string-name"), None)
        if target is None:
            target = next((c for c in parts if etree.QName(c).localname == "surname"), None)
        if target is None:
            raise ValueError("Author name has no safely editable name element")
        self._set_text(target, value)

    def set_author_name_parts(self, index: int, values: list[str]) -> bool:
        """Edit existing name fields without parsing a combined display name."""
        parts = self._author_name_parts(self.authors()[index])
        if len(parts) != len(values):
            raise ValueError("The author's name fields changed; reopen the editor")
        changes = [(node, value) for node, value in zip(parts, values)
                   if value != "".join(node.itertext())]
        if any(len(node) for node, _ in changes):
            raise ValueError("This name field contains inline formatting; edit it in Raw XML to preserve its markup")
        if changes and not any(value.strip() for value in values):
            raise ValueError("An author must have at least one non-empty name field")
        for node, value in changes:
            self._set_text(node, value)
        return bool(changes)

    AUTHOR_NAME_FIELDS = ('initials', 'degrees', 'surname', 'given-name',
                          'suffix', 'e-address')
    AUTHOR_ATTRIBUTES = ('seq', 'author-instance-id', 'orcid')
    AUTHOR_FIELD_ALIASES = {'given-name': ('given-name', 'given-names')}

    def author_form(self, index: int) -> dict[str, str]:
        """Every editable author field, including attributes and absent fields.

        Mirrors ``affiliation_form``: existing attributes and name parts are
        returned as they are, and the ANI person fields the document does not
        carry come back empty so the user can fill them in.
        """
        node = self.authors()[index]
        fields = {
            f'@{name}': value
            for name, value in node.attrib.items()
            if not name.startswith('{')
        }
        for child in node:
            if isinstance(child.tag, str) and etree.QName(child).localname in self.AUTHOR_NAME_FIELDS:
                fields.setdefault(etree.QName(child).localname, ''.join(child.itertext()))
        for part in self._author_name_parts(node):
            fields.setdefault(etree.QName(part).localname, ''.join(part.itertext()))
        for name in self.AUTHOR_NAME_FIELDS:
            aliases = self.AUTHOR_FIELD_ALIASES.get(name, (name,))
            if not any(alias in fields for alias in aliases):
                fields[name] = ''
        return fields

    def _author_field_node(self, container, key: str):
        names = self.AUTHOR_FIELD_ALIASES.get(key, (key,))
        return next(
            (child for child in container
             if isinstance(child.tag, str) and etree.QName(child).localname in names),
            None,
        )

    def set_author_form(self, index: int, values: dict[str, str]) -> bool:
        """Apply the author form, creating missing ANI person fields on demand."""
        node = self.authors()[index]
        old = self.author_form(index)
        for key in set(values) - set(old):
            if key.startswith('@') and key[1:] in self.AUTHOR_ATTRIBUTES:
                continue
            if key in self.AUTHOR_NAME_FIELDS:
                continue
            raise ValueError("Author fields changed; reopen the editor")
        if values == old:
            return False
        if not any(value.strip() for key, value in values.items() if not key.startswith('@')):
            raise ValueError("An author must have at least one non-empty name field")
        # JATS keeps the name parts inside a <name> wrapper, so edits and the
        # inline-markup guard must look at that container, not only at the
        # author element itself.
        container = next(
            (child for child in node
             if isinstance(child.tag, str) and etree.QName(child).localname == 'name'),
            node,
        )
        # Validate before touching XML so a rejected field changes nothing.
        for key, value in values.items():
            if key.startswith('@') or value == old.get(key, ''):
                continue
            existing = self._author_field_node(container, key)
            if existing is not None and len(existing):
                raise ValueError(
                    f"{key} contains inline formatting; use Raw XML to preserve its markup")
        children = [child for child in container if isinstance(child.tag, str)]
        namespace = etree.QName(children[0]).namespace if children else (
            ANI_CE_NS if self.profile == 'ANI' else etree.QName(node).namespace)
        changed = False
        for key, value in values.items():
            if key.startswith('@'):
                name = key[1:]
                if value == old.get(key, ''):
                    continue
                if value:
                    node.set(name, value)
                elif name in node.attrib:
                    del node.attrib[name]
                changed = True
                continue
            existing = self._author_field_node(container, key)
            if existing is not None:
                if value != ''.join(existing.itertext()):
                    existing.text = value
                    changed = True
                continue
            if not value or key not in self.AUTHOR_NAME_FIELDS:
                continue
            child = etree.Element(f'{{{namespace}}}{key}' if namespace else key)
            rank = self.AUTHOR_NAME_FIELDS.index(key)
            position = next(
                (i for i, element in enumerate(container)
                 if isinstance(element.tag, str)
                 and etree.QName(element).localname in self.AUTHOR_NAME_FIELDS
                 and self.AUTHOR_NAME_FIELDS.index(etree.QName(element).localname) > rank),
                len(container),
            )
            child.text = value
            container.insert(position, child)
            changed = True
        if changed:
            self.dirty = True
            self.validation = []
        return changed

    def add_author(self, name: str) -> None:
        if self.profile != "JATS":
            raise ValueError("Adding authors is supported for JATS XML only")
        group = self._find(("contrib-group",))
        if group is None:
            raise ValueError("No JATS contributor group exists")
        contrib = etree.SubElement(group, f"{{{etree.QName(group).namespace}}}contrib", attrib={"contrib-type": "author"})
        etree.SubElement(contrib, f"{{{etree.QName(group).namespace}}}name")
        etree.SubElement(contrib[0], f"{{{etree.QName(group).namespace}}}surname").text = name
        self.dirty = True
        self.validation = []

    def remove_author(self, index: int) -> None:
        node = self.authors()[index]
        # Keep document integrity when any ID is referenced elsewhere.
        ids = {value for key, value in node.attrib.items() if key in {"id", "xml:id"}}
        if ids and any(ref.get("rid", "") in ids for ref in self.tree.iter()):
            raise ValueError("This author has references; remove or resolve them explicitly first")
        node.getparent().remove(node)
        self.dirty = True
        self.validation = []

    def set_keyword(self, index: int, value: str) -> None:
        self._set_text(self.keywords()[index], value)

    def add_keyword(self, value: str) -> None:
        if self.profile == "ANI":
            citation = self._find(("citation-info",))
            if citation is None:
                raise ValueError("No ANI citation-info element exists")
            namespace = etree.QName(citation).namespace
            group = citation.find(f"{{{namespace}}}author-keywords")
            if group is None:
                group = etree.SubElement(citation, f"{{{namespace}}}author-keywords")
            etree.SubElement(group, f"{{{namespace}}}author-keyword").text = value
            self.dirty = True
            self.validation = []
            return
        if self.profile != "JATS":
            raise ValueError("Adding keywords is supported for JATS XML only")
        group = self._find(("kwd-group",))
        if group is None:
            raise ValueError("No JATS keyword group exists")
        etree.SubElement(group, f"{{{etree.QName(group).namespace}}}kwd").text = value
        self.dirty = True
        self.validation = []

    def commit_raw(self, text: str) -> tuple[bool, str | None, int | None, int | None]:
        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, recover=False, remove_blank_text=False)
            candidate = etree.fromstring(text.encode(self.encoding), parser)
            self.tree = etree.ElementTree(candidate)
            self.profile = self._profile()
            self.dirty = etree.tostring(self.tree, encoding=self.encoding, xml_declaration=True) != self.original_bytes
            self.validation = []
            self.raw_valid = True
            return True, None, None, None
        except etree.XMLSyntaxError as exc:
            self.validation = []
            self.raw_valid = False
            entry = exc.error_log.last_error
            return False, str(exc), entry.line if entry else None, entry.column if entry else None

    def xml_text(self) -> str:
        return etree.tostring(self.tree, encoding=self.encoding, xml_declaration=True, pretty_print=True).decode(self.encoding)

    def validate(self) -> list[Issue]:
        if not self.raw_valid:
            self.validation = [Issue("error", "The raw XML editor contains unparsed changes")]
            return self.validation
        issues: list[Issue] = []
        try:
            etree.fromstring(etree.tostring(self.tree), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, recover=False))
            issues.append(Issue("info", "XML is well-formed"))
        except etree.XMLSyntaxError as exc:
            e = exc.error_log.last_error
            return [Issue("error", str(exc), e.line if e else None, e.column if e else None)]
        if self.profile == "Unknown":
            issues.append(Issue("warning", "Document profile is unknown; structured mappings are limited"))
        else:
            issues.append(Issue("info", f"Schema validation unavailable: no trusted local {self.profile} XSD is installed"))
        if not self.title().strip():
            issues.append(Issue("warning", "Missing or empty title", field="title"))
        if not self.authors():
            issues.append(Issue("warning", "No authors found", field="authors"))
        if not self.abstract().strip():
            issues.append(Issue("warning", "Missing or empty abstract", field="abstract"))
        if self.profile == "ANI":
            issues.append(Issue("info", "CAR output follows the supplied template provisionally; official schema compliance is not verified."))
            namespace = {"ani": "http://www.elsevier.com/xml/ani/ani"}
            for tag, label in (("unit-id", "Unit ID"), ("order-id", "Order ID"),
                               ("parcel-id", "Parcel ID"), ("supplier-id", "Supplier ID"),
                               ("sourcetitle", "Journal/source title")):
                nodes = self.tree.xpath(f"//ani:{tag}", namespaces=namespace)
                if not nodes or not any("".join(node.itertext()).strip() for node in nodes):
                    issues.append(Issue("warning", f"CAR metadata not supplied: {label}. Confirm with the receiving team."))
            if self.tree.xpath('//ani:itemid[@idtype="ABSN" and text()="ABSN"]', namespaces=namespace):
                issues.append(Issue("warning", "Article number uses the workflow placeholder ABSN; confirm whether a real identifier is required."))
        self.validation = issues
        return issues

    def save_copy(self, destination: Path) -> None:
        if self.source_path is not None and destination.resolve() == self.source_path.resolve():
            raise ValueError("Save Copy cannot overwrite the source XML")
        if not self.validation:
            raise ValueError("Validate the current XML before exporting a copy")
        if not self.raw_valid:
            raise ValueError("Fix the raw XML parse error before exporting a copy")
        if any(issue.severity == "error" for issue in self.validation):
            raise ValueError("Fix XML validation errors before exporting a copy")
        data = etree.tostring(self.tree, encoding=self.encoding, xml_declaration=True, pretty_print=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, destination)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        self.original_bytes = data
        self.dirty = False
