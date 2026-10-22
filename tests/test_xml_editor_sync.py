from pathlib import Path

import pytest
from PySide6.QtGui import QTextCursor
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


@pytest.mark.parametrize('first,second', [('preview', 'raw'), ('raw', 'preview')])
def test_unfinished_xml_survives_switching_editors_and_can_be_completed(qapp, first, second):
    window = XmlCorrectionWindow()
    window.load_xml_text('<article><article-title>Original</article-title></article>', Path('draft.xml'))
    before = window.session.xml_text()
    incomplete = '<article><article-title>Unfinished correction'
    try:
        editor = getattr(window, first)
        other = getattr(window, second)
        editor.setPlainText(incomplete)
        assert other.toPlainText() == incomplete
        assert window.session.xml_text() == before
        assert not window.session.raw_valid
        assert any(issue.severity == 'error' for issue in window.session.validate())
        assert not window.title_edit.isEnabled()

        window.mode_tabs.setCurrentWidget(other)
        other.moveCursor(QTextCursor.End)
        other.insertPlainText(' continued')
        assert editor.toPlainText() == incomplete + ' continued'
        assert not window.session.raw_valid
        other.insertPlainText('</article-title></article>')
        assert editor.toPlainText() == other.toPlainText()
        assert window.session.raw_valid
        assert window.session.title() == 'Unfinished correction continued'
        assert window.title_edit.isEnabled()

        other.undo()
        assert editor.toPlainText() == other.toPlainText()
        other.redo()
        assert editor.toPlainText() == other.toPlainText()
        assert window.session.title() == 'Unfinished correction continued'
    finally:
        window.deleteLater()


def test_valid_xml_is_mirrored_without_reformatting(qapp):
    window = XmlCorrectionWindow()
    window.load_xml_text('<article><article-title>Original</article-title></article>', Path('draft.xml'))
    text = '<article>\n  <article-title>Changed</article-title>\n</article>\n'
    try:
        window.raw.setPlainText(text)
        assert window.preview.toPlainText() == text
        window._retain_draft()
        window.load_xml_text('<article/>', Path('other.xml'))
        window.activate_draft('|draft.xml')
        assert window.raw.toPlainText() == text
        assert window.preview.toPlainText() == text
    finally:
        window.deleteLater()
