"""Regression tests for Phase 3 — XML Revision and Content Integrity.

Covers:
- Preservation of manual XML corrections during regeneration and recovery of archived revisions.
- Prevention of stale validation results (binding to exact revision fingerprint).
- Preservation of alphabetic and Greek superscripts/subscripts (A06).
- Non-UTF-8 XML handling (ISO-8859-1, UTF-16) across open, activate, undo/redo, workspace save/reopen, raw edits, and UTF-8 export (A02).
- Safe restoration of malformed or incomplete workspace files (R02).
"""

from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
import pytest
from lxml import etree

from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.core.xml_revisions import XmlRevision, validation_record
from pdf_to_jats.core.xml_validation import ExportMode, ValidationStatus, fingerprint, validate_xml
from pdf_to_jats.core.draft_workspace import canonical_history, session_from_record, stage_workspace
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow
from pdf_to_jats.models.document import Document
from pdf_to_jats.models.block import TextBlock
from pdf_to_jats.models.author import Author
from pdf_to_jats.models.affiliation import Affiliation


ANI_NS = JATSGenerator.ANI_NS
CE_NS = JATSGenerator.CE_NS


# ─────────────────────────────────────────────────────────────────────────────
# 1. Preservation of manual XML corrections during regeneration & archives
# ─────────────────────────────────────────────────────────────────────────────

def test_regeneration_archived_revision_is_fully_recoverable(qapp, monkeypatch):
    """When new PDF generation is accepted, the previous corrected revision is archived and can be restored."""
    window = XmlCorrectionWindow()
    try:
        initial_xml = '<article><article-title>Original Extraction</article-title><abstract><p>Text</p></abstract></article>'
        window.load_xml_text(initial_xml, Path("article.xml"))
        key = window._draft_key

        # Make manual corrections
        window.title_edit.setPlainText("Manually Corrected Title")
        window.abstract_edit.setPlainText("Manually Corrected Abstract")
        corrected_title = window.session.title()
        assert corrected_title == "Manually Corrected Title"

        # Validate the corrected draft
        window.session.validate()
        assert window.session.validation_result is not None
        corrected_fp = fingerprint(window.session.xml_bytes())

        # Accept new PDF extraction
        new_xml = '<article><article-title>Second Extraction</article-title><abstract><p>New Text</p></abstract></article>'
        monkeypatch.setattr(window, "review_regeneration", lambda *_: True)
        assert window.load_xml_text(new_xml, Path("article.xml"))

        # Current active draft is the new extraction
        assert window.session.title() == "Second Extraction"
        # The new draft has NOT been validated, so its validation_result must be None
        assert window.session.validation_result is None

        # Verify archive exists
        archive_key = f"{key}|revision:1"
        assert archive_key in window._drafts

        # Activate the archived revision
        assert window.activate_draft(archive_key)
        assert window.session.title() == "Manually Corrected Title"
        assert window.session.abstract() == "Manually Corrected Abstract"
        # The restored session's XML matches what was corrected
        assert fingerprint(window.session.xml_bytes()) == corrected_fp
    finally:
        window.deleteLater()


def test_regeneration_reject_preserves_corrections_and_marks_pending(qapp, monkeypatch):
    """When regeneration is rejected, existing corrections remain active and new XML is pending."""
    window = XmlCorrectionWindow()
    try:
        initial_xml = '<article><article-title>First</article-title></article>'
        window.load_xml_text(initial_xml, Path("article.xml"))
        key = window._draft_key

        window.title_edit.setPlainText("My Important Edits")
        assert window.session.title() == "My Important Edits"

        # User rejects new extraction
        new_xml = '<article><article-title>Second From PDF</article-title></article>'
        monkeypatch.setattr(window, "review_regeneration", lambda *_: False)
        window.load_xml_text(new_xml, Path("article.xml"))

        # Title is still user's edits
        assert window.session.title() == "My Important Edits"
        record = window._drafts[key]
        assert record.get("pending_generated") == new_xml
        assert "not been applied" in window.status.text()
    finally:
        window.deleteLater()


def test_new_extraction_does_not_inherit_stale_validation_or_export():
    """A new candidate session from fresh extraction must not carry over previous validation records."""
    initial = '<article><article-title>Title 1</article-title></article>'
    session = XmlDocumentSession.from_text(initial, Path("art.xml"))
    session.validate()
    assert session.last_validated is not None
    old_fp = session.last_validated["revision"]["sha256"]

    # Simulating load of new extraction
    new_xml = '<article><article-title>Title 2 Changed</article-title></article>'
    new_session = XmlDocumentSession.from_text(new_xml, Path("art.xml"))
    new_fp = fingerprint(new_session.xml_bytes())
    assert old_fp != new_fp

    # New session must not consider old validation valid
    assert new_session.validation_result is None
    assert new_session.last_validated is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Prevention of stale validation results
# ─────────────────────────────────────────────────────────────────────────────

def test_validation_invalidated_by_field_and_raw_edits(tmp_path: Path):
    """Any modification to session XML clears validation_result and blocks save_copy."""
    xml = '<article><article-title>Valid Title</article-title></article>'
    session = XmlDocumentSession.from_text(xml, tmp_path / "article.xml")
    session.validate()
    assert session.validation_result is not None

    # Edit title
    session.set_title("Updated Title")
    assert session.validation_result is None
    with pytest.raises(ValueError, match="Validate the current XML"):
        session.save_copy(tmp_path / "out.xml")

    # Re-validate
    session.validate()
    assert session.validation_result is not None

    # Raw edit
    session.commit_raw('<article><article-title>Raw Edit</article-title></article>')
    assert session.validation_result is None
    with pytest.raises(ValueError, match="Validate the current XML"):
        session.save_copy(tmp_path / "out.xml")


def test_reopened_draft_requires_validation_before_export(tmp_path: Path):
    """When a workspace draft is restored, it retains provenance but requires fresh validation before export."""
    xml = '<article><article-title>Draft Title</article-title></article>'
    session = XmlDocumentSession.from_text(xml, tmp_path / "article.xml")
    session.validate()
    val_record = session.last_validated

    record = {
        "xml": session.xml_text(),
        "path": str(session.path),
        "current_revision": XmlRevision(session.xml_bytes()).to_record(),
        "last_validated": val_record,
    }
    restored = session_from_record(record)
    # Validation status is cleared on restoration
    assert restored.validation_result is None
    with pytest.raises(ValueError, match="Validate the current XML"):
        restored.save_copy(tmp_path / "out.xml")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Preservation of alphabetic and Greek superscripts and subscripts (A06)
# ─────────────────────────────────────────────────────────────────────────────

def test_alphabetic_subscript_and_superscript_preserved_in_ani_xml(tmp_path: Path):
    """Verify that alphabetic and Greek subscript/superscript runs are preserved in title and abstract."""
    doc = Document(
        title="Measurement of Vmax and Km in enzyme kinetics",
        abstract="Rate constant was ka and temperature coefficient was αA with Ca2+ ions.",
        metadata={
            "title_script_runs": [
                {"start": 16, "end": 19, "type": "sub", "text": "max", "source": "manual"},
                {"start": 25, "end": 26, "type": "sub", "text": "m", "source": "geometry"},
            ],
            "abstract_script_runs": [
                {"start": 19, "end": 20, "type": "sub", "text": "a", "source": "font_flag"},
                {"start": 54, "end": 55, "type": "sub", "text": "A", "source": "lexicon"},
                {"start": 63, "end": 65, "type": "sup", "text": "2+", "source": "geometry"},
            ],
        },
    )

    out_file = tmp_path / "enzymes.xml"
    JATSGenerator().generate(doc, out_file)

    tree = etree.parse(str(out_file))
    root = tree.getroot()

    # Title check: V<inf>max</inf> and K<inf>m</inf>
    titletext = root.find(f".//{{{ANI_NS}}}titletext")
    assert titletext is not None
    infs = titletext.findall(f"{{{ANI_NS}}}inf")
    assert len(infs) == 2
    assert infs[0].text == "max"
    assert infs[1].text == "m"

    # Abstract check: k<inf>a</inf>, α<inf>A</inf>, and Ca<sup>2+</sup>
    para = root.find(f".//{{{ANI_NS}}}abstract/{{{CE_NS}}}para")
    assert para is not None
    abs_infs = para.findall(f"{{{ANI_NS}}}inf")
    abs_sups = para.findall(f"{{{ANI_NS}}}sup")
    assert len(abs_infs) == 2
    assert abs_infs[0].text == "a"
    assert abs_infs[1].text == "A"
    assert len(abs_sups) == 1
    assert abs_sups[0].text == "2+"


def test_alphabetic_script_runs_without_explicit_source_default_to_manual(tmp_path: Path):
    """Script runs without explicit 'source' key default to manual and are preserved when offsets match."""
    doc = Document(
        title="Activity of ATPase_a and IgG_b antibodies",
        metadata={
            "title_script_runs": [
                {"start": 19, "end": 20, "type": "sub", "text": "a"},
                {"start": 29, "end": 30, "type": "sub", "text": "b"},
            ]
        },
    )
    out_file = tmp_path / "antibodies.xml"
    JATSGenerator().generate(doc, out_file)

    tree = etree.parse(str(out_file))
    titletext = tree.find(f".//{{{ANI_NS}}}titletext")
    assert titletext is not None
    infs = titletext.findall(f"{{{ANI_NS}}}inf")
    assert len(infs) == 2
    assert infs[0].text == "a"
    assert infs[1].text == "b"


def test_stale_alphabetic_offset_drift_is_dropped_not_relocated(tmp_path: Path):
    """Unlike numeric runs, alphabetic scripts with stale offsets are not ambiguously relocated to word letters."""
    doc = Document(
        title="Study on enzymes and kinetics",  # 'max' is not at offset 10..13
        metadata={
            "title_script_runs": [
                {"start": 10, "end": 13, "type": "sub", "text": "max", "source": "geometry"}
            ]
        },
    )
    out_file = tmp_path / "stale.xml"
    JATSGenerator().generate(doc, out_file)

    tree = etree.parse(str(out_file))
    titletext = tree.find(f".//{{{ANI_NS}}}titletext")
    assert titletext is not None
    infs = titletext.findall(f"{{{ANI_NS}}}inf")
    # Dropped because text[10:13] (' enzym') does not match expected ('max')
    assert len(infs) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Non-UTF-8 XML handling (ISO-8859-1, UTF-16) across lifecycle (A02)
# ─────────────────────────────────────────────────────────────────────────────

def test_iso_8859_1_lifecycle_open_activate_undo_and_workspace_restore(qapp, tmp_path: Path):
    """ISO-8859-1 document survives opening, draft activation, undo/redo, and workspace save/open without mojibake."""
    raw_iso_bytes = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
        '<article><article-title>Caf\xe9 &amp; Cr\xe8me</article-title><abstract><p>Donn\xe9es</p></abstract></article>'
    ).encode("iso-8859-1")

    src_file = tmp_path / "source_iso.xml"
    src_file.write_bytes(raw_iso_bytes)

    session = XmlDocumentSession.open(src_file)
    assert session.encoding.upper() in {"ISO-8859-1", "ISO8859-1"}
    assert session.title() == "Café & Crème"
    assert session.abstract() == "Données"
    assert session.source_bytes == raw_iso_bytes

    # from_text keeps ISO-8859-1 when text is encodable in ISO-8859-1
    from_txt_session = XmlDocumentSession.from_text(session.xml_text(), tmp_path / "draft.xml")
    assert from_txt_session.encoding.upper() in {"ISO-8859-1", "ISO8859-1"}
    assert from_txt_session.title() == "Café & Crème"

    # Test undo/redo in XmlCorrectionWindow
    window = XmlCorrectionWindow()
    try:
        window.load_xml_text(session.xml_text(), tmp_path / "article.xml")
        assert window.session.title() == "Café & Crème"

        # Edit title
        window.title_edit.setPlainText("Café Modifié")
        assert window.session.title() == "Café Modifié"

        # Undo
        window._undo_field()
        assert window.session.title() == "Café & Crème"

        # Redo
        window._redo_field()
        assert window.session.title() == "Café Modifié"

        # Undo back to start
        window._undo_field()
        assert window.session.title() == "Café & Crème"

        # Workspace round trip (.jatsdraft)
        ws_text = window._workspace_text()
        staged = stage_workspace(window._workspace_content(ws_text))
        restored_session = session_from_record(staged["articles"][window._draft_key])
        assert restored_session.title() == "Café & Crème"
        assert restored_session.abstract() == "Données"
    finally:
        window.deleteLater()


def test_utf16_document_lifecycle(tmp_path: Path):
    """UTF-16 XML document opens, parses Unicode characters, and preserves content."""
    utf16_content = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<article><article-title>Scientific Café with α-helix</article-title></article>'
    )
    utf16_bytes = utf16_content.encode("utf-16")
    src_file = tmp_path / "source_utf16.xml"
    src_file.write_bytes(utf16_bytes)

    session = XmlDocumentSession.open(src_file)
    assert session.encoding.upper() in {"UTF-16", "UTF-16LE", "UTF-16BE"}
    assert session.title() == "Scientific Café with α-helix"
    assert session.source_bytes == utf16_bytes

    reopened = XmlDocumentSession.from_text(session.xml_text(), tmp_path / "draft.xml")
    assert reopened.title() == "Scientific Café with α-helix"


def test_raw_editor_declaration_edit_and_utf8_export(tmp_path: Path):
    """User can edit the encoding declaration in raw tab, and export a UTF-8 copy."""
    xml = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<article><article-title>Caf\xe9</article-title></article>'
    session = XmlDocumentSession.from_text(xml, tmp_path / "draft.xml")

    # Change declaration in raw editor to UTF-8
    updated_raw = '<?xml version="1.0" encoding="UTF-8"?>\n<article><article-title>Caf\xe9 \u03b1</article-title></article>'
    ok, err, _, _ = session.commit_raw(updated_raw)
    assert ok and err is None
    assert session.encoding == "UTF-8"
    assert session.title() == "Café α"

    # Export UTF-8 copy
    session.validate()
    out_copy = tmp_path / "exported_utf8.xml"
    session.save_copy(out_copy, encoding="UTF-8")

    out_bytes = out_copy.read_bytes()
    assert b"encoding=\"UTF-8\"" in out_bytes or b"encoding='UTF-8'" in out_bytes
    assert "Café α".encode("utf-8") in out_bytes


# ─────────────────────────────────────────────────────────────────────────────
# 5. Safe restoration of malformed or incomplete workspace files (R02)
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_workspace_rejects_corrupted_revision_fingerprint():
    """stage_workspace detects tampering or corruption where bytes do not match revision sha256."""
    data = b"<article><article-title>Real</article-title></article>"
    b64 = base64.b64encode(data).decode("ascii")
    bad_record = {
        "version": 1,
        "active": "art1",
        "articles": {
            "art1": {
                "path": "test.xml",
                "xml": data.decode(),
                "current_revision": {"sha256": "wrong_sha256_hash", "bytes_base64": b64},
                "history": [data.decode()],
                "history_index": 0,
            }
        },
    }
    with pytest.raises(ValueError, match="fingerprint does not match"):
        stage_workspace(bad_record)


def test_stage_workspace_rejects_malformed_xml_in_current_revision():
    """stage_workspace rejects corrupted XML bytes in revision record."""
    bad_bytes = b"<article><unclosed>"
    bad_record = {
        "version": 1,
        "active": "art1",
        "articles": {
            "art1": {
                "path": "test.xml",
                "xml": "<article><unclosed>",
                "current_revision": {
                    "sha256": fingerprint(bad_bytes),
                    "bytes_base64": base64.b64encode(bad_bytes).decode("ascii"),
                },
                "history": ["<article><unclosed>"],
                "history_index": 0,
            }
        },
    }
    with pytest.raises(Exception):
        stage_workspace(bad_record)


def test_activate_draft_marks_unparsed_raw_edits_as_invalid(qapp):
    """When a workspace containing unparsed raw edits is activated, session.raw_valid is False."""
    window = XmlCorrectionWindow()
    try:
        valid_xml = "<article><article-title>Valid</article-title></article>"
        unparsed_raw = "<article><article-title>Unclosed Tag"
        record = {
            "path": "article.xml",
            "xml": valid_xml,
            "raw": unparsed_raw,
            "history": [valid_xml],
            "history_index": 0,
        }
        window._drafts["test_draft"] = record
        assert window.activate_draft("test_draft")

        # Raw editor has the unparsed text
        assert window.raw.toPlainText() == unparsed_raw
        # Session raw_valid must be False so unparsed raw edits cannot export
        assert window.session.raw_valid is False
    finally:
        window.deleteLater()


def test_stage_workspace_rejects_invalid_bounding_boxes():
    """decode_workflow rejects malformed bounding boxes where x2 < x1 or y2 < y1."""
    block = TextBlock(
        id="b1", page=1, text="Test",
        bbox=[100, 200, 50, 150],  # Inverted box
        x=100, y=200, width=-50, height=-50, font_size=12.0
    )
    doc = Document(blocks=[block])
    from dataclasses import asdict
    payload = {
        "version": 1,
        "articles": {},
        "workflow": {
            "document": asdict(doc),
            "state": {
                "_finished_segment_keys": [],
                "_deleted_segment_keys": [],
                "_current_segment_key": None,
                "_article_draft_keys": {},
                "_startup_flow": True,
                "_explicit_number_workflow": True,
                "_html_preview_merges": [],
                "_manual_document_author_links": {},
            },
        },
    }
    with pytest.raises(ValueError, match="Invalid workspace bounding box"):
        stage_workspace(payload)
