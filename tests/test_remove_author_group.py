from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox, QInputDialog, QPushButton

from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


SOURCE = (
    '<units xmlns="http://www.elsevier.com/xml/ani/ani">'
    '<author-group seq="1"><author id="a1"><surname>Smith</surname></author>'
    '<affiliation id="aff1">University A</affiliation></author-group>'
    '<author-group seq="2"><author><surname>Jones</surname></author>'
    '<affiliation>University B</affiliation></author-group></units>'
)


@pytest.mark.parametrize('confirmed', [True, False])
def test_remove_group_refreshes_xml_and_supports_undo(qapp, monkeypatch, confirmed):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(SOURCE, Path('draft.xml'))
    window._refresh()
    original = window.session.xml_text()
    window.author_list.setCurrentRow(0)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args:
                        QMessageBox.Yes if confirmed else QMessageBox.No)
    try:
        window.remove_author()
        if not confirmed:
            assert window.session.xml_text() == original
            assert not window.session.dirty
            return
        assert len(window.session.affiliation_groups()) == 1
        assert [window.session.author_name(a) for a in window.session.authors()] == ['Jones']
        assert 'University A' not in window.raw.toPlainText()
        assert window.session.dirty
        removed = window.session.xml_text()
        window._undo_field()
        assert window.session.xml_text() == original
        window._redo_field()
        assert window.session.xml_text() == removed
    finally:
        window.deleteLater()


def test_group_removal_rejects_external_references():
    source = SOURCE.replace('</units>', '<xref rid="other aff1 a1"/></units>')
    session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    original = session.xml_text()
    with pytest.raises(ValueError, match='references'):
        session.remove_author_group(session.affiliation_groups()[0][3])
    assert session.xml_text() == original
    assert not session.dirty


def test_last_empty_group_can_be_removed():
    session = XmlDocumentSession.from_text('<root><author-group/></root>', Path('draft.xml'))
    session.remove_author_group(session.affiliation_groups()[0][3])
    assert session.affiliation_groups() == []
    assert session.dirty


def test_add_group_selects_editable_group_and_supports_undo(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(SOURCE, Path('draft.xml'))
    window._refresh()
    original = window.session.xml_text()
    try:
        window.add_author_group()
        groups = window.session.affiliation_groups()
        assert len(groups) == 3
        group = groups[-1][3]
        assert group.get('seq') == '3'
        assert len(groups[-1][1]) == 1
        assert window.author_list.currentItem().text() == 'Group 3: No affiliation specified'
        assert 'author-group seq="3"' in window.raw.toPlainText()
        window._undo_field()
        assert window.session.xml_text() == original
        window._redo_field()
        assert len(window.session.affiliation_groups()) == 3
        group = window.session.affiliation_groups()[-1][3]
        values = window.session.affiliation_form(group)
        values['organization'] = 'New University'
        window.session.set_affiliation_form(group, values)
        window.session.add_author('Peters', group=group)
        assert [window.session._local_name(child) for child in group] == ['author', 'author', 'affiliation']
        assert window.session.author_name(group[1]) == 'Peters'
    finally:
        window.deleteLater()


def test_add_first_group_before_abstract():
    session = XmlDocumentSession.from_text(
        '<root xmlns="http://www.elsevier.com/xml/ani/ani"><head>'
        '<citation-title/><abstract/></head></root>', Path('draft.xml'))
    group = session.add_author_group()
    assert [session._local_name(child) for child in group.getparent()] == [
        'citation-title', 'author-group', 'abstract']
    assert group.get('seq') == '1'
    assert session.dirty


@pytest.mark.parametrize('copy', [True, False])
@pytest.mark.parametrize('accepted', [True, False])
def test_transfer_author_updates_groups_and_supports_undo(qapp, monkeypatch, copy, accepted):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(SOURCE, Path('draft.xml'))
    window._refresh()
    window.author_list.setCurrentRow(1)
    original = window.session.xml_text()
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *args: (args[3][0], accepted))
    try:
        window.transfer_author(copy=copy)
        if not accepted:
            assert window.session.xml_text() == original
            assert not window.session.dirty
            return
        groups = window.session.affiliation_groups()
        assert len(groups[0][1]) == (1 if copy else 0)
        assert len(groups[1][1]) == 2
        target = groups[1][3]
        assert [window.session._local_name(child) for child in target] == ['author', 'author', 'affiliation']
        assert window.session.author_name(target[1]) == 'Smith'
        assert target[1].get('id') == ('a1_copy1' if copy else 'a1')
        assert window.author_list.currentItem().text().strip() == 'Smith'
        changed = window.session.xml_text()
        window._undo_field()
        assert window.session.xml_text() == original
        window._redo_field()
        assert window.session.xml_text() == changed
    finally:
        window.deleteLater()


@pytest.mark.parametrize('copy', [True, False])
@pytest.mark.parametrize('sequence', ['6', '1', None])
def test_transfer_preserves_original_author_sequence(copy, sequence):
    session = XmlDocumentSession.from_text(SOURCE, Path('draft.xml'))
    author = session.authors()[0]
    if sequence is not None:
        author.set('seq', sequence)
    target = session.affiliation_groups()[1][3]
    target[0].set('seq', '4')
    transferred = session.transfer_author(0, target, copy=copy)
    assert transferred.get('seq') == sequence
    assert target[0].get('seq') == '4'
    if copy:
        assert author.get('seq') == sequence
    reloaded = XmlDocumentSession.from_text(session.xml_text(), Path('draft.xml'))
    assert reloaded.affiliation_groups()[1][3][1].get('seq') == sequence


def test_copy_preserves_markup_and_remaps_internal_references():
    session = XmlDocumentSession.from_text(SOURCE.replace(
        '<surname>Smith</surname>', '<surname><bold id="n1">Smith</bold></surname><xref rid="n1 external"/>'), Path('draft.xml'))
    target = session.affiliation_groups()[1][3]
    first = session.transfer_author(0, target, copy=True)
    second = session.transfer_author(0, target, copy=True)
    assert first[0][0].get('id') == 'n1_copy1'
    assert first[1].get('rid') == 'n1_copy1 external'
    assert second.get('id') == 'a1_copy2'
    assert session.authors()[0].get('id') == 'a1'
    before = session.xml_text()
    with pytest.raises(ValueError, match='different'):
        session.transfer_author(0, session.authors()[0].getparent())
    assert session.xml_text() == before


def test_make_existing_author_corresponding_and_undo(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(SOURCE, Path('draft.xml'))
    window._refresh()
    original = window.session.xml_text()
    try:
        window.findChild(QPushButton, 'corresponding_author_1').click()
        person, details, affiliations = window.session.correspondence()
        assert ('surname', 'Jones') in details
        assert window.session._affiliation_label(affiliations[0]) == 'University B'
        assert window.tabs.tabText(window.tabs.currentIndex()) == 'Corresponding Author'
        assert len(window.session.authors()) == 2
        window._undo_field()
        assert window.session.xml_text() == original
        window._redo_field()
        window.author_list.itemWidget(window.author_list.item(1)).findChild(
            QPushButton, 'corresponding_author_0').click()
        person, details, affiliations = window.session.correspondence()
        assert ('surname', 'Smith') in details
        assert window.session._affiliation_label(affiliations[0]) == 'University A'
        assert affiliations[0].get('id') != 'aff1'
        assert len(window.session.tree.xpath('//*[local-name()="correspondence"]')) == 1
    finally:
        window.deleteLater()
