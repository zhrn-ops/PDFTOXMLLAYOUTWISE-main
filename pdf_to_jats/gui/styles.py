"""Centralized visual tokens and application-wide dark theme."""

COLORS = {
    "background": "#0B1220",
    "sidebar": "#0E1828",
    "panel": "#1C2940",
    "editor": "#0B1220",
    "primary": "#3B82F6",
    "primary_hover": "#5595FA",
    "border": "#28374D",
    "text": "#E8EEF7",
    "muted": "#A6B3C6",
    "success": "#34D399",
    "warning": "#FBBF24",
    "error": "#F87171",
}

APP_STYLE = f"""
QMainWindow, QWidget, QSplitter, QScrollArea {{
    background: {COLORS['background']}; color: {COLORS['text']};
    font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt;
}}
QTreeWidget, QListWidget, QTextEdit, QPlainTextEdit, QTextBrowser {{
    background: {COLORS['editor']}; border: 1px solid {COLORS['border']};
    border-radius: 8px; color: {COLORS['text']}; selection-background-color: {COLORS['primary']};
}}
QTreeWidget::item, QListWidget::item {{ padding: 4px 3px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {COLORS['primary']}; color: white; }}
QHeaderView::section {{ background: {COLORS['panel']}; color: {COLORS['text']}; padding: 6px; border: none; }}
QGroupBox {{ color: {COLORS['text']}; font-weight: 600; border: 1px solid {COLORS['border']}; border-radius: 6px; margin-top: 9px; padding-top: 9px; }}
QComboBox, QLineEdit {{ color: {COLORS['text']}; background: {COLORS['editor']}; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 6px 8px; }}
QComboBox QAbstractItemView {{ color: {COLORS['text']}; background: {COLORS['panel']}; selection-background-color: {COLORS['primary']}; }}
QLabel {{ background: transparent; color: {COLORS['text']}; }}
QPushButton {{ min-height: 20px; padding: 7px 11px; border-radius: 8px; background: {COLORS['panel']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']}; }}
QPushButton:hover {{ background: #20324b; border-color: #4d6684; }}
QPushButton:pressed {{ background: #10243a; }}
QPushButton:disabled, QComboBox:disabled, QLineEdit:disabled {{ background: #121c2a; color: #718096; border-color: #263448; }}
QTabWidget::pane {{ border: 1px solid {COLORS['border']}; border-radius: 8px; background: {COLORS['panel']}; }}
QTabBar::tab {{ background: {COLORS['sidebar']}; color: {COLORS['muted']}; padding: 7px 12px; border: 1px solid {COLORS['border']}; border-bottom: none; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {COLORS['primary']}; color: white; }}
QTabBar::tab:!selected:hover {{ background: #20324b; }}
QSplitter::handle {{ background: transparent; width: 8px; height: 8px; }}
QSplitter::handle:hover {{ background: #28374D; }}
QToolTip {{ background: {COLORS['panel']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']}; }}
"""

APP_STYLE += """
QWidget#workflowSidebar { background: #0E1828; border: 1px solid #202E43; border-radius: 12px; }
QLabel#brand { font-size: 21px; font-weight: 700; padding: 6px 0; }
QLabel#pageTitle { font-size: 22px; font-weight: 600; }
QLabel#muted { color: #A6B3C6; }
QLabel#eyebrow { color: #8295B0; font-size: 11px; font-weight: 600; padding-bottom: 8px; }
QWidget#emptyPage { background: #131D2E; border: 1px solid #28374D; border-radius: 12px; }
QLabel#emptyBadge { color: #78AAFF; font-size: 16px; font-weight: 600; padding: 16px; }
QLabel#emptyTitle { font-size: 24px; font-weight: 600; padding: 10px 0; }
QPushButton#primaryButton { background: #3B82F6; border-color: #3B82F6; color: white; font-weight: 600; padding: 9px 20px; }
QPushButton#primaryButton:hover { background: #5595FA; border-color: #5595FA; }
QPushButton#primaryButton:pressed { background: #2563EB; }
QPushButton#primaryButton:disabled { background: #1C2940; border-color: #28374D; color: #718096; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border: 1px solid #78AAFF; }
QTabBar::tab { padding: 9px 12px; border: none; }
QTabBar::tab:selected { background: #203B60; color: #DBEAFE; }
QScrollBar:vertical { background: #0B1220; width: 10px; margin: 0; }
QScrollBar:horizontal { background: #0B1220; height: 10px; margin: 0; }
QScrollBar::handle { background: #34465F; border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: #516886; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""
