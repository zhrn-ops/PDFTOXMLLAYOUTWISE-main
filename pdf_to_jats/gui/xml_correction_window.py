"""Standalone XML correction workspace integrated with the converter."""

from __future__ import annotations

from pathlib import Path

import fitz
from lxml import etree
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor, QTextCursor, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QFileDialog, QFormLayout, QHBoxLayout, QDialog, QDialogButtonBox,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QComboBox, QPlainTextEdit, QSplitter, QTabWidget, QVBoxLayout, QWidget, QMenu, QTextEdit, QScrollArea,
)

from pdf_to_jats.core.xml_correction import XmlDocumentSession, normalize_organization
from pdf_to_jats.core.inline_script_detector import preserve_matching_runs
from pdf_to_jats.gui.pdf_viewer import PDFViewer
from pdf_to_jats.gui.article_drafts import ArticleDrafts

SCRIPT_COLORS = {"sup": "#78AAFF", "sub": "#FBBF24"}


def _script_legend() -> QLabel:
    label = QLabel(
        f'<span style="color:{SCRIPT_COLORS["sup"]}">Superscript</span>'
        ' &nbsp;·&nbsp; '
        f'<span style="color:{SCRIPT_COLORS["sub"]}">Subscript</span>'
    )
    label.setToolTip("Select text, then use the toolbar or right-click to change its formatting.")
    return label


class XmlCorrectionWindow(QWidget, ArticleDrafts):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("xmlCorrectionWorkspace")
        self.setMinimumSize(900, 620)
        self.setStyleSheet("QWidget#xmlCorrectionWorkspace { background:#101d2c; color:#e7f0ff; } QLabel { color:#dce9fa; } QPushButton { background:#14283c; color:#e7f0ff; border:1px solid #294663; border-radius:5px; padding:7px 12px; } QPushButton:hover { background:#1b3a59; } QLineEdit,QPlainTextEdit,QListWidget { background:#091421; color:#e7f0ff; border:1px solid #294663; border-radius:4px; padding:6px; } QTabWidget::pane { border:1px solid #294663; } QTabBar::tab { background:#14283c; color:#cfe0f2; padding:8px 14px; } QTabBar::tab:selected { background:#0874d1; }")
        self.session: XmlDocumentSession | None = None
        self._syncing = False
        self._init_drafts()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("XML Correction Workspace")
        title.setStyleSheet("font-size:20px;font-weight:700;color:#f4f8ff")
        subtitle = QLabel("Review and correct the generated XML here. Validation and export happen in this workspace; extraction does not write an XML file.")
        subtitle.setWordWrap(True)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)
        for label, callback in (("Open XML...", self.open_xml), ("Open Drafts", self.open_drafts), ("Save Draft", self.save_draft), ("Validate && Export", self.save_copy)):
            button = QPushButton(label)
            if callback == self.open_xml:
                # QPushButton.clicked emits a checked bool; it is not a path.
                button.clicked.connect(lambda _checked=False: self.open_xml())
            else:
                button.clicked.connect(callback)
            header.addWidget(button)
        back = QPushButton("← Back")
        back.clicked.connect(self.go_back)
        header.addWidget(back)
        root.addLayout(header)
        self.draft_selector = QComboBox()
        self.draft_selector.setToolTip("Switch articles without losing corrections")
        self.draft_selector.currentIndexChanged.connect(self._select_draft)
        root.addWidget(self.draft_selector)
        self.summary = QLabel("No XML file open")
        self.summary.setStyleSheet("background:#10243a;border:1px solid #294663;border-radius:5px;padding:10px;color:#a9c8ec")
        root.addWidget(self.summary)
        splitter = QSplitter(Qt.Horizontal)
        self.tabs = QTabWidget()
        title_page = QWidget(); title_layout = QVBoxLayout(title_page)
        title_layout.addWidget(QLabel("Title"))
        self.title_edit = QPlainTextEdit()
        self.title_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.title_edit.setPlaceholderText("Enter or edit the article title")
        self.title_edit.textChanged.connect(self._title_changed)
        title_layout.addWidget(self._formatting_toolbar(self.title_edit, "title"))
        title_layout.addWidget(self.title_edit, 1)
        title_layout.addWidget(_script_legend())
        self.tabs.addTab(title_page, "Title")
        self.author_list = QListWidget()
        self.author_list.itemDoubleClicked.connect(lambda _item: self.edit_author())
        author_buttons = QHBoxLayout()
        edit_author = QPushButton("Edit selected"); edit_author.clicked.connect(self.edit_author)
        add_author = QPushButton("Add"); add_author.clicked.connect(self.add_author)
        remove_author = QPushButton("Remove"); remove_author.clicked.connect(self.remove_author)
        author_buttons.addWidget(edit_author); author_buttons.addWidget(add_author); author_buttons.addWidget(remove_author)
        self.abstract_edit = QPlainTextEdit(); self.abstract_edit.textChanged.connect(self._abstract_changed)
        self.keyword_list = QListWidget()
        kw_buttons = QHBoxLayout(); kw_edit = QPushButton("Edit selected"); kw_edit.clicked.connect(self.edit_keyword); kw_add = QPushButton("Add"); kw_add.clicked.connect(self.add_keyword); kw_remove = QPushButton("Remove"); kw_remove.clicked.connect(self.remove_keyword)
        kw_buttons.addWidget(kw_edit); kw_buttons.addWidget(kw_add); kw_buttons.addWidget(kw_remove)
        keywords_page = QWidget(); keywords_layout = QVBoxLayout(keywords_page)
        keywords_layout.addWidget(self.keyword_list); keywords_layout.addLayout(kw_buttons)
        self.tabs.addTab(keywords_page, "Keywords")
        authors_page = QWidget(); author_layout = QVBoxLayout(authors_page); author_layout.addWidget(QLabel("Double-click an author or affiliation to edit its fields.")); author_layout.addWidget(self.author_list)
        self.author_list.setWordWrap(True)
        author_layout.addLayout(author_buttons)
        self.tabs.addTab(authors_page, "Authors && Affiliations")
        abstract_page = QWidget(); abstract_layout = QVBoxLayout(abstract_page)
        abstract_layout.addWidget(self._formatting_toolbar(self.abstract_edit, "abstract"))
        abstract_layout.addWidget(self.abstract_edit)
        abstract_layout.addWidget(_script_legend())
        self.tabs.addTab(abstract_page, "Abstract")
        self.correspondence_details = QListWidget()
        self.correspondence_details.setObjectName('correspondence_details')
        self.correspondence_details.setWordWrap(True)
        self.correspondence_affiliations = QListWidget()
        self.correspondence_affiliations.setObjectName('correspondence_affiliations')
        self.correspondence_affiliations.setWordWrap(True)
        self.correspondence_affiliations.itemDoubleClicked.connect(
            lambda item: self.edit_affiliation_item(item))
        correspondence_edit = QPushButton("Edit affiliation")
        correspondence_edit.setObjectName('correspondence_edit_affiliation')
        correspondence_edit.setToolTip("Edit the selected affiliation's fields")
        correspondence_edit.clicked.connect(
            lambda _checked=False: self.edit_affiliation_item(
                self.correspondence_affiliations.currentItem()))
        correspondence_page = QWidget()
        correspondence_layout = QVBoxLayout(correspondence_page)
        correspondence_layout.addWidget(QLabel("Corresponding author"))
        correspondence_layout.addWidget(self.correspondence_details)
        correspondence_layout.addWidget(QLabel("Corresponding author affiliation"))
        correspondence_layout.addWidget(QLabel("Double-click an affiliation to edit its fields."))
        correspondence_layout.addWidget(self.correspondence_affiliations, 1)
        correspondence_buttons = QHBoxLayout()
        correspondence_buttons.addWidget(correspondence_edit)
        correspondence_buttons.addStretch()
        correspondence_layout.addLayout(correspondence_buttons)
        self.tabs.addTab(correspondence_page, "Corresponding Author")
        self.validation_list = QListWidget(); self.tabs.addTab(self.validation_list, "Validation")
        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.setContentsMargins(0,0,0,0)
        right_layout.addWidget(QLabel("XML Preview / Raw XML"))
        self.mode_tabs = QTabWidget()
        self.preview = QPlainTextEdit(); self.preview.setLineWrapMode(QPlainTextEdit.WidgetWidth); self.preview.setStyleSheet("font-family:Consolas,monospace")
        self.raw = QPlainTextEdit(); self.raw.setLineWrapMode(QPlainTextEdit.WidgetWidth); self.raw.setStyleSheet("font-family:Consolas,monospace"); self.raw.textChanged.connect(self._raw_changed)
        self.preview.textChanged.connect(self._preview_changed)
        self.mode_tabs.addTab(self.preview, "Preview"); self.mode_tabs.addTab(self.raw, "Raw XML")
        self.pdf_preview = PDFViewer()
        self.pdf_preview.setMinimumSize(0, 0)
        self.pdf_preview_path: Path | None = None
        self._pdf_text_document = None
        pdf_page = QWidget()
        pdf_layout = QVBoxLayout(pdf_page)
        pdf_layout.setContentsMargins(0, 0, 0, 0)
        pdf_splitter = QSplitter(Qt.Vertical)
        pdf_splitter.addWidget(self.pdf_preview)
        text_panel = QWidget()
        text_layout = QVBoxLayout(text_panel)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_heading = QLabel("Selectable PDF Text · Select text and press Ctrl+C to copy")
        text_heading.setStyleSheet("color:#A8B5C7;font-weight:600;padding:4px;")
        text_layout.addWidget(text_heading)
        self.pdf_text = QPlainTextEdit()
        self.pdf_text.setReadOnly(True)
        self.pdf_text.setPlaceholderText("Open a PDF in the Converter to view and copy its text here.")
        self.pdf_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        text_layout.addWidget(self.pdf_text, 1)
        pdf_splitter.addWidget(text_panel)
        pdf_splitter.setSizes([540, 220])
        pdf_splitter.setChildrenCollapsible(False)
        pdf_layout.addWidget(pdf_splitter)
        self.pdf_preview.pageChanged.connect(self._update_pdf_text_page)
        self.mode_tabs.addTab(pdf_page, "PDF Preview")
        right_layout.addWidget(self.mode_tabs)
        splitter.addWidget(self.tabs); splitter.addWidget(right); splitter.setSizes([560, 700]); splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)
        for editor, field in ((self.title_edit, "title"), (self.abstract_edit, "abstract")):
            editor.setContextMenuPolicy(Qt.CustomContextMenu)
            editor.customContextMenuRequested.connect(
                lambda point, e=editor, f=field: self._field_menu(e, f, point)
            )
            editor.installEventFilter(self)
        footer = QHBoxLayout(); self.status = QLabel("Ready"); footer.addWidget(self.status,1); footer.addWidget(QLabel("Save drafts anytime; validate before export.")); save = QPushButton("Validate && Export"); save.clicked.connect(self.save_copy); footer.addWidget(save); root.addLayout(footer)
        outer.addWidget(content, 1)

    def go_back(self) -> None:
        self._retain_draft()
        main_window = self.window()
        if hasattr(main_window, "show_converter_page"):
            main_window.show_converter_page()

    def set_pdf_source(self, path: Path | None) -> None:
        """Show the converter's current source PDF in this workspace."""
        if path is None or not path.is_file():
            self.pdf_preview_path = None
            if self._pdf_text_document is not None:
                self._pdf_text_document.close()
                self._pdf_text_document = None
            self.pdf_text.clear()
            return
        resolved = path.resolve()
        if resolved == self.pdf_preview_path:
            return
        if self._pdf_text_document is not None:
            self._pdf_text_document.close()
        self._pdf_text_document = fitz.open(resolved)
        self.pdf_preview.load_pdf(str(resolved))
        self.pdf_preview_path = resolved
        self._update_pdf_text_page(0, self._pdf_text_document.page_count)

    def _update_pdf_text_page(self, page_index: int, _page_count: int) -> None:
        """Populate the copyable text surface for the PDF preview's active page."""
        if self._pdf_text_document is None or not 0 <= page_index < self._pdf_text_document.page_count:
            self.pdf_text.clear()
            return
        self.pdf_text.setPlainText(self._pdf_text_document.load_page(page_index).get_text("text"))
        self.pdf_text.moveCursor(QTextCursor.MoveOperation.Start)

    def open_xml(self, path: Path | None = None) -> bool:
        # Be defensive for callers that connect Qt's clicked(bool) signal
        # directly instead of using the no-argument wrapper above.
        if isinstance(path, bool):
            path = None
        if path is None:
            selected, _ = QFileDialog.getOpenFileName(self, "Open XML", "", "XML files (*.xml);;All files (*)")
            if not selected: return False
            path = Path(selected)
        try:
            key = 'file:' + str(Path(path).resolve())
            if key in self._drafts:
                return self.activate_draft(key)
            session = XmlDocumentSession.open(path)
            self._retain_draft()
            self.session = session
            self._draft_key = "file:" + str(Path(path).resolve())
        except (OSError, etree.XMLSyntaxError, ValueError) as exc:
            QMessageBox.critical(self, "Could not open XML", str(exc)); return False
        self._refresh()
        self._retain_draft()
        return True

    def load_xml_text(
        self,
        text: str,
        label_path: Path,
        pdf_source: Path | None = None,
    ) -> bool:
        """Load generated XML directly into the correction workspace, without saving it."""
        self._retain_draft()
        key = getattr(self, '_incoming_draft_key', None) or (str(pdf_source or '') + '|' + str(label_path))
        self._incoming_draft_key = None
        previous = self._drafts.get(key)
        if previous:
            if self._regeneration_content(previous.get('generated_xml')) == self._regeneration_content(text):
                return self.activate_draft(key)
            if not self.review_regeneration(previous['xml'], text):
                previous['pending_generated'] = text
                return self.activate_draft(key)
            revision = 1
            while f'{key}|revision:{revision}' in self._drafts:
                revision += 1
            archive = dict(previous)
            archive['path'] = str(Path(previous['path']).with_stem(Path(previous['path']).stem + f'_revision_{revision}'))
            self._drafts[f'{key}|revision:{revision}'] = archive
        try:
            self.session = XmlDocumentSession.from_text(text, label_path)
            self._draft_key = key
            self._drafts[key] = {"generated_xml": text}
            self.set_pdf_source(pdf_source)
        except (OSError, etree.XMLSyntaxError, ValueError) as exc:
            QMessageBox.critical(self, "Could not prepare XML correction", str(exc))
            return False
        self._refresh()
        self._retain_draft()
        return True

    def _refresh(self, *, preserve_abstract: bool = False) -> None:
        if not self.session: return
        for index in range(self.tabs.count()):
            self.tabs.widget(index).setEnabled(True)
        self._record_history()
        s = self.session; self._syncing = True
        self._refresh_fields(preserve_abstract=preserve_abstract)
        text = s.xml_text(); self.preview.setPlainText(text); self.raw.setPlainText(text)
        source_label = "FILE" if s.source_path is not None else "DRAFT IN MEMORY"
        validation_label = "Needs review" if s.validation else "Not validated"
        self.summary.setText(f"{source_label}  {s.path.name}  ·  {s.path}\nVALIDATION  {validation_label}     AUTHORS  {len(s.authors())}     AFFILIATIONS  {len(s.affiliations())}     PROFILE  {s.profile}")
        self.status.setText("Draft retained in workspace; Save Draft to keep it after closing")
        self._draft_status()
        self._syncing = False

    def eventFilter(self, watched, event):
        if watched in (self.title_edit, self.abstract_edit) and event.type() in (
            QEvent.ShortcutOverride, QEvent.KeyPress
        ):
            undo = event.matches(QKeySequence.StandardKey.Undo)
            redo = event.matches(QKeySequence.StandardKey.Redo) or (
                event.key() == Qt.Key_Z
                and event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier)
            )
            if undo or redo:
                event.accept()
                if event.type() == QEvent.KeyPress:
                    self._undo_field() if undo else self._redo_field()
                return True
        return super().eventFilter(watched, event)

    def _record_history(self):
        text = self.session.xml_text()
        if getattr(self, "_history_session", None) is not self.session:
            self._history_session = self.session
            self._history = [text]
            self._history_index = 0
        elif self._history[self._history_index] != text:
            self._history = self._history[:self._history_index + 1] + [text]
            self._history_index += 1

    def _undo_field(self):
        self._move_history(-1)

    def _redo_field(self):
        self._move_history(1)

    def _move_history(self, step):
        if not self.session:
            return
        self._record_history()
        index = self._history_index + step
        if 0 <= index < len(self._history):
            self._history_index = index
            self.session.commit_raw(self._history[index])
            self._refresh()

    def _formatting_toolbar(self, editor, field):
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        for label, tag, hint in (
            ("Superscript", "sup", "Make the selected text superscript"),
            ("Subscript", "inf", "Make the selected text subscript"),
            ("Normal text", "normal", "Remove superscript or subscript formatting from the selection"),
        ):
            button = QPushButton(label)
            button.setObjectName(f"{field}_{tag}_button")
            button.setToolTip(hint)
            button.setFocusPolicy(Qt.NoFocus)
            button.setEnabled(False)
            button.clicked.connect(
                lambda checked=False, t=tag: self._format_selection(editor, field, t)
            )
            editor.selectionChanged.connect(
                lambda b=button: b.setEnabled(
                    self.session is not None and editor.textCursor().hasSelection()
                )
            )
            layout.addWidget(button)
        layout.addStretch()
        return toolbar

    def _field_menu(self, editor, field, point):
        menu = QMenu(editor)
        for label, callback in (("Undo (Ctrl+Z)", self._undo_field), ("Redo (Ctrl+Y)", self._redo_field),
                                ("Cut", editor.cut), ("Copy", editor.copy), ("Paste", editor.paste),
                                ("Select all", editor.selectAll)):
            menu.addAction(label, callback)
        menu.addSeparator()
        for label, tag in (("Superscript", "sup"), ("Subscript", "inf"), ("Normal text", "normal")):
            action = menu.addAction(label)
            action.setEnabled(self.session is not None and editor.textCursor().hasSelection())
            action.triggered.connect(lambda checked=False, t=tag: self._format_selection(editor, field, t))
        menu.exec(editor.mapToGlobal(point))

    def _format_selection(self, editor, field, tag):
        if not self.session:
            return
        cursor = editor.textCursor()
        anchor, position = cursor.anchor(), cursor.position()
        scroll_position = editor.verticalScrollBar().value()
        # Qt positions count UTF-16 code units; XML offsets count Unicode characters.
        value = editor.toPlainText().encode("utf-16-le")
        start = len(value[:cursor.selectionStart() * 2].decode("utf-16-le"))
        end = len(value[:cursor.selectionEnd() * 2].decode("utf-16-le"))
        self._record_history()
        try:
            self.session.apply_script(field, start, end, tag)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._refresh()
        cursor = editor.textCursor()
        cursor.setPosition(anchor)
        cursor.setPosition(position, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.verticalScrollBar().setValue(scroll_position)
        editor.setFocus()

    def _refresh_fields(self, *, preserve_abstract: bool = False) -> None:
        """Refresh structured controls without replacing either XML editor."""
        if not self.session: return
        s = self.session
        self.title_edit.setPlainText(s.title())
        if not preserve_abstract:
            self.abstract_edit.setPlainText(s.abstract())
        self._highlight_scripts(self.title_edit, s.title_node())
        self._highlight_scripts(self.abstract_edit, s.abstract_node())
        self.author_list.clear()
        authors = s.authors()

        def affiliation_editable(node) -> bool:
            return etree.QName(node).localname == 'affiliation'

        def add_affiliation_item(target, text: str) -> None:
            item = QListWidgetItem(text)
            if affiliation_editable(target):
                item.setData(Qt.UserRole + 1, s.tree.getpath(target))
                item.setToolTip("Double-click to edit affiliation fields")
            else:
                item.setToolTip("This affiliation has no editable fields here; use Raw XML")
            self.author_list.addItem(item)

        for number, (label, indices, nodes, container) in enumerate(s.affiliation_groups(), 1):
            is_group = container is not None and etree.QName(container).localname == 'author-group'
            heading = QListWidgetItem(f"Group {number}: {label}" if is_group else label)
            heading.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if len(nodes) == 1:
                if affiliation_editable(nodes[0]):
                    heading.setData(Qt.UserRole + 1, s.tree.getpath(nodes[0]))
                    heading.setToolTip("Double-click to edit affiliation fields")
                else:
                    heading.setToolTip("This affiliation has no editable fields here; use Raw XML")
            elif not nodes and is_group:
                # Double-clicking the group lets the user fill in an affiliation
                # for authors that currently have none.
                heading.setData(Qt.UserRole + 1, s.tree.getpath(container))
                heading.setToolTip("Double-click to add affiliation fields")
            font = heading.font(); font.setBold(True); heading.setFont(font)
            self.author_list.addItem(heading)
            if len(nodes) > 1:
                for index, target in enumerate(nodes, 1):
                    add_affiliation_item(
                        target,
                        f"    Affiliation {index}: {s._affiliation_label(target)}",
                    )
            for index in indices:
                # Blank ANI authors are common in drafts; keep them selectable
                # so their empty fields can be filled from the editor.
                name = s.author_name(authors[index]) or f"Unnamed author {index + 1}"
                item = QListWidgetItem("    " + name)
                item.setData(Qt.UserRole, index)
                self.author_list.addItem(item)
        self.keyword_list.clear()
        for node in s.keywords(): self.keyword_list.addItem(" ".join("".join(node.itertext()).split()))
        self._fill_correspondence()

    def _fill_correspondence(self) -> None:
        """Show the corresponding author and their editable affiliations."""
        self.correspondence_details.clear()
        self.correspondence_affiliations.clear()
        if not self.session:
            return
        person, details, affiliations = self.session.correspondence()
        if person is None:
            empty = QListWidgetItem("No corresponding author found in this XML")
            empty.setFlags(Qt.ItemIsEnabled)
            self.correspondence_details.addItem(empty)
            return
        labels = {'initials': 'Initials', 'given-name': 'Given names',
                  'given-names': 'Given names', 'surname': 'Surname',
                  'string-name': 'Full name', 'degrees': 'Degrees',
                  'email': 'Email', 'phone': 'Phone', 'fax': 'Fax'}
        for field, value in details:
            item = QListWidgetItem(
                f"{labels.get(field, field.replace('-', ' ').title())}: {value}")
            item.setFlags(Qt.ItemIsEnabled)
            self.correspondence_details.addItem(item)
        if not affiliations:
            note = QListWidgetItem("No affiliation recorded for the corresponding author")
            note.setFlags(Qt.ItemIsEnabled)
            self.correspondence_affiliations.addItem(note)
            return
        for index, node in enumerate(affiliations, 1):
            label = self.session._affiliation_label(node)
            item = QListWidgetItem(f"Affiliation {index}: {label}" if len(affiliations) > 1 else label)
            if etree.QName(node).localname == 'affiliation':
                item.setData(Qt.UserRole + 1, self.session.tree.getpath(node))
                item.setToolTip("Double-click to edit affiliation fields")
            else:
                item.setToolTip("This affiliation has no editable fields here; use Raw XML")
            self.correspondence_affiliations.addItem(item)

    def _highlight_scripts(self, editor: QPlainTextEdit, node) -> None:
        """Tint script spans without modifying text, XML, or the undo history."""
        selections = []
        if self.session is not None and node is not None:
            source, runs = self.session._text_and_script_runs(node)
            text = editor.toPlainText()
            for run in preserve_matching_runs(source, text, runs):
                color = SCRIPT_COLORS.get(run["type"])
                if color is None:
                    continue
                start, end = int(run["start"]), int(run["end"])
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(editor.document())
                # Qt uses UTF-16 positions, including for non-BMP characters.
                selection.cursor.setPosition(len(text[:start].encode("utf-16-le")) // 2)
                selection.cursor.setPosition(
                    len(text[:end].encode("utf-16-le")) // 2, QTextCursor.KeepAnchor
                )
                selection.format.setForeground(QColor(color))
                selections.append(selection)
        editor.setExtraSelections(selections)

    def _title_changed(self) -> None:
        if not self._syncing and self.session:
            value = self.title_edit.toPlainText()
            try: self.session.set_title(value)
            except ValueError as exc: self.status.setText(str(exc)); return
            position = self.title_edit.textCursor().position()
            self._refresh()
            self.title_edit.blockSignals(True)
            self.title_edit.setPlainText(value)
            cursor = self.title_edit.textCursor()
            cursor.setPosition(min(position, self.title_edit.document().characterCount() - 1))
            self.title_edit.setTextCursor(cursor)
            self._highlight_scripts(self.title_edit, self.session.title_node())
            self.title_edit.blockSignals(False)

    def _abstract_changed(self) -> None:
        if not self._syncing and self.session:
            try: self.session.set_abstract(self.abstract_edit.toPlainText())
            except ValueError as exc: self.status.setText(str(exc)); return
            # The model's display text normalizes whitespace. Do not replace
            # the active editor after each keystroke: a trailing space or
            # newline is part of the user's next word/paragraph in progress.
            self._refresh(preserve_abstract=True)

    def _raw_changed(self) -> None:
        self._xml_editor_changed(self.raw, self.preview)

    def _preview_changed(self) -> None:
        self._xml_editor_changed(self.preview, self.raw)

    def _xml_editor_changed(self, edited: QPlainTextEdit, other: QPlainTextEdit) -> None:
        if self._syncing or not self.session: return
        text = edited.toPlainText()
        # Both tabs edit the same draft, including incomplete XML. Parsing
        # controls model updates and export, not which text the other tab sees.
        self._syncing = True
        try:
            if other.toPlainText() != text:
                other.setPlainText(text)
        finally:
            self._syncing = False
        ok, message, line, column = self.session.commit_raw(text)
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if page is not self.validation_list:
                page.setEnabled(ok)
        if ok:
            self.session.validation = []
            self._record_history()
            self._syncing = True
            self._refresh_fields()
            source_label = "FILE" if self.session.source_path is not None else "DRAFT IN MEMORY"
            self.summary.setText(f"{source_label}  {self.session.path.name}  ·  {self.session.path}\nVALIDATION  Not validated     AUTHORS  {len(self.session.authors())}     AFFILIATIONS  {len(self.session.affiliations())}     PROFILE  {self.session.profile}")
            self.status.setText("Draft changed; Save Draft to keep changes after closing")
            self._draft_status()
            self._syncing = False
        else:
            self._unparsed_text = text
            self.status.setText(f"XML parse error at line {line}, column {column}: {message}")

    def edit_affiliation_item(self, item) -> None:
        """Open the affiliation editor for a list row carrying a node path."""
        if item is None:
            self.status.setText("Select an affiliation to edit")
            return
        path = item.data(Qt.UserRole + 1)
        if not path:
            self.status.setText(
                item.toolTip() or "This affiliation has no editable fields here; use Raw XML")
            return
        self.edit_affiliation(path)

    def edit_author(self) -> None:
        if not self.session or self.author_list.currentRow() < 0: return
        affinity = self.author_list.currentItem()
        affiliation_path = affinity.data(Qt.UserRole + 1)
        if affiliation_path:
            self.edit_affiliation(affiliation_path)
            return
        index = affinity.data(Qt.UserRole)
        if index is None:
            self.status.setText(
                affinity.toolTip() or "Select an author or affiliation field to edit"
            )
            return
        try:
            values = self.session.author_form(index)
        except (IndexError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit author")
        dialog.resize(520, 460)
        layout = QFormLayout(dialog)
        labels = {'@seq': 'Sequence', '@author-instance-id': 'Author instance ID',
                  '@orcid': 'ORCID', 'initials': 'Initials', 'degrees': 'Degrees',
                  'surname': 'Surname', 'given-name': 'Given names',
                  'given-names': 'Given names', 'string-name': 'Full name',
                  'suffix': 'Suffix', 'e-address': 'Email'}
        fields: dict[str, QLineEdit] = {}
        for key, value in values.items():
            name = key[1:] if key.startswith('@') else key
            label = labels.get(key, name.replace('-', ' ').title())
            field = QLineEdit(value)
            field.setObjectName(f"author_{name}")
            field.setPlaceholderText(label)
            layout.addRow(label, field)
            fields[key] = field
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            try:
                submitted = {key: field.text() for key, field in fields.items()}
                if self.session.set_author_form(index, submitted):
                    self._refresh()
            except ValueError as exc:
                QMessageBox.warning(self, "Cannot edit author", str(exc))
        dialog.deleteLater()

    def edit_affiliation(self, path) -> None:
        if not self.session:
            return
        nodes = self.session.tree.xpath(path, namespaces={k: v for k, v in self.session.tree.getroot().nsmap.items() if k})
        if not nodes:
            return
        node = nodes[0]
        try:
            values = self.session.affiliation_form(node)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit affiliation")
        dialog.resize(600, 640)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        labels = {'affiliation-instance-id': 'Affiliation instance ID',
                  'organization': 'Organization', 'address-part': 'Address',
                  'city': 'City', 'state': 'State', 'postal-code': 'Postal code',
                  'country': 'Country', 'source-text': 'Source text'}
        fields: dict[str, QWidget] = {}
        containers: dict[str, QWidget] = {}

        def organization_keys() -> list[str]:
            return [key for key in fields if key.partition(':')[0] == 'organization']

        def organization_label(index: int) -> str:
            return 'Organization' if index == 1 else f'Organization {index}'

        def strip_commas(field: QLineEdit, text: str) -> None:
            # Organization names carry no comma separators; drop them as the
            # user types so the field always matches what the XML will store.
            if ',' not in text:
                return
            before = text[:field.cursorPosition()].replace(',', '')
            field.blockSignals(True)
            field.setText(text.replace(',', ''))
            field.setCursorPosition(len(before))
            field.blockSignals(False)

        def add_field(key: str, value: str) -> tuple[str, QWidget]:
            base = key.split(':')[0].split('@')[0]
            field = QLineEdit(normalize_organization(value) if base == 'organization' else value)
            field.setObjectName(f'affiliation_{key}')
            if base == 'organization':
                field.textChanged.connect(
                    lambda text, target=field: strip_commas(target, text)
                )
            label = 'Country ISO code' if '@iso-code' in key else labels[base]
            if ':' in key:
                label += ' ' + key.split(':')[1].split('@')[0]
            fields[key] = field
            if base != 'organization':
                return label, field
            container = QWidget()
            row_layout = QHBoxLayout(container)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(field, 1)
            remove = QPushButton("Remove")
            remove.setObjectName(f'affiliation_remove_{key}')
            remove.setToolTip("Remove this organization from the affiliation")
            remove.clicked.connect(lambda _checked=False, f=field: remove_field(f))
            row_layout.addWidget(remove)
            containers[key] = container
            return label, container

        def remove_field(field: QLineEdit) -> None:
            # Resolve the current key: renumbering changes it after a removal.
            key = next((key for key, value in fields.items() if value is field), None)
            if key is not None:
                remove_organization(key)

        def remove_organization(key: str) -> None:
            container = containers.pop(key)
            fields.pop(key, None)
            row, _role = form.getWidgetPosition(container)
            if row >= 0:
                form.removeRow(row)  # also disposes of the row's widgets
            # Renumber the survivors so the form always describes the final,
            # contiguous organization list that the XML should keep.
            for index, survivor in enumerate(organization_keys(), 1):
                target = 'organization' if index == 1 else f'organization:{index}'
                if target == survivor:
                    continue
                field = fields.pop(survivor)
                moved = containers.pop(survivor)
                fields[target], containers[target] = field, moved
                field.setObjectName(f'affiliation_{target}')
                for button in moved.findChildren(QPushButton):
                    if button.objectName().startswith('affiliation_remove_'):
                        button.setObjectName(f'affiliation_remove_{target}')
                moved_row, _role = form.getWidgetPosition(moved)
                label_item = form.itemAt(moved_row, QFormLayout.LabelRole)
                if label_item is not None and label_item.widget() is not None:
                    label_item.widget().setText(organization_label(index))

        # Source text is verbatim, often long text, so it gets its own
        # multi-line editor below the fields instead of a one-line box.
        source_field = QPlainTextEdit()
        source_field.setObjectName('affiliation_source-text')
        source_field.setPlaceholderText("Verbatim affiliation as printed in the source")
        source_field.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        source_field.setPlainText(values.get('source-text', ''))
        source_field.setMinimumHeight(60)
        fields['source-text'] = source_field

        for key, value in values.items():
            if key == 'source-text':
                continue
            label, widget = add_field(key, value)
            form.addRow(label, widget)

        def add_organization() -> None:
            keys = organization_keys()
            index = len(keys) + 1
            key = 'organization' if index == 1 else f'organization:{index}'
            label, widget = add_field(key, '')
            # Keep organizations together even though other fields follow them.
            if keys:
                position, _role = form.getWidgetPosition(containers[keys[-1]])
                position += 1
            else:
                position = 1  # directly after the affiliation instance ID
            form.insertRow(position, label, widget)
            fields[key].setFocus()

        add_organization_button = QPushButton("Add organization")
        add_organization_button.setObjectName('affiliation_add_organization')
        add_organization_button.setToolTip("Append another organization entry to this affiliation")
        add_organization_button.clicked.connect(lambda _checked=False: add_organization())
        scroll.setWidget(form_widget)
        source_pane = QWidget()
        source_layout = QVBoxLayout(source_pane)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(QLabel("Source text"))
        source_layout.addWidget(source_field, 1)
        fields_splitter = QSplitter(Qt.Vertical)
        fields_splitter.setObjectName('affiliation_source_splitter')
        # The divider resizes the field, but never hides either pane.
        fields_splitter.setChildrenCollapsible(False)
        fields_splitter.addWidget(scroll)
        fields_splitter.addWidget(source_pane)
        fields_splitter.setStretchFactor(0, 1)
        fields_splitter.setStretchFactor(1, 0)
        fields_splitter.setSizes([380, 130])
        layout.addWidget(fields_splitter, 1)
        organization_actions = QHBoxLayout()
        organization_actions.addWidget(add_organization_button)
        organization_actions.addStretch()
        layout.addLayout(organization_actions)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.rejected.connect(dialog.reject)

        def field_text(field: QWidget) -> str:
            if isinstance(field, QPlainTextEdit):
                return field.toPlainText()
            return field.text()

        def apply():
            submitted = {key: field_text(field) for key, field in fields.items()}
            # Blank organization rows are not kept: the XML receives the final
            # non-empty list, so removed and never-filled entries both vanish.
            organization_values = [
                submitted.pop(key)
                for key in sorted(
                    (key for key in submitted if key.partition(':')[0] == 'organization'),
                    key=lambda key: int(key.partition(':')[2] or '1'),
                )
            ]
            organization_values = [
                normalized for normalized in map(normalize_organization, organization_values)
                if normalized
            ]
            for index, value in enumerate(organization_values, 1):
                submitted['organization' if index == 1 else f'organization:{index}'] = value
            try:
                changed = self.session.set_affiliation_form(node, submitted)
            except ValueError as exc:
                QMessageBox.warning(dialog, "Cannot update affiliation", str(exc))
                return
            if changed:
                self._refresh()
            dialog.accept()

        buttons.accepted.connect(apply)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def add_author(self) -> None:
        if not self.session: return
        value, ok = QInputDialog.getText(self, "Add author", "Author name")
        if ok and value.strip():
            try: self.session.add_author(value.strip()); self._refresh()
            except ValueError as exc: QMessageBox.information(self, "Cannot add author", str(exc))

    def remove_author(self) -> None:
        if not self.session or self.author_list.currentRow() < 0: return
        index = self.author_list.currentItem().data(Qt.UserRole)
        if index is None: return
        if QMessageBox.question(self, "Remove author", "Remove the selected author from the XML?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        try: self.session.remove_author(index); self._refresh()
        except ValueError as exc: QMessageBox.warning(self, "Cannot remove author", str(exc))

    def edit_keyword(self) -> None:
        if not self.session or self.keyword_list.currentRow() < 0: return
        i=self.keyword_list.currentRow(); value,ok=QInputDialog.getText(self,"Edit keyword","Keyword",text=self.keyword_list.currentItem().text())
        if ok: self.session.set_keyword(i,value); self._refresh()

    def add_keyword(self) -> None:
        if not self.session:return
        value,ok=QInputDialog.getText(self,"Add keyword","Keyword")
        if ok and value.strip():
            try:self.session.add_keyword(value.strip());self._refresh()
            except ValueError as exc:QMessageBox.information(self,"Cannot add keyword",str(exc))

    def remove_keyword(self) -> None:
        if not self.session or self.keyword_list.currentRow()<0:return
        node=self.session.keywords()[self.keyword_list.currentRow()]; node.getparent().remove(node); self.session.dirty=True; self.session.validation=[]; self._refresh()

    def validate(self) -> None:
        if not self.session:return
        issues=self.session.validate(); self.validation_list.clear()
        for issue in issues: self.validation_list.addItem(f"{issue.severity.upper()}: {issue.message}" + (f" (line {issue.line}, column {issue.column})" if issue.line else ""))
        errors=sum(i.severity=="error" for i in issues); warnings=sum(i.severity=="warning" for i in issues)
        status="Invalid" if errors else "Needs review" if warnings else "Valid"
        source_label = "FILE" if self.session.source_path is not None else "DRAFT IN MEMORY"
        self.summary.setText(f"{source_label}  {self.session.path.name}  ·  {self.session.path}\nVALIDATION  {status}     AUTHORS  {len(self.session.authors())}     AFFILIATIONS  {len(self.session.affiliations())}     PROFILE  {self.session.profile}")
        self.status.setText(f"Validation complete · {errors} errors · {warnings} warnings")

    def save_copy(self) -> bool:
        if not self.session:return False
        self.validate()
        if any(issue.severity == "error" for issue in self.session.validation):
            QMessageBox.warning(self, "XML has errors", "Fix validation errors before exporting a copy.")
            self.tabs.setCurrentWidget(self.validation_list)
            return False
        suggested=self.session.path.with_name(self.session.path.stem+"_corrected.xml")
        selected,_=QFileDialog.getSaveFileName(self,"Save Corrected XML Copy",str(suggested),"XML files (*.xml)")
        if not selected:return False
        dest=Path(selected)
        if dest.exists() and QMessageBox.question(self,"Replace file?",f"Replace existing file {dest.name}?",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return False
        try:self.session.save_copy(dest)
        except (OSError,ValueError) as exc:QMessageBox.critical(self,"Save failed",str(exc));return False
        self._retain_draft()
        self._drafts[self._draft_key]["exported_xml"] = self.session.xml_text()
        self._drafts[self._draft_key]["export_path"] = str(dest)
        QMessageBox.information(self,"Copy saved",f"Corrected XML saved to:\n{dest}"); self.status.setText(f"Saved copy: {dest}"); return True
