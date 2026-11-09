"""Synthetic schemas test mechanics only; these are not publisher schemas."""
from pathlib import Path

from lxml import etree
import pytest

from pdf_to_jats.core import atomic_io
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.core.validator import Validator
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.core.xml_validation import (
    ExportMode, SchemaProfile, ValidationStatus as Status, fingerprint, validate_xml,
)
from pdf_to_jats.models.document import Document


XML = b'<article><article-title>Scientific title</article-title></article>'
XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:element name="article"><xs:complexType><xs:sequence>
<xs:element name="article-title" type="xs:string"/>
</xs:sequence></xs:complexType></xs:element></xs:schema>'''


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / 'entry.xsd'
    path.write_text(XSD, encoding='utf-8')
    return SchemaProfile('Synthetic JATS test', 'JATS', path)


def test_missing_schema_is_explicit_and_legacy_api_reports_it(tmp_path):
    path = tmp_path / 'article.xml'
    path.write_bytes(XML)
    result = validate_xml(XML)
    assert result.well_formedness == Status.WELL_FORMED
    assert result.schema_status == Status.SCHEMA_UNAVAILABLE
    assert result.fingerprint == fingerprint(XML)
    assert any('Schema validation unavailable' in i.message for i in Validator().validate(path))
    with pytest.raises(ValueError, match='selected local schema'):
        result.require_export(ExportMode.VALIDATED)
    result.require_export(ExportMode.DRAFT)


def test_standalone_fallback_preserves_drafts_but_never_claims_schema_validity(tmp_path, profile, monkeypatch):
    import xml.etree.ElementTree as stdlib_etree
    from pdf_to_jats.core import xml_validation, jats_generator
    monkeypatch.setattr(xml_validation, 'etree', None)
    result = validate_xml(XML, profile)
    assert result.well_formedness == Status.WELL_FORMED
    assert result.schema_status == Status.SCHEMA_UNAVAILABLE
    result.require_export(ExportMode.DRAFT)
    with pytest.raises(ValueError):
        result.require_export(ExportMode.VALIDATED)
    with pytest.raises(ValueError):
        validate_xml(b'<!DOCTYPE article [<!ENTITY x "private">]><article>&x;</article>').require_export(ExportMode.DRAFT)
    monkeypatch.setattr(jats_generator, 'etree', stdlib_etree)
    monkeypatch.setattr(jats_generator, 'LXML_AVAILABLE', False)
    target = tmp_path / 'fallback.xml'
    JATSGenerator().generate(Document(title='Study'), target)
    assert stdlib_etree.parse(target).getroot().tag == '{http://www.elsevier.com/xml/ani/ani}units'


@pytest.mark.parametrize('data,expected', [(XML, Status.SCHEMA_VALID),
                                         (b'<article/>', Status.SCHEMA_INVALID)])
def test_schema_dimension_is_independent_of_semantic_warnings(profile, data, expected):
    result = validate_xml(data, profile)
    assert result.well_formedness == Status.WELL_FORMED
    assert result.schema_status == expected
    assert result.semantic_issues  # authors/abstract absent even with a valid test XSD
    result.require_export(ExportMode.DRAFT)


def test_malformed_xml_never_exports(profile):
    result = validate_xml(b'<article>', profile)
    assert result.well_formedness == Status.NOT_WELL_FORMED
    assert result.syntax_issues[0].line == 1
    for mode in ExportMode:
        with pytest.raises(ValueError, match='parse/security'):
            result.require_export(mode)


@pytest.mark.parametrize('content', [None, '<broken>', '<not-a-schema/>'])
def test_missing_or_unusable_schema_is_unavailable(tmp_path, content):
    path = tmp_path / 'entry.xsd'
    if content is not None:
        path.write_text(content)
    result = validate_xml(XML, SchemaProfile('broken', 'JATS', path))
    assert result.schema_status == Status.SCHEMA_UNAVAILABLE
    with pytest.raises(ValueError):
        result.require_export(ExportMode.VALIDATED)


@pytest.mark.parametrize('namespace,family,root', [('urn:j', 'JATS', 'article'),
    ('http://www.elsevier.com/xml/ani/ani', 'ANI', 'units')])
def test_namespaced_schema_and_wrong_profile(tmp_path, namespace, family, root):
    path = tmp_path / 'namespaced.xsd'
    path.write_text(f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="{namespace}">'
                    f'<xs:element name="{root}" type="xs:string"/></xs:schema>')
    data = f'<{root} xmlns="{namespace}">content</{root}>'.encode()
    result = validate_xml(data, SchemaProfile('test', family, path))
    assert result.schema_status == Status.SCHEMA_VALID
    wrong = 'ANI' if family == 'JATS' else 'JATS'
    assert validate_xml(data, SchemaProfile('wrong', wrong, path)).schema_status == Status.SCHEMA_UNAVAILABLE


def test_ani_never_uses_legacy_jats_schema(profile):
    result = validate_xml(JATSGenerator().to_bytes(Document(title='Study')), profile)
    assert result.format == 'ANI'
    assert result.schema_status == Status.SCHEMA_UNAVAILABLE


@pytest.mark.parametrize('location', ['https://example.invalid/private.xsd', '../outside.xsd'])
def test_schema_imports_cannot_escape_selected_folder(tmp_path, location):
    folder = tmp_path / 'bundle'
    folder.mkdir()
    path = folder / 'entry.xsd'
    path.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
                    f'<xs:include schemaLocation="{location}"/></xs:schema>')
    (tmp_path / 'outside.xsd').write_text(XSD)
    result = validate_xml(XML, SchemaProfile('restricted', 'JATS', path))
    assert result.schema_status == Status.SCHEMA_UNAVAILABLE


def test_local_schema_include_and_missing_dependency(tmp_path):
    path = tmp_path / 'entry.xsd'
    child = tmp_path / 'child.xsd'
    child.write_text(XSD)
    path.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
                    '<xs:include schemaLocation="child.xsd"/></xs:schema>')
    selected = SchemaProfile('bundle', 'JATS', path)
    assert validate_xml(XML, selected).schema_status == Status.SCHEMA_VALID
    child.unlink()
    assert validate_xml(XML, selected).schema_status == Status.SCHEMA_UNAVAILABLE


def test_schema_dtd_and_unresolved_instance_entities_are_blocked(tmp_path):
    path = tmp_path / 'entry.xsd'
    path.write_text('<!DOCTYPE schema [<!ENTITY x "secret">]>' + XSD)
    assert validate_xml(XML, SchemaProfile('test', 'JATS', path)).schema_status == Status.SCHEMA_UNAVAILABLE
    data = b'<!DOCTYPE article [<!ENTITY x SYSTEM "file:///private/sentinel">]><article>&x;</article>'
    result = validate_xml(data)
    assert result.well_formedness == Status.WELL_FORMED
    with pytest.raises(ValueError, match='Unresolved entities'):
        result.require_export(ExportMode.DRAFT)


def test_unknown_nodes_survive_draft_but_strict_schema_rejects_them(tmp_path, profile):
    data = XML.replace(b'</article>', b'<unknown>keep</unknown></article>')
    session = XmlDocumentSession(tmp_path / 'source.xml', data)
    session.validate(profile)
    assert session.validation_result.schema_status == Status.SCHEMA_INVALID
    target = tmp_path / 'draft.xml'
    session.save_copy(target)
    assert b'<unknown>keep</unknown>' in target.read_bytes()
    with pytest.raises(ValueError, match='Validated export'):
        session.save_copy(tmp_path / 'strict.xml', mode=ExportMode.VALIDATED)


def test_validated_copy_matches_validated_bytes_and_edits_invalidate(tmp_path, profile):
    session = XmlDocumentSession(tmp_path / 'source.xml', XML)
    session.validate(profile)
    target = tmp_path / 'strict.xml'
    session.save_copy(target, mode=ExportMode.VALIDATED)
    assert fingerprint(target.read_bytes()) == session.validation_result.fingerprint
    session.set_title('Edited')
    assert session.validation_result is None
    with pytest.raises(ValueError, match='Validate the current XML'):
        session.save_copy(target, mode=ExportMode.VALIDATED)
    assert b'Edited' not in target.read_bytes()


def test_direct_tree_edit_also_invalidates_validation(tmp_path, profile):
    session = XmlDocumentSession(tmp_path / 'source.xml', XML)
    session.validate(profile)
    session.title_node().text = 'Bypassed setter'
    with pytest.raises(ValueError, match='Validate the current XML'):
        session.save_copy(tmp_path / 'out.xml')


def test_schema_removed_after_validation_blocks_strict_copy(tmp_path, profile):
    session = XmlDocumentSession(tmp_path / 'source.xml', XML)
    session.validate(profile)
    profile.schema_path.unlink()
    with pytest.raises(ValueError, match='Schema unavailable'):
        session.save_copy(tmp_path / 'out.xml', mode=ExportMode.VALIDATED)
    assert not (tmp_path / 'out.xml').exists()


def test_malformed_raw_edit_cannot_export_last_good_tree(tmp_path, profile):
    session = XmlDocumentSession(tmp_path / 'source.xml', XML)
    session.validate(profile)
    session.commit_raw('<article>')
    session.validate(profile)
    assert session.validation_result is None
    with pytest.raises(ValueError):
        session.save_copy(tmp_path / 'out.xml')


@pytest.mark.parametrize('inner', [
    '<italic>H</italic><sub>2</sub><italic>O</italic>',
    '<italic>A</italic> <italic>B</italic>',
    '<custom><i>A</i><i>B</i></custom>',
    '<m:math xmlns:m="urn:math"><m:mi>x</m:mi><m:mi>n</m:mi></m:math>',
    '<italic>H</italic><!--note--><?review keep?><sub>2</sub>',
])
def test_serialization_preserves_inline_text_tails_and_unknown_content(tmp_path, inner):
    source = f'<article><p>{inner}</p></article>'.encode()
    session = XmlDocumentSession(tmp_path / 'source.xml', source)
    expected = etree.tostring(session.tree.getroot()[0])
    serialized = etree.fromstring(session.xml_bytes())[0]
    assert etree.tostring(serialized, with_tail=False) == expected


def test_inherited_xml_space_preserve(tmp_path):
    source = b'<article xml:space="preserve"><front><title-group><article-title>A</article-title></title-group></front></article>'
    session = XmlDocumentSession(tmp_path / 'source.xml', source)
    assert etree.tostring(etree.fromstring(session.xml_bytes())) == source


def test_non_utf8_unicode_boundary_preserves_characters(tmp_path):
    source = '<?xml version="1.0" encoding="ISO-8859-1"?><article><article-title>Caf\u00e9</article-title></article>'.encode('latin-1')
    session = XmlDocumentSession(tmp_path / 'source.xml', source)
    reopened = XmlDocumentSession.from_text(session.xml_text(), tmp_path / 'draft.xml')
    assert reopened.title() == 'Caf\u00e9'
    ok, *_ = session.commit_raw(session.xml_text().replace('Caf\u00e9', '\u03b1'))
    assert ok and session.title() == '\u03b1'


@pytest.mark.parametrize('operation', ['fsync', 'replace'])
def test_atomic_failure_preserves_existing_file_and_cleans_temp(tmp_path, monkeypatch, operation):
    target = tmp_path / 'out.xml'
    target.write_bytes(b'previous')
    def fail(*args):
        raise OSError('injected failure')
    monkeypatch.setattr(atomic_io.os, operation, fail)
    with pytest.raises(OSError, match='injected'):
        JATSGenerator().generate(Document(title='Study'), target)
    assert target.read_bytes() == b'previous'
    assert list(tmp_path.iterdir()) == [target]


def test_generator_strict_export_requires_profile_before_writing(tmp_path):
    target = tmp_path / 'out.xml'
    target.write_bytes(b'previous')
    with pytest.raises(ValueError, match='Validated export'):
        JATSGenerator().generate(Document(title='Study'), target, mode=ExportMode.VALIDATED)
    assert target.read_bytes() == b'previous'


@pytest.mark.parametrize('short_write', [False, True])
def test_interrupted_or_short_write_preserves_output(tmp_path, monkeypatch, short_write):
    target = tmp_path / 'out.xml'
    target.write_bytes(b'previous')
    original = atomic_io.os.fdopen
    class InterruptedStream:
        def __init__(self, fd, mode):
            self.stream = original(fd, mode)
        def __enter__(self):
            return self
        def write(self, data):
            self.stream.write(data[:9])
            if short_write:
                return 9
            raise OSError('simulated disk full')
        def __exit__(self, *args):
            self.stream.close()
    monkeypatch.setattr(atomic_io.os, 'fdopen', InterruptedStream)
    with pytest.raises(OSError):
        JATSGenerator().generate(Document(title='Study'), target)
    assert target.read_bytes() == b'previous'
    assert list(tmp_path.iterdir()) == [target]


def test_missing_unused_schema_import_still_blocks_validated_export(tmp_path):
    path = tmp_path / 'entry.xsd'
    path.write_text(XSD.replace('<xs:element name="article">',
        '<xs:import namespace="urn:missing" schemaLocation="missing.xsd"/>'
        '<xs:element name="article">', 1))
    result = validate_xml(XML, SchemaProfile('incomplete', 'JATS', path))
    assert result.schema_status == Status.SCHEMA_UNAVAILABLE


def test_legacy_export_reports_missing_schema_without_reporting_failed_output(tmp_path):
    from types import SimpleNamespace
    from pdf_to_jats.gui.main_window import MainWindow
    path = tmp_path / 'draft.xml'
    path.write_bytes(b'<article><article-title>T</article-title><contrib>Author</contrib><abstract>A</abstract></article>')
    messages = []
    window = SimpleNamespace(validator=Validator(), _log=messages.append)
    assert MainWindow._validate_draft_export(window, path) == []
    assert any('publisher validation is incomplete' in message for message in messages)


def test_gui_validated_export_uses_selected_profile(tmp_path, profile, qapp, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow
    window = XmlCorrectionWindow()
    target = tmp_path / 'strict.xml'
    notices = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: notices.append(args[2]))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    try:
        window.load_xml_text(XML.decode(), tmp_path / 'draft.xml')
        window.schema_profile = profile
        assert window.save_validated_copy()
        assert validate_xml(target.read_bytes(), profile).schema_status == Status.SCHEMA_VALID
        assert 'Schema-valid for selected profile' in window.summary.text()
        assert notices and 'Additional publisher business rules are not verified' in notices[0]
        window.title_edit.setPlainText('Changed after export')
        assert window.session.validation_result is None
        assert window.validation_list.count() == 0
    finally:
        window.deleteLater()


def test_gui_draft_and_validated_exports_are_distinct(tmp_path, qapp, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton
    from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow
    window = XmlCorrectionWindow()
    target = tmp_path / 'out.xml'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    try:
        window.load_xml_text(XML.decode(), tmp_path / 'draft.xml')
        window.validate()
        assert 'schema unavailable' in window.summary.text()
        buttons = {button.text() for button in window.findChildren(QPushButton)}
        assert {'Draft Export', 'Validated Export'} <= buttons
        assert not window.save_validated_copy()
        assert warnings and not target.exists()
        assert window.save_copy()
        assert target.exists()
        assert 'Publisher validation is incomplete' in window.status.text()
    finally:
        window.deleteLater()
