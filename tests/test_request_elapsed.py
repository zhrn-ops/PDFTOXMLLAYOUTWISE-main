from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
from types import SimpleNamespace

import pytest

from pdf_to_jats.gui.main_window import MainWindow


@pytest.mark.parametrize("outcome", ["success", "declined", "error"])
def test_finish_step_reports_duration_and_preserves_result(monkeypatch, outcome):
    messages = []
    window = SimpleNamespace(_log=messages.append)
    now = [10.0]
    monkeypatch.setattr("pdf_to_jats.gui.main_window.time.perf_counter", lambda: now[0])

    def action():
        assert messages == ["Generating XML draft..."]
        now[0] = 12.5
        if outcome == "error":
            raise ValueError("generation failed")
        return False if outcome == "declined" else "<article/>"

    if outcome == "error":
        with pytest.raises(ValueError, match="generation failed"):
            MainWindow._run_article_finish_step(window, "Generating XML draft", action)
        assert messages[-1] == "Generating XML draft: failed after 2.50 seconds."
    else:
        result = MainWindow._run_article_finish_step(window, "Generating XML draft", action)
        assert result == (False if outcome == "declined" else "<article/>")
        status = "not completed" if outcome == "declined" else "completed"
        assert messages[-1] == f"Generating XML draft: {status} in 2.50 seconds."


def test_request_elapsed_updates_stops_and_resets(qapp, monkeypatch):
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    window.request_elapsed_label = QLabel(window)
    window._request_elapsed_timer = QTimer(window)
    window._request_started_at = None
    messages = []
    window._log = messages.append
    now = [100.0]
    monkeypatch.setattr("pdf_to_jats.gui.main_window.time.perf_counter", lambda: now[0])
    try:
        window._set_article_finish_busy(True)
        assert window._request_elapsed_timer.isActive()
        assert window._request_progress_dialog.isVisible()
        assert window._request_progress_dialog.maximum() == 0
        now[0] = 112.5
        window._update_request_elapsed()
        assert "12.5 seconds elapsed" in window.request_elapsed_label.text()
        assert "Elapsed: 12.5 seconds" in window._request_progress_dialog.labelText()
        assert "Loading the model" in window._request_progress_dialog.labelText()
        assert "Pending" in window._request_progress_dialog.labelText()
        window._on_request_progress("Qwen request round trip: 10.00 seconds.")
        window._on_request_progress("Qwen Model loading: 2.00 seconds.")
        window._on_request_progress("Qwen Prompt processing: 3.00 seconds.")
        window._on_request_progress("Qwen Response generation: 4.00 seconds.")
        window._on_request_progress("Qwen transport/client overhead (approximate): 1.00 seconds.")

        window._set_article_finish_busy(False)
        assert not window._request_elapsed_timer.isActive()
        assert window._request_progress_dialog.isVisible()
        assert "20.0%" in window._request_progress_dialog.labelText()
        assert "4.00 s" in window._request_progress_dialog.labelText()
        assert "Pending" not in window._request_progress_dialog.labelText()
        assert "12.50 seconds" in messages[-1]
        completed = window.request_elapsed_label.text()
        now[0] = 200.0
        window._update_request_elapsed()
        assert window.request_elapsed_label.text() == completed

        window._set_article_finish_busy(True)
        assert "0.0 seconds elapsed" in window.request_elapsed_label.text()
        assert "Pending" in window._request_progress_dialog.labelText()
        window._set_article_finish_busy(False)
        assert "Unavailable" in window._request_progress_dialog.labelText()
        window._request_progress_dialog.cancel()
        assert not window._request_progress_dialog.isVisible()
    finally:
        window._request_elapsed_timer.stop()
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        window.deleteLater()
