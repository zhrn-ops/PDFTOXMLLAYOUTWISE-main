"""Elsevier ANI XML generation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

try:
    from lxml import etree  # type: ignore
    LXML_AVAILABLE = True
except ModuleNotFoundError:
    import xml.etree.ElementTree as etree

    LXML_AVAILABLE = False

from pdf_to_jats.core.alternate_names import assigned_names
from pdf_to_jats.core.country_codes import country_code
from pdf_to_jats.core.title_order import english_titles_first
from pdf_to_jats.core.atomic_io import atomic_write_bytes
from pdf_to_jats.core.xml_validation import ExportMode, SchemaProfile, validate_xml
from pdf_to_jats.models.document import Document
from pdf_to_jats.core.inline_script_detector import normalize_inline_runs


class JATSGenerator:
    """Generate Elsevier ANI-style XML from the intermediate document."""

    ANI_NS = "http://www.elsevier.com/xml/ani/ani"
    XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
    CE_NS = "http://www.elsevier.com/xml/ani/common"
    SCHEMA_LOCATION = "http://www.elsevier.com/xml/ani/ani http://www.elsevier.com/xml/ani/ani515-input-CAR.xsd"

    def generate(self, document: Document, output_path: Path, *,
                 mode: ExportMode = ExportMode.DRAFT,
                 profile: SchemaProfile | None = None) -> Path:
        """Atomically publish a draft, or require the selected schema for strict export."""
        data = self.to_bytes(document)
        result = validate_xml(data, profile)
        result.require_export(mode)
        atomic_write_bytes(output_path, data)
        return output_path

    def to_bytes(self, document: Document) -> bytes:
        """Build ANI XML in memory without creating an output file."""
        root = self._build_root(document)
        english_titles_first(root)
        self._line_break_elements(root)
        if LXML_AVAILABLE:
            return etree.tostring(
                root,
                pretty_print=False,
                xml_declaration=True,
                encoding="UTF-8",
                standalone=False,
            )
        return etree.tostring(root, encoding="utf-8", xml_declaration=True)

    def _line_break_elements(self, node: Any, in_inline: bool = False) -> None:
        """Put every element-only container on its own lines, without indent."""
        def local_name(element: Any) -> str:
            return element.tag.rsplit('}', 1)[-1] if isinstance(element.tag, str) else ''

        # Text-bearing/inline elements are kept intact so their spacing and
        # mixed content are never rewritten by line breaks.
        inline = {"p", "para", "titletext", "source-text", "organization",
                  "address-part", "city", "state", "postal-code", "keyword",
                  "kwd", "keywd", "italic", "sub", "sup", "inf", "mi", "mo",
                  "mn", "mtext"}
        in_inline = in_inline or local_name(node) in inline
        if (len(node) and not in_inline
                and not (node.text or "").strip()
                and all(not (child.tail or "").strip() for child in node)):
            node.text = "\n"
            for child in node:
                if isinstance(child.tag, str):
                    self._line_break_elements(child, in_inline)
                child.tail = "\n"
            return
        for child in node:
            if isinstance(child.tag, str):
                self._line_break_elements(child, in_inline)

    def to_string(self, document: Document) -> str:
        """Return generated ANI XML for the correction workspace."""

        return self.to_bytes(document).decode("UTF-8")

    def _build_root(self, document: Document) -> Any:
        nsmap = {
            None: self.ANI_NS,
            "xsi": self.XSI_NS,
            "ce": self.CE_NS,
        }
        root = (etree.Element(self._qname("units"), nsmap=nsmap) if LXML_AVAILABLE
                else etree.Element(self._qname("units")))
        root.set(self._qname_attr("schemaLocation", self.XSI_NS), self.SCHEMA_LOCATION)

        unit = etree.SubElement(root, self._qname("unit"))

        self._append_unit_info(unit, document)
        content = etree.SubElement(unit, self._qname("unit-content"))
        bibrecord = etree.SubElement(content, self._qname("bibrecord"))
        self._append_item_info(bibrecord, document)
        self._append_head(bibrecord, document)
        self._append_references(bibrecord, document)
        self._append_body(content, document)
        return root

    def _append_body(self, parent: Any, document: Document) -> None:
        """Write only reviewed paragraph units; proposals are never exported."""

        paragraphs = [
            paragraph
            for paragraph in document.paragraphs
            if paragraph.status == "accepted" and paragraph.role in {"body", "unclassified"} and paragraph.text.strip()
        ]
        if not paragraphs:
            return
        body = etree.SubElement(parent, self._qname("body"))
        for paragraph in paragraphs:
            para = etree.SubElement(body, self._qname("para", self.CE_NS))
            text, runs = normalize_inline_runs(paragraph.text, paragraph.inline_runs)
            self._append_scripted_text(para, self._sanitize_para_text(text), runs)

    def _append_unit_info(self, parent: Any, document: Document) -> None:
        unit_info = etree.SubElement(parent, self._qname("unit-info"))
        etree.SubElement(unit_info, self._qname("unit-id")).text = self._metadata_value(document, "unit_id")
        etree.SubElement(unit_info, self._qname("order-id")).text = self._metadata_value(document, "order_id")
        etree.SubElement(unit_info, self._qname("parcel-id")).text = self._metadata_value(document, "parcel_id")
        etree.SubElement(unit_info, self._qname("supplier-id")).text = self._metadata_value(document, "supplier_id")
        etree.SubElement(unit_info, self._qname("timestamp")).text = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _append_item_info(self, parent: Any, document: Document) -> None:
        item_info = etree.SubElement(parent, self._qname("item-info"))
        status = etree.SubElement(item_info, self._qname("status"))
        status.set("state", "new")
        status.set("stage", "S300")

        itemidlist = etree.SubElement(item_info, self._qname("itemidlist"))
        for name in ("pii", "doi", "ern"):
            self._optional_text(itemidlist, name, document.metadata.get(name), self.CE_NS)
        abstract_number = self._metadata_value(document, "abstract_number", "ABSN")
        default_itemids = [(abstract_number, "ABSN")]
        for item_id, idtype in self._metadata_list(document, "itemids", default_itemids):
            itemid = etree.SubElement(itemidlist, self._qname("itemid"))
            itemid.set("idtype", idtype)
            itemid.text = item_id

    def _append_head(self, parent: Any, document: Document) -> None:
        head = etree.SubElement(parent, self._qname("head"))
        citation_info = etree.SubElement(head, self._qname("citation-info"))
        etree.SubElement(citation_info, self._qname("citation-type")).set("code", "cb")
        citation_language = etree.SubElement(citation_info, self._qname("citation-language"))
        citation_language.set(self._qname_attr("lang", "http://www.w3.org/XML/1998/namespace"), self._metadata_value(document, "language", "ENG"))
        abstract_language = etree.SubElement(citation_info, self._qname("abstract-language"))
        abstract_language.set(self._qname_attr("lang", "http://www.w3.org/XML/1998/namespace"), self._metadata_value(document, "language", "ENG"))

        keywords = document.metadata.get("keywords", [])
        if isinstance(keywords, list):
            keyword_terms = [self._sanitize_xml_text(str(term)).strip() for term in keywords if str(term).strip()]
            if keyword_terms:
                author_keywords = etree.SubElement(citation_info, self._qname("author-keywords"))
                for term in keyword_terms:
                    etree.SubElement(author_keywords, self._qname("author-keyword")).text = term

        related = document.metadata.get("related_item")
        if isinstance(related, dict) and any(related.get(k) for k in ("pii", "doi")):
            item = etree.SubElement(head, self._qname("related-item"), type=str(related.get("type", "original")))
            identifiers = etree.SubElement(item, self._qname("itemidlist"))
            for name in ("pii", "doi"):
                self._optional_text(identifiers, name, related.get(name), self.CE_NS)

        citation_title = etree.SubElement(head, self._qname("citation-title"))
        title_language = (
            str(document.metadata.get("title_language") or "").strip().upper()
            or self._metadata_value(document, "language", "ENG").strip().upper()
            or "ENG"
        )
        titletext = etree.SubElement(citation_title, self._qname("titletext"))
        titletext.set(self._qname_attr("lang", "http://www.w3.org/XML/1998/namespace"), title_language)
        titletext.set("original", "y")
        title_text = self._sanitize_title(document.title, document.abstract_number())
        self._append_scripted_text(titletext, title_text, self._script_runs(document, "title"))

        seen_titles = {" ".join(title_text.split()).casefold()}
        for alternate in document.alternate_titles:
            alternate_text = self._sanitize_title(alternate.text, document.abstract_number())
            alternate_key = " ".join(alternate_text.split()).casefold()
            if not alternate_key or alternate_key in seen_titles:
                continue
            seen_titles.add(alternate_key)
            alternate_node = etree.SubElement(citation_title, self._qname("titletext"))
            alternate_language = str(alternate.language or "UND").strip().upper() or "UND"
            alternate_node.set(
                self._qname_attr("lang", "http://www.w3.org/XML/1998/namespace"),
                alternate_language,
            )
            alternate_node.set("original", "n")
            self._append_scripted_text(alternate_node, alternate_text, [])

        # Multiple affiliations repeat the same author object in the XML.
        # Sequence identifies their original byline position, not occurrences.
        author_sequences = {id(author): position for position, author in enumerate(document.authors, start=1)}
        for seq, (affiliation, group_authors) in enumerate(self._author_groups(document), start=1):
            author_group = etree.SubElement(head, self._qname("author-group"))
            author_group.set("seq", str(seq))
            for author in group_authors:
                author_el = etree.SubElement(author_group, self._qname("author"))
                author_el.set("seq", str(author_sequences[id(author)]))
                initials = self._sanitize_xml_text(author.initials)
                surname = self._sanitize_xml_text(author.surname)
                given_names = self._sanitize_xml_text(author.given_names)
                display_name = " ".join(author.display_name.split())
                given_name_only = bool(given_names) and not surname and (
                    not display_name
                    or display_name.casefold() == " ".join(given_names.split()).casefold()
                )
                initials_only = bool(initials) and not surname and not given_names and (
                    not display_name
                    or display_name.casefold() == " ".join(initials.split()).casefold()
                )
                # Repeating a known partial name supplies no evidence for
                # additional name fields.
                if (not initials or not surname) and not (given_name_only or initials_only):
                    parsed_initials, parsed_given_names, parsed_surname = self._split_name(
                        author.display_name or f"{author.initials} {author.surname}".strip()
                    )
                    initials = initials or parsed_initials
                    given_names = given_names or parsed_given_names
                    surname = surname or parsed_surname
                elif not given_names and surname and author.display_name.strip():
                    # Initials and surname can already be populated while the
                    # full given name is only present in the display name.
                    # Require the parsed surname to agree: surname-first names
                    # such as "Sheu J-Y" must not infer "Sheu" as a given name.
                    _, parsed_given_names, parsed_surname = self._split_name(author.display_name)
                    if parsed_surname.casefold() == surname.casefold():
                        given_names = self._sanitize_xml_text(parsed_given_names)
                if initials and given_names and self._name_token_is_initials(given_names):
                    given_names = ""
                if initials:
                    etree.SubElement(author_el, self._qname("initials", self.CE_NS)).text = initials
                if author.degrees.strip():
                    etree.SubElement(author_el, self._qname("degrees", self.CE_NS)).text = self._sanitize_xml_text(author.degrees)
                if surname:
                    etree.SubElement(author_el, self._qname("surname", self.CE_NS)).text = surname
                if given_names:
                    etree.SubElement(author_el, self._qname("given-name", self.CE_NS)).text = given_names
                seen_alt_names = {self._name_key(given_names), self._name_key(surname)}
                for alternate in [*author.alternate_names, *assigned_names(author, document.authors, document.blocks)]:
                    alt_text = self._sanitize_xml_text(" ".join(str(alternate.text or "").split()))
                    # A native-script byline is exported as ce:alt-name beside the
                    # English name ("Aliasghar" + "علی اصغر پیشداد"), not as a
                    # second author.
                    if not alt_text or self._name_key(alt_text) in seen_alt_names:
                        continue
                    seen_alt_names.add(self._name_key(alt_text))
                    etree.SubElement(author_el, self._qname("alt-name", self.CE_NS)).text = alt_text
            if affiliation is not None:
                affiliation_el = etree.SubElement(author_group, self._qname("affiliation"))
                self._append_affiliation(affiliation_el, affiliation)

        self._append_correspondence(head, document)
        self._append_grants(head, document)

        if document.abstract:
            abstracts = etree.SubElement(head, self._qname("abstracts"))
            abstract = etree.SubElement(abstracts, self._qname("abstract"))
            abstract.set("original", "y")
            abstract.set(self._qname_attr("lang", "http://www.w3.org/XML/1998/namespace"), self._metadata_value(document, "language", "ENG"))
            self._optional_text(abstract, "publishercopyright", document.metadata.get("publisher_copyright"))
            para = etree.SubElement(abstract, self._qname("para", self.CE_NS))
            abstract_text = self._sanitize_para_text(document.abstract)
            self._append_scripted_text(para, abstract_text, self._script_runs(document, "abstract"))

        source = etree.SubElement(head, self._qname("source"))
        if document.metadata.get("srcid"):
            source.set("srcid", str(document.metadata["srcid"]))
        for tag, key in (("sourcetitle", "journal_title"), ("sourcetitle-abbrev", "journal_abbrev"),
                         ("volumetitle", "volume_title"), ("issuetitle", "issue_title"), ("issn", "issn")):
            self._optional_text(source, tag, document.metadata.get(key))
        for item in document.metadata.get("isbns", []):
            if isinstance(item, dict) and item.get("value"):
                node = self._optional_text(source, "isbn", item["value"])
                for attribute in ("type", "length"):
                    if item.get(attribute):
                        node.set(attribute, str(item[attribute]))

        if document.metadata.get("volume") or document.metadata.get("issue") or document.metadata.get("pages"):
            volisspag = etree.SubElement(source, self._qname("volisspag"))
            vin = etree.SubElement(volisspag, self._qname("volume-issue-number"))
            if document.metadata.get("volume"):
                etree.SubElement(vin, self._qname("vol-first")).text = str(document.metadata["volume"])
            if document.metadata.get("issue"):
                etree.SubElement(vin, self._qname("iss-first")).text = str(document.metadata["issue"])
            pages = document.metadata.get("pages")
            if isinstance(pages, dict):
                page_info = etree.SubElement(volisspag, self._qname("page-information"))
                pages_el = etree.SubElement(page_info, self._qname("pages"))
                etree.SubElement(pages_el, self._qname("first-page")).text = str(pages.get("first", ""))
                etree.SubElement(pages_el, self._qname("last-page")).text = str(pages.get("last", ""))

        self._optional_text(source, "article-number", document.metadata.get("article_number"))

        if document.metadata.get("publication_year"):
            etree.SubElement(source, self._qname("publicationyear")).set("first", str(document.metadata["publication_year"]))

        if document.metadata.get("publication_date"):
            pub = document.metadata["publication_date"]
            publicationdate = etree.SubElement(source, self._qname("publicationdate"))
            etree.SubElement(publicationdate, self._qname("year")).text = str(pub.get("year", ""))
            etree.SubElement(publicationdate, self._qname("month")).text = str(pub.get("month", "")).zfill(2)
            etree.SubElement(publicationdate, self._qname("day")).text = str(pub.get("day", "")).zfill(2)
            etree.SubElement(publicationdate, self._qname("date-text")).text = str(pub.get("date_text", ""))

        if document.metadata.get("website"):
            website = etree.SubElement(source, self._qname("website"), type="item")
            address = self._optional_text(website, "e-address", document.metadata["website"], self.CE_NS)
            address.set("type", "url")
        if document.metadata.get("publisher_name"):
            publisher = etree.SubElement(source, self._qname("publisher"))
            self._optional_text(publisher, "publishername", document.metadata["publisher_name"])
        if document.metadata.get("conference_event_id") or document.metadata.get("report_number"):
            additional = etree.SubElement(source, self._qname("additional-srcinfo"))
            for section, tag, key in (("conferenceinfo", "confevent-id", "conference_event_id"),
                                      ("reportinfo", "reportnumber", "report_number")):
                if document.metadata.get(key):
                    container = etree.SubElement(additional, self._qname(section))
                    self._optional_text(container, tag, document.metadata[key])

    def _optional_text(self, parent, tag, value, namespace=None):
        if value is None or not str(value).strip():
            return None
        node = etree.SubElement(parent, self._qname(tag, namespace))
        node.text = self._sanitize_xml_text(str(value))
        return node

    def _append_references(self, parent, document):
        references = [text for text in document.references if str(text).strip()]
        if not references:
            return
        tail = etree.SubElement(parent, self._qname("tail"))
        bibliography = etree.SubElement(tail, self._qname("bibliography"), refcount=str(len(references)))
        for index, text in enumerate(references, 1):
            reference = etree.SubElement(bibliography, self._qname("reference"), seq=str(index))
            # Preserve source citations verbatim; do not guess bibliographic fields.
            self._optional_text(reference, "ref-fulltext", text)
            self._optional_text(reference, "source-text", text, self.CE_NS)

    def _append_grants(self, parent, document):
        grants = document.metadata.get("grants", [])
        grants = [g for g in grants if isinstance(g, dict) and any(g.get(k) for k in
                  ("grant_id", "acronym", "agency", "agency_id"))] if isinstance(grants, list) else []
        if not grants and not document.metadata.get("grant_text"):
            return
        container = etree.SubElement(parent, self._qname("grantlist"))
        for data in grants:
            grant = etree.SubElement(container, self._qname("grant"))
            self._optional_text(grant, "grant-id", data.get("grant_id"))
            self._optional_text(grant, "grant-acronym", data.get("acronym"))
            if data.get("agency"):
                agency = etree.SubElement(grant, self._qname("grant-agency"))
                self._optional_text(agency, "organization", data["agency"])
            self._optional_text(grant, "grant-agency-id", data.get("agency_id"))
        self._optional_text(container, "grant-text", document.metadata.get("grant_text"))

    def _author_groups(self, document: Document) -> list[tuple[Any, list[Any]]]:
        """Group consecutive authors without changing the printed sequence.

        ANI expresses the author/affiliation link structurally, so every
        ``<author-group>`` carries one affiliation plus the authors pointing at
        it. Repeat an affiliation when it occurs again later in the byline.
        Authors with several affiliations have adjacent occurrences, while
        authors with no resolved affiliation stay in their original position.
        """

        groups: list[tuple[Any, list[Any]]] = []
        referenced: set[str] = set()
        for author in document.authors:
            affiliations = [
                affiliation for affiliation in document.affiliations
                if affiliation.id in author.affiliation_ids
            ]
            for affiliation in affiliations or [None]:
                if affiliation is not None:
                    referenced.add(affiliation.id)
                if groups and groups[-1][0] is affiliation:
                    groups[-1][1].append(author)
                else:
                    groups.append((affiliation, [author]))
        # Preserve unreferenced institutions without moving any author.
        for affiliation in document.affiliations:
            if affiliation.id not in referenced:
                groups.append((affiliation, []))
        return groups

    def _append_affiliation(self, parent, affiliation):
        if not affiliation.structured:
            self._append_affiliation_text(parent, affiliation.text)
            return
        for tag in ('organization', 'address-part', 'city', 'state', 'postal-code', 'country'):
            for value in affiliation.structured.get(tag, []):
                if not value:
                    continue
                node = etree.SubElement(parent, self._qname(tag))
                if tag == 'country':
                    node.set('iso-code', self._country_iso_code(value))
                else:
                    node.text = self._sanitize_xml_text(value)
        etree.SubElement(parent, self._qname('source-text', self.CE_NS)).text = self._sanitize_xml_text(affiliation.text)

    def _append_affiliation_text(self, parent: Any, text: str) -> None:
        organization, city, country = self._split_affiliation(text)
        if organization:
            etree.SubElement(parent, self._qname("organization")).text = organization
        if city:
            etree.SubElement(parent, self._qname("city")).text = city
        if country:
            country_el = etree.SubElement(parent, self._qname("country"))
            country_el.set("iso-code", self._country_iso_code(country))
        if text.strip():
            etree.SubElement(parent, self._qname("source-text", self.CE_NS)).text = self._sanitize_xml_text(text)

    def _append_correspondence(self, parent: Any, document: Document) -> None:
        author = document.corresponding_author
        if author is None:
            return
        correspondence = etree.SubElement(parent, self._qname("correspondence"))
        person = etree.SubElement(correspondence, self._qname("person"))
        etree.SubElement(person, self._qname("initials", self.CE_NS)).text = self._sanitize_xml_text(author.initials)
        given_names = self._sanitize_xml_text(author.given_names)
        if not given_names and author.surname and author.display_name.strip():
            _, parsed_given, parsed_surname = self._split_name(author.display_name)
            if parsed_surname.casefold() == author.surname.casefold():
                given_names = self._sanitize_xml_text(parsed_given)
        self._optional_text(person, "degrees", author.degrees, self.CE_NS)
        self._optional_text(person, "surname", author.surname, self.CE_NS)
        if given_names and not self._name_token_is_initials(given_names):
            etree.SubElement(person, self._qname("given-name", self.CE_NS)).text = given_names
        for affiliation_id in author.affiliation_ids:
            affiliation = next((item for item in document.affiliations if item.id == affiliation_id), None)
            if affiliation is None:
                continue
            affiliation_el = etree.SubElement(correspondence, self._qname("affiliation"))
            self._append_affiliation(affiliation_el, affiliation)

    def _split_name(self, full_name: str) -> tuple[str, str, str]:
        parts = [part for part in full_name.split() if part]
        if not parts:
            return "", "", ""
        if len(parts) == 1:
            return parts[0][:1].upper() + ".", parts[0], parts[0]
        particles = {"da", "das", "de", "del", "della", "der", "di", "do", "dos", "du", "la", "le", "van", "vander", "von"}
        surname_start = next((index for index, part in enumerate(parts[1:], start=1) if part.rstrip(".").lower() in particles), len(parts) - 1)
        given = parts[:surname_start]
        initials = "".join(f"{part[0].upper()}." for part in given)
        return initials, " ".join(given), " ".join(parts[surname_start:])

    @staticmethod
    def _name_key(value: str) -> str:
        return " ".join(str(value or "").split()).casefold()

    @staticmethod
    def _name_token_is_initials(value: str) -> bool:
        """Return true when a purported given name is only initials."""

        tokens = value.split()
        return bool(tokens) and all(
            re.fullmatch(r"(?:[A-Z](?:\.|-))+(?:[A-Z])?\.?", token)
            for token in tokens
        )

    def _split_affiliation(self, text: str) -> tuple[str, str, str]:
        # Keep the institutional hierarchy together. Earlier code treated
        # comma-separated departments as cities (e.g. "Department of
        # Pediatrics"), producing structurally incorrect affiliation fields.
        text = self._repair_mojibake(text)
        parts = [self._sanitize_xml_text(part).strip() for part in text.split(",") if part.strip()]
        if parts:
            repeated_country = re.fullmatch(
                r"(?P<country>UK|USA|United Kingdom|United States(?: of America)?)"
                r"(?:\s+\1)+",
                parts[-1],
                flags=re.IGNORECASE,
            )
            if repeated_country:
                parts[-1] = repeated_country.group("country")
        # Only a complete trailing address component is a country candidate.
        # Never interpret short codes in the middle of an institution/address.
        country_index = (len(parts) - 1 if len(parts) > 1 and country_code(parts[-1]) else None)
        country = parts[country_index] if country_index is not None else ""
        location_end = country_index if country_index is not None else len(parts)
        city = parts[location_end - 1] if location_end > 1 else ""
        organization_end = location_end - 1 if city else location_end
        organization = ", ".join(parts[:organization_end]) if organization_end else (parts[0] if parts else text)
        return organization, city, country

    def _country_iso_code(self, country: str) -> str:
        code = country_code(country)
        if not code:
            raise ValueError(f'Country {country!r} needs review: select a valid three-letter country code.')
        return code

    @staticmethod
    def _repair_mojibake(value: str) -> str:
        """Undo common UTF-8 bytes decoded as Latin-1 when it is reversible."""

        text = str(value or "")
        if not any(marker in text for marker in ("Ã", "Â", "â")):
            return text
        try:
            repaired = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
        return repaired if repaired.count("�") <= text.count("�") else text

    def _metadata_value(self, document: Document, key: str, default: str = "") -> str:
        value = document.metadata.get(key, default)
        return str(value) if value is not None else default

    def _sanitize_xml_text(self, value: str | None) -> str:
        """Remove control characters that are invalid in XML content."""

        if value is None:
            return ""
        text = str(value)
        return "".join(
            ch
            for ch in text
            if ch in "\t\n\r" or ord(ch) >= 0x20
        )

    def _sanitize_para_text(self, value: str | None) -> str:
        """Normalize paragraph whitespace so serialized paragraphs have no hard enters."""

        return re.sub(r"\s+", " ", self._sanitize_xml_text(value)).strip()

    def _script_runs(self, document: Document, field: str) -> list[dict[str, Any]]:
        runs = document.metadata.get(f"{field}_script_runs", [])
        return [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []

    def _append_scripted_text(self, parent: Any, text: str, runs: list[dict[str, Any]]) -> None:
        """Append inline sup/sub elements from character-offset script runs."""
        valid = []
        for run in runs:
            try:
                start, end = int(run["start"]), int(run["end"])
                kind = str(run["type"])
                expected = run.get("text")
            except (KeyError, TypeError, ValueError):
                continue
            if kind not in {"sup", "sub"}:
                continue
            if expected and not re.fullmatch(r"[\d+\-−]+", str(expected)):
                # Preserve explicit or measured alphabetic/Greek annotations
                # only at their exact matching offsets. Never relocate a letter
                # to a nearby ordinary word after text edits.
                source = str(run.get("source") or "manual")
                if (source not in {"manual", "geometry", "font_flag", "lexicon"}
                        or not 0 <= start < end <= len(text)
                        or text[start:end] != expected):
                    continue
            # Only relocate an offset when its expected run has one unambiguous
            # nearby match. Never wrap an unrelated character just because a
            # stale offset is still within the text bounds.
            if expected and (start >= len(text) or text[start:end] != expected):
                nearby = []
                search_from = max(0, start - 30)
                while True:
                    found_idx = text.find(str(expected), search_from)
                    if found_idx < 0 or found_idx > start + 60:
                        break
                    nearby.append(found_idx)
                    search_from = found_idx + 1
                if len(nearby) != 1:
                    continue
                start = nearby[0]
                end = start + len(str(expected))
            elif not expected and text[start:end] == "":
                continue
            if 0 <= start < end <= len(text):
                valid.append((start, end, kind))
        valid.sort()
        cursor = 0
        previous = None
        for start, end, kind in valid:
            if start < cursor:
                continue
            segment = text[cursor:start]
            if previous is None:
                parent.text = (parent.text or "") + segment
            else:
                previous.tail = (previous.tail or "") + segment
            # Elsevier ANI schema uses <ce:sup> and <ce:inf> (inferior), not <ce:sub>
            tag_name = "inf" if kind == "sub" else "sup"
            element = etree.SubElement(parent, self._qname(tag_name, self.CE_NS))
            element.text = text[start:end]
            previous = element
            cursor = end
        remaining = text[cursor:]
        if previous is None:
            parent.text = (parent.text or "") + remaining
        else:
            previous.tail = (previous.tail or "") + remaining

    def _sanitize_title(self, value: str | None, abstract_number: str = "") -> str:
        """Remove obvious DOI and section-heading noise from the title field."""

        text = re.sub(r"\s+", " ", self._sanitize_xml_text(value)).strip()
        if not text:
            return ""
        # With no supplied identifier, retain the title verbatim.  Only a
        # clearly editorial label can be discarded safely; guessing a number
        # from ordinary title text risks deleting real content.
        if not abstract_number or abstract_number.upper() == "ABSN":
            text = re.sub(
                r"^\s*(?:abstract\s*(?:no\.?|number|nr\.?|id)?|absn)\s*[:#|]\s*",
                "",
                text,
                count=1,
                flags=re.IGNORECASE,
            )
        if abstract_number and abstract_number.upper() != "ABSN":
            # A soft/discretionary hyphen can be embedded beside the visible
            # dash in extracted PDF text, e.g. ``EPO-\u00ad0818``.  It remains
            # the same ABSN identifier and must not survive in titletext.
            number_pattern = re.escape(abstract_number).replace(
                r"\-", r"[-\u00ad\u2010-\u2015]+"
            )
            text = re.sub(
                rf"^\s*[\(\[]?{number_pattern}[\)\]]?\s*(?:\||\u2502|[:.\-\u2013\u2014])?\s+",
                "",
                text,
                count=1,
                flags=re.IGNORECASE,
            )
        text = re.sub(r"^\s*doi:\s*\S+\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bA\s*B\s*S\s*T\s*R\s*A\s*C\s*T\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s{2,}", " ", text).strip(" -:;,.")
        return text

    def _metadata_list(self, document: Document, key: str, default: list[tuple[str, str]]) -> list[tuple[str, str]]:
        value = document.metadata.get(key)
        if isinstance(value, list) and value:
            return [(str(item.get("value", "")), str(item.get("idtype", "OSIN"))) for item in value if isinstance(item, dict)]
        return default

    def _qname(self, tag: str, namespace: str | None = None) -> str:
        if namespace is None:
            namespace = self.ANI_NS
        return f"{{{namespace}}}{tag}"

    def _qname_attr(self, name: str, namespace: str) -> str:
        return f"{{{namespace}}}{name}"
