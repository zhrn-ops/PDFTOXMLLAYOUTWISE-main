"""Retained XML article drafts and portable review-workspace files."""
from pathlib import Path
from copy import deepcopy
import fitz
from lxml import etree
import difflib
import json

from PySide6.QtWidgets import QFileDialog, QMessageBox, QDialog, QVBoxLayout, QPlainTextEdit, QDialogButtonBox
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.core.atomic_io import atomic_write_bytes
from pdf_to_jats.core.draft_workspace import canonical_history, session_from_record, stage_workspace
from pdf_to_jats.core.xml_revisions import XmlRevision
from pdf_to_jats.core.xml_validation import unicode_xml_bytes


class ArticleDrafts:
    @staticmethod
    def _regeneration_content(text):
        """Ignore only ANI's generated unit timestamp when comparing drafts."""
        if text is None:
            return None
        try:
            root = etree.fromstring(unicode_xml_bytes(text), etree.XMLParser(
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
        self._record_history()
        self._drafts[self._draft_key] = dict(
            previous, xml=self.session.xml_text(), raw=(getattr(self, '_unparsed_text', self.raw.toPlainText()) if not self.session.raw_valid else self.raw.toPlainText()),
            path=str(self.session.path), source=str(self.session.source_path or ''),
            pdf=str(self.pdf_preview_path or ''), dirty=self.session.dirty,
            history=list(getattr(self, '_history', [self.session.xml_text()])),
            history_index=getattr(self, '_history_index', 0),
            current_revision=XmlRevision(self.session.xml_bytes()).to_record(),
            source_revision=XmlRevision(self.session.source_bytes).to_record(),
            saved_revision=XmlRevision(self.session.original_bytes).to_record(),
            last_validated=deepcopy(self.session.last_validated),
            last_export=deepcopy(self.session.last_export),
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
        session = session_from_record(record)
        self.set_pdf_source(Path(record['pdf']) if record.get('pdf') else None)
        self.session = session
        self._draft_key = key
        self._history_session = session
        self._history = [canonical_history(text, session.path)
                         for text in record.get('history', [record['xml']])]
        self._history_index = record.get('history_index', len(self._history) - 1)
        self._refresh()
        if record.get('raw', record['xml']) != record['xml']:
            # The retained text is the accepted state for this draft, so a
            # comment it already holds is not treated as a newly added one.
            self._xml_text_baseline = record['raw']
            self.raw.setPlainText(record['raw'])
            valid, _, _, _ = session.commit_raw(record['raw'])
            if not valid:
                session.raw_valid = False
                self._unparsed_text = record['raw']
        session.dirty = record.get('dirty', False)
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
        try:
            atomic_write_bytes(path, text.encode('utf-8'))
        except OSError as exc:
            QMessageBox.warning(self, 'Draft save failed', str(exc))
            return False
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
            data = stage_workspace(json.loads(Path(selected).read_text(encoding='utf-8')))
            # Open all referenced, available PDFs before replacing live state.
            # Missing PDFs remain recoverable as XML-only workspaces.
            sources = {record.get('pdf') for record in data['articles'].values() if record.get('pdf')}
            if data.get('workflow'):
                metadata = data['workflow']['document'].get('metadata', {})
                sources.add(metadata.get('source_pdf') or metadata.get('source_path'))
            for source in sources:
                if source and Path(source).is_file():
                    with fitz.open(source) as pdf:
                        if pdf.page_count:
                            pdf.load_page(0).get_text('text')
        except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError, fitz.FileDataError) as exc:
            QMessageBox.warning(self, 'Could not open drafts', str(exc))
            return
        if not self.confirm_close_drafts('opening another workspace'):
            return
        checkpoint = {name: getattr(self, name, None) for name in (
            'session', '_drafts', '_draft_key', '_draft_file', '_saved_workspace',
            '_workflow_snapshot', '_history', '_history_index', '_history_session')}
        old_raw = self.raw.toPlainText()
        old_pdf = self.pdf_preview_path
        workflow_checkpoint = main._workflow_checkpoint() if hasattr(main, '_workflow_checkpoint') else None
        try:
            if hasattr(main, 'restore_workflow'):
                main.restore_workflow(data.get('workflow'))
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
                self.set_pdf_source(None)
                self.validation_list.clear()
                self._update_draft_selector()
            self._draft_file = Path(selected)
            self._workflow_snapshot = data.get('workflow')
            self._saved_workspace = self._workspace_text()
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            self._syncing = False
            for name, value in checkpoint.items():
                setattr(self, name, value)
            try:
                if workflow_checkpoint is not None:
                    main._restore_workflow_checkpoint(workflow_checkpoint)
                self.set_pdf_source(old_pdf)
                if self.session:
                    self._refresh()
                    if old_raw != self.session.xml_text():
                        self._xml_text_baseline = old_raw
                        self.raw.setPlainText(old_raw)
                self._update_draft_selector()
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as redraw_error:
                QMessageBox.warning(self, 'Workspace data retained',
                    f'Replacement failed: {exc}. The old data is retained, but its view could not refresh: {redraw_error}')
                return
            QMessageBox.warning(self, 'Could not open drafts',
                                f'Previous workspace restored: {exc}')
            return
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
