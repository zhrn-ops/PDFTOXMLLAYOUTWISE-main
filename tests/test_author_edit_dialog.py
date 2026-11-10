from pathlib import Path

import pytest
from lxml import etree
from PySide6.QtWidgets import QDialog, QLineEdit

from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


SOURCES = [
    '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
    'xmlns:ce="http://www.elsevier.com/xml/ani/common"><author-group>'
    '<author seq="1"><ce:initials>A.</ce:initials><ce:surname>Smith</ce:surname>'
    '<ce:given-name>Alice</ce:given-name><ce:degrees>PhD</ce:degrees></author>'
    '</author-group></units>',
    '<article><contrib-group><contrib id="a1"><name><surname>Smith</surname>'
    '<given-names initials="A.">Alice</given-names></name>'
    '<xref ref-type="aff" rid="aff1">1</xref></contrib></contrib-group></article>',
    '<article><contrib-group><contrib><string-name>Alice Smith</string-name>'
    '</contrib></contrib-group></article>',
]


@pytest.mark.parametrize('source', SOURCES)
def test_confirming_unchanged_author_is_noop(qapp, monkeypatch, source):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    window._refresh()
    original = window.session.xml_text()
    window.author_list.setCurrentRow(1)
    monkeypatch.setattr(QDialog, 'exec', lambda self: QDialog.Accepted)
    try:
        window.edit_author()
        assert window.session.xml_text() == original
        assert not window.session.dirty
        assert len(window._history) == 1
    finally:
        window.deleteLater()


@pytest.mark.parametrize('source', SOURCES[:2])
def test_editing_surname_preserves_other_fields_and_undo(qapp, monkeypatch, source):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    window._refresh()
    original = window.session.xml_text()
    window.author_list.setCurrentRow(1)

    def accept(dialog):
        dialog.findChild(QLineEdit, 'author_surname').setText('Jones')
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, 'exec', accept)
    try:
        window.edit_author()
        assert window.session.xml_text() == original.replace('Smith', 'Jones')
        window._undo_field()
        assert window.session.xml_text() == original
        window._redo_field()
        assert window.session.xml_text() == original.replace('Smith', 'Jones')
    finally:
        window.deleteLater()


ANI_AUTHOR = (
    '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
    'xmlns:ce="http://www.elsevier.com/xml/ani/common"><author-group>'
    '<author seq="1" author-instance-id="auth1" orcid="0000-0001-2345-6789">'
    '<ce:initials>A.</ce:initials><ce:degrees/><ce:surname>Smith</ce:surname>'
    '<ce:given-name>Alice</ce:given-name><ce:suffix/><ce:e-address/>'
    '</author></author-group></units>'
)


def test_author_form_lists_attributes_and_every_person_field(tmp_path):
    session = XmlDocumentSession.from_text(ANI_AUTHOR, tmp_path / 'draft.xml')
    assert session.author_form(0) == {
        '@seq': '1',
        '@author-instance-id': 'auth1',
        '@orcid': '0000-0001-2345-6789',
        'initials': 'A.',
        'degrees': '',
        'surname': 'Smith',
        'given-name': 'Alice',
        'suffix': '',
        'e-address': '',
        'alt-name': '',
    }


def test_author_form_fills_empty_person_fields_and_attributes(tmp_path):
    session = XmlDocumentSession.from_text(ANI_AUTHOR, tmp_path / 'draft.xml')
    values = session.author_form(0)
    values.update({'degrees': 'PhD', 'suffix': 'Jr',
                   'e-address': 'alice@example.com',
                   '@orcid': '0000-0002-0000-0000'})

    assert session.set_author_form(0, values) is True
    author = etree.fromstring(session.xml_text().encode()).find(
        './/{http://www.elsevier.com/xml/ani/ani}author')
    assert author.get('orcid') == '0000-0002-0000-0000'
    assert author.get('author-instance-id') == 'auth1'
    assert [etree.QName(child).localname for child in author] == [
        'initials', 'degrees', 'surname', 'given-name', 'suffix', 'e-address',
    ]
    assert [child.text for child in author] == [
        'A.', 'PhD', 'Smith', 'Alice', 'Jr', 'alice@example.com',
    ]


def test_author_form_edits_the_alternate_language_name(tmp_path):
    session = XmlDocumentSession.from_text(ANI_AUTHOR, tmp_path / 'draft.xml')
    values = session.author_form(0)
    values['alt-name'] = 'علی اصغر پیشداد'

    assert session.set_author_form(0, values) is True
    author = etree.fromstring(session.xml_text().encode()).find(
        './/{http://www.elsevier.com/xml/ani/ani}author')
    alt = author.find('{http://www.elsevier.com/xml/ani/common}alt-name')
    assert alt.text == 'علی اصغر پیشداد'
    assert [etree.QName(child).localname for child in author][-1] == 'alt-name'


def test_author_form_reads_and_writes_alternate_name_as_one_whole_name(tmp_path):
    session = XmlDocumentSession.from_text(
        '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
        'xmlns:ce="http://www.elsevier.com/xml/ani/common"><author-group>'
        '<author><ce:surname>Mousavi</ce:surname>'
        '<ce:given-name>Somayeh</ce:given-name>'
        '<ce:alt-name><ce:given-name>سولماز</ce:given-name>'
        '<ce:surname>موسوی</ce:surname></ce:alt-name>'
        '</author></author-group></units>',
        tmp_path / 'draft.xml',
    )
    assert session.author_form(0)['alt-name'] == 'سولماز موسوی'
    assert session.author_alt_names(session.authors()[0]) == ['سولماز موسوی']

    values = session.author_form(0)
    values['alt-name'] = 'س. موسوی'
    assert session.set_author_form(0, values) is True
    alt = etree.fromstring(session.xml_text().encode()).find(
        './/{http://www.elsevier.com/xml/ani/ani}author').find(
        '{http://www.elsevier.com/xml/ani/common}alt-name')
    assert alt.text == 'س. موسوی'
    assert len(alt) == 0


def test_author_list_row_shows_captured_alternate_name(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
        'xmlns:ce="http://www.elsevier.com/xml/ani/common"><author-group>'
        '<author><ce:surname>Pishdad</ce:surname>'
        '<ce:given-name>Aliasghar</ce:given-name>'
        '<ce:alt-name>علی اصغر پیشداد</ce:alt-name>'
        '</author></author-group></units>',
        Path('draft.xml'),
    )
    window._refresh()
    try:
        assert window.author_list.item(1).text().strip() == (
            'Pishdad Aliasghar  —  علی اصغر پیشداد')
    finally:
        window.deleteLater()


def test_author_form_creates_missing_fields_in_schema_order(tmp_path):
    session = XmlDocumentSession.from_text(
        '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
        'xmlns:ce="http://www.elsevier.com/xml/ani/common"><author-group>'
        '<author><ce:surname>Smith</ce:surname></author></author-group></units>',
        tmp_path / 'draft.xml',
    )
    values = session.author_form(0)
    assert values['initials'] == '' and values['suffix'] == ''
    values.update({'initials': 'A.', 'degrees': 'PhD',
                   'given-name': 'Alice', 'e-address': 'a@b.c'})

    assert session.set_author_form(0, values) is True
    author = etree.fromstring(session.xml_text().encode()).find(
        './/{http://www.elsevier.com/xml/ani/ani}author')
    assert [etree.QName(child).localname for child in author] == [
        'initials', 'degrees', 'surname', 'given-name', 'e-address',
    ]
    assert author.find('{http://www.elsevier.com/xml/ani/common}initials').text == 'A.'


def test_author_form_rejects_invented_fields_and_empty_names(tmp_path):
    session = XmlDocumentSession.from_text(ANI_AUTHOR, tmp_path / 'draft.xml')
    values = session.author_form(0)
    values['city'] = 'Boston'
    with pytest.raises(ValueError, match='reopen the editor'):
        session.set_author_form(0, values)

    values = session.author_form(0)
    values.update({'initials': '', 'surname': '', 'given-name': ''})
    with pytest.raises(ValueError, match='non-empty name field'):
        session.set_author_form(0, values)


def test_author_form_refuses_inline_markup_inside_a_jats_name(tmp_path):
    session = XmlDocumentSession.from_text(
        '<article><contrib-group><contrib><name><surname>Smith</surname>'
        '<given-names>A<i>lice</i></given-names></name></contrib></contrib-group></article>',
        tmp_path / 'draft.xml',
    )
    values = session.author_form(0)
    values['given-names'] = 'Alice B.'

    with pytest.raises(ValueError, match='inline formatting'):
        session.set_author_form(0, values)
    assert '<i>lice</i>' in session.xml_text()


def test_author_form_does_not_duplicate_given_names(tmp_path):
    session = XmlDocumentSession.from_text(SOURCES[1], tmp_path / 'draft.xml')
    assert 'given-name' not in session.author_form(0)
    values = session.author_form(0)
    values['given-names'] = 'Alice B.'

    assert session.set_author_form(0, values) is True
    contrib = etree.fromstring(session.xml_text().encode()).find('.//contrib')
    assert [etree.QName(child).localname for child in contrib.find('name')] == [
        'surname', 'given-names',
    ]


def test_blank_author_is_listed_and_can_be_filled_in(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
        'xmlns:ce="http://www.elsevier.com/xml/ani/common"><author-group>'
        '<author><ce:initials/><ce:surname/></author></author-group></units>',
        Path('draft.xml'),
    )
    window._refresh()
    try:
        assert window.author_list.item(1).text().strip() == 'Unnamed author 1'
        window.author_list.setCurrentRow(1)

        def accept(dialog):
            dialog.findChild(QLineEdit, 'author_surname').setText('Sheu')
            dialog.findChild(QLineEdit, 'author_initials').setText('J.-Y.')
            return QDialog.Accepted

        monkeypatch.setattr(QDialog, 'exec', accept)
        window.edit_author()
        assert window.author_list.item(1).text().strip() == 'J.-Y. Sheu'
        author = etree.fromstring(window.session.xml_text().encode()).find(
            './/{http://www.elsevier.com/xml/ani/ani}author')
        assert author.find(
            '{http://www.elsevier.com/xml/ani/common}surname').text == 'Sheu'
    finally:
        window.deleteLater()


def test_dialog_edits_email_and_orcid_like_affiliation_fields(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(ANI_AUTHOR, Path('draft.xml'))
    window._refresh()
    window.author_list.setCurrentRow(1)

    def accept(dialog):
        dialog.findChild(QLineEdit, 'author_e-address').setText('alice@example.com')
        dialog.findChild(QLineEdit, 'author_orcid').setText('0000-0002-1111-2222')
        dialog.findChild(QLineEdit, 'author_degrees').setText('PhD')
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, 'exec', accept)
    try:
        window.edit_author()
        author = etree.fromstring(window.session.xml_text().encode()).find(
            './/{http://www.elsevier.com/xml/ani/ani}author')
        assert author.get('orcid') == '0000-0002-1111-2222'
        assert author.find(
            '{http://www.elsevier.com/xml/ani/common}e-address').text == 'alice@example.com'
        assert author.find(
            '{http://www.elsevier.com/xml/ani/common}degrees').text == 'PhD'
    finally:
        window.deleteLater()


def test_cancel_author_edit_preserves_xml(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(SOURCES[0], Path('draft.xml'))
    window._refresh()
    original = window.session.xml_text()
    window.author_list.setCurrentRow(1)

    def cancel(dialog):
        dialog.findChild(QLineEdit, 'author_surname').setText('Jones')
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', cancel)
    try:
        window.edit_author()
        assert window.session.xml_text() == original
        assert not window.session.dirty
    finally:
        window.deleteLater()
