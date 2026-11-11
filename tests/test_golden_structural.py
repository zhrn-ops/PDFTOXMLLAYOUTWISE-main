"""Golden XML structural fixture tests preserving text, tails, order, and semantic markup.

Covers:
- Structural comparison ensuring exact element tag, attribute, text, tail, and child sequence preservation.
- Multicolumn scientific document fixture with alphabetic/numeric scripts and formulas.
- Author-affiliation structural grouping fixture.
- Mixed-content preservation (inline math, comments, tails).
"""

from __future__ import annotations

from pathlib import Path
import pytest
from lxml import etree

from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.models.document import Document
from pdf_to_jats.models.author import Author
from pdf_to_jats.models.affiliation import Affiliation
from pdf_to_jats.models.paragraph import Paragraph


ANI_NS = JATSGenerator.ANI_NS
CE_NS = JATSGenerator.CE_NS


def assert_structural_equality(node_a: etree._Element, node_b: etree._Element) -> None:
    """Recursively assert tag, text, tail, attributes, and exact child order.

    Newline-bearing, whitespace-only text/tails are treated as insignificant
    indentation. Every other difference is compared exactly, so a lost space
    inside mixed inline content (``<italic>x</italic> y``) is still detected.
    """
    assert node_a.tag == node_b.tag, f"Tag mismatch: {node_a.tag} != {node_b.tag}"
    assert node_a.attrib == node_b.attrib, f"Attribute mismatch at {node_a.tag}: {node_a.attrib} != {node_b.attrib}"

    def norm(val: str | None) -> str:
        if val is None:
            return ""
        # Pretty-print indentation always contains a newline. A plain space or
        # tab is meaningful inline spacing and must not be normalized away.
        if not val.strip() and "\n" in val:
            return ""
        return val

    assert norm(node_a.text) == norm(node_b.text), f"Text mismatch at {node_a.tag}: {repr(node_a.text)} != {repr(node_b.text)}"
    assert norm(node_a.tail) == norm(node_b.tail), f"Tail mismatch at {node_a.tag}: {repr(node_a.tail)} != {repr(node_b.tail)}"
    assert len(node_a) == len(node_b), f"Child count mismatch under {node_a.tag}: {len(node_a)} != {len(node_b)}"

    for child_a, child_b in zip(node_a, node_b):
        assert_structural_equality(child_a, child_b)


@pytest.mark.scientific
def test_golden_scientific_document_structure(tmp_path: Path):
    """Verify that a comprehensive scientific document generates expected structural ANI XML."""
    doc = Document(
        title="Kinetic Analysis of Ca2+-ATPase and H2O Transport at Vmax",
        abstract="Inhibition by TiO2 and SO42- was monitored. The constant ka reached 10-3 s-1.",
        authors=[
            Author(
                id="a1", display_name="Marie Curie", given_names="Marie", surname="Curie",
                initials="M.", degrees="PhD", affiliation_ids=["aff1"]
            ),
            Author(
                id="a2", display_name="Pierre Curie", given_names="Pierre", surname="Curie",
                initials="P.", degrees="PhD", affiliation_ids=["aff1", "aff2"]
            ),
        ],
        corresponding_author=Author(
            id="a1", display_name="Marie Curie", given_names="Marie", surname="Curie",
            initials="M.", degrees="PhD", affiliation_ids=["aff1"]
        ),
        affiliations=[
            Affiliation(id="aff1", text="Faculty of Sciences, Sorbonne University, Paris, France"),
            Affiliation(id="aff2", text="ESPCI Paris, Paris, France"),
        ],
        paragraphs=[
            Paragraph(
                id="p1", page=1, column=0, status="accepted", role="body",
                text="Experiments were performed under steady-state conditions.",
                bbox=[0.0, 0.0, 500.0, 14.0],
            )
        ],
        metadata={
            "unit_id": "00000001",
            "order_id": "ORD001",
            "parcel_id": "PARCEL1",
            "supplier_id": "4",
            "abstract_number": "P-101",
            "title_script_runs": [
                {"start": 22, "end": 24, "type": "sup", "text": "2+", "source": "geometry"},
                {"start": 37, "end": 38, "type": "sub", "text": "2", "source": "geometry"},
                {"start": 54, "end": 57, "type": "sub", "text": "max", "source": "manual"},
            ],
            "abstract_script_runs": [
                {"start": 17, "end": 18, "type": "sub", "text": "2", "source": "lexicon"},
                {"start": 25, "end": 27, "type": "sub", "text": "4", "source": "lexicon"},
                {"start": 27, "end": 29, "type": "sup", "text": "2-", "source": "lexicon"},
                {"start": 57, "end": 58, "type": "sub", "text": "a", "source": "font_flag"},
                {"start": 69, "end": 71, "type": "sup", "text": "-3", "source": "geometry"},
                {"start": 74, "end": 76, "type": "sup", "text": "-1", "source": "geometry"},
            ],
        },
    )

    out_file = tmp_path / "golden.xml"
    JATSGenerator().generate(doc, out_file)

    tree = etree.parse(str(out_file))
    root = tree.getroot()

    # Verify namespace and schema location
    assert root.tag == f"{{{ANI_NS}}}units"

    # Title verification
    titletext = root.find(f".//{{{ANI_NS}}}titletext")
    assert titletext is not None
    title_sups = titletext.findall(f"{{{CE_NS}}}sup")
    title_infs = titletext.findall(f"{{{CE_NS}}}inf")
    assert len(title_sups) == 1 and title_sups[0].text == "2+"
    assert len(title_infs) == 2
    assert [inf.text for inf in title_infs] == ["2", "max"]

    # Author groups structural verification
    groups = root.findall(f".//{{{ANI_NS}}}head/{{{ANI_NS}}}author-group")
    assert len(groups) == 2  # aff1 group and aff2 group

    # Group 1 has both Curie authors and Sorbonne affiliation
    g1_authors = groups[0].findall(f"{{{ANI_NS}}}author")
    assert len(g1_authors) == 2
    assert groups[0].find(f"{{{ANI_NS}}}affiliation/{{{ANI_NS}}}organization").text == "Faculty of Sciences, Sorbonne University"

    # Correspondence verification
    corr = root.find(f".//{{{ANI_NS}}}head/{{{ANI_NS}}}correspondence")
    assert corr is not None
    assert corr.find(f"{{{ANI_NS}}}person/{{{CE_NS}}}surname").text == "Curie"
    assert corr.find(f"{{{ANI_NS}}}affiliation/{{{ANI_NS}}}city").text == "Paris"


@pytest.mark.scientific
def test_mixed_content_inline_preservation(tmp_path: Path):
    """Ensure complex mixed content with unknown nodes, comments, and tails round-trips exactly."""
    xml_data = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<article xmlns:m="http://www.w3.org/1998/Math/MathML">\n'
        '<front><article-meta><title-group>\n'
        '<article-title>Analysis of <italic>E. coli</italic> <!--reviewed-->formula '
        '<m:math><m:mi>x</m:mi><m:mn>2</m:mn></m:math> rate</article-title>\n'
        '</title-group></article-meta></front>\n'
        '</article>'
    )
    src_file = tmp_path / "mixed.xml"
    src_file.write_text(xml_data, encoding="utf-8")

    session = XmlDocumentSession.open(src_file)
    exported = session.xml_text()

    tree_orig = etree.fromstring(xml_data.encode("utf-8"), etree.XMLParser(remove_blank_text=False))
    tree_exported = etree.fromstring(exported.encode("utf-8"), etree.XMLParser(remove_blank_text=False))

    title_orig = tree_orig.find(".//article-title")
    title_exp = tree_exported.find(".//article-title")
    assert_structural_equality(title_orig, title_exp)


def test_comparator_rejects_leading_space_change():
    with pytest.raises(AssertionError):
        assert_structural_equality(etree.fromstring("<r><p>text</p></r>"),
                                   etree.fromstring("<r><p> text</p></r>"))


def test_comparator_rejects_lost_inline_tail_space():
    with pytest.raises(AssertionError):
        assert_structural_equality(etree.fromstring("<r><p><italic>x</italic> y</p></r>"),
                                   etree.fromstring("<r><p><italic>x</italic>y</p></r>"))


def test_comparator_rejects_internal_space_change():
    with pytest.raises(AssertionError):
        assert_structural_equality(etree.fromstring("<r><p>a b</p></r>"),
                                   etree.fromstring("<r><p>a  b</p></r>"))


def test_comparator_rejects_changed_comment():
    with pytest.raises(AssertionError):
        assert_structural_equality(etree.fromstring("<r><p>x</p><!--reviewed--></r>"),
                                   etree.fromstring("<r><p>x</p><!--approved--></r>"))


def test_comparator_rejects_added_processing_instruction():
    with pytest.raises(AssertionError):
        assert_structural_equality(etree.fromstring("<r><p>x</p></r>"),
                                   etree.fromstring("<r><?review keep?><p>x</p></r>"))


def test_comparator_ignores_newline_indentation_only():
    assert_structural_equality(etree.fromstring("<r><p>x</p></r>"),
                               etree.fromstring("<r>\n  <p>x</p>\n</r>"))
