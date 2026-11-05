from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from pdf_to_jats.gui.main_window import MainWindow
from pdf_to_jats.gui.styles import APP_STYLE
from pdf_to_jats.utils.config import AppConfig


def test_theme_toggle_preserves_xml_and_restores_dark_theme(qapp, tmp_path, monkeypatch):
    preferences = {}

    class Settings:
        def __init__(self, *args):
            pass

        def value(self, key, default):
            return preferences.get(key, default)

        def setValue(self, key, value):
            preferences[key] = value

    monkeypatch.setattr('pdf_to_jats.gui.main_window.QSettings', Settings)
    monkeypatch.setattr('pdf_to_jats.gui.main_window.load_config', lambda: AppConfig(
        output_dir=tmp_path, generated_xml_dir=tmp_path,
        openrouter_settings_path=tmp_path / 'settings.json'))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Discard)
    window = MainWindow()
    restored = None
    try:
        editor = window._xml_correction_window
        editor.load_xml_text('<article><article-title>Original</article-title></article>', Path('article.xml'))
        editor.title_edit.setPlainText('Corrected')
        original_xml = editor.session.xml_text()
        history = list(editor._history)
        dark_correction = editor.styleSheet()
        window.theme_toggle.click()
        assert window._theme == 'light'
        assert '#f4f6fa' in window.styleSheet()
        assert '#ffffff' in editor.styleSheet()
        assert window.theme_toggle.text() == 'Dark mode'
        assert editor.session.xml_text() == original_xml
        assert editor._history == history
        assert preferences['theme'] == 'light'
        restored = MainWindow()
        assert restored._theme == 'light'
        window.theme_toggle.click()
        assert window.styleSheet() == APP_STYLE
        assert editor.styleSheet() == dark_correction
        assert editor.session.xml_text() == original_xml
    finally:
        if restored:
            restored.close()
        window.close()
