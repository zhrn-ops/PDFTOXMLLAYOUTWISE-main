from pathlib import Path

import pytest

from pdf_to_jats.core.xml_correction import XmlDocumentSession


def session(extra='', second_given='Alice', second_surname='Smith', attributes=''):
    return XmlDocumentSession.from_text(
        '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
        'xmlns:ce="http://www.elsevier.com/xml/ani/common"><unit><head>'
        '<author-group><author seq="1" author-instance-id="a1">'
        '<ce:initials>A.</ce:initials><ce:surname>Smith</ce:surname>'
        '<ce:given-name>Alice</ce:given-name></author><affiliation>One</affiliation></author-group>'
        f'<author-group><author seq="2" {attributes}><ce:initials>A.</ce:initials>'
        f'<ce:surname>{second_surname}</ce:surname><ce:given-name>{second_given}</ce:given-name>'
        '</author><affiliation>Two</affiliation></author-group>'
        '<correspondence><person><ce:initials>A.</ce:initials><ce:surname>Smith</ce:surname>'
        '<ce:given-name>Alice</ce:given-name><ce:e-address>alice@example.org</ce:e-address>'
        '</person><affiliation>Contact address</affiliation></correspondence>'
        f'</head></unit>{extra}</units>', Path('sync.xml'))


def test_author_changes_sync_groups_and_correspondence_but_not_local_fields():
    s = session()
    form = s.author_form(0)
    form.update({'surname': 'Jones', 'given-name': 'Alicia', 'alt-name': 'أليس', '@seq': '9'})
    assert s.set_author_form(0, form)
    assert s.author_form(1)['surname'] == 'Jones'
    assert s.author_form(1)['given-name'] == 'Alicia'
    assert s.author_form(1)['alt-name'] == 'أليس'
    assert s.author_form(1)['@seq'] == '2'
    assert '@author-instance-id' not in s.author_form(1)
    assert s.corresponding_author_form()['surname'] == 'Jones'
    assert s.corresponding_author_form()['e-address'] == 'alice@example.org'
    assert 'Contact address' in s.xml_text() and '>Two<' in s.xml_text()


def test_corresponding_edit_syncs_back_and_can_be_edited_again():
    s = session()
    form = s.corresponding_author_form()
    form['surname'] = 'Jones'
    s.set_corresponding_author_form(form)
    assert all(s.author_form(i)['surname'] == 'Jones' for i in (0, 1))
    form = s.author_form(1)
    form['surname'] = 'Brown'
    s.set_author_form(1, form)
    assert s.author_form(0)['surname'] == 'Brown'
    assert s.corresponding_author_form()['surname'] == 'Brown'


def test_same_surname_different_given_name_is_not_matched():
    s = session(second_given='Andrew')
    form = s.author_form(0)
    form['surname'] = 'Jones'
    s.set_author_form(0, form)
    assert s.author_form(1)['surname'] == 'Smith'


def test_identifier_match_supports_different_existing_spelling():
    s = session(second_given='Alicia', attributes='author-instance-id="a1"')
    form = s.author_form(0)
    form['surname'] = 'Jones'
    s.set_author_form(0, form)
    assert s.author_form(1)['surname'] == 'Jones'
    assert s.author_form(1)['given-name'] == 'Alicia'


def test_conflicting_identifiers_prevent_name_match():
    s = session(attributes='author-instance-id="different"')
    form = s.author_form(0)
    form['surname'] = 'Jones'
    s.set_author_form(0, form)
    assert s.author_form(1)['surname'] == 'Smith'


def test_synchronization_does_not_cross_articles():
    s = session(extra='<unit><head><author-group><author><ce:surname>Smith</ce:surname>'
                '<ce:given-name>Alice</ce:given-name></author></author-group></head></unit>')
    form = s.author_form(0)
    form['surname'] = 'Jones'
    s.set_author_form(0, form)
    assert s.author_form(2)['surname'] == 'Smith'


def test_matching_inline_markup_blocks_entire_edit_atomically():
    s = session(second_surname='<ce:italic>Smith</ce:italic>')
    original = s.xml_text()
    form = s.author_form(0)
    form['surname'] = 'Jones'
    with pytest.raises(ValueError, match='inline formatting'):
        s.set_author_form(0, form)
    assert s.xml_text() == original
    assert not s.dirty


def test_initial_only_correspondence_is_not_guessed_between_names():
    s = session(second_given='Andrew')
    person, _, _ = s.correspondence()
    person.remove(next(child for child in person if s._local_name(child) == 'given-name'))
    form = s.author_form(0)
    form['surname'] = 'Jones'
    s.set_author_form(0, form)
    assert s.corresponding_author_form()['surname'] == 'Smith'


def test_jats_wrapped_names_preserve_affiliation_references():
    s = XmlDocumentSession.from_text(
        '<article><front><contrib-group><contrib id="a1"><name><surname>Smith</surname>'
        '<given-names>Alice</given-names></name><xref rid="aff1"/></contrib></contrib-group>'
        '<contrib-group><contrib id="a2"><name><surname>Smith</surname>'
        '<given-names>Alice</given-names></name><xref rid="aff2"/></contrib></contrib-group>'
        '</front></article>', Path('jats.xml'))
    form = s.author_form(0)
    form['given-names'] = 'Alicia'
    s.set_author_form(0, form)
    assert s.author_form(1)['given-names'] == 'Alicia'
    assert s.authors()[1].find('xref').get('rid') == 'aff2'
    assert s.authors()[1].get('id') == 'a2'


def test_ui_undo_and_redo_restore_all_synchronized_entries(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog, QLineEdit
    from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow

    window = XmlCorrectionWindow()
    window.session = session()
    window._refresh()
    original = window.session.xml_text()
    window.author_list.setCurrentRow(1)

    def accept(dialog):
        dialog.findChild(QLineEdit, 'author_surname').setText('Jones')
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, 'exec', accept)
    try:
        window.edit_author()
        edited = window.session.xml_text()
        assert edited.count('>Jones<') == 3
        window._undo_field()
        assert window.session.xml_text() == original
        window._redo_field()
        assert window.session.xml_text() == edited
    finally:
        window.deleteLater()
