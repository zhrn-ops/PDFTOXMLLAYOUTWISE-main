from pathlib import Path

from PySide6.QtCore import Qt
import pytest
from lxml import etree
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QPushButton, QPlainTextEdit

from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


def session():
    return XmlDocumentSession.from_text('''<units><head>
      <author-group><affiliation id="a"><organization>University A</organization>
        <country iso-code="USA"/><source-text>Original text</source-text>
      </affiliation></author-group>
      <author-group><affiliation id="b"><country iso-code="usa"/>
        <organization> university   A </organization><source-text>Other text</source-text>
      </affiliation></author-group>
      <author-group><affiliation><organization>University A</organization>
        <country iso-code="CAN"/></affiliation></author-group>
      <author-group><affiliation/></author-group>
      <author-group><affiliation/></author-group>
      <correspondence><affiliation><organization>University A</organization>
        <country iso-code="USA"/></affiliation></correspondence>
    </head></units>''', Path('duplicates.xml'))


def test_matches_current_fields_ignoring_ids_source_and_formatting():
    s = session()
    before = s.xml_text()
    matches = s.duplicate_affiliations()
    assert list(matches.values()) == [['Group 2'], ['Group 1']]
    assert s.xml_text() == before
    assert not s.dirty


def test_jats_labels_and_empty_affiliations_are_not_match_content():
    s = XmlDocumentSession.from_text('''<article><aff id="a"><label>1</label>University A</aff>
        <aff id="b"><label>2</label> university A </aff><aff/><aff/>
        <aff>University B</aff></article>''', Path('jats.xml'))
    assert list(s.duplicate_affiliations().values()) == [['Group 2'], ['Group 1']]


def test_highlights_are_editable_and_clear_after_correction(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    try:
        window.session = session()
        window._refresh_fields()
        first = window.author_list.item(0)
        assert 'Repeated affiliation' in first.text()
        assert 'Group 2' in first.toolTip()
        assert first.background().color().name() == '#fff0bf'
        assert first.data(Qt.UserRole + 1)
        assert 'Repeated affiliation' not in window.author_list.item(2).text()
        def accept_correction(dialog):
            dialog.findChild(QLineEdit, 'affiliation_organization').setText('University B')
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
            return QDialog.Accepted

        monkeypatch.setattr(QDialog, 'exec', accept_correction)
        window.author_list.setCurrentRow(1)
        window.author_list.itemDoubleClicked.emit(window.author_list.item(1))
        assert all('Repeated affiliation' not in window.author_list.item(i).text()
                   for i in range(window.author_list.count()))
        for index in (0, 1):
            item = window.author_list.item(index)
            assert item.background().style() == Qt.NoBrush
            assert 'Repeated affiliation' not in item.toolTip()
    finally:
        window.session.dirty = False
        window.close()


def test_merge_preserves_authors_and_sequence_numbers():
    s = session()
    entries = s.duplicate_affiliation_sets()[0]
    for seq, (_, node) in enumerate(entries, 1):
        author = etree.Element('author', seq=str(seq), id=f'author{seq}')
        etree.SubElement(author, 'surname').text = f'Person {seq}'
        node.getparent().insert(0, author)
    s.merge_duplicate_affiliations([node for _, node in entries])
    assert [a.get('seq') for a in s.authors()] == ['1', '2']
    assert [a.get('id') for a in s.authors()] == ['author1', 'author2']
    assert len({a.getparent() for a in s.authors()}) == 1
    assert not s.duplicate_affiliations()
    assert s.dirty


def test_referenced_affiliation_is_not_removed_or_partially_modified():
    s = session()
    etree.SubElement(s.tree.getroot(), 'xref', rid='b')
    before = s.xml_text()
    with pytest.raises(ValueError, match='references'):
        s.merge_duplicate_affiliations([node for _, node in s.duplicate_affiliation_sets()[0]])
    assert s.xml_text() == before
    assert not s.dirty


def test_duplicate_review_removes_set_and_supports_undo(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = session()
    original = window.session.xml_text()
    window._refresh()

    def review(dialog):
        details = dialog.findChild(QPlainTextEdit, 'duplicate_details')
        assert 'Group 1 — KEEP' in details.toPlainText()
        assert 'Group 2 — REMOVE' in details.toPlainText()
        dialog.findChild(QPushButton, 'merge_duplicate_affiliations').click()
        assert details.toPlainText() == 'No duplicate affiliations remain.'
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, 'exec', review)
    try:
        window.review_duplicates.click()
        assert not window.review_duplicates.isEnabled()
        assert not window.session.duplicate_affiliations()
        window._undo_field()
        assert window.session.xml_text() == original
        assert window.review_duplicates.isEnabled()
    finally:
        window.session.dirty = False
        window.close()
