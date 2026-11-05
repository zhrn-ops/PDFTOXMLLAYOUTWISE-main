"""XML code editor presentation without rewriting the document."""

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat,
    QTextOption,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget


PALETTES = {
    'dark': dict(background='#091421', text='#e7f0ff', gutter='#101d2c',
                 muted='#8295b0', current='#14283c', tag='#78aaff',
                 attribute='#c4b5fd', string='#86efac', comment='#8295b0', entity='#fbbf24',
                 selection='#1f4b7a', reveal='#1d4a73'),
    'light': dict(background='#ffffff', text='#172b45', gutter='#edf2f8',
                  muted='#52657d', current='#edf4ff', tag='#175bc0',
                  attribute='#7c3c9f', string='#176e42', comment='#64748b', entity='#925900',
                  selection='#cfe0fa', reveal='#cfe4ff'),
}

MONOSPACE_FAMILIES = ['Cascadia Code', 'Consolas', 'Menlo', 'DejaVu Sans Mono', 'Courier New']


class XmlHighlighter(QSyntaxHighlighter):
    # highlightBlock can run before __init__ finishes; keep a usable default.
    colors = PALETTES['dark']

    def set_theme(self, theme):
        self.colors = PALETTES[theme]
        self.rehighlight()

    def highlightBlock(self, text):
        def paint(start, end, kind):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self.colors[kind]))
            # Qt offsets count UTF-16 units, unlike Python string indices.
            offset = len(text[:start].encode('utf-16-le')) // 2
            length = len(text[start:end].encode('utf-16-le')) // 2
            self.setFormat(offset, length, fmt)

        state = max(0, self.previousBlockState())
        pos = 0
        while pos < len(text):
            if state in (2, 3):
                terminator = '-->' if state == 2 else ']]>'
                end = text.find(terminator, pos)
                stop = len(text) if end < 0 else end + len(terminator)
                paint(pos, stop, 'comment' if state == 2 else 'string')
                pos = stop
                if end >= 0:
                    state = 0
                continue
            if state in (4, 5):
                end = text.find('"' if state == 4 else "'", pos)
                stop = len(text) if end < 0 else end + 1
                paint(pos, stop, 'string')
                pos = stop
                if end >= 0:
                    state = 1
                continue
            if text.startswith('<!--', pos):
                state = 2
                continue
            if text.startswith('<![CDATA[', pos):
                state = 3
                continue
            if text[pos] == '<':
                match = re.match(r'<[!?/]?[\w:.-]*', text[pos:])
                stop = pos + len(match[0])
                paint(pos, stop, 'tag')
                pos, state = stop, 1
                continue
            if state == 1:
                if text[pos] in "\"'":
                    quote = text[pos]
                    end = text.find(quote, pos + 1)
                    stop = len(text) if end < 0 else end + 1
                    paint(pos, stop, 'string')
                    state = (4 if quote == '"' else 5) if end < 0 else 1
                    pos = stop
                    continue
                match = re.match(r'[\w:.-]+(?=\s*=)', text[pos:])
                if match:
                    paint(pos, pos + len(match[0]), 'attribute')
                    pos += len(match[0])
                    continue
                if text[pos] in '/?>':
                    paint(pos, pos + 1, 'tag')
                    if text[pos] == '>':
                        state = 0
            if text[pos] == '&':
                match = re.match(r'&[\w#]+;', text[pos:])
                if match:
                    paint(pos, pos + len(match[0]), 'entity')
                    pos += len(match[0])
                    continue
            pos += 1
        self.setCurrentBlockState(state)


class LineNumbers(QWidget):
    def paintEvent(self, event):
        self.parent().paint_line_numbers(event)


class XmlCodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._revealed_span = None
        font = QFont()
        font.setFamilies(MONOSPACE_FAMILIES)
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        font.setPointSize(11)
        self.setFont(font)
        # Long attribute lists and text nodes stay readable without horizontal
        # scrolling; wrapping breaks at word boundaries at the viewport edge.
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.gutter = LineNumbers(self)
        self.highlighter = XmlHighlighter(self.document())
        self.blockCountChanged.connect(self.update_gutter_width)
        self.updateRequest.connect(self.update_gutter)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.set_theme('dark')
        self.textChanged.connect(self.clear_reveal)
        self.update_gutter_width()

    def set_theme(self, theme):
        revealed = self._revealed_span
        self.colors = PALETTES[theme]
        families = ','.join(f'"{family}"' for family in MONOSPACE_FAMILIES)
        self.setStyleSheet(
            f"QPlainTextEdit {{ background:{self.colors['background']}; "
            f"color:{self.colors['text']}; selection-background-color:{self.colors['selection']}; "
            f"font-family:{families},monospace; font-size:11pt; }}"
        )
        self.highlighter.set_theme(theme)
        # Re-polishing the document for a new stylesheet can report a text
        # change, which would drop the locator band mid-theme-switch.
        self._revealed_span = revealed
        self.highlight_current_line()
        self.gutter.update()

    def gutter_width(self):
        return 20 + self.fontMetrics().horizontalAdvance('9') * len(str(max(1, self.blockCount())))

    def update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_gutter_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.gutter.setGeometry(rect.left(), rect.top(), self.gutter_width(), rect.height())

    def highlight_current_line(self):
        selections = []
        span = QTextEdit.ExtraSelection()
        span.format.setBackground(QColor(self.colors['current']))
        span.format.setProperty(QTextFormat.FullWidthSelection, True)
        span.cursor = self.textCursor()
        span.cursor.clearSelection()
        selections.append(span)
        if self._revealed_span is not None:
            band = QTextEdit.ExtraSelection()
            band.format.setBackground(QColor(self.colors['reveal']))
            band.format.setProperty(QTextFormat.FullWidthSelection, True)
            band.cursor = QTextCursor(self.document().findBlock(self._revealed_span[0]))
            band.cursor.clearSelection()
            selections.append(band)
        self.setExtraSelections(selections)
        self.gutter.update()

    def revealed_span(self):
        """The character span last revealed by the workspace, or ``None``."""
        return self._revealed_span

    def reveal_span(self, start, end):
        """Scroll to ``start`` and band its line, without selecting any text."""
        last = max(0, self.document().characterCount() - 1)
        self._revealed_span = (min(start, last), min(end, last))
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._revealed_span[0])
        self.setTextCursor(cursor)
        self.centerCursor()
        self.highlight_current_line()

    def clear_reveal(self):
        """Drop the locator band once the user edits or clicks in this pane."""
        if self._revealed_span is not None:
            self._revealed_span = None
            self.highlight_current_line()

    def showEvent(self, event):
        super().showEvent(event)
        # A reveal made while this tab was hidden still lands in view.
        if self._revealed_span is not None:
            self.centerCursor()

    def mousePressEvent(self, event):
        self.clear_reveal()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        self.clear_reveal()
        super().keyPressEvent(event)

    def paint_line_numbers(self, event):
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor(self.colors['gutter']))
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid() and top <= event.rect().bottom():
            height = self.blockBoundingRect(block).height()
            if block.isVisible() and top + height >= event.rect().top():
                current = block.blockNumber() == self.textCursor().blockNumber()
                painter.setPen(QColor(self.colors['text' if current else 'muted']))
                painter.drawText(0, int(top), self.gutter.width() - 8,
                                 self.fontMetrics().height(), Qt.AlignRight, str(block.blockNumber() + 1))
            top += height
            block = block.next()
