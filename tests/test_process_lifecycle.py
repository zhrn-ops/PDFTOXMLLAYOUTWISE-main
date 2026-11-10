"""Regression tests for R01 and R04 process lifecycle and concurrency safeguards.

Covers:
- R01: MainWindow closeEvent safeguards during active background PDF load and viewer rasterization.
- R01: PDFViewer.cleanup halts in-flight threads gracefully without crashing.
- R04: _on_article_finish_worker_complete ignores stale responses when document generation has changed.
"""

from __future__ import annotations

from pathlib import Path
import threading
import time
import pytest
from PySide6.QtCore import QEvent, QThread
from PySide6.QtGui import QCloseEvent
import fitz

import pdf_to_jats.gui.pdf_viewer as pdf_viewer_module
from pdf_to_jats.gui.main_window import MainWindow
from pdf_to_jats.gui.pdf_viewer import PDFViewer
from pdf_to_jats.models.document import Document
from pdf_to_jats.models.block import TextBlock


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "lifecycle_sample.pdf"
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=500, height=700)
        page.insert_text((50, 50), f"Page {i + 1} Content", fontsize=14)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.mark.recovery
def test_close_event_blocked_when_pdf_loading(qapp, sample_pdf: Path):
    """R01: MainWindow.closeEvent ignores close requests while background PDF load thread is active."""
    window = MainWindow()
    try:
        # Start PDF loading in background (wait=False)
        window._load_pdf_path(str(sample_pdf), wait=False)
        assert window._pdf_load_thread is not None
        assert window._pdf_load_thread.isRunning()

        # Attempt to close while thread is running
        event = QCloseEvent()
        window.closeEvent(event)
        # Event must be ignored to prevent shutting down during active extraction
        assert not event.isAccepted()

        # Wait for thread to finish cleanly before closing
        while window._pdf_load_thread and window._pdf_load_thread.isRunning():
            qapp.processEvents()
            window._pdf_load_thread.wait(50)
    finally:
        window.close()


@pytest.mark.recovery
def test_viewer_cleanup_cancels_in_flight_raster_threads(qapp, sample_pdf: Path, monkeypatch):
    """R01: cleanup waits for a raster worker that is still inside rendering."""
    started = threading.Event()
    release = threading.Event()
    real_open = fitz.open

    class BlockingPage:
        def __init__(self, page):
            self._page = page

        def get_pixmap(self, *args, **kwargs):
            started.set()
            release.wait(10)
            return self._page.get_pixmap(*args, **kwargs)

    class BlockingDocument:
        def __init__(self, path):
            self._doc = real_open(path)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._doc.close()

        def load_page(self, index):
            return BlockingPage(self._doc.load_page(index))

    monkeypatch.setattr(
        pdf_viewer_module.fitz, "open", lambda path: BlockingDocument(path)
    )
    viewer = PDFViewer()
    timer = None
    try:
        viewer.load_pdf(str(sample_pdf), page_count=3, page_sizes=[(500, 700)] * 3)
        deadline = time.monotonic() + 5
        while not started.is_set() and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert started.is_set(), "raster worker never entered rendering"
        threads = list(viewer._page_render_threads)
        assert threads, "no raster thread was recorded"

        # Release the worker while cleanup is waiting, without relying on the
        # Qt event loop (which cleanup intentionally blocks).
        timer = threading.Timer(0.25, release.set)
        timer.start()
        viewer.cleanup()

        assert len(viewer._page_render_threads) == 0
        assert len(viewer._page_render_workers) == 0
        # This is the regression check: clearing the lists is not enough; the
        # worker thread must have actually stopped before cleanup returns.
        assert all(not thread.isRunning() for thread in threads)
    finally:
        release.set()
        if timer is not None:
            timer.cancel()
        viewer.deleteLater()


@pytest.mark.recovery
def test_article_finish_drops_stale_response_on_generation_mismatch(qapp):
    """R04: _on_article_finish_worker_complete drops responses from older document generations."""
    window = MainWindow()
    try:
        window.document = Document(
            title="Current Document Title",
            blocks=[TextBlock(id="b1", page=1, text="Current Text", bbox=[10, 10, 100, 20], x=10, y=10, width=90, height=10)]
        )
        initial_gen = window._document_generation

        # Set up a pending finish with the initial generation
        segment = {"index": 0, "block_ids": ["b1"]}
        key = "seg_0"
        window._pending_article_finish = (segment, key, initial_gen)

        # Simulate user opening another document or updating generation
        window._document_generation += 1

        # Worker emits response from the old request
        stale_response = {"authors": [{"surname": "OldAuthor"}]}
        window._on_article_finish_worker_complete(stale_response, None)

        # The stale finish must be ignored; document title and authors must not be corrupted
        assert window.document.title == "Current Document Title"
        assert len(window.document.authors) == 0
    finally:
        window.close()
