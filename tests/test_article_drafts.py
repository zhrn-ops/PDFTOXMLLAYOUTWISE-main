from pathlib import Path
import json

from PySide6.QtWidgets import QFileDialog, QMessageBox
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.main_window import MainWindow
from pdf_to_jats.models.document import Document
from pdf_to_jats.models.block import TextBlock
import fitz
from pdf_to_jats.core.jats_generator import JATSGenerator
from lxml import etree


def xml(title):
    return f'<article><article-title>{title}</article-title><abstract><p>Text</p></abstract></article>'


def test_switch_drafts_retains_corrections_invalid_xml_and_history(qapp):
    window = XmlCorrectionWindow()
    try:
        window.load_xml_text(xml('First'), Path('first.xml'))
        first = window._draft_key
        window.title_edit.setPlainText('Corrected')
        window.load_xml_text(xml('Second'), Path('second.xml'))
        second = window._draft_key
        window.preview.setPlainText('<article>unfinished')
        window.activate_draft(first)
        assert window.session.title() == 'Corrected'
        window._undo_field()
        assert window.session.title() == 'First'
        window._redo_field()
        assert window.session.title() == 'Corrected'
        window.activate_draft(second)
        assert window.raw.toPlainText() == '<article>unfinished'
        assert not window.session.raw_valid
        window.activate_draft(first)
        assert window.session.title() == 'Corrected'
    finally:
        window.deleteLater()


def test_switching_saved_articles_does_not_prompt_but_edits_do(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    prompts = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: prompts.append(a) or QMessageBox.Cancel)
    try:
        window.load_xml_text(xml('First'), Path('first.xml'))
        first = window._draft_key
        window.load_xml_text(xml('Second'), Path('second.xml'))
        second = window._draft_key
        window._saved_workspace = window._workspace_text()
        window.activate_draft(first)
        assert window.confirm_close_drafts()
        assert not prompts
        # Navigation is still stored so an explicit save can restore that view.
        assert json.loads(window._workspace_text())['active'] == first
        window.title_edit.setPlainText('Actual correction')
        window.activate_draft(second)
        assert not window.confirm_close_drafts()
        assert len(prompts) == 1
    finally:
        window.deleteLater()


def test_pdf_article_navigation_ignored_but_block_changes_prompt(qapp, monkeypatch):
    window = MainWindow()
    prompts = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: prompts.append(a) or QMessageBox.Cancel)
    try:
        window.document = Document(blocks=[TextBlock(
            id='b1', page=1, text='Original', bbox=[0, 0, 10, 10],
            x=0, y=0, width=10, height=10)])
        window._current_segment_key = 'first'
        editor = window._xml_correction_window
        editor._saved_workspace = editor._workspace_text()
        window._current_segment_key = 'second'
        assert editor.confirm_close_drafts()
        assert not prompts
        window.document.blocks[0].text = 'Changed'
        assert not editor.confirm_close_drafts()
        assert len(prompts) == 1
    finally:
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Discard)
        window.close()


def test_regeneration_preserves_corrections_and_archives_accepted_revision(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    try:
        window.load_xml_text(xml('Initial'), Path('article.xml'))
        key = window._draft_key
        window.title_edit.setPlainText('Manual correction')
        window.load_xml_text(xml('Initial'), Path('article.xml'))
        assert window.session.title() == 'Manual correction'
        monkeypatch.setattr(window, 'review_regeneration', lambda *_: False)
        window.load_xml_text(xml('New extraction'), Path('article.xml'))
        assert window.session.title() == 'Manual correction'
        assert 'not been applied' in window.status.text()
        monkeypatch.setattr(window, 'review_regeneration', lambda *_: True)
        window.load_xml_text(xml('New extraction'), Path('article.xml'))
        assert window.session.title() == 'New extraction'
        assert len(window._drafts) == 2
        window.activate_draft(key + '|revision:1')
        assert window.session.title() == 'Manual correction'
    finally:
        window.deleteLater()


def test_timestamp_only_regeneration_keeps_corrected_draft_without_prompt(qapp, monkeypatch):
    window = XmlCorrectionWindow()
    generated = JATSGenerator().to_string(Document(title='Original', abstract='Study'))
    root = etree.fromstring(generated.encode())
    root.find('.//{http://www.elsevier.com/xml/ani/ani}timestamp').text = '2099-01-01T00:00:00Z'
    regenerated = etree.tostring(root, encoding='unicode')
    prompts = []
    monkeypatch.setattr(window, 'review_regeneration', lambda *args: prompts.append(args) or False)
    try:
        window.load_xml_text(generated, Path('article.xml'))
        window.title_edit.setPlainText('Manual correction')
        corrected = window.session.xml_text()
        window._saved_workspace = window._workspace_text()
        window.load_xml_text(regenerated, Path('article.xml'))
        assert not prompts
        assert window.session.xml_text() == corrected
        assert len(window._drafts) == 1
        assert window.confirm_close_drafts()
        root.find('.//{http://www.elsevier.com/xml/ani/ani}titletext').text = 'Changed extraction'
        window.load_xml_text(etree.tostring(root, encoding='unicode'), Path('article.xml'))
        assert len(prompts) == 1
        assert window.session.title() == 'Manual correction'
    finally:
        window.deleteLater()


def test_regeneration_comparison_does_not_ignore_content_timestamps():
    first = '<article><timestamp>2026</timestamp></article>'
    second = '<article><timestamp>2027</timestamp></article>'
    assert XmlCorrectionWindow._regeneration_content(first) != XmlCorrectionWindow._regeneration_content(second)


def test_save_and_reopen_drafts_without_validation(qapp, tmp_path, monkeypatch):
    path = tmp_path / 'review.jatsdraft'
    window = XmlCorrectionWindow()
    restored = XmlCorrectionWindow()
    try:
        window.load_xml_text(xml('Initial'), Path('article.xml'))
        window.title_edit.setPlainText('Corrected')
        window.raw.setPlainText('<unfinished')
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), ''))
        assert window.save_draft()
        assert window.confirm_close_drafts()
        assert json.loads(path.read_text(encoding='utf-8'))['articles']
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(path), ''))
        restored.open_drafts()
        assert restored.session.title() == 'Corrected'
        assert restored.raw.toPlainText() == '<unfinished'
        assert not restored.session.raw_valid
        assert restored.confirm_close_drafts()
    finally:
        window.deleteLater()
        restored.deleteLater()


def test_export_clears_dirty_and_later_edits_report_stale_export(qapp, tmp_path, monkeypatch):
    window = XmlCorrectionWindow()
    try:
        window.load_xml_text(xml('Initial'), Path('article.xml'))
        window.title_edit.setPlainText('Corrected')
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path / 'out.xml'), ''))
        monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: QMessageBox.Ok)
        assert window.save_copy()
        assert not window.session.dirty
        window.title_edit.setPlainText('Another correction')
        assert window.status.text() == 'Changes not yet exported'
        assert window.session.dirty
    finally:
        window.deleteLater()


def test_workspace_round_trip_restores_pdf_blocks_and_draft(qapp, tmp_path, monkeypatch):
    source = tmp_path / 'source.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), 'Title')
        pdf.save(source)
    path = tmp_path / 'workspace.jatsdraft'
    window = MainWindow()
    restored = MainWindow()
    try:
        block = TextBlock(id='b1', page=1, text='Title', bbox=[72, 60, 150, 80],
                          x=72, y=60, width=78, height=20, role='title',
                          metadata={'article_locked': True})
        window.document = Document(blocks=[block], metadata={'source_pdf': str(source)})
        editor = window._xml_correction_window
        editor.load_xml_text(xml('Title'), Path('article.xml'), source)
        editor.title_edit.setPlainText('Manual title')
        window._article_draft_keys = {'article1': editor._draft_key}
        window._finished_segment_keys = ['article1']
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), ''))
        assert editor.save_draft()
        assert editor.confirm_close_drafts()
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(path), ''))
        restored._xml_correction_window.open_drafts()
        assert restored.document.blocks[0].text == 'Title'
        assert restored.document.blocks[0].metadata['article_locked']
        assert restored._finished_segment_keys == ['article1']
        assert restored._article_draft_keys == window._article_draft_keys
        assert restored._xml_correction_window.session.title() == 'Manual title'
        assert restored._xml_correction_window.confirm_close_drafts()
    finally:
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Discard)
        window.close()
        restored.close()


def test_save_extraction_before_first_xml_draft(qapp, tmp_path, monkeypatch):
    window = MainWindow()
    try:
        window.document = Document(title='Work in progress')
        path = tmp_path / 'early.jatsdraft'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), ''))
        assert window._xml_correction_window.save_draft()
        data = json.loads(path.read_text(encoding='utf-8'))
        assert data['workflow']['document']['title'] == 'Work in progress'
        assert data['active'] is None
        assert window._xml_correction_window.confirm_close_drafts()
    finally:
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Discard)
        window.close()


def test_cancel_workspace_replacement_preserves_current_draft(qapp, tmp_path, monkeypatch):
    window = XmlCorrectionWindow()
    other = XmlCorrectionWindow()
    try:
        window.load_xml_text(xml('Keep me'), Path('current.xml'))
        other.load_xml_text(xml('Replacement'), Path('other.xml'))
        path = tmp_path / 'other.jatsdraft'
        path.write_text(other._workspace_text(), encoding='utf-8')
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(path), ''))
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Cancel)
        window.open_drafts()
        assert window.session.title() == 'Keep me'
        assert len(window._drafts) == 1
    finally:
        window.deleteLater()
        other.deleteLater()


def test_edit_pdf_selection_targets_selected_article(qapp, monkeypatch):
    window = MainWindow()
    try:
        window.document = Document()
        selected = {'index': 1}
        other = {'index': 2}
        window._finished_segment_keys = ['one', 'two']
        monkeypatch.setattr(window, '_segments_with_keys', lambda: [(selected, 'one'), (other, 'two')])
        monkeypatch.setattr(window, '_segment_at_tab', lambda index: selected)
        monkeypatch.setattr(window, '_segment_key', lambda segment: 'one' if segment is selected else 'two')
        reopened = []
        monkeypatch.setattr(window, '_reopen_segment', lambda segment, key: reopened.append(key))
        window.reopen_current_article()
        assert reopened == ['one']
    finally:
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Discard)
        window.close()
