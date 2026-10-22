"""Retained XML article drafts and portable review-workspace files."""
from pathlib import Path
from lxml import etree
import difflib
import json
import os
import tempfile

from PySide6.QtWidgets import QFileDialog, QMessageBox, QDialog, QVBoxLayout, QPlainTextEdit, QDialogButtonBox
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.core.workflow_state import decode_workflow


class ArticleDrafts:
    @staticmethod
    def _regeneration_content(text):
        """Ignore only ANI's generated unit timestamp when comparing drafts."""
        if text is None:
            return None
        try:
            root = etree.fromstring(text.encode('utf-8'), etree.XMLParser(
                resolve_entities=False, no_network=True, load_dtd=False))
        except (ValueError, etree.XMLSyntaxError):
            return text
        ns = {'ani': 'http://www.elsevier.com/xml/ani/ani'}
        if root.tag == '{http://www.elsevier.com/xml/ani/ani}units':
            for node in root.findall('ani:unit/ani:unit-info/ani:timestamp', ns):
                node.text = '[generation time]'
        return etree.tostring(root, encoding='unicode')

    def _init_drafts(self):
        self._drafts = {}
        self._draft_key = None
        self._draft_file = None
        self._saved_workspace = None
        self._workflow_snapshot = None

    def _retain_draft(self):
        if self.session is None:
            return
        if self._draft_key is None:
            self._draft_key = 'file:' + str(self.session.path.resolve())
        previous = self._drafts.get(self._draft_key, {})
        self._drafts[self._draft_key] = dict(
            previous, xml=self.session.xml_text(), raw=(getattr(self, '_unparsed_text', self.raw.toPlainText()) if not self.session.raw_valid else self.raw.toPlainText()),
            path=str(self.session.path), source=str(self.session.source_path or ''),
            pdf=str(self.pdf_preview_path or ''), dirty=self.session.dirty,
            history=list(getattr(self, '_history', [self.session.xml_text()])),
            history_index=getattr(self, '_history_index', 0),
        )
        self._update_draft_selector()

    def _update_draft_selector(self):
        self.draft_selector.blockSignals(True)
        self.draft_selector.clear()
        for key, record in self._drafts.items():
            self.draft_selector.addItem(Path(record['path']).name, key)
        self.draft_selector.setCurrentIndex(self.draft_selector.findData(self._draft_key))
        self.draft_selector.blockSignals(False)

    def _select_draft(self, index):
        key = self.draft_selector.itemData(index)
        if key and key != self._draft_key:
            self.activate_draft(key)

    def activate_draft(self, key):
        self._retain_draft()
        if key not in self._drafts:
            return False
        record = self._drafts[key]
        session = XmlDocumentSession.from_text(record['xml'], Path(record['path']))
        session.source_path = Path(record['source']) if record.get('source') else None
        self.session = session
        self._draft_key = key
        self._history_session = session
        self._history = record.get('history', [record['xml']])
        self._history_index = record.get('history_index', len(self._history) - 1)
        self._refresh()
        if record.get('raw', record['xml']) != record['xml']:
            self.raw.setPlainText(record['raw'])
        session.dirty = record.get('dirty', False)
        self.set_pdf_source(Path(record['pdf']) if record.get('pdf') else None)
        self._update_draft_selector()
        self._draft_status()
        return True

    def _draft_status(self):
        record = self._drafts.get(self._draft_key, {})
        exported = record.get('exported_xml')
        if record.get('pending_generated'):
            self.status.setText('Corrected draft retained; new PDF changes have not been applied')
        elif exported:
            changed = not self.session.raw_valid or exported != self.session.xml_text()
            self.status.setText('Changes not yet exported' if changed else 'Latest revision exported')

    def _workspace_text(self):
        self._retain_draft()
        main = self.window()
        if hasattr(main, 'capture_workflow') and main.document is not None:
            self._workflow_snapshot = main.capture_workflow()
        return json.dumps({'version': 1, 'active': self._draft_key, 'articles': self._drafts,
                           'workflow': self._workflow_snapshot}, ensure_ascii=False, indent=2)

    def save_draft(self):
        if not self.session and getattr(self.window(), 'document', None) is None:
            return False
        selected = str(self._draft_file or '')
        if not selected:
            selected, _ = QFileDialog.getSaveFileName(self, 'Save article drafts', '', 'Article drafts (*.jatsdraft)')
        if not selected:
            return False
        path = Path(selected)
        if path.suffix.lower() != '.jatsdraft':
            path = Path(str(path) + '.jatsdraft')
            if path.exists() and QMessageBox.question(
                    self, 'Replace draft file?', f'Replace {path.name}?',
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return False
        text = self._workspace_text()
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.draft-', suffix='.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(text)
            os.replace(temporary, path)
        except OSError as exc:
            QMessageBox.warning(self, 'Draft save failed', str(exc))
            return False
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        self._draft_file = path
        self._saved_workspace = text
        self.status.setText(f'Drafts saved: {path.name}')
        return True

    @staticmethod
    def _workspace_content(text):
        """Compare saved work independently of the article currently in view."""
        if text is None:
            return None
        data = json.loads(text)
        data.pop('active', None)
        workflow = data.get('workflow')
        if workflow is not None:
            workflow.get('state', {}).pop('_current_segment_key', None)
        return data

    def confirm_close_drafts(self, action='closing'):
        if not self.session and getattr(self.window(), 'document', None) is None:
            return True
        if self._workspace_content(self._workspace_text()) == self._workspace_content(self._saved_workspace):
            return True
        answer = QMessageBox.question(self, 'Save article drafts?',
            f'Save your article drafts before {action}? Exported XML files are already on disk.',
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        return answer == QMessageBox.Discard or (answer == QMessageBox.Save and self.save_draft())

    def open_drafts(self):
        main = self.window()
        if getattr(main, '_article_finish_thread', None) is not None or getattr(main, '_pdf_load_thread', None) is not None:
            QMessageBox.information(self, 'Processing in progress', 'Wait for the current operation before opening drafts.')
            return
        selected, _ = QFileDialog.getOpenFileName(self, 'Open article drafts', '', 'Article drafts (*.jatsdraft)')
        if not selected:
            return
        try:
            data = json.loads(Path(selected).read_text(encoding='utf-8'))
            if (data['version'] != 1 or not isinstance(data['articles'], dict)
                    or (data['active'] is not None and data['active'] not in data['articles'])
                    or (not data['articles'] and not data.get('workflow'))):
                raise ValueError('Unsupported or empty article draft file')
            for record in data['articles'].values():
                XmlDocumentSession.from_text(record['xml'], Path(record['path']))
                if not isinstance(record.get('raw', ''), str):
                    raise ValueError('Invalid draft text')
                history = record.get('history', [record['xml']])
                index = record.get('history_index', len(history) - 1)
                if not history or not isinstance(index, int) or not 0 <= index < len(history):
                    raise ValueError('Invalid draft history')
                for revision in history:
                    XmlDocumentSession.from_text(revision, Path(record['path']))
            if data.get('workflow'):
                decode_workflow(data['workflow'])
        except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
            QMessageBox.warning(self, 'Could not open drafts', str(exc))
            return
        if not self.confirm_close_drafts('opening another workspace'):
            return
        if data.get('workflow') and hasattr(main, 'restore_workflow'):
            try:
                main.restore_workflow(data['workflow'])
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, 'Could not restore PDF workspace', str(exc))
                return
        self.session = None
        self._drafts = data['articles']
        self._draft_key = None
        if data['active'] is not None:
            self.activate_draft(data['active'])
        else:
            self._syncing = True
            for editor in (self.title_edit, self.abstract_edit, self.raw, self.preview):
                editor.clear()
            self._syncing = False
            self._update_draft_selector()
        self._draft_file = Path(selected)
        self._workflow_snapshot = data.get('workflow')
        self._saved_workspace = self._workspace_text()
        if hasattr(main, 'pages'):
            main.pages.setCurrentWidget(self if self.session else main.converter_page)
            main.convert_step_btn.setChecked(self.session is None)
            main.correct_step_btn.setChecked(self.session is not None)

    def review_regeneration(self, old, proposed):
        dialog = QDialog(self)
        dialog.setWindowTitle('Review regenerated XML — your existing draft is retained')
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        comparison = QPlainTextEdit()
        comparison.setReadOnly(True)
        comparison.setPlainText(''.join(difflib.unified_diff(
            self._regeneration_content(old).splitlines(True),
            self._regeneration_content(proposed).splitlines(True),
            fromfile='Current corrected draft', tofile='New PDF extraction')))
        layout.addWidget(comparison)
        buttons = QDialogButtonBox()
        create = buttons.addButton('Use new revision', QDialogButtonBox.AcceptRole)
        keep = buttons.addButton('Keep corrected draft', QDialogButtonBox.RejectRole)
        create.clicked.connect(dialog.accept)
        keep.clicked.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.Accepted
