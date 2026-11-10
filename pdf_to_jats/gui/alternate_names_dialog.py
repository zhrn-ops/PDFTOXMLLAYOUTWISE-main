"""Explicit assignment of whole native-language author captures."""

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QAbstractItemView, QHeaderView,
)

from pdf_to_jats.core.alternate_names import name_key


class AlternateNamesDialog(QDialog):
    def __init__(self, blocks, authors, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Assign alternate names')
        self.blocks = blocks
        self.choices = []
        layout = QVBoxLayout(self)
        hint = QLabel('Each capture must contain one person’s complete name. '
                      'Assign it to a main author, leave it unassigned, or keep it as a main author. '
                      'If a block contains several people, cancel and capture each name separately.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        table = QTableWidget(len(blocks), 2)
        table.setHorizontalHeaderLabels(['Captured name (whole text)', 'Assignment'])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table = table
        for row, block in enumerate(blocks):
            table.setItem(row, 0, QTableWidgetItem(block.text.strip()))
            choice = QComboBox()
            choice.addItem('Unassigned alternate name', ('unassigned', ''))
            choice.addItem('Keep as main author', ('main', ''))
            for author in authors:
                key = name_key(author.display_name)
                if key and sum(name_key(item.display_name) == key for item in authors) == 1:
                    alternates = ' · '.join(name.text for name in author.alternate_names)
                    label = author.display_name + (f' — {alternates}' if alternates else '')
                    choice.addItem(label, ('assigned', author.display_name))
            target = block.metadata.get('alternate_name_target', '')
            if block.metadata.get('keep_main_author'):
                choice.setCurrentIndex(1)
            elif target:
                index = next((i for i in range(2, choice.count())
                              if name_key(choice.itemData(i)[1]) == name_key(target)), -1)
                if index < 0:
                    choice.addItem(f'Target unavailable: {target} — reassign', ('assigned', target))
                    index = choice.count() - 1
                choice.setCurrentIndex(index)
            table.setCellWidget(row, 1, choice)
            self.choices.append(choice)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(850, 400)

    def apply(self):
        """Commit only after Save; opening or cancelling changes no source data."""
        for block, choice in zip(self.blocks, self.choices):
            mode, target = choice.currentData()
            block.metadata.pop('alternate_name_target', None)
            block.metadata.pop('keep_main_author', None)
            if mode == 'main':
                block.metadata['keep_main_author'] = True
            elif mode == 'assigned':
                block.metadata['alternate_name_target'] = target
