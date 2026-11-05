from pathlib import Path

from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


def test_abstract_find_navigation_wrap_and_no_xml_changes(qapp):
    window = XmlCorrectionWindow()
    try:
        window.load_xml_text('<article><abstract><p>Study first. A study second.</p></abstract></article>', Path('draft.xml'))
        original = window.session.xml_text()
        history = list(window._history)
        window.abstract_find.setText('study')
        assert window.abstract_edit.textCursor().selectedText() == 'Study'
        window.abstract_find_next.click()
        assert window.abstract_edit.textCursor().selectionStart() == 15
        window.abstract_find_next.click()
        assert window.abstract_edit.textCursor().selectionStart() == 0
        assert window.abstract_find_status.text() == 'Wrapped'
        window.abstract_find_previous.click()
        assert window.abstract_edit.textCursor().selectionStart() == 15
        window.abstract_find.setText('missing')
        assert window.abstract_find_status.text() == 'No matches'
        assert not window.abstract_edit.textCursor().hasSelection()
        window.abstract_find.clear()
        assert window.abstract_find_status.text() == ''
        assert window.session.xml_text() == original
        assert window._history == history
        assert not window.session.dirty
    finally:
        window.deleteLater()
