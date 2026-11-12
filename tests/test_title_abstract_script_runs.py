"""Unit tests for title and abstract superscript and subscript detection and XML generation."""

import os
from pathlib import Path
from lxml import etree
import pytest

from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.models.document import Document
from pdf_to_jats.models.block import TextBlock
from pdf_to_jats.models.author import Author
from pdf_to_jats.models.affiliation import Affiliation
from pdf_to_jats.models.paragraph import Paragraph
from pdf_to_jats.gui.main_window import MainWindow

ANI_NS = JATSGenerator.ANI_NS
CE_NS = JATSGenerator.CE_NS


@pytest.fixture(autouse=True)
def offscreen_qt():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _min_window() -> MainWindow:
    window = MainWindow.__new__(MainWindow)
    window.document = None
    return window


def test_jats_generator_emits_sup_and_inf_for_title_and_abstract(tmp_path: Path):
    """Verify that title and abstract output valid <sup> and <inf> elements."""
    doc = Document(
        title="Study on H2O and CO2 dynamics",
        abstract="Concentration was 10-3 mol/L and Ca2+ ions were monitored.",
        metadata={
            "title_script_runs": [
                {"start": 10, "end": 11, "type": "sub", "text": "2"},
                {"start": 19, "end": 20, "type": "sub", "text": "2"},
            ],
            "abstract_script_runs": [
                {"start": 20, "end": 22, "type": "sup", "text": "-3"},
                {"start": 35, "end": 37, "type": "sup", "text": "2+"},
            ],
        },
    )

    output_path = tmp_path / "test_article.xml"
    JATSGenerator().generate(doc, output_path)

    xml = output_path.read_text(encoding="utf-8")
    assert "<ce:inf>" not in xml and "<ce:sup>" not in xml
    tree = etree.parse(str(output_path))
    root = tree.getroot()

    # Check titletext
    titletext = root.find(f".//{{{ANI_NS}}}titletext")
    assert titletext is not None
    infs = titletext.findall(f"{{{ANI_NS}}}inf")
    assert len(infs) == 2
    assert infs[0].text == "2"
    assert infs[1].text == "2"
    assert titletext.find(f"{{{CE_NS}}}sub") is None

    # Check abstract para
    para = root.find(f".//{{{ANI_NS}}}abstract/{{{CE_NS}}}para")
    assert para is not None
    sups = para.findall(f"{{{ANI_NS}}}sup")
    assert len(sups) == 2
    assert sups[0].text == "-3"
    assert sups[1].text == "2+"


def test_jats_generator_self_heals_title_offset_drift(tmp_path: Path):
    """When _sanitize_title strips a prefix, offset drift self-heals using expected run text."""
    doc = Document(
        title="Abstract No: 4349 | Study on H2O dynamics",
        metadata={
            "abstract_number": "4349",
            # Run was calculated before 'Abstract No: 4349 | ' was stripped:
            "title_script_runs": [
                {"start": 30, "end": 31, "type": "sub", "text": "2"}
            ],
        },
    )

    output_path = tmp_path / "test_offset.xml"
    JATSGenerator().generate(doc, output_path)

    tree = etree.parse(str(output_path))
    titletext = tree.find(f".//{{{ANI_NS}}}titletext")
    assert titletext is not None
    inf = titletext.find(f"{{{ANI_NS}}}inf")
    assert inf is not None
    assert inf.text == "2"


def test_script_runs_detected_when_title_block_has_abstract_number_prefix():
    """Verify that a title block carrying a marker prefix still matches the stripped target title."""
    window = _min_window()

    block = TextBlock(
        id="b1",
        page=1,
        text="P017 GLP-1 receptor and H2O in T2D",
        bbox=[10, 10, 200, 20],
        x=10,
        y=10,
        width=190,
        height=10,
        font_size=12.0,
        metadata={
            "text_spans": [
                {"text": "P017 GLP-1 receptor and H", "size": 12.0, "origin": [10, 18], "flags": 0},
                {"text": "2", "size": 8.0, "origin": [180, 21], "flags": 0},
                {"text": "O in T2D", "size": 12.0, "origin": [185, 18], "flags": 0},
            ]
        },
    )

    title = "GLP-1 receptor and H2O in T2D"
    runs = window._script_runs_for_blocks([block], title)

    assert len(runs) == 1
    assert runs[0]["type"] == "sub"
    assert runs[0]["text"] == "2"
    assert title[runs[0]["start"]:runs[0]["end"]] == "2"


def test_script_runs_detected_via_font_flag():
    """Verify that PyMuPDF font flags (flags & 1) mark superscript even if font size is close to base."""
    window = _min_window()

    block = TextBlock(
        id="b2",
        page=1,
        text="Einstein gave E = mc2.",
        bbox=[10, 10, 200, 20],
        x=10,
        y=10,
        width=190,
        height=10,
        font_size=12.0,
        metadata={
            "text_spans": [
                {"text": "Einstein gave E = mc", "size": 12.0, "origin": [10, 18], "flags": 0},
                {"text": "2", "size": 11.5, "origin": [150, 17], "flags": 1},
                {"text": ".", "size": 12.0, "origin": [155, 18], "flags": 0},
            ]
        },
    )

    title = "Einstein gave E = mc2."
    runs = window._script_runs_for_blocks([block], title)

    assert len(runs) == 1
    assert runs[0]["type"] == "sup"
    assert runs[0]["text"] == "2"


def test_authors_and_body_remain_unaffected(tmp_path: Path):
    """Verify that author groups and body paragraphs do not receive unwanted script tags."""
    doc = Document(
        title="A Simple Title",
        abstract="A Simple Abstract",
        authors=[
            Author(
                id="a1",
                display_name="Jane Doe",
                given_names="Jane",
                surname="Doe",
                initials="J.",
                affiliation_ids=["aff1"],
            )
        ],
        affiliations=[
            Affiliation(
                id="aff1",
                text="Department of Biology, University of Science",
            )
        ],
        paragraphs=[
            Paragraph(
                id="p1",
                page=1,
                column=0,
                text="Body paragraph mentioning H2O and 10-3 without metadata runs.",
                bbox=[10, 50, 200, 80],
                status="accepted",
                role="body",
            )
        ],
    )

    output_path = tmp_path / "test_unaffected.xml"
    JATSGenerator().generate(doc, output_path)

    tree = etree.parse(str(output_path))
    root = tree.getroot()

    # Author surname has no children
    surname = root.find(f".//{{{CE_NS}}}surname")
    assert surname is not None
    assert surname.text == "Doe"
    assert len(list(surname)) == 0

    # Body paragraph has no script children when not flagged
    body_para = root.find(f".//{{{ANI_NS}}}body/{{{CE_NS}}}para")
    assert body_para is not None
    assert len(list(body_para)) == 0
    assert "H2O" in body_para.text
