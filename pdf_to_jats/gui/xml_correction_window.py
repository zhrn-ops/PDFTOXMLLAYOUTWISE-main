"""Standalone XML correction workspace integrated with the converter."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy

import fitz
from lxml import etree
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor, QTextCursor, QKeySequence, QTextDocument, QFont
from PySide6.QtWidgets import (
    QWidget, QFileDialog, QFormLayout, QHBoxLayout, QDialog, QDialogButtonBox, QStyledItemDelegate,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QComboBox, QPlainTextEdit, QSplitter, QTabWidget, QVBoxLayout, QWidget, QMenu, QTextEdit, QScrollArea,
)

from pdf_to_jats.core.xml_correction import XmlDocumentSession, normalize_organization
from pdf_to_jats.core.draft_workspace import canonical_history
from pdf_to_jats.core.xml_validation import ExportMode, SchemaProfile, ValidationStatus
from pdf_to_jats.core.inline_script_detector import preserve_matching_runs
from pdf_to_jats.core.language_codes import LANGUAGES, UNDETERMINED
from pdf_to_jats.gui.pdf_viewer import PDFViewer
from pdf_to_jats.gui.xml_code_editor import XmlCodeEditor
from pdf_to_jats.gui.article_drafts import ArticleDrafts
from pdf_to_jats.gui.parser_reviews import ParserReviews
from pdf_to_jats.gui.styles import themed_style

SCRIPT_COLORS = {"sup": "#78AAFF", "sub": "#FBBF24"}
# Appendix A codes, so every language the table accepts can be picked here.
LANGUAGE_CHOICES = tuple(sorted(row["alpha3"] for row in LANGUAGES)) + (UNDETERMINED,)
LANGUAGE_LABELS = {row["alpha3"]: f"{row['alpha3']} — {row['name']}" for row in LANGUAGES}
LANGUAGE_LABELS[UNDETERMINED] = f"{UNDETERMINED} — Undetermined"


def add_language_choices(combo: QComboBox) -> None:
    """List every appendix code with its language name, storing the code as item data."""
    for code in LANGUAGE_CHOICES:
        combo.addItem(LANGUAGE_LABELS.get(code, code), code)


def selected_language(combo: QComboBox) -> str:
    """Read the code from a language picker, including freely typed input."""
    index = combo.currentIndex()
    if index >= 0 and combo.currentText() == combo.itemText(index) and combo.itemData(index):
        return str(combo.itemData(index)).strip().upper()
    return combo.currentText().split("—")[0].strip().upper()


def select_language(combo: QComboBox, code: str) -> None:
    """Show an existing code even when the XML holds a value outside the appendix."""
    wanted = str(code or "").strip().upper()
    index = combo.findData(wanted) if wanted else -1
    if index >= 0:
        combo.setCurrentIndex(index)
    else:
        combo.setCurrentText(str(code or ""))


SCRIPT_BACKGROUNDS = {
    'dark': {'sup': '#183653', 'sub': '#513a10'},
    'light': {'sup': '#cfe4ff', 'sub': '#ffe39a'},
}


class _AuthorRowDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.data(Qt.UserRole) is not None:
            option.text = ''  # The row widget renders author names.


def _tag_end(text: str, start: int) -> int:
    """Return the index of a tag's closing '>', ignoring quoted '>'."""
    quote = ''
    for position in range(start + 1, len(text)):
        character = text[position]
        if quote:
            if character == quote:
                quote = ''
        elif character in '"\'':
            quote = character
        elif character == '>':
            return position
    return -1


def _element_spans(text: str) -> list[tuple[int, int]]:
    """Character span of every element in ``text``, in document order.

    Comments, CDATA, processing instructions and the doctype are skipped so the
    result lines up with ``ElementTree.iter()`` filtered to real elements.
    """
    spans: list[tuple[int, int]] = []
    open_elements: list[int] = []
    position = 0
    while position < len(text):
        start = text.find('<', position)
        if start < 0:
            break
        if text.startswith('<!--', start):
            end = text.find('-->', start)
            position = len(text) if end < 0 else end + 3
            continue
        if text.startswith('<![CDATA[', start):
            end = text.find(']]>', start)
            position = len(text) if end < 0 else end + 3
            continue
        if text.startswith('<?', start):
            end = text.find('?>', start)
            position = len(text) if end < 0 else end + 2
            continue
        if text.startswith('<!', start):
            end = text.find('>', start)
            position = len(text) if end < 0 else end + 1
            continue
        end = _tag_end(text, start)
        if end < 0:
            break
        if text.startswith('</', start):
            if open_elements:
                index = open_elements.pop()
                spans[index] = (spans[index][0], end + 1)
        else:
            spans.append((start, end + 1))
            if text[end - 1] != '/':
                open_elements.append(len(spans) - 1)
        position = end + 1
    return spans


def _script_legend_text(theme='dark') -> str:
    return ' &nbsp;·&nbsp; '.join(
        f'<span style="color:{themed_style(SCRIPT_COLORS[kind], theme)};'
        f'background-color:{SCRIPT_BACKGROUNDS[theme][kind]};font-weight:700">'
        f' {label} </span>'
        for kind, label in (('sup', 'Superscript'), ('sub', 'Subscript'))
    )


def _script_legend() -> QLabel:
    label = QLabel(
        f'<span style="color:{SCRIPT_COLORS["sup"]}">Superscript</span>'
        ' &nbsp;·&nbsp; '
        f'<span style="color:{SCRIPT_COLORS["sub"]}">Subscript</span>'
    )
    label.setText(_script_legend_text())
    label.setToolTip("Select text, then use the toolbar or right-click to change its formatting.")
    label.setProperty('darkLegend', label.text())
    return label


class XmlCorrectionWindow(QWidget, ArticleDrafts, ParserReviews):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("xmlCorrectionWorkspace")
        self.setMinimumSize(900, 620)
        self.setStyleSheet("QWidget#xmlCorrectionWorkspace { background:#101d2c; color:#e7f0ff; } QLabel { color:#dce9fa; } QPushButton { background:#14283c; color:#e7f0ff; border:1px solid #294663; border-radius:5px; padding:7px 12px; } QPushButton:hover { background:#1b3a59; } QLineEdit,QPlainTextEdit,QListWidget { background:#091421; color:#e7f0ff; border:1px solid #294663; border-radius:4px; padding:6px; } QTabWidget::pane { border:1px solid #294663; } QTabBar::tab { background:#14283c; color:#cfe0f2; padding:8px 14px; } QTabBar::tab:selected { background:#0874d1; }")
        self.session: XmlDocumentSession | None = None
        self.schema_profile: SchemaProfile | None = None
        self._syncing = False
        self._xml_text_baseline = ''
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
        title_heading = QHBoxLayout()
        title_heading.addWidget(QLabel("Title"))
        title_heading.addStretch(1)
        title_heading.addWidget(QLabel("Language (xml:lang)"))
        self.title_language = QComboBox()
        self.title_language.setEditable(True)
        add_language_choices(self.title_language)
        self.title_language.setMaximumWidth(190)
        self.title_language.setToolTip(
            "Language code for the primary title, e.g. ENG or FAS. "
            "Use the same code as the title's printed language."
        )
        self.title_language.activated.connect(lambda _index: self._title_language_changed())
        if self.title_language.lineEdit() is not None:
            self.title_language.lineEdit().editingFinished.connect(self._title_language_changed)
        title_heading.addWidget(self.title_language)
        title_layout.addLayout(title_heading)
        self.title_edit = QPlainTextEdit()
        self.title_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.title_edit.setPlaceholderText("Enter or edit the article title")
        self.title_edit.textChanged.connect(self._title_changed)
        title_layout.addWidget(self._formatting_toolbar(self.title_edit, "title"))
        title_layout.addWidget(self.title_edit, 2)
        title_layout.addWidget(_script_legend())
        other_title_heading = QLabel("Other language titles")
        other_title_heading.setStyleSheet("font-weight:600;padding-top:8px;")
        other_title_heading.setToolTip(
            "Translated titles are written as extra titletext/article-title nodes "
            "with their own xml:lang."
        )
        title_layout.addWidget(other_title_heading)
        self.other_title_list = QListWidget()
        self.other_title_list.setObjectName("other_titles")
        self.other_title_list.setWordWrap(True)
        self.other_title_list.itemDoubleClicked.connect(lambda _item: self.edit_other_title())
        self.other_title_list.currentRowChanged.connect(self._other_title_selection_changed)
        title_layout.addWidget(self.other_title_list, 1)
        other_title_buttons = QHBoxLayout()
        self.add_other_title_button = QPushButton("Add title")
        self.add_other_title_button.setToolTip("Add a title in another language")
        self.add_other_title_button.clicked.connect(self.add_other_title)
        self.edit_other_title_button = QPushButton("Edit selected")
        self.edit_other_title_button.clicked.connect(self.edit_other_title)
        self.remove_other_title_button = QPushButton("Remove")
        self.remove_other_title_button.setToolTip("Remove this translated title from the XML")
        self.remove_other_title_button.clicked.connect(self.remove_other_title)
        other_title_buttons.addWidget(self.add_other_title_button)
        other_title_buttons.addWidget(self.edit_other_title_button)
        other_title_buttons.addWidget(self.remove_other_title_button)
        title_layout.addLayout(other_title_buttons)
        self.tabs.addTab(title_page, "Title")
        self.author_list = QListWidget()
        self.author_list.itemDoubleClicked.connect(lambda _item: self.edit_author())
        self.author_list.setItemDelegate(_AuthorRowDelegate(self.author_list))
        author_buttons = QHBoxLayout()
        edit_author = QPushButton("Edit selected"); edit_author.clicked.connect(self.edit_author)
        add_author = QPushButton("Add author"); add_author.clicked.connect(self.add_author)
        add_group = QPushButton("Add author group")
        add_group.setObjectName('add_author_group')
        add_group.clicked.connect(self.add_author_group)
        remove_author = QPushButton("Remove"); remove_author.clicked.connect(self.remove_author)
        remove_author.setToolTip("Remove the selected author or author group")
        author_buttons.addWidget(edit_author); author_buttons.addWidget(add_author); author_buttons.addWidget(remove_author)
        author_buttons.addWidget(add_group)
        self.abstract_edit = QPlainTextEdit(); self.abstract_edit.textChanged.connect(self._abstract_changed)
        self.keyword_list = QListWidget()
        kw_buttons = QHBoxLayout(); kw_edit = QPushButton("Edit selected"); kw_edit.clicked.connect(self.edit_keyword); kw_add = QPushButton("Add"); kw_add.clicked.connect(self.add_keyword); kw_remove = QPushButton("Remove"); kw_remove.clicked.connect(self.remove_keyword)
        kw_buttons.addWidget(kw_edit); kw_buttons.addWidget(kw_add); kw_buttons.addWidget(kw_remove)
        keywords_page = QWidget(); keywords_layout = QVBoxLayout(keywords_page)
        keywords_layout.addWidget(self.keyword_list); keywords_layout.addLayout(kw_buttons)
        self.tabs.addTab(keywords_page, "Keywords")
        authors_page = QWidget(); author_layout = QVBoxLayout(authors_page); author_layout.addWidget(QLabel("Double-click an author or affiliation to edit its fields.")); author_layout.addWidget(self.author_list)
        self.author_list.setWordWrap(True)
        self.parser_review = QLabel()
        self.parser_review.setWordWrap(True)
        self.parser_review.setTextFormat(Qt.PlainText)
        self.parser_review.setStyleSheet('color: #dc4444;')
        self.parser_review.hide()
        author_layout.insertWidget(1, self.parser_review)
        self.parser_reviews_button = QPushButton("Parser reviews and history")
        self.parser_reviews_button.clicked.connect(self.show_parser_reviews)
        self.parser_reviews_button.hide()
        self.review_duplicates = QPushButton('Review duplicate affiliations')
        self.review_duplicates.setObjectName('review_duplicate_affiliations')
        self.review_duplicates.clicked.connect(self.show_duplicate_affiliations)
        author_layout.insertWidget(1, self.review_duplicates)
        author_layout.addLayout(author_buttons)
        self.tabs.addTab(authors_page, "Authors && Affiliations")
        abstract_page = QWidget(); abstract_layout = QVBoxLayout(abstract_page)
        find_row = QHBoxLayout()
        self.abstract_find = QLineEdit()
        self.abstract_find.setObjectName('abstract_find')
        self.abstract_find.setPlaceholderText('Find in abstract (Ctrl+F)')
        self.abstract_find.setClearButtonEnabled(True)
        self.abstract_find.setToolTip('Case-insensitive search. Press Enter for the next match.')
        find_row.addWidget(self.abstract_find, 1)
        self.abstract_find_previous = QPushButton('Previous')
        self.abstract_find_next = QPushButton('Next')
        find_row.addWidget(self.abstract_find_previous)
        find_row.addWidget(self.abstract_find_next)
        self.abstract_find_status = QLabel()
        find_row.addWidget(self.abstract_find_status)
        self.abstract_find.textChanged.connect(lambda: self._find_abstract(restart=True))
        self.abstract_find.returnPressed.connect(self._find_abstract)
        self.abstract_find_previous.clicked.connect(lambda: self._find_abstract(backward=True))
        self.abstract_find_next.clicked.connect(lambda: self._find_abstract())
        abstract_layout.addLayout(find_row)
        grammar_button = QPushButton('Check grammar && typos')
        grammar_button.setObjectName('check_abstract_grammar')
        grammar_button.setToolTip('Review common English typos and grammar issues locally')
        grammar_button.clicked.connect(self.check_abstract_grammar)
        abstract_layout.addWidget(grammar_button)
        abstract_layout.addWidget(self._formatting_toolbar(self.abstract_edit, "abstract"))
        abstract_layout.addWidget(self.abstract_edit)
        abstract_layout.addWidget(_script_legend())
        self.tabs.addTab(abstract_page, "Abstract")
        self.correspondence_details = QListWidget()
        self.correspondence_details.setObjectName('correspondence_details')
        self.correspondence_details.setWordWrap(True)
        self.correspondence_details.itemDoubleClicked.connect(
            lambda _item: self.edit_corresponding_author())
        self.correspondence_affiliations = QListWidget()
        self.correspondence_affiliations.setObjectName('correspondence_affiliations')
        self.correspondence_affiliations.setWordWrap(True)
        self.correspondence_affiliations.itemDoubleClicked.connect(
            lambda item: self.edit_affiliation_item(item))
        correspondence_person_edit = QPushButton("Edit corresponding author")
        correspondence_person_edit.setObjectName('correspondence_edit_person')
        correspondence_person_edit.setToolTip("Edit the corresponding author's name and contact fields")
        correspondence_person_edit.clicked.connect(self.edit_corresponding_author)
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
        correspondence_buttons.addWidget(correspondence_person_edit)
        correspondence_buttons.addWidget(correspondence_edit)
        correspondence_buttons.addStretch()
        correspondence_layout.addLayout(correspondence_buttons)
        self.tabs.addTab(correspondence_page, "Corresponding Author")
        self.validation_list = QListWidget(); self.tabs.addTab(self.validation_list, "Validation")
        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.setContentsMargins(0,0,0,0)
        right_layout.addWidget(QLabel("XML Preview / Raw XML"))
        self.mode_tabs = QTabWidget()
        self.preview = XmlCodeEditor()
        self.raw = XmlCodeEditor(); self.raw.textChanged.connect(self._raw_changed)
        self.preview.textChanged.connect(self._preview_changed)
        self.mode_tabs.addTab(self.preview, "Preview"); self.mode_tabs.addTab(self.raw, "Raw XML")
        self.pdf_preview = PDFViewer(text_selectable=True)
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
        # Clicking a component follows it into both XML panes. Typing must not
        # drag the XML view around, so the reveal is click-driven, not caret-driven.
        self.author_list.currentItemChanged.connect(lambda current, _previous: self._reveal_list_node(current))
        self.keyword_list.currentRowChanged.connect(self._reveal_keyword)
        self.correspondence_affiliations.currentRowChanged.connect(
            lambda row: self._reveal_list_node(self.correspondence_affiliations.item(row)))
        for editor, field in ((self.title_edit, "title"), (self.abstract_edit, "abstract")):
            editor.setContextMenuPolicy(Qt.CustomContextMenu)
            editor.customContextMenuRequested.connect(
                lambda point, e=editor, f=field: self._field_menu(e, f, point)
            )
            editor.installEventFilter(self)
            editor.viewport().installEventFilter(self)
        schema_row = QHBoxLayout()
        self.schema_label = QLabel("No schema selected ? publisher validation incomplete")
        self.schema_label.setWordWrap(True)
        schema_row.addWidget(self.schema_label, 1)
        choose_schema = QPushButton("Select local schema?")
        choose_schema.clicked.connect(self.select_schema)
        schema_row.addWidget(choose_schema)
        root.addLayout(schema_row)
        footer = QHBoxLayout()
        self.status = QLabel("Ready")
        footer.addWidget(self.status, 1)
        save = QPushButton("Draft Export")
        save.setToolTip("Previously Validate & Export. Checks XML syntax and reports issues; publisher validation may be incomplete.")
        save.clicked.connect(self.save_copy)
        footer.addWidget(save)
        validated = QPushButton("Validated Export")
        validated.setToolTip("Requires successful validation against the selected local XSD profile. Additional publisher business rules are not certified.")
        validated.clicked.connect(self.save_validated_copy)
        footer.addWidget(validated)
        root.addLayout(footer)
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
        candidate = fitz.open(resolved)
        try:
            sizes = [(float(page.rect.width), float(page.rect.height)) for page in candidate]
            first_text = candidate[0].get_text('text') if candidate.page_count else ''
            self.pdf_preview.load_pdf(str(resolved), page_count=candidate.page_count, page_sizes=sizes)
        except (OSError, ValueError, RuntimeError):
            candidate.close()
            raise
        previous = self._pdf_text_document
        self._pdf_text_document = candidate
        self.pdf_preview_path = resolved
        self.pdf_text.setPlainText(first_text)
        if previous is not None:
            previous.close()

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
        try:
            candidate = XmlDocumentSession.from_text(text, label_path)
        except (ValueError, etree.XMLSyntaxError) as exc:
            QMessageBox.critical(self, "Could not prepare XML correction", str(exc))
            return False
        self._retain_draft()
        key = getattr(self, '_incoming_draft_key', None) or (str(pdf_source or '') + '|' + str(label_path))
        self._incoming_draft_key = None
        previous = self._drafts.get(key)
        if previous:
            if self._regeneration_content(previous.get('generated_xml')) == self._regeneration_content(text):
                return self.activate_draft(key)
            baseline = previous.get('generated_xml')
            if baseline is not None:
                # Compare using the editor's serialization.
                baseline = XmlDocumentSession.from_text(baseline, label_path).xml_text()
            corrected = (
                self._regeneration_content(previous['xml'])
                != self._regeneration_content(baseline)
                or previous.get('raw', previous['xml']) != previous['xml']
            )
            if corrected and not self.review_regeneration(previous['xml'], text):
                previous['pending_generated'] = text
                return self.activate_draft(key)
            revision = 1
            while f'{key}|revision:{revision}' in self._drafts:
                revision += 1
            archive = deepcopy(previous)
            archive['path'] = str(Path(previous['path']).with_stem(Path(previous['path']).stem + f'_revision_{revision}'))
            self._drafts[f'{key}|revision:{revision}'] = archive
        try:
            self.set_pdf_source(pdf_source)
            self.session = candidate
            self._draft_key = key
            self._drafts[key] = {"generated_xml": text,
                "original_generated_xml": (previous.get('original_generated_xml', previous.get('generated_xml', text))
                                           if previous else text)}
            if previous:
                from pdf_to_jats.core.xml_validation import fingerprint
                candidate_fp = fingerprint(candidate.xml_bytes())
                prev_val = previous.get('last_validated')
                if prev_val and prev_val.get('revision', {}).get('sha256') == candidate_fp:
                    candidate.last_validated = deepcopy(prev_val)
                prev_exp = previous.get('last_export')
                if prev_exp and prev_exp.get('revision', {}).get('sha256') == candidate_fp:
                    candidate.last_export = deepcopy(prev_exp)
                    for field in ('exported_xml', 'export_path'):
                        if field in previous:
                            self._drafts[key][field] = previous[field]
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
        text = s.xml_text()
        # A redraw for the same document must not throw away the reader's place.
        self._set_xml_pane_text(text, reset=getattr(self, '_pane_session', None) is not s)
        self._pane_session = s
        self._xml_text_baseline = text
        source_label = "FILE" if s.source_path is not None else "DRAFT IN MEMORY"
        if s.validation_result is None:
            self.validation_list.clear()
        validation_label = "Needs review" if s.validation else "Not validated"
        self.summary.setText(f"{source_label}  {s.path.name}  ·  {s.path}\nVALIDATION  {validation_label}     AUTHORS  {len(s.authors())}     AFFILIATIONS  {len(s.affiliations())}     PROFILE  {s.profile}")
        self.status.setText("Draft retained in workspace; Save Draft to keep it after closing")
        self._draft_status()
        self._syncing = False

    def eventFilter(self, watched, event):
        for editor, field in ((self.title_edit, "title"), (self.abstract_edit, "abstract")):
            if watched is editor.viewport() and event.type() == QEvent.MouseButtonPress:
                self._reveal_field_node(field)
        if watched is self.abstract_edit and event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress):
            if event.matches(QKeySequence.StandardKey.Find):
                event.accept()
                if event.type() == QEvent.KeyPress:
                    self.abstract_find.setFocus()
                    self.abstract_find.selectAll()
                return True
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

    def _find_abstract(self, *, backward=False, restart=False):
        query = self.abstract_find.text()
        if not query:
            self.abstract_find_status.clear()
            cursor = self.abstract_edit.textCursor()
            cursor.clearSelection()
            self.abstract_edit.setTextCursor(cursor)
            return
        document = self.abstract_edit.document()
        cursor = self.abstract_edit.textCursor()
        position = 0 if restart else (cursor.selectionStart() if backward else cursor.selectionEnd())
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlags()
        found = document.find(query, position, flags)
        wrapped = found.isNull()
        if wrapped:
            found = document.find(query, document.characterCount() - 1 if backward else 0, flags)
        if found.isNull():
            self.abstract_find_status.setText('No matches')
            cursor.clearSelection()
            self.abstract_edit.setTextCursor(cursor)
        else:
            self.abstract_edit.setTextCursor(found)
            self.abstract_edit.ensureCursorVisible()
            self.abstract_find_status.setText('Wrapped' if wrapped else 'Match found')

    def _record_history(self):
        text = canonical_history(self.session.xml_text(), self.session.path)
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

    def _parser_issue_targets(self) -> dict[str, str]:
        """Describe the authors and affiliation groups a parser note points at.

        Signatures detect edits that a reviewer can confirm and invalidate
        earlier acceptances when the affected information changes.
        """
        if not self.session:
            return {}
        authors = self.session.authors()
        signatures: dict[str, str] = {}
        author_groups: dict[str, list[tuple[str, str]]] = {}
        for number, (_label, indices, nodes, _container) in enumerate(
                self.session.affiliation_groups(), 1):
            labels = tuple(sorted(self._parser_affiliation_signature(node) for node in nodes))
            seqs = tuple(sorted(authors[index].get('seq') or str(index + 1)
                                for index in indices))
            group = str(number)
            label_signature = '|'.join(labels)
            signatures[f'group:{group}'] = label_signature + '::' + ','.join(seqs)
            for index in indices:
                seq = authors[index].get('seq') or str(index + 1)
                author_groups.setdefault(seq, []).append((group, label_signature))
        for index, node in enumerate(authors, 1):
            seq = node.get('seq') or str(index)
            name = ' '.join(self.session.author_name(node).split())
            groups = ';'.join(f'{number}:{label}' for number, label
                              in sorted(author_groups.get(seq, [])))
            signatures[f'author:{seq}'] = f'{name}::{groups}::corresponding={node in self.session.correspondence()}'
        return signatures

    def _parser_affiliation_signature(self, node) -> str:
        if not self.session:
            return ''
        if self.session._local_name(node) == 'affiliation':
            values = self.session.affiliation_form(node)
            return '|'.join(f'{key}={value}' for key, value in sorted(values.items()))
        return ' '.join(self.session._affiliation_label(node).split())

    def set_parser_issues(self, linked) -> None:
        """Retain parsing diagnostics alongside their author/affiliation targets."""
        from pdf_to_jats.core.jats_generator import JATSGenerator
        from pdf_to_jats.models.document import Document

        if not self.session or self._draft_key is None:
            return
        sequences = {author.id: str(index) for index, author in enumerate(linked.authors, 1)
                     if author.id}
        groups = JATSGenerator()._author_groups(Document(
            authors=linked.authors, affiliations=linked.affiliations))
        signatures = self._parser_issue_targets()
        records = []
        for issue in linked.issues:
            author_seq = sequences.get(issue.author_id)
            group_seqs = [str(index) for index, (affiliation, _) in enumerate(groups, 1)
                          if affiliation is not None and issue.affiliation_id
                          and affiliation.id == issue.affiliation_id]
            targets = {key: signatures[key] for key in
                       ([f'author:{author_seq}'] if author_seq is not None else [])
                       + [f'group:{seq}' for seq in group_seqs]
                       if key in signatures}
            records.append({
                'message': issue.message, 'severity': issue.severity,
                'author_seq': author_seq, 'group_seqs': group_seqs,
                'correspondence': 'correspond' in issue.message.lower(),
                'targets': targets,
            })
        record = self._drafts[self._draft_key]
        record['parser_issues'] = records
        record['parser_warnings'] = [issue.message for issue in linked.issues]
        self._refresh()
        self._retain_draft()

    def _show_parser_issues(self) -> None:
        """Show diagnostics at their fields; never insert them into the XML."""
        record = self._drafts.get(self._draft_key, {})
        self._prune_parser_issues(record)
        all_issues = record.get('parser_issues', [])
        issues = [issue for issue in all_issues if issue.get('status', 'PENDING') == 'PENDING']
        self.parser_reviews_button.setText(f'Parser reviews ({len(issues)} pending) and history')
        unmatched = []
        authors = self.session.authors()
        matched = set()
        group_issues = {}
        for _, indices, _, container in self.session.affiliation_groups():
            if container is None:
                continue
            sequences = {authors[index].get('seq') for index in indices}
            found = [i for i, issue in enumerate(issues)
                     if (issue.get('author_seq') and issue['author_seq'] in sequences)
                     or container.get('seq') in issue.get('group_seqs', [])]
            group_issues[self.session.tree.getpath(container)] = found
            matched.update(found)
        for index, issue in enumerate(issues):
            if index not in matched:
                unmatched.append(issue['message'])
        if not issues:
            unmatched.extend(record.get('parser_warnings', []))
        notice = ('Parser review notes — check against the PDF; '
                  'use Parser reviews to pass a review or confirm a correction.')
        self.parser_review.setText('\n'.join([notice, *unmatched]) if issues or unmatched else '')
        self.parser_review.setVisible(bool(issues or unmatched))
        for row in range(self.author_list.count()):
            item = self.author_list.item(row)
            group_path = item.data(Qt.UserRole + 2)
            index = item.data(Qt.UserRole)
            if group_path:
                found = group_issues.get(group_path, [])
            elif index is not None:
                sequence = authors[index].get('seq')
                found = [i for i, issue in enumerate(issues)
                         if sequence and issue.get('author_seq') == sequence]
            else:
                continue
            if not found:
                continue
            message = '\n'.join(dict.fromkeys(issues[i]['message'] for i in found))
            if not item.data(Qt.UserRole + 3):
                item.setBackground(QColor('#54252b'))
                item.setForeground(QColor('#ffb4b4'))
            item.setToolTip(item.toolTip() + '\nParser review: ' + message)
            widget = self.author_list.itemWidget(item)
            if widget is None:
                item.setText(item.text() + ('\nParser review note (hover for details)' if item.data(Qt.UserRole + 3)
                                            else '\nReview: ' + message))
            else:
                label = widget.layout().itemAt(0).widget()
                label.setText(label.text() + '\nParser review pending (see group reviews)')
                label.setWordWrap(True)
                label.setStyleSheet('color: #ffb4b4;')
                label.setToolTip(message)
                item.setSizeHint(widget.sizeHint())
        for issue in issues:
            if issue.get('correspondence'):
                item = QListWidgetItem('Parser review: ' + issue['message'])
                item.setForeground(QColor('#dc4444'))
                self.correspondence_details.insertItem(0, item)

    def _fill_other_titles(self, *, select: int | None = None) -> None:
        """List every title after the primary one, with its language tag."""

        self.other_title_list.clear()
        entries = self.session.titles() if self.session is not None else []
        for index, entry in enumerate(entries[1:], start=1):
            language = entry.get("language") or "und"
            text = " ".join(entry.get("text", "").split())
            item = QListWidgetItem(f"{language}  ·  {text}")
            item.setData(Qt.UserRole, index)
            item.setToolTip(
                f"xml:lang: {entry.get('language') or 'not set'}\n{entry.get('text', '')}"
            )
            self.other_title_list.addItem(item)
        if select is not None and 0 <= select < self.other_title_list.count():
            self.other_title_list.setCurrentRow(select)
        self._other_title_selection_changed()

    def _other_title_selection_changed(self) -> None:
        selected = self.other_title_list.currentRow() >= 0
        self.edit_other_title_button.setEnabled(selected)
        self.remove_other_title_button.setEnabled(selected)

    def _refresh_fields(self, *, preserve_abstract: bool = False) -> None:
        """Refresh structured controls without replacing either XML editor."""
        if not self.session: return
        s = self.session
        self.title_edit.setPlainText(s.title())
        self.title_language.blockSignals(True)
        select_language(self.title_language, s.title_language())
        self.title_language.blockSignals(False)
        self._fill_other_titles()
        if not preserve_abstract:
            self.abstract_edit.setPlainText(s.abstract())
        self._highlight_scripts(self.title_edit, s.title_node())
        self._highlight_scripts(self.abstract_edit, s.abstract_node())
        self.author_list.clear()
        authors = s.authors()
        duplicates = s.duplicate_affiliations()
        duplicate_sets = s.duplicate_affiliation_sets()
        badges = {s.tree.getpath(node): number for number, entries in enumerate(duplicate_sets, 1)
                  for _, node in entries}
        self.review_duplicates.setText(f'Review duplicate affiliations ({len(duplicate_sets)} sets)')
        self.review_duplicates.setEnabled(bool(duplicate_sets))

        def highlight_duplicates(item, nodes):
            locations = list(dict.fromkeys(location for node in nodes
                                for location in duplicates.get(s.tree.getpath(node), [])))
            if not locations:
                return
            message = 'Repeated affiliation — also in ' + '; '.join(locations)
            numbers = sorted({badges[s.tree.getpath(node)] for node in nodes if s.tree.getpath(node) in badges})
            badge = ' / '.join(f'Duplicate set {number}' for number in numbers)
            item.setData(Qt.UserRole + 3, badge)
            item.setText(badge + ' | ' + item.text() + '\n' + message)
            item.setBackground(QColor('#fff0bf'))
            item.setForeground(QColor('#614400'))
            item.setToolTip(message + '\nShared affiliations may be intentional. Review before changing.\n'
                            + item.toolTip())

        def affiliation_editable(node) -> bool:
            return etree.QName(node).localname == 'affiliation'

        def add_affiliation_item(target, text: str) -> None:
            item = QListWidgetItem(text)
            if affiliation_editable(target):
                item.setData(Qt.UserRole + 1, s.tree.getpath(target))
                item.setToolTip("Double-click to edit affiliation fields")
            else:
                item.setToolTip("This affiliation has no editable fields here; use Raw XML")
            highlight_duplicates(item, [target])
            self.author_list.addItem(item)

        for number, (label, indices, nodes, container) in enumerate(s.affiliation_groups(), 1):
            is_group = container is not None and etree.QName(container).localname == 'author-group'
            heading = QListWidgetItem(f"Group {number}: {label}" if is_group else label)
            heading.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if is_group:
                heading.setData(Qt.UserRole + 2, s.tree.getpath(container))
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
            highlight_duplicates(heading, nodes)
            self.author_list.addItem(heading)
            review_row = QListWidgetItem()
            self.author_list.addItem(review_row)
            reviews = self._reviews_for_group(container, indices)
            pending = sum(issue.get('status', 'PENDING') == 'PENDING' for issue in reviews)
            review_button = QPushButton(f'Parser reviews ({pending} pending) and history')
            review_button.setObjectName(f'parser_reviews_group_{number}')
            review_button.clicked.connect(
                lambda _checked=False, entries=reviews: self.show_parser_reviews(entries))
            self.author_list.setItemWidget(review_row, review_button)
            review_row.setSizeHint(review_button.sizeHint())
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
                alt_names = s.author_alt_names(authors[index])
                # Show the captured other-language name beside the English one
                # so a reviewer can see that both forms survived conversion.
                row_text = name + (f"  —  {' · '.join(alt_names)}" if alt_names else "")
                item = QListWidgetItem("    " + row_text)
                item.setData(Qt.UserRole, index)
                self.author_list.addItem(item)
                row_widget = QWidget(self.author_list.viewport())
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(18, 6, 12, 6)
                row_layout.setSpacing(10)
                name_label = QLabel(row_text)
                name_label.setMinimumWidth(0)
                name_label.setToolTip(row_text)
                name_label.setTextFormat(Qt.PlainText)
                name_label.setAttribute(Qt.WA_TransparentForMouseEvents)
                row_layout.addWidget(name_label, 1)
                assign = QPushButton('Assign affiliation')
                assign.clicked.connect(lambda _checked=False, entry=item: self.assign_author_affiliation(entry))
                row_layout.addWidget(assign)
                for label, copy_author in [('Copy', True), ('Move', False), ('Corresponding', None)]:
                    button = QPushButton(label)
                    button.setFlat(True)
                    button.setCursor(Qt.PointingHandCursor)
                    button.setStyleSheet(
                        'QPushButton { min-height: 20px; padding: 3px 8px; '
                        'border: none; border-radius: 4px; background: transparent; }'
                        'QPushButton:hover { background: rgba(128, 128, 128, 35); }'
                        'QPushButton:focus { border: 1px solid #78AAFF; }')
                    if copy_author is None:
                        button.setObjectName(f'corresponding_author_{index}')
                        button.setToolTip(f'Make {name} the corresponding author')
                        button.clicked.connect(lambda _checked=False, entry=item: self.make_corresponding_author(entry))
                    else:
                        button.setObjectName(f'{"copy" if copy_author else "move"}_author_{index}')
                        button.setToolTip(f'{label} {name} to another author group')
                        button.clicked.connect(
                            lambda _checked=False, entry=item, copy=copy_author:
                            self._transfer_author_row(entry, copy=copy))
                    row_layout.addWidget(button)
                # Retain the item's text for searching and accessibility, while
                # the row widget displays the name with actions aligned right.
                self.author_list.setItemWidget(item, row_widget)
                # Measure after parenting and polishing so the active theme's
                # button padding and font metrics are included in row height.
                row_widget.ensurePolished()
                for button in row_widget.findChildren(QPushButton):
                    button.ensurePolished()
                row_layout.invalidate()
                row_layout.activate()
                item.setSizeHint(row_widget.sizeHint())
        self.keyword_list.clear()
        for node in s.keywords(): self.keyword_list.addItem(" ".join("".join(node.itertext()).split()))
        self._fill_correspondence()
        self._show_parser_issues()

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
                  'email': 'Email', 'phone': 'Phone', 'fax': 'Fax',
                  'alt-name': 'Alternate name (other language)'}
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

    def _reveal_field_node(self, field: str) -> None:
        """Follow the caret in a component editor to its element in the XML."""
        if self._syncing or not self.session:
            return
        self._reveal_node(
            self.session.title_node() if field == 'title' else self.session.abstract_node()
        )

    def _reveal_keyword(self, row: int) -> None:
        if self._syncing or not self.session or row < 0:
            return
        nodes = self.session.keywords()
        if row < len(nodes):
            self._reveal_node(nodes[row])

    def _reveal_list_node(self, item) -> None:
        """Reveal the element a list row stands for (author, group, affiliation)."""
        if self._syncing or not self.session or item is None:
            return
        path = item.data(Qt.UserRole + 2) or item.data(Qt.UserRole + 1)
        if path:
            nodes = self.session.tree.xpath(
                path,
                namespaces={key: value for key, value in self.session.tree.getroot().nsmap.items() if key},
            )
            if nodes:
                self._reveal_node(nodes[0])
            return
        index = item.data(Qt.UserRole)
        authors = self.session.authors()
        if index is not None and 0 <= index < len(authors):
            self._reveal_node(authors[index])

    def _reveal_node(self, node) -> None:
        """Scroll both XML panes to ``node`` and band its opening tag."""
        span = self._xml_span(node)
        if span is None:
            return
        text = self.preview.toPlainText()
        # Qt positions count UTF-16 units, unlike Python string indices.
        start = len(text[:span[0]].encode('utf-16-le')) // 2
        end = len(text[:span[1]].encode('utf-16-le')) // 2
        for editor in (self.preview, self.raw):
            editor.reveal_span(start, end)

    def _xml_span(self, node) -> tuple[int, int] | None:
        """Map a tree node to its character span in the XML the panes show."""
        if node is None or self.session is None or not self.session.raw_valid:
            return None
        text = self.preview.toPlainText()
        if text != self.raw.toPlainText():
            return None
        elements = [element for element in self.session.tree.iter() if isinstance(element.tag, str)]
        index = next((position for position, element in enumerate(elements) if element is node), None)
        spans = _element_spans(text)
        # Unequal counts mean the panes and the model diverged (mid-edit XML).
        if index is None or len(spans) != len(elements):
            return None
        return spans[index]

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        original = self.property('darkStyle') or self.styleSheet()
        self.setProperty('darkStyle', original)
        self.setStyleSheet(themed_style(original, theme) +
                           (' QTabBar::tab:selected { color:white; }' if theme == 'light' else ''))
        for editor in (self.preview, self.raw):
            editor.set_theme(theme)
        for label in self.findChildren(QLabel):
            original = label.property('darkLegend')
            if original:
                label.setText(_script_legend_text(theme))
        if self.session is not None:
            self._highlight_scripts(self.title_edit, self.session.title_node())
            self._highlight_scripts(self.abstract_edit, self.session.abstract_node())

    def _highlight_scripts(self, editor: QPlainTextEdit, node) -> None:
        """Highlight script spans without modifying text, XML, or undo history."""
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
                selection.format.setForeground(QColor(themed_style(color, getattr(self, '_theme', 'dark'))))
                selection.format.setBackground(QColor(
                    SCRIPT_BACKGROUNDS[getattr(self, '_theme', 'dark')][run['type']]))
                selection.format.setFontWeight(QFont.Bold)
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

    def _title_language_changed(self) -> None:
        """Apply the editable language code to the primary title."""

        if self._syncing or not self.session:
            return
        language = selected_language(self.title_language)
        if language == self.session.title_language():
            return
        try:
            self.session.set_title_language(language)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._refresh()

    def add_other_title(self) -> None:
        """Open the title editor for a new translated title."""

        if not self.session:
            return
        self._show_title_dialog(
            None, {"text": "", "language": "UND"}
        )

    def edit_other_title(self) -> None:
        """Edit the selected translated title."""

        if not self.session:
            return
        item = self.other_title_list.currentItem()
        index = item.data(Qt.UserRole) if item is not None else None
        entries = self.session.titles()
        if not isinstance(index, int) or not 0 < index < len(entries):
            self.status.setText("Select a translated title to edit")
            return
        self._show_title_dialog(index, entries[index])

    def remove_other_title(self) -> None:
        """Remove the selected translated title from the XML."""

        if not self.session:
            return
        item = self.other_title_list.currentItem()
        index = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(index, int):
            self.status.setText("Select a translated title to remove")
            return
        try:
            self.session.remove_title(index)
        except (IndexError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        self._refresh()

    def _show_title_dialog(self, index: int | None, entry: dict[str, str]) -> None:
        """Collect a title and its language before writing it to the XML."""

        dialog = QDialog(self)
        dialog.setWindowTitle("Edit title" if index is not None else "Add title")
        dialog.resize(560, 340)
        layout = QVBoxLayout(dialog)
        language = QComboBox()
        language.setEditable(True)
        add_language_choices(language)
        select_language(language, str(entry.get("language") or UNDETERMINED))
        form = QFormLayout()
        form.addRow("Language (xml:lang)", language)
        layout.addLayout(form)
        layout.addWidget(QLabel("Title text"))
        editor = QPlainTextEdit()
        editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        editor.setPlainText(str(entry.get("text") or ""))
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        editor.setFocus()
        accepted = dialog.exec() == QDialog.Accepted
        text = editor.toPlainText().strip()
        code = selected_language(language)
        dialog.deleteLater()
        if not accepted:
            return
        if not text:
            QMessageBox.information(self, "Title required", "Enter the title text before saving.")
            return
        try:
            if index is None:
                self.session.add_title(text, code)
                new_row = len(self.session.titles()) - 2
                self._refresh()
                self.other_title_list.setCurrentRow(new_row)
            else:
                self.session.set_title(text, index)
                unchanged = code.casefold() == (self.session.title_language(index) or '').casefold()
                if not unchanged:
                    self.session.set_title_language(code, index)
                self._refresh()
                self.other_title_list.setCurrentRow(index - 1)
        except (IndexError, ValueError) as exc:
            self.status.setText(str(exc))

    def check_abstract_grammar(self):
        if not self.session:
            return
        from pdf_to_jats.gui.grammar_review import GrammarReviewDialog
        dialog = GrammarReviewDialog(self.abstract_edit, self._record_history, self)
        dialog.exec()
        dialog.deleteLater()

    def _abstract_changed(self) -> None:
        if not self._syncing and self.session:
            try: self.session.set_abstract(self.abstract_edit.toPlainText())
            except ValueError as exc: self.status.setText(str(exc)); return
            # The model's display text normalizes whitespace. Do not replace
            # the active editor after each keystroke: a trailing space or
            # newline is part of the user's next word/paragraph in progress.
            self._refresh(preserve_abstract=True)

    def _set_xml_pane_text(self, text: str, *, reset: bool = False) -> None:
        """Replace both pane texts, keeping scroll position and caret by default."""
        for editor in (self.preview, self.raw):
            position = 0 if reset else editor.textCursor().position()
            vertical = 0 if reset else editor.verticalScrollBar().value()
            horizontal = 0 if reset else editor.horizontalScrollBar().value()
            editor.setPlainText(text)
            cursor = editor.textCursor()
            cursor.setPosition(min(position, max(0, len(text))))
            editor.setTextCursor(cursor)
            editor.verticalScrollBar().setValue(
                min(vertical, editor.verticalScrollBar().maximum()))
            editor.horizontalScrollBar().setValue(
                min(horizontal, editor.horizontalScrollBar().maximum()))

    def _restore_xml_text(self, text: str) -> None:
        """Put both panes back on the last accepted XML without touching the model."""
        self._syncing = True
        try:
            for editor in (self.preview, self.raw):
                if editor.toPlainText() != text:
                    editor.setPlainText(text)
        finally:
            self._syncing = False

    def _raw_changed(self) -> None:
        self._xml_editor_changed(self.raw, self.preview)

    def _preview_changed(self) -> None:
        self._xml_editor_changed(self.preview, self.raw)

    def _xml_editor_changed(self, edited: QPlainTextEdit, other: QPlainTextEdit) -> None:
        if self._syncing or not self.session: return
        text = edited.toPlainText()
        # Comments are not authored from this workspace; a document that ships
        # with them keeps them, but new ones are refused rather than written.
        if text.count('<!--') > self._xml_text_baseline.count('<!--'):
            position = edited.textCursor().position()
            self._restore_xml_text(self._xml_text_baseline)
            cursor = edited.textCursor()
            cursor.setPosition(min(position, len(self._xml_text_baseline)))
            edited.setTextCursor(cursor)
            self.status.setText(
                "XML comments are disabled in this editor; remove the <!-- --> block to continue")
            return
        # Both tabs edit the same draft, including incomplete XML. Parsing
        # controls model updates and export, not which text the other tab sees.
        self._syncing = True
        try:
            if other.toPlainText() != text:
                other.setPlainText(text)
        finally:
            self._syncing = False
        self._xml_text_baseline = text
        ok, message, line, column = self.session.commit_raw(text)
        self.validation_list.clear()
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

    def show_duplicate_affiliations(self):
        if not self.session:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Review duplicate affiliations')
        dialog.resize(780, 560)
        layout = QVBoxLayout(dialog)
        help_text = QLabel('Select a duplicate set to compare its groups and authors.\n'
                           'Remove duplicates keeps the first affiliation and moves all authors into its group.\n'
                           'Author sequence numbers are preserved; group order changes. You can Undo this action.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        choices = QListWidget()
        choices.setObjectName('duplicate_sets')
        choices.setWordWrap(True)
        layout.addWidget(choices)
        details = QPlainTextEdit()
        details.setObjectName('duplicate_details')
        details.setReadOnly(True)
        layout.addWidget(details, 1)
        actions = QHBoxLayout()
        remove = QPushButton('Remove duplicates — keep first group')
        remove.setObjectName('merge_duplicate_affiliations')
        jump = QPushButton('Go to first affiliation')
        close = QPushButton('Close')
        for button in (jump, remove, close):
            actions.addWidget(button)
        layout.addLayout(actions)
        sets = []

        def populate():
            sets[:] = self.session.duplicate_affiliation_sets()
            choices.clear()
            for number, entries in enumerate(sets, 1):
                choices.addItem(f'Duplicate set {number}: ' + ', '.join(label for label, _ in entries))
            remove.setEnabled(bool(sets))
            jump.setEnabled(bool(sets))
            if sets:
                choices.setCurrentRow(0)
            else:
                details.setPlainText('No duplicate affiliations remain.')

        def show_details(row):
            if not 0 <= row < len(sets):
                return
            chunks = []
            for index, (label, node) in enumerate(sets[row]):
                names = [self.session.author_name(author) or 'Unnamed author'
                         for author in node.getparent() if self.session._local_name(author) == 'author']
                fields = [' '.join(''.join(child.itertext()).split())
                          for child in node if self.session._local_name(child) not in {'source-text', 'label'}]
                chunks.append(f'{label} — ' + ('KEEP' if index == 0 else 'REMOVE duplicate; move authors')
                              + '\n' + (', '.join(filter(None, fields)) or self.session._affiliation_label(node))
                              + '\nAuthors: ' + (', '.join(names) or 'None')
                              + '\nSource text: ' + self.session._affiliation_label(node))
            details.setPlainText('\n\n'.join(chunks))

        def merge():
            row = choices.currentRow()
            if not 0 <= row < len(sets):
                return
            self._record_history()
            try:
                self.session.merge_duplicate_affiliations([node for _, node in sets[row]])
            except ValueError as exc:
                QMessageBox.information(dialog, 'Review affiliations individually', str(exc))
                return
            self._refresh()
            populate()

        def go_to():
            row = choices.currentRow()
            if not 0 <= row < len(sets):
                return
            path = self.session.tree.getpath(sets[row][0][1])
            for index in range(self.author_list.count()):
                item = self.author_list.item(index)
                if item.data(Qt.UserRole + 1) == path:
                    self.author_list.setCurrentItem(item)
                    self.author_list.scrollToItem(item)
                    break
            dialog.accept()

        choices.currentRowChanged.connect(show_details)
        remove.clicked.connect(merge)
        jump.clicked.connect(go_to)
        close.clicked.connect(dialog.accept)
        populate()
        dialog.exec()
        dialog.deleteLater()

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
                  'suffix': 'Suffix', 'e-address': 'Email',
                  'alt-name': 'Alternate name (other language)'}
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

    def edit_corresponding_author(self) -> None:
        """Edit the existing corresponding-author person fields."""
        if not self.session:
            return
        try:
            values = self.session.corresponding_author_form()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit corresponding author")
        dialog.resize(520, 360)
        layout = QFormLayout(dialog)
        labels = {'initials': 'Initials', 'degrees': 'Degrees',
                  'surname': 'Surname', 'given-name': 'Given names',
                  'given-names': 'Given names', 'string-name': 'Full name',
                  'suffix': 'Suffix', 'e-address': 'Email',
                  'email': 'Email', 'phone': 'Phone', 'fax': 'Fax',
                  'alt-name': 'Alternate name (other language)'}
        fields: dict[str, QLineEdit] = {}
        for key, value in values.items():
            label = labels.get(key, key.replace('-', ' ').title())
            field = QLineEdit(value)
            field.setObjectName(f"correspondence_{key}")
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
                if self.session.set_corresponding_author_form(submitted):
                    self._refresh()
            except ValueError as exc:
                QMessageBox.warning(self, "Cannot edit corresponding author", str(exc))
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
            return sorted(
                (key for key in fields if key.partition(':')[0] == 'organization'),
                key=lambda key: int(key.partition(':')[2] or '1'),
            )

        def organization_label(index: int) -> str:
            return 'Organization' if index == 1 else f'Organization {index}'

        def add_field(key: str, value: str) -> tuple[str, QWidget]:
            base = key.split(':')[0].split('@')[0]
            field = QLineEdit(normalize_organization(value) if base == 'organization' else value)
            field.setObjectName(f'affiliation_{key}')
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
            split = QPushButton("Split by commas")
            split.setObjectName(f'affiliation_split_{key}')
            split.setToolTip("Preview separate organization entries for this field")
            split.clicked.connect(lambda _checked=False, f=field: split_organization(f))
            row_layout.addWidget(split)
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
                    elif button.objectName().startswith('affiliation_split_'):
                        button.setObjectName(f'affiliation_split_{target}')
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

        def split_organization(field: QLineEdit) -> None:
            parts = [part.strip() for part in field.text().split(',') if part.strip()]
            if len(parts) < 2:
                QMessageBox.information(dialog, "Split organization",
                                        "Enter at least two non-empty entries separated by commas.")
                return
            keys = organization_keys()
            index = next(i for i, key in enumerate(keys) if fields[key] is field)
            preview = '\n'.join(
                f"{organization_label(index + offset)}: {part}"
                for offset, part in enumerate(parts, 1)
            )
            if QMessageBox.question(
                dialog, "Split organization",
                "Replace this organization field with these entries?\n\n" + preview
                + "\n\nYou can edit each entry before saving the affiliation.",
                QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel,
            ) != QMessageBox.Ok:
                return
            values = [fields[key].text() for key in keys]
            values[index:index + 1] = parts
            for _ in range(len(parts) - 1):
                add_organization()
            for key, value in zip(organization_keys(), values):
                fields[key].setText(value)
            field.setFocus()

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

    def add_author_group(self) -> None:
        if not self.session: return
        try:
            self._record_history()
            group = self.session.add_author_group()
            path = self.session.tree.getpath(group)
            self._refresh()
            for row in range(self.author_list.count()):
                if self.author_list.item(row).data(Qt.UserRole + 2) == path:
                    self.author_list.setCurrentRow(row)
                    break
        except ValueError as exc:
            QMessageBox.information(self, "Cannot add author group", str(exc))

    def add_author(self) -> None:
        if not self.session: return
        value, ok = QInputDialog.getText(self, "Add author", "Author name")
        if ok and value.strip():
            try:
                group = None
                if self.session.profile == 'ANI':
                    row = self.author_list.currentRow()
                    while row >= 0:
                        path = self.author_list.item(row).data(Qt.UserRole + 2)
                        if path:
                            matches = self.session.tree.xpath(path, namespaces={
                                key: value for key, value in self.session.tree.getroot().nsmap.items() if key})
                            group = matches[0] if matches else None
                            break
                        row -= 1
                self._record_history()
                self.session.add_author(value.strip(), group=group)
                self._refresh()
            except ValueError as exc: QMessageBox.information(self, "Cannot add author", str(exc))

    def make_corresponding_author(self, item) -> None:
        if not self.session: return
        index = item.data(Qt.UserRole)
        if index is None: return
        try:
            self._record_history()
            self.session.set_corresponding_author(index)
            self._refresh()
            for tab in range(self.tabs.count()):
                if self.tabs.tabText(tab) == 'Corresponding Author':
                    self.tabs.setCurrentIndex(tab)
                    break
        except ValueError as exc:
            QMessageBox.information(self, 'Cannot set corresponding author', str(exc))

    def assign_author_affiliation(self, item) -> None:
        index = item.data(Qt.UserRole)
        if not self.session or index is None:
            return
        author = self.session.authors()[index]
        destinations = [(f'Group {number}: {label}', container)
                        for number, (label, _, _, container) in enumerate(self.session.affiliation_groups(), 1)
                        if container is not None and self.session._local_name(container) == 'author-group'
                        and container is not author.getparent()]
        choices = [label for label, _ in destinations] + ['Create new affiliation group...']
        label, accepted = QInputDialog.getItem(self, 'Assign affiliation', 'Affiliation group', choices, 0, False)
        if not accepted:
            return
        try:
            self._record_history()
            if label == choices[-1]:
                destination = self.session.add_author_group()
                # add_author_group creates a blank author for manual editing.
                # Assignment supplies a real author instead.
                for child in list(destination):
                    if self.session._local_name(child) == 'author':
                        destination.remove(child)
            else:
                destination = next(node for text, node in destinations if text == label)
            self.session.transfer_author(self.session.authors().index(author), destination, copy=False)
            path = self.session.tree.getpath(destination)
            self._refresh()
            new_index = self.session.authors().index(author)
            for row in range(self.author_list.count()):
                entry = self.author_list.item(row)
                if entry.data(Qt.UserRole) == new_index:
                    self.author_list.setCurrentItem(entry)
                    self.author_list.scrollToItem(entry)
                    break
            if label == choices[-1]:
                self.edit_affiliation(path)
        except ValueError as exc:
            QMessageBox.information(self, 'Cannot assign affiliation', str(exc))

    def _transfer_author_row(self, item, *, copy: bool) -> None:
        self.author_list.setCurrentItem(item)
        self.transfer_author(copy=copy)

    def transfer_author(self, *, copy: bool) -> None:
        if not self.session: return
        item = self.author_list.currentItem()
        index = item.data(Qt.UserRole) if item is not None else None
        action = 'Copy author' if copy else 'Move author'
        if index is None:
            QMessageBox.information(self, action, 'Select an author first.')
            return
        source = self.session.authors()[index].getparent()
        destinations = [(f'Group {number}: {label}', container)
                        for number, (label, _, _, container) in enumerate(self.session.affiliation_groups(), 1)
                        if container is not None and container is not source
                        and self.session._local_name(container) == 'author-group']
        if not destinations:
            QMessageBox.information(self, action, 'Add another author group first.')
            return
        label, accepted = QInputDialog.getItem(
            self, action, 'Destination author group', [label for label, _ in destinations], 0, False)
        if not accepted: return
        destination = next(container for text, container in destinations if text == label)
        try:
            self._record_history()
            author = self.session.transfer_author(index, destination, copy=copy)
            new_index = self.session.authors().index(author)
            self._refresh()
            for row in range(self.author_list.count()):
                if self.author_list.item(row).data(Qt.UserRole) == new_index:
                    self.author_list.setCurrentRow(row)
                    break
        except ValueError as exc:
            QMessageBox.information(self, action, str(exc))

    def remove_author(self) -> None:
        if not self.session or self.author_list.currentRow() < 0: return
        group_path = self.author_list.currentItem().data(Qt.UserRole + 2)
        if group_path:
            if QMessageBox.question(
                self, "Remove author group",
                "Remove the selected author group, including all its authors and affiliations, from the XML?",
                QMessageBox.Yes | QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            try:
                groups = self.session.tree.xpath(group_path, namespaces={
                    key: value for key, value in self.session.tree.getroot().nsmap.items() if key
                })
                if not groups:
                    raise ValueError("Author groups changed; select the group again")
                self._record_history()
                self.session.remove_author_group(groups[0])
                self._refresh()
            except ValueError as exc:
                QMessageBox.warning(self, "Cannot remove author group", str(exc))
            return
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

    def select_schema(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Select trusted local entry XSD", "", "XML Schema (*.xsd)")
        if not selected:
            return
        family, accepted = QInputDialog.getItem(self, "Schema profile", "This schema validates:",
                                                ["JATS", "ANI"], 1 if self.session and self.session.profile == "ANI" else 0, False)
        if not accepted:
            return
        self.schema_profile = SchemaProfile(Path(selected).name, family, Path(selected))
        self.schema_label.setText(f"{family}: {selected}")
        if self.session:
            self.session.validation = []
            self.validate()

    def validate(self) -> None:
        if not self.session:
            return
        issues = self.session.validate(self.schema_profile)
        self.validation_list.clear()
        for issue in issues:
            self.validation_list.addItem(f"{issue.severity.upper()}: {issue.message}" +
                (f" (line {issue.line}, column {issue.column})" if issue.line else ""))
        result = self.session.validation_result
        if result is None or result.well_formedness != ValidationStatus.WELL_FORMED:
            status = "Not well-formed"
        elif result.schema_status == ValidationStatus.SCHEMA_VALID:
            status = "Schema-valid for selected profile; review semantic issues"
        elif result.schema_status == ValidationStatus.SCHEMA_INVALID:
            status = "Well-formed; schema-invalid"
        else:
            status = "Well-formed; schema unavailable ? publisher validation incomplete"
        source_label = "FILE" if self.session.source_path is not None else "DRAFT IN MEMORY"
        self.summary.setText(f"{source_label}  {self.session.path.name}  ?  {self.session.path}\nVALIDATION  {status}     AUTHORS  {len(self.session.authors())}     AFFILIATIONS  {len(self.session.affiliations())}     PROFILE  {self.session.profile}")
        self.status.setText(status)

    def save_validated_copy(self) -> bool:
        return self.save_copy(mode=ExportMode.VALIDATED)

    def save_copy(self, *, mode: ExportMode = ExportMode.DRAFT) -> bool:
        if not self.session:
            return False
        self._prune_parser_issues(self._drafts.get(self._draft_key, {}))
        if mode == ExportMode.VALIDATED and any(
                issue['status'] == 'PENDING' for issue in self._review_records()):
            QMessageBox.warning(self, 'Pending parser reviews',
                                'Resolve all parser reviews before validated export. Draft export is still available.')
            self.show_parser_reviews()
            return False
        self.validate()
        try:
            result = self.session.validation_result
            if result is None:
                raise ValueError("Fix the raw XML parse error before exporting")
            result.require_export(mode)
        except ValueError as exc:
            QMessageBox.warning(self, "XML export blocked", str(exc))
            self.tabs.setCurrentWidget(self.validation_list)
            return False
        suggested = self.session.path.with_name(self.session.path.stem + "_corrected.xml")
        title = "Draft Export ? publisher validation incomplete" if mode == ExportMode.DRAFT else "Validated Export ? selected schema"
        selected, _ = QFileDialog.getSaveFileName(self, title, str(suggested), "XML files (*.xml)")
        if not selected:
            return False
        dest = Path(selected)
        if dest.exists() and QMessageBox.question(self, "Replace file?", f"Replace existing file {dest.name}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return False
        try:
            self.session.save_copy(dest, mode=mode)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self._retain_draft()
        self._drafts[self._draft_key]["exported_xml"] = self.session.xml_text()
        self._drafts[self._draft_key]["export_path"] = str(dest)
        notice = ("Draft exported. Publisher validation is incomplete; review the Validation tab."
                  if mode == ExportMode.DRAFT else
                  "Export validated against the selected schema. Additional publisher business rules are not verified.")
        QMessageBox.information(self, "Copy saved", f"{notice}\n{dest}")
        self.status.setText(notice)
        return True
