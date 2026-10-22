"""Tests for the Corresponding Author tab and correspondence lookup."""

from pathlib import Path

from lxml import etree
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QPushButton

from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow

ANI = (
    '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
    'xmlns:ce="http://www.elsevier.com/xml/ani/common"><head>'
    '<author-group seq="1"><author seq="1"><ce:initials>A.</ce:initials>'
    '<ce:surname>Smith</ce:surname></author>'
    '<affiliation affiliation-instance-id="aff1"><organization>Uni</organization>'
    '<city>Town</city><country iso-code="USA"/></affiliation></author-group>'
    '<correspondence><person><ce:initials>A.</ce:initials>'
    '<ce:degrees>MD</ce:degrees><ce:surname>Smith</ce:surname>'
    '<ce:email>a.smith@example.com</ce:email></person>'
    '<affiliation affiliation-instance-id="corr1"><organization>Corr Uni</organization>'
    '<city>Boston</city></affiliation></correspondence>'
    '</head><tail/></units>'
)


def _session(tmp_path, source=ANI):
    return XmlDocumentSession.from_text(source, tmp_path / 'draft.xml')


def _window(tmp_path, source=ANI):
    window = XmlCorrectionWindow()
    window.session = _session(tmp_path, source)
    window._refresh()
    return window


def _rows(list_widget):
    return [list_widget.item(i).text() for i in range(list_widget.count())]


def _tab_titles(window):
    return [window.tabs.tabText(i) for i in range(window.tabs.count())]


def test_correspondence_lookup_returns_person_details_and_affiliations(tmp_path):
    session = _session(tmp_path)
    person, details, affiliations = session.correspondence()

    assert etree.QName(person).localname == 'person'
    assert details == [
        ('initials', 'A.'),
        ('degrees', 'MD'),
        ('surname', 'Smith'),
        ('email', 'a.smith@example.com'),
    ]
    assert [etree.QName(node).localname for node in affiliations] == ['affiliation']
    assert session._affiliation_label(affiliations[0]) == 'Corr Uni Boston'


def test_correspondence_falls_back_to_the_matching_author_group(tmp_path):
    source = ANI.replace(
        '<affiliation affiliation-instance-id="corr1"><organization>Corr Uni</organization>'
        '<city>Boston</city></affiliation>',
        '',
    )
    session = _session(tmp_path, source)
    _person, _details, affiliations = session.correspondence()

    assert [session._affiliation_label(node) for node in affiliations] == ['Uni Town']


def test_correspondence_lookup_returns_nothing_without_a_correspondence_entry(tmp_path):
    session = XmlDocumentSession.from_text(
        '<units xmlns="http://www.elsevier.com/xml/ani/ani"><head/></units>',
        tmp_path / 'draft.xml',
    )

    assert session.correspondence() == (None, [], [])


def test_corresponding_author_tab_sits_after_abstract_and_lists_details(qapp, tmp_path):
    window = _window(tmp_path)
    try:
        titles = _tab_titles(window)
        assert 'Corresponding Author' in titles
        assert titles.index('Corresponding Author') == titles.index('Abstract') + 1
        assert _rows(window.correspondence_details) == [
            'Initials: A.',
            'Degrees: MD',
            'Surname: Smith',
            'Email: a.smith@example.com',
        ]
        assert _rows(window.correspondence_affiliations) == ['Corr Uni Boston']
    finally:
        window.deleteLater()


def test_corresponding_author_affiliation_opens_the_normal_editor(qapp, monkeypatch, tmp_path):
    window = _window(tmp_path)
    def fill(dialog):
        dialog.findChild(QPushButton, 'affiliation_add_organization').click()
        for key, value in {
            'state': 'MA',
            'postal-code': '02115',
            'organization:2': 'Medical School',
        }.items():
            dialog.findChild(QLineEdit, f'affiliation_{key}').setText(value)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        affiliations = window.correspondence_affiliations
        affiliations.setCurrentRow(0)
        affiliations.itemDoubleClicked.emit(affiliations.currentItem())

        updated = next(
            node for node in etree.fromstring(window.session.xml_text().encode()).iter()
            if isinstance(node.tag, str)
            and etree.QName(node).localname == 'affiliation'
            and node.get('affiliation-instance-id') == 'corr1'
        )
        assert [etree.QName(child).localname for child in updated] == [
            'organization', 'organization', 'city', 'state', 'postal-code',
        ]
        assert [child.text for child in updated.findall(
            '{http://www.elsevier.com/xml/ani/ani}organization')] == [
            'Corr Uni', 'Medical School',
        ]
        assert updated.find('{http://www.elsevier.com/xml/ani/ani}state').text == 'MA'
        # The tab redraws from the updated XML.
        assert _rows(window.correspondence_affiliations) == [
            'Corr Uni Medical School Boston MA 02115'
        ]
    finally:
        window.deleteLater()


def test_edit_affiliation_button_targets_the_selected_row(qapp, monkeypatch, tmp_path):
    window = _window(tmp_path)
    monkeypatch.setattr(QDialog, 'exec', _accept({'city': 'Cambridge'}))
    try:
        affiliations = window.correspondence_affiliations
        affiliations.setCurrentRow(0)
        window.findChild(QPushButton, 'correspondence_edit_affiliation').click()
        assert '<city>Cambridge</city>' in window.session.xml_text()
    finally:
        window.deleteLater()


def test_tab_reports_missing_correspondence(qapp, tmp_path):
    source = '<units xmlns="http://www.elsevier.com/xml/ani/ani"><head/></units>'
    window = _window(tmp_path, source)
    try:
        assert _rows(window.correspondence_details) == [
            'No corresponding author found in this XML'
        ]
        assert _rows(window.correspondence_affiliations) == []
    finally:
        window.deleteLater()


def _accept(fields):
    """Drive the real affiliation dialog: fill fields, then press OK."""

    def run(dialog):
        for key, value in fields.items():
            dialog.findChild(QLineEdit, f'affiliation_{key}').setText(value)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    return run
