"""Review and apply individual offline grammar suggestions."""

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPushButton, QVBoxLayout, QHBoxLayout, QLineEdit

from pdf_to_jats.core.grammar_check import check_grammar


class GrammarReviewDialog(QDialog):
    def __init__(self, editor, before_edit, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.before_edit = before_edit
        self.setWindowTitle('Abstract grammar and typo check')
        self.resize(720, 460)
        layout = QVBoxLayout(self)
        note = QLabel('Basic English checks • Runs locally\n'
                      'Reviews common typos, grammar and punctuation patterns. Unknown technical words '
                      'are left alone. Hyphenated words are flagged for optional review. It may miss errors; '
                      'review suggestions against the scientific meaning.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.setObjectName('grammar_suggestions')
        layout.addWidget(self.results)
        layout.addWidget(QLabel('Replacement (editable — apply only if appropriate):'))
        self.replacement_edit = QLineEdit()
        self.replacement_edit.setObjectName('grammar_replacement')
        layout.addWidget(self.replacement_edit)
        self.results.currentRowChanged.connect(self.select_suggestion)
        self.status = QLabel()
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton('Apply suggestion')
        self.apply_button.setObjectName('apply_grammar_suggestion')
        self.ignore_button = QPushButton('Ignore')
        recheck = QPushButton('Check again')
        close = QPushButton('Close')
        for button in (self.apply_button, self.ignore_button, recheck, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.apply_button.clicked.connect(self.apply_suggestion)
        self.ignore_button.clicked.connect(self.ignore_suggestion)
        recheck.clicked.connect(self.recheck)
        close.clicked.connect(self.accept)
        self.recheck()

    def recheck(self):
        self.snapshot = self.editor.toPlainText()
        self.suggestions = check_grammar(self.snapshot)
        self.render()

    def select_suggestion(self, index):
        valid = 0 <= index < len(self.suggestions)
        self.replacement_edit.setEnabled(valid)
        self.replacement_edit.setText(self.suggestions[index].replacement if valid else '')

    def render(self):
        self.results.clear()
        for suggestion in self.suggestions:
            original = self.snapshot[suggestion.start:suggestion.end]
            context = self.snapshot[max(0, suggestion.start - 45):suggestion.end + 45].replace('\n', ' ')
            self.results.addItem(f'{suggestion.message}: “{original}” → “{suggestion.replacement}”\n{context}')
        available = bool(self.suggestions)
        self.apply_button.setEnabled(available)
        self.ignore_button.setEnabled(available)
        self.status.setText(f'{len(self.suggestions)} suggestions to review.' if available else
                            'No remaining suggestions from these basic checks.')
        if available:
            self.results.setCurrentRow(0)

    def ignore_suggestion(self):
        index = self.results.currentRow()
        if index >= 0:
            self.suggestions.pop(index)
            self.render()

    def apply_suggestion(self):
        if self.editor.toPlainText() != self.snapshot:
            self.recheck()
            self.status.setText('Abstract changed. Suggestions refreshed; select a suggestion again.')
            return
        index = self.results.currentRow()
        if index < 0:
            return
        suggestion = self.suggestions[index]
        self.before_edit()
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(len(self.snapshot[:suggestion.start].encode('utf-16-le')) // 2)
        cursor.setPosition(len(self.snapshot[:suggestion.end].encode('utf-16-le')) // 2,
                           QTextCursor.KeepAnchor)
        cursor.insertText(self.replacement_edit.text())
        self.editor.setTextCursor(cursor)
        self.recheck()
