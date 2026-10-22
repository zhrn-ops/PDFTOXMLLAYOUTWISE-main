from pathlib import Path

from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
import pytest
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


def _colored_spans(editor):
    return [(span.cursor.selectedText(), span.format.foreground().color().name())
            for span in editor.extraSelections()]


@pytest.mark.parametrize('source', [
    '<article><abstract><p>Start</p></abstract></article>',
    '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
    'xmlns:ce="http://www.elsevier.com/xml/ani/common">'
    '<abstracts><abstract><ce:para>Start</ce:para></abstract></abstracts></units>',
])
def test_abstract_typing_preserves_spaces_and_paragraph_breaks(qapp, source):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(source, Path('draft.xml'))
    window._refresh()
    try:
        editor = window.abstract_edit
        editor.moveCursor(QTextCursor.End)
        QTest.keyClicks(editor, ' ')
        assert editor.toPlainText() == 'Start '
        QTest.keyClicks(editor, 'next word')
        assert editor.toPlainText() == 'Start next word'
        assert window.session.abstract() == 'Start next word'
        window._undo_field()
        window._redo_field()
        assert editor.toPlainText() == 'Start next word'
        editor.moveCursor(QTextCursor.End)
        QTest.keyClick(editor, Qt.Key_Return)
        QTest.keyClick(editor, Qt.Key_Return)
        QTest.keyClicks(editor, 'Second paragraph')
        assert editor.toPlainText() == 'Start next word\n\nSecond paragraph'
        assert editor.textCursor().position() == len(editor.toPlainText())
    finally:
        window.deleteLater()


def test_abstract_typing_after_unicode_preserves_cursor_and_scripts(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<article><abstract><p>\U0001f600 H<sub>2</sub>O</p></abstract></article>', Path('draft.xml')
    )
    window._refresh()
    try:
        window.abstract_edit.moveCursor(QTextCursor.End)
        QTest.keyClicks(window.abstract_edit, ' next word')
        assert window.abstract_edit.toPlainText() == '\U0001f600 H2O next word'
        assert _colored_spans(window.abstract_edit) == [('2', '#fbbf24')]
        assert window.abstract_edit.textCursor().position() == len(
            window.abstract_edit.toPlainText().encode('utf-16-le')) // 2
    finally:
        window.deleteLater()


def test_script_colors_follow_xml_edits_and_unicode_offsets(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<article><article-title>😀 H<sub>2</sub>O x<sup>3</sup></article-title>'
        '<abstract><p>A<sup>2</sup></p><p>B<inf>3</inf></p></abstract></article>',
        Path('draft.xml'),
    )
    original = window.session.xml_text()
    try:
        window._refresh()
        assert _colored_spans(window.title_edit) == [('2', '#fbbf24'), ('3', '#78aaff')]
        assert _colored_spans(window.abstract_edit) == [('2', '#78aaff'), ('3', '#fbbf24')]
        assert window.session.xml_text() == original
        assert not window.session.dirty
        cursor = window.title_edit.textCursor()
        cursor.setPosition(0)
        window.title_edit.setTextCursor(cursor)
        window.title_edit.insertPlainText('New ')
        assert _colored_spans(window.title_edit) == [('2', '#fbbf24'), ('3', '#78aaff')]
        window.raw.setPlainText('<article><article-title>Plain title</article-title></article>')
        assert _colored_spans(window.title_edit) == []
        assert _colored_spans(window.abstract_edit) == []
    finally:
        window.deleteLater()


def test_script_selection_preserves_paragraphs_and_replaces_existing_script():
    session = XmlDocumentSession.from_text(
        '<article><article-title>H2O</article-title><abstract><p>A2</p><p>B3</p></abstract></article>',
        Path('draft.xml'),
    )
    session.apply_script('title', 1, 2, 'inf')
    assert '<inf>2</inf>' in session.xml_text()
    session.apply_script('title', 1, 2, 'sup')
    assert '<sup>2</sup>' in session.xml_text()
    assert '<inf>' not in session.xml_text()
    session.apply_script('abstract', 5, 6, 'sup')
    assert '<p>A2</p>' in session.xml_text()
    assert '<p>B<sup>3</sup></p>' in session.xml_text()


def test_title_formatting_undo_redo(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<article><article-title>H2O</article-title></article>', Path('draft.xml')
    )
    window._refresh()
    try:
        cursor = window.title_edit.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(2, QTextCursor.KeepAnchor)
        window.title_edit.setTextCursor(cursor)
        window._format_selection(window.title_edit, 'title', 'inf')
        assert _colored_spans(window.title_edit) == [('2', '#fbbf24')]
        assert '<inf>2</inf>' in window.session.xml_text()
        assert '&lt;inf&gt;' not in window.session.xml_text()
        window.title_edit.setFocus()
        QTest.keyClick(window.title_edit, Qt.Key_Z, Qt.ControlModifier)
        assert '<inf>' not in window.session.xml_text()
        assert _colored_spans(window.title_edit) == []
        QTest.keyClick(window.title_edit, Qt.Key_Y, Qt.ControlModifier)
        assert '<inf>2</inf>' in window.session.xml_text()
        assert _colored_spans(window.title_edit) == [('2', '#fbbf24')]
        QTest.keyClick(window.title_edit, Qt.Key_Z, Qt.ControlModifier)
        QTest.keyClick(window.title_edit, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        assert '<inf>2</inf>' in window.session.xml_text()
    finally:
        window.deleteLater()


def test_normal_text_clears_only_selected_script_across_paragraphs():
    session = XmlDocumentSession.from_text(
        '<article><abstract><p>A<sup>123</sup></p><p>B<sub>45</sub>C</p></abstract></article>',
        Path('draft.xml'),
    )
    original_text = session.abstract()
    session.apply_script('abstract', 2, 8, 'normal')
    assert session.abstract() == original_text
    assert '<p>A<sup>1</sup>23</p>' in session.xml_text()
    assert '<p>B4<sub>5</sub>C</p>' in session.xml_text()


@pytest.mark.parametrize('field', ['title', 'abstract'])
def test_toolbar_formats_clears_and_undoes_without_losing_selection(qapp, field):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<article><article-title>H<sup>2</sup>O</article-title>'
        '<abstract><p>H<sup>2</sup>O</p></abstract></article>', Path('draft.xml')
    )
    window._refresh()
    editor = getattr(window, field + '_edit')
    buttons = {tag: window.findChild(QPushButton, f'{field}_{tag}_button')
               for tag in ('sup', 'inf', 'normal')}
    try:
        assert all(not button.isEnabled() for button in buttons.values())
        cursor = editor.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(2, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        assert all(button.isEnabled() for button in buttons.values())
        QTest.mouseClick(buttons['normal'], Qt.LeftButton)
        assert editor.toPlainText() == 'H2O'
        assert _colored_spans(editor) == []
        assert editor.textCursor().selectedText() == '2'
        window._undo_field()
        assert _colored_spans(editor) == [('2', '#78aaff')]
        window._redo_field()
        assert _colored_spans(editor) == []
        cursor = editor.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(2, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        QTest.mouseClick(buttons['inf'], Qt.LeftButton)
        assert _colored_spans(editor) == [('2', '#fbbf24')]
        QTest.mouseClick(buttons['sup'], Qt.LeftButton)
        assert _colored_spans(editor) == [('2', '#78aaff')]
        assert editor.textCursor().selectedText() == '2'
    finally:
        window.deleteLater()
