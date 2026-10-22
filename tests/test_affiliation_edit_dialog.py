"""Tests for structured ANI affiliation correction (form + dialog)."""

from pathlib import Path

import pytest
from lxml import etree
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLineEdit, QPlainTextEdit, QPushButton, QSplitter,
)

from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow

ANI = (
    '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
    'xmlns:ce="http://www.elsevier.com/xml/ani/common"><head>'
    '<author-group seq="1"><author seq="1"><ce:initials>A.</ce:initials>'
    '<ce:surname>Smith</ce:surname></author>'
    '<affiliation affiliation-instance-id="aff1"><organization>Uni</organization>'
    '<city>Town</city><country iso-code="USA"/></affiliation></author-group>'
    '<correspondence><person><ce:surname>Smith</ce:surname></person>'
    '<affiliation><organization>Corr Uni</organization></affiliation></correspondence>'
    '</head><tail><bibliography><reference seq="1"><ref-authors><author seq="1">'
    '<ce:surname>Reference</ce:surname></author></ref-authors></reference>'
    '</bibliography></tail></units>'
)

FIELDS = {
    'affiliation-instance-id', 'organization', 'address-part', 'city', 'state',
    'postal-code', 'country', 'country@iso-code', 'source-text',
}


def _affiliation(session, organization):
    return next(
        node for node in session.tree.iter()
        if isinstance(node.tag, str)
        and etree.QName(node).localname == 'affiliation'
        and session._affiliation_label(node) == organization
    )


def _rows(window):
    return [
        (window.author_list.item(i).text(), window.author_list.item(i).data(257))
        for i in range(window.author_list.count())
    ]


def _accept(fields, button=QDialogButtonBox.Ok):
    """Drive the real dialog: fill form fields, then press the button."""

    def run(dialog):
        for key, value in fields.items():
            dialog.findChild(QLineEdit, f'affiliation_{key}').setText(value)
        dialog.findChild(QDialogButtonBox).button(button).click()
        return QDialog.Rejected

    return run


def test_affiliation_form_lists_every_field_even_when_absent(tmp_path):
    session = XmlDocumentSession.from_text(ANI, tmp_path / 'draft.xml')
    values = session.affiliation_form(_affiliation(session, 'Uni Town'))

    assert set(values) == FIELDS
    assert values['organization'] == 'Uni'
    assert values['city'] == 'Town'
    assert values['country'] == ''
    assert values['country@iso-code'] == 'USA'
    assert values['source-text'] == ''


def test_affiliation_form_creates_fields_in_schema_order(tmp_path):
    session = XmlDocumentSession.from_text(ANI, tmp_path / 'draft.xml')
    affiliation = _affiliation(session, 'Uni Town')
    values = session.affiliation_form(affiliation)
    values.update({
        'affiliation-instance-id': 'aff2',
        'address-part': '1 Main Street',
        'state': 'CA',
        'postal-code': '90210',
        'country': 'United States',
        'source-text': 'Uni, 1 Main Street, CA 90210, United States',
    })

    assert session.set_affiliation_form(affiliation, values) is True
    xml = session.xml_text()
    assert 'affiliation-instance-id="aff2"' in xml
    assert '<state>CA</state>' in xml
    assert '<postal-code>90210</postal-code>' in xml
    assert 'iso-code="USA"' in xml

    result = etree.fromstring(xml.encode())
    updated = next(node for node in result.iter()
                   if isinstance(node.tag, str) and node.get('affiliation-instance-id') == 'aff2')
    assert [etree.QName(child).localname for child in updated] == [
        'organization', 'address-part', 'city', 'state', 'postal-code',
        'country', 'source-text',
    ]
    assert updated.find('{http://www.elsevier.com/xml/ani/common}source-text').text == (
        'Uni, 1 Main Street, CA 90210, United States'
    )


def test_unfilled_optional_fields_are_not_written(tmp_path):
    session = XmlDocumentSession.from_text(ANI, tmp_path / 'draft.xml')
    affiliation = _affiliation(session, 'Uni Town')
    values = session.affiliation_form(affiliation)
    values['state'] = 'CA'

    session.set_affiliation_form(affiliation, values)
    xml = session.xml_text()
    assert '<state>CA</state>' in xml
    assert '<address-part' not in xml and '<postal-code' not in xml


def test_affiliation_form_appends_additional_organizations(tmp_path):
    session = XmlDocumentSession.from_text(ANI, tmp_path / 'draft.xml')
    affiliation = _affiliation(session, 'Uni Town')
    values = session.affiliation_form(affiliation)
    values['organization'] = 'Department of Physics'
    values['organization:2'] = 'Uni'
    values['organization:3'] = 'Research Institute'

    assert session.set_affiliation_form(affiliation, values) is True
    result = etree.fromstring(session.xml_text().encode())
    updated = _affiliation_xml(result, 'aff1')
    assert [etree.QName(child).localname for child in updated] == [
        'organization', 'organization', 'organization', 'city', 'country',
    ]
    assert [child.text for child in updated[:3]] == [
        'Department of Physics', 'Uni', 'Research Institute',
    ]


def test_removing_an_organization_drops_it_from_the_xml(tmp_path):
    source = ANI.replace(
        '<organization>Uni</organization>',
        '<organization>Uni</organization><organization>Medical School</organization>'
        '<organization>Research Institute</organization>',
    )
    session = XmlDocumentSession.from_text(source, tmp_path / 'draft.xml')
    affiliation = _affiliation_xml(session.tree, 'aff1')
    values = session.affiliation_form(affiliation)
    # The dialog renumbers the survivors after a removal, so the form names the
    # final organization list and the trailing entry disappears.
    values['organization:2'] = values.pop('organization:3')
    assert session.set_affiliation_form(affiliation, values) is True

    result = etree.fromstring(session.xml_text().encode())
    updated = _affiliation_xml(result, 'aff1')
    assert [child.text for child in updated.findall(
        '{http://www.elsevier.com/xml/ani/ani}organization')] == [
        'Uni', 'Research Institute',
    ]


def test_removing_every_organization_keeps_the_other_fields(tmp_path):
    session = XmlDocumentSession.from_text(ANI, tmp_path / 'draft.xml')
    affiliation = _affiliation(session, 'Uni Town')
    values = session.affiliation_form(affiliation)
    values.pop('organization')

    assert session.set_affiliation_form(affiliation, values) is True
    result = etree.fromstring(session.xml_text().encode())
    updated = _affiliation_xml(result, 'aff1')
    assert updated.findall('{http://www.elsevier.com/xml/ani/ani}organization') == []
    assert updated.find('{http://www.elsevier.com/xml/ani/ani}city').text == 'Town'


def test_affiliation_form_rejects_gaps_in_the_organization_list(tmp_path):
    session = XmlDocumentSession.from_text(ANI, tmp_path / 'draft.xml')
    affiliation = _affiliation(session, 'Uni Town')
    values = session.affiliation_form(affiliation)
    values['organization:3'] = 'Gap'

    with pytest.raises(ValueError, match='reopen the editor'):
        session.set_affiliation_form(affiliation, values)


def test_affiliation_form_rejects_fields_the_document_does_not_have(tmp_path):
    session = XmlDocumentSession.from_text(ANI, tmp_path / 'draft.xml')
    affiliation = _affiliation(session, 'Uni Town')
    values = session.affiliation_form(affiliation)
    values['city:2'] = 'Elsewhere'

    with pytest.raises(ValueError, match='reopen the editor'):
        session.set_affiliation_form(affiliation, values)


def _affiliation_xml(root, instance_id):
    return next(
        node for node in root.iter()
        if isinstance(node.tag, str)
        and etree.QName(node).localname == 'affiliation'
        and node.get('affiliation-instance-id') == instance_id
    )


def test_every_affiliation_and_no_reference_author_is_listed(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(ANI, Path('draft.xml'))
    window._refresh()
    try:
        rows = _rows(window)
        labels = [text for text, _path in rows]
        assert 'Group 1: Uni Town' in labels
        # Correspondence affiliations belong to the corresponding-author tab.
        assert 'Corr Uni' not in labels
        assert labels == ['Group 1: Uni Town', '    A. Smith']
        assert all(path for text, path in rows if text.startswith('Group 1'))
        assert not any('Reference' in label for label in labels)
    finally:
        window.deleteLater()


def test_double_click_affiliation_opens_complete_form_and_updates_xml(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(ANI, Path('draft.xml'))
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(
        i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))
    monkeypatch.setattr(QDialog, 'exec', _accept({
        'affiliation-instance-id': 'aff2',
        'address-part': '2 Side Street',
        'state': 'NY',
        'postal-code': '10001',
    }))
    try:
        window.author_list.itemDoubleClicked.emit(window.author_list.currentItem())
        xml = window.session.xml_text()
        assert 'affiliation-instance-id="aff2"' in xml
        assert '<address-part>2 Side Street</address-part>' in xml
        assert '<state>NY</state>' in xml
        assert '<postal-code>10001</postal-code>' in xml
        assert window.session.dirty
    finally:
        window.deleteLater()


def test_cancelling_affiliation_dialog_preserves_xml(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(ANI, Path('draft.xml'))
    window._refresh()
    original = window.session.xml_text()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))
    monkeypatch.setattr(QDialog, 'exec', _accept({'state': 'CA'}, QDialogButtonBox.Cancel))
    try:
        window.edit_author()
        assert window.session.xml_text() == original
        assert not window.session.dirty
    finally:
        window.deleteLater()


def test_dialog_adds_another_organization_to_an_affiliation(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(ANI, Path('draft.xml'))
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))

    def fill(dialog):
        dialog.findChild(QPushButton, 'affiliation_add_organization').click()
        dialog.findChild(QLineEdit, 'affiliation_organization:2').setText('Medical School')
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        window.edit_author()
        result = etree.fromstring(window.session.xml_text().encode())
        updated = _affiliation_xml(result, 'aff1')
        assert [etree.QName(child).localname for child in updated][:3] == [
            'organization', 'organization', 'city',
        ]
        assert [child.text for child in updated[:2]] == ['Uni', 'Medical School']
    finally:
        window.deleteLater()


def test_dialog_ignores_an_added_but_blank_organization(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(ANI, Path('draft.xml'))
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))

    def fill(dialog):
        dialog.findChild(QPushButton, 'affiliation_add_organization').click()
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        window.edit_author()
        result = etree.fromstring(window.session.xml_text().encode())
        updated = _affiliation_xml(result, 'aff1')
        assert [child.text for child in updated.findall(
            '{http://www.elsevier.com/xml/ani/ani}organization')] == ['Uni']
    finally:
        window.deleteLater()


def test_dialog_removes_the_selected_organization(qapp, monkeypatch):
    source = ANI.replace(
        '<organization>Uni</organization>',
        '<organization>Uni</organization><organization>Medical School</organization>',
    )
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))

    def fill(dialog):
        dialog.findChild(QPushButton, 'affiliation_remove_organization:2').click()
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        window.edit_author()
        result = etree.fromstring(window.session.xml_text().encode())
        updated = _affiliation_xml(result, 'aff1')
        assert [child.text for child in updated.findall(
            '{http://www.elsevier.com/xml/ani/ani}organization')] == ['Uni']
    finally:
        window.deleteLater()


def test_dialog_can_remove_more_organizations_after_renumbering(qapp, monkeypatch):
    source = ANI.replace(
        '<organization>Uni</organization>',
        '<organization>Uni</organization><organization>Medical School</organization>'
        '<organization>Research Institute</organization>',
    )
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))

    def fill(dialog):
        dialog.findChild(QPushButton, 'affiliation_remove_organization:2').click()
        # The survivor is renumbered, so its Remove button must follow suit.
        dialog.findChild(QPushButton, 'affiliation_remove_organization:2').click()
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        window.edit_author()
        result = etree.fromstring(window.session.xml_text().encode())
        updated = _affiliation_xml(result, 'aff1')
        assert [child.text for child in updated.findall(
            '{http://www.elsevier.com/xml/ani/ani}organization')] == ['Uni']
    finally:
        window.deleteLater()


def test_dialog_removing_the_first_organization_keeps_the_rest(qapp, monkeypatch):
    source = ANI.replace(
        '<organization>Uni</organization>',
        '<organization>Uni</organization><organization>Medical School</organization>',
    )
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))

    def fill(dialog):
        dialog.findChild(QPushButton, 'affiliation_remove_organization').click()
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        window.edit_author()
        result = etree.fromstring(window.session.xml_text().encode())
        updated = _affiliation_xml(result, 'aff1')
        assert [child.text for child in updated.findall(
            '{http://www.elsevier.com/xml/ani/ani}organization')] == ['Medical School']
    finally:
        window.deleteLater()


def test_dialog_numbers_added_organizations_after_existing_ones(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(ANI, Path('draft.xml'))
    affiliation = _affiliation(window.session, 'Uni Town')
    values = window.session.affiliation_form(affiliation)
    values['organization:2'] = 'Medical School'
    window.session.set_affiliation_form(affiliation, values)
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))

    def fill(dialog):
        dialog.findChild(QPushButton, 'affiliation_add_organization').click()
        dialog.findChild(QLineEdit, 'affiliation_organization:3').setText('Research Institute')
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        window.edit_author()
        result = etree.fromstring(window.session.xml_text().encode())
        updated = _affiliation_xml(result, 'aff1')
        assert [child.text for child in updated[:3]] == [
            'Uni', 'Medical School', 'Research Institute',
        ]
    finally:
        window.deleteLater()


def test_organization_commas_are_removed_before_writing_xml(tmp_path):
    session = XmlDocumentSession.from_text(ANI, tmp_path / 'draft.xml')
    affiliation = _affiliation(session, 'Uni Town')
    values = session.affiliation_form(affiliation)
    values['organization'] = ', Dept. of Internal Medicine '
    values['organization:2'] = 'Uni, Medical School'
    values['organization:3'] = 'Uni,Medical'

    assert session.set_affiliation_form(affiliation, values) is True
    result = etree.fromstring(session.xml_text().encode())
    updated = _affiliation_xml(result, 'aff1')
    assert [child.text for child in updated.findall(
        '{http://www.elsevier.com/xml/ani/ani}organization')] == [
        'Dept. of Internal Medicine', 'Uni Medical School', 'UniMedical',
    ]
    # Comma-rich prose in other fields is untouched.
    assert updated.find('{http://www.elsevier.com/xml/ani/ani}city').text == 'Town'


def test_dialog_organization_field_never_holds_commas(qapp, monkeypatch):
    source = ANI.replace(
        '<organization>Uni</organization>',
        '<organization>, Dept. of Internal Medicine </organization>',
    )
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(
        i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))

    def fill(dialog):
        field = dialog.findChild(QLineEdit, 'affiliation_organization')
        # The stored value is shown already cleaned when the dialog opens.
        assert field.text() == 'Dept. of Internal Medicine'
        # Typing a comma drops it immediately.
        field.setText('Dept. of Internal Medicine, Oncology')
        assert field.text() == 'Dept. of Internal Medicine Oncology'
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        window.edit_author()
        result = etree.fromstring(window.session.xml_text().encode())
        updated = _affiliation_xml(result, 'aff1')
        assert [child.text for child in updated.findall(
            '{http://www.elsevier.com/xml/ani/ani}organization')] == [
            'Dept. of Internal Medicine Oncology',
        ]
    finally:
        window.deleteLater()


def test_source_text_field_is_a_resizable_multi_line_editor(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(ANI, Path('draft.xml'))
    window._refresh()
    rows = _rows(window)
    window.author_list.setCurrentRow(next(
        i for i, (text, _p) in enumerate(rows) if text.startswith('Group 1')))

    def fill(dialog):
        dialog.show()
        qapp.processEvents()
        # Source text is verbatim and often long, so it is not a one-line box.
        assert dialog.findChild(QLineEdit, 'affiliation_source-text') is None
        editor = dialog.findChild(QPlainTextEdit, 'affiliation_source-text')
        splitter = dialog.findChild(QSplitter, 'affiliation_source_splitter')
        assert editor is not None and splitter is not None
        assert not editor.isReadOnly()
        assert splitter.orientation() == Qt.Vertical
        # Dragging the divider gives the field more or less room.
        start = editor.height()
        splitter.setSizes([120, 420])
        qapp.processEvents()
        expanded = editor.height()
        assert expanded > start
        splitter.setSizes([420, 120])
        qapp.processEvents()
        assert editor.height() < expanded
        editor.setPlainText('Uni,\n1 Main Street, Town')
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', fill)
    try:
        window.edit_author()
        result = etree.fromstring(window.session.xml_text().encode())
        updated = _affiliation_xml(result, 'aff1')
        assert updated.find(
            '{http://www.elsevier.com/xml/ani/common}source-text').text == (
            'Uni,\n1 Main Street, Town')
    finally:
        window.deleteLater()


def test_group_without_affiliation_can_get_one_from_the_dialog(qapp, monkeypatch):
    source = (
        '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
        'xmlns:ce="http://www.elsevier.com/xml/ani/common"><author-group>'
        '<author><ce:surname>Smith</ce:surname></author></author-group></units>'
    )
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    window._refresh()
    window.author_list.setCurrentRow(0)
    monkeypatch.setattr(QDialog, 'exec', _accept({
        'organization': 'New University',
        'city': 'Boston',
        'country@iso-code': 'USA',
    }))
    try:
        window.edit_author()
        xml = window.session.xml_text()
        assert '<affiliation>' in xml
        assert '<organization>New University</organization>' in xml
        assert '<city>Boston</city>' in xml
        assert '<country iso-code="USA"/>' in xml
    finally:
        window.deleteLater()
