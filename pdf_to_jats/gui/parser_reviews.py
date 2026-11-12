"""Human resolution of parser diagnostics, retained outside article XML."""
from copy import deepcopy
from datetime import datetime
import json
import os
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)


class ParserReviews:
    def _review_records(self):
        record = self._drafts.get(self._draft_key, {})
        issues = record.setdefault('parser_issues', [])
        known = {issue['message'] for issue in issues}
        for message in record.get('parser_warnings', []):
            if message not in known:
                issues.append({'message': message, 'targets': {}})
                known.add(message)
        current = self._parser_issue_targets()
        for issue in issues:
            issue.setdefault('review_id', str(uuid4()))
            issue.setdefault('status', 'PENDING')
            if 'targets' not in issue:
                keys = [f"author:{issue.get('author_seq')}"]
                keys += [f'group:{seq}' for seq in issue.get('group_seqs', [])]
                issue['targets'] = {key: current[key] for key in keys if key in current}
            issue.setdefault('baseline_xml', self.session.xml_text())
        return issues

    def _review_values(self, issue):
        current = self._parser_issue_targets()
        return {key: current.get(key) for key in issue['targets']} if issue['targets'] else {
            'document': self.session.xml_text()}

    def _review_changed(self, issue):
        baseline = issue['targets'] or {'document': issue['baseline_xml']}
        return self._review_values(issue) != baseline

    def _prune_parser_issues(self, record):
        # Changes invalidate acceptance; edits alone never prove a semantic fix.
        for issue in self._review_records():
            if issue['status'] != 'PENDING' and self._review_values(issue) != issue.get('resolved_values'):
                issue['status'] = 'PENDING'
                issue['reopened_reason'] = 'Information changed after resolution.'
        record['parser_warnings'] = [i['message'] for i in record.get('parser_issues', [])
                                     if i['status'] == 'PENDING']

    def _resolve_parser_review(self, issue, action, reviewer, acknowledgment, comment=''):
        if issue['status'] != 'PENDING':
            raise ValueError('This review is already resolved.')
        if action not in ('FIXED', 'PASSED') or not reviewer.strip() or not acknowledgment:
            raise ValueError('A reviewer and acknowledgment are required.')
        if not self.session.raw_valid:
            raise ValueError('Fix the XML syntax before resolving reviews.')
        if action == 'FIXED' and not self._review_changed(issue):
            raise ValueError('Change the affected information before confirming a fix.')
        values = self._review_values(issue)
        event = dict(review_id=issue['review_id'], timestamp=datetime.now().astimezone().isoformat(),
                     document=str(self.session.path), warning=issue['message'], action=action,
                     reviewer=reviewer.strip(), acknowledgment=acknowledgment, comment=comment,
                     previous_value=issue['targets'] or {'document': issue['baseline_xml']},
                     updated_value=values)
        path = self.session.path.resolve().with_name(self.session.path.stem + '_review_log.txt')
        # One JSON object per line is UTF-8 text and safely escapes user newlines.
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        record = self._drafts[self._draft_key]
        record.setdefault('review_history', []).append(deepcopy(event))
        record['review_log_path'] = str(path)
        issue.update(status=action, reviewer=reviewer.strip(), resolved_at=event['timestamp'],
                     acknowledgment=acknowledgment, resolved_values=values)
        issue.pop('reopened_reason', None)
        self._refresh()
        self._retain_draft()

    def show_parser_reviews(self):
        if not self.session:
            return
        self._prune_parser_issues(self._drafts[self._draft_key])
        dialog = QDialog(self)
        dialog.setWindowTitle('Parser reviews and history')
        dialog.resize(780, 620)
        layout = QVBoxLayout(dialog)
        log_path = self.session.path.resolve().with_name(self.session.path.stem + '_review_log.txt')
        location = QLabel(f'Resolutions are recorded in: {log_path}')
        location.setWordWrap(True)
        location.setTextFormat(Qt.PlainText)
        layout.addWidget(location)
        listing = QListWidget()
        layout.addWidget(listing)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        layout.addWidget(details)
        layout.addWidget(QLabel('Reviewer name'))
        reviewer = QLineEdit()
        layout.addWidget(reviewer)
        comment = QLineEdit()
        comment.setPlaceholderText('Optional comment')
        layout.addWidget(comment)
        acknowledge = QCheckBox('I checked this information against the PDF and accept the current value.')
        layout.addWidget(acknowledge)
        passed = QPushButton('Pass review')
        fixed = QPushButton('Confirm correction — Fixed')
        layout.addWidget(passed)
        layout.addWidget(fixed)
        issues = self._review_records()

        def selected():
            row = listing.currentRow()
            return issues[row] if 0 <= row < len(issues) else None

        def update_buttons():
            issue = selected()
            ready = bool(issue and issue['status'] == 'PENDING' and reviewer.text().strip()
                         and acknowledge.isChecked() and self.session.raw_valid)
            passed.setEnabled(ready)
            fixed.setEnabled(ready and self._review_changed(issue))

        def selection_changed():
            acknowledge.setChecked(False)
            issue = selected()
            history = self._drafts[self._draft_key].get('review_history', [])
            lines = []
            if issue:
                lines = [issue['message'], '', f"Status: {issue['status']}",
                         issue.get('reopened_reason', ''),
                         'Affected information has changed. Confirm the correction after checking the PDF.'
                         if self._review_changed(issue) else 'Check the current information against the PDF.',
                         '', 'History:']
                for event in history:
                    if event['review_id'] == issue['review_id']:
                        lines.extend([f"{event['timestamp']} ? {event['action']} ? {event['reviewer']}",
                                      event['acknowledgment'], event.get('comment', ''), ''])
            details.setPlainText('\n'.join(lines))
            update_buttons()

        def populate():
            row = max(0, listing.currentRow())
            listing.clear()
            for issue in issues:
                listing.addItem(f"{issue['status']}: {issue['message']}")
            listing.setCurrentRow(row)

        def resolve(action):
            try:
                self._resolve_parser_review(selected(), action, reviewer.text(),
                    acknowledge.text(), comment.text())
            except (OSError, ValueError) as exc:
                QMessageBox.warning(dialog, 'Review remains pending', str(exc))
                return
            populate()

        listing.currentRowChanged.connect(selection_changed)
        reviewer.textChanged.connect(update_buttons)
        acknowledge.toggled.connect(update_buttons)
        passed.clicked.connect(lambda: resolve('PASSED'))
        fixed.clicked.connect(lambda: resolve('FIXED'))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        populate()
        update_buttons()
        dialog.exec()
