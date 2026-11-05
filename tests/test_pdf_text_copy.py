import fitz
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pdf_to_jats.gui.pdf_viewer import PDFViewer


@pytest.mark.parametrize('scale', [1, 2])
def test_drag_pdf_text_and_copy(qapp, tmp_path, scale):
    path = tmp_path / 'text.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 70), 'Copy this text')
        page.insert_text((50, 130), 'Leave this text')
        doc.save(path)
    viewer = PDFViewer(text_selectable=True)
    viewer._pdf_path = path
    label = viewer.label
    label.resize(600, 600)
    label.setProperty('pageScale', scale)
    try:
        QTest.mousePress(label, Qt.LeftButton, pos=QPoint(40 * scale, 50 * scale))
        QTest.mouseMove(label, QPoint(150 * scale, 80 * scale))
        QTest.mouseRelease(label, Qt.LeftButton, pos=QPoint(150 * scale, 80 * scale))
        assert viewer._selected_pdf_text == 'Copy this text'
        assert viewer.copy_text_btn.isEnabled()
        viewer.copy_text_btn.click()
        assert QApplication.clipboard().text() == 'Copy this text'
        viewer._select_pdf_text(0, [300, 300, 350, 350])
        assert not viewer.copy_text_btn.isEnabled()
        assert viewer._selected_pdf_text == ''
    finally:
        viewer.close()
