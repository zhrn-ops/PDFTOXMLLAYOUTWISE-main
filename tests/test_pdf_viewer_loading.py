"""Regression coverage for asynchronous, session-safe PDF rendering."""

import fitz
import time
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pdf_to_jats.gui.pdf_viewer import PDFViewer


def _wait_for_render(qapp, viewer: PDFViewer, page_index: int) -> None:
    key = (str(viewer._pdf_path), page_index, viewer._page_scale)
    deadline = time.monotonic() + 5
    while key not in viewer._page_pixmaps and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    assert key in viewer._page_pixmaps


def _make_pdf(path, page_count: int, prefix: str) -> None:
    document = fitz.open()
    for index in range(page_count):
        page = document.new_page()
        page.insert_text((72, 72), f"{prefix} page {index + 1}")
    document.save(path)
    document.close()


def test_viewer_renders_on_demand_and_keeps_bounded_lru_cache(tmp_path, qapp):
    path = tmp_path / "many-pages.pdf"
    _make_pdf(path, 4, "first")
    with fitz.open(path) as document:
        page_sizes = [(float(page.rect.width), float(page.rect.height)) for page in document]

    viewer = PDFViewer()
    viewer.resize(800, 650)
    viewer.show()
    viewer.load_pdf(path, page_count=len(page_sizes), page_sizes=page_sizes)
    try:
        assert len(viewer._page_labels) == 1
        _wait_for_render(qapp, viewer, 0)
        viewer.next_page()
        assert len(viewer._page_labels) == 2
        _wait_for_render(qapp, viewer, 1)

        viewer._page_cache_limit = 1
        viewer.next_page()
        _wait_for_render(qapp, viewer, 2)
        assert viewer._page_cache_bytes <= (
            viewer._page_pixmaps[next(reversed(viewer._page_pixmaps))].width()
            * viewer._page_pixmaps[next(reversed(viewer._page_pixmaps))].height()
            * 4
        )
    finally:
        viewer.close()


def test_opening_another_document_discards_stale_raster_results(tmp_path, qapp):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _make_pdf(first, 2, "old")
    _make_pdf(second, 1, "new")
    viewer = PDFViewer()
    viewer.resize(800, 650)
    viewer.show()
    try:
        with fitz.open(first) as document:
            first_sizes = [(float(page.rect.width), float(page.rect.height)) for page in document]
        viewer.load_pdf(first, page_count=2, page_sizes=first_sizes)
        old_generation = viewer._generation
        viewer.load_pdf(second, page_count=1, page_sizes=first_sizes[:1])
        assert viewer._generation == old_generation + 1

        viewer._on_page_raster_ready(str(first), 0, viewer._page_scale, old_generation, None, RuntimeError("stale"))
        assert str(viewer._pdf_path) == str(second)
        assert not viewer._page_pixmaps
        _wait_for_render(qapp, viewer, 0)
        assert all(key[0] == str(second) for key in viewer._page_pixmaps)
    finally:
        viewer.close()


def test_scrolling_materializes_and_renders_later_pages(tmp_path, qapp):
    path = tmp_path / "scroll-pages.pdf"
    _make_pdf(path, 3, "scroll")
    with fitz.open(path) as document:
        page_sizes = [(float(page.rect.width), float(page.rect.height)) for page in document]

    viewer = PDFViewer()
    viewer.resize(800, 650)
    viewer.show()
    viewer.load_pdf(path, page_count=len(page_sizes), page_sizes=page_sizes)
    try:
        _wait_for_render(qapp, viewer, 0)
        second_page_top = viewer._page_labels[0].height() + viewer._page_gap + 8
        viewer.scroll_area.verticalScrollBar().setValue(second_page_top)
        _wait_for_render(qapp, viewer, 1)
        assert viewer._page_index == 1
        assert 1 in viewer._page_labels
        assert (str(path), 1, viewer._page_scale) in viewer._page_pixmaps
        assert viewer._page_labels[1].pixmap() is not None
    finally:
        viewer.close()
