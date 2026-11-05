from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


ARTICLE = (
    '<article>'
    '<article-title>Alpha title</article-title>'
    '<kwd-group><kwd>One</kwd><kwd>Two</kwd></kwd-group>'
    '</article>'
)

LONG = (
    '<article><article-title>Alpha title</article-title><abstract>'
    + ''.join(f'<p>Paragraph {index} filler text</p>' for index in range(120))
    + '</abstract></article>'
)


def span_for(editor, opening, closing):
    text = editor.toPlainText()
    start = text.find(opening)
    assert start >= 0
    return start, text.find(closing, start) + len(closing)


def click_title(window, qapp):
    QTest.mouseClick(window.title_edit.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(8, 8))
    qapp.processEvents()


def test_clicking_the_title_marks_its_element_in_both_panes(qapp):
    window = XmlCorrectionWindow()
    window.show()
    window.load_xml_text(ARTICLE, Path('article.xml'))
    try:
        click_title(window, qapp)
        for editor in (window.preview, window.raw):
            assert editor.revealed_span() == span_for(
                editor, '<article-title>', '</article-title>')
            assert editor.textCursor().block().text() == '<article-title>Alpha title</article-title>'
            # The locator is a band, not a text selection, so the XML stays
            # readable instead of being washed out by an inactive selection.
            assert editor.textCursor().selectedText() == ''
    finally:
        window.deleteLater()


def test_keyword_row_marks_the_matching_element(qapp):
    window = XmlCorrectionWindow()
    window.load_xml_text(ARTICLE, Path('article.xml'))
    try:
        window.keyword_list.setCurrentRow(1)
        for editor in (window.preview, window.raw):
            assert editor.revealed_span() == span_for(editor, '<kwd>Two</kwd>', '</kwd>')
            assert editor.textCursor().block().text() == '<kwd>Two</kwd>'
    finally:
        window.deleteLater()


def test_editing_the_pane_clears_the_locator_band(qapp):
    window = XmlCorrectionWindow()
    window.show()
    window.load_xml_text(ARTICLE, Path('article.xml'))
    try:
        click_title(window, qapp)
        assert window.raw.revealed_span() is not None
        window.raw.setPlainText(window.raw.toPlainText())
        assert window.raw.revealed_span() is None
    finally:
        window.deleteLater()


def test_typing_a_component_keeps_the_xml_panes_in_place(qapp):
    window = XmlCorrectionWindow()
    window.show()
    window.load_xml_text(LONG, Path('long.xml'))
    try:
        bar = window.preview.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        start = bar.value()
        assert start > 0

        window.title_edit.moveCursor(window.title_edit.textCursor().MoveOperation.End)
        window.title_edit.insertPlainText(' updated')
        assert window.preview.verticalScrollBar().value() == start
        assert window.preview.revealed_span() is None

        window.abstract_edit.moveCursor(window.abstract_edit.textCursor().MoveOperation.End)
        window.abstract_edit.insertPlainText(' tail')
        assert window.preview.verticalScrollBar().value() == start
        assert window.preview.revealed_span() is None
    finally:
        window.deleteLater()
