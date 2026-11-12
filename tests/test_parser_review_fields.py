from pathlib import Path

from PySide6.QtCore import Qt

from pdf_to_jats.core.author_linker import LinkedAuthors, LinkIssue
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow
from pdf_to_jats.models.author import Author
from pdf_to_jats.models.affiliation import Affiliation
from pdf_to_jats.models.document import Document


def test_explicit_corresponding_author_review_requires_acknowledgment(qapp, tmp_path):
    author = Author(id='author_1', surname='Smith', affiliation_ids=['1'])
    affiliation = Affiliation(id='1', text='University')
    warning = 'No corresponding author was matched explicitly; used the first author. Review correspondence.'
    linked = LinkedAuthors([author], [affiliation], issues=[
        LinkIssue('warning', warning, author_id='author_1'),
        LinkIssue('warning', 'Review organization', affiliation_id='1'),
    ])
    xml = JATSGenerator().to_string(Document(authors=[author], affiliations=[affiliation]))
    window = XmlCorrectionWindow()
    try:
        assert window.load_xml_text(xml, tmp_path / 'correspondence-review.xml')
        window.set_parser_issues(linked)
        key = window._draft_key
        item = next(window.author_list.item(i) for i in range(window.author_list.count())
                    if window.author_list.item(i).data(Qt.UserRole) is not None)
        window.make_corresponding_author(item)
        record = window._drafts[key]
        issue = record['parser_issues'][0]
        assert issue['status'] == 'PENDING'
        window._resolve_parser_review(issue, 'PASSED', 'Reviewer', 'Checked against PDF')
        record = window._drafts[key]
        assert [i['message'] for i in record['parser_issues'] if i['status'] == 'PENDING'] == ['Review organization']
        assert warning not in record['parser_warnings']
        assert all(warning not in window.author_list.item(i).text()
                   for i in range(window.author_list.count()))
        assert window.session.author_name(window.session.correspondence()[0]).endswith('Smith')
        assert window.load_xml_text(xml, Path('other-correspondence.xml'))
        window.activate_draft(key)
        assert all(warning not in window.author_list.item(i).text()
                   for i in range(window.author_list.count()))
    finally:
        window.deleteLater()


def test_parser_notes_clear_when_corrections_are_confirmed(qapp, tmp_path):
    author = Author(id='author_1', surname='Smith', affiliation_ids=['1'])
    affiliation = Affiliation(id='1', text='University 1')
    linked = LinkedAuthors([author], [affiliation], issues=[
        LinkIssue('warning', 'Review surname', author_id='author_1'),
        LinkIssue('warning', 'Review organization', affiliation_id='1'),
    ])
    xml = JATSGenerator().to_string(Document(authors=[author], affiliations=[affiliation]))
    window = XmlCorrectionWindow()
    try:
        assert window.load_xml_text(xml, tmp_path / 'clear-review.xml')
        key = window._draft_key
        window.set_parser_issues(linked)
        heading = next(window.author_list.item(i) for i in range(window.author_list.count())
                       if window.author_list.item(i).data(Qt.UserRole + 2))
        assert 'Review surname' in heading.text()
        assert heading.background().color().name() == '#54252b'

        values = window.session.author_form(0)
        values['surname'] = 'Jones'
        assert window.session.set_author_form(0, values)
        window._refresh()
        issue = window._drafts[key]['parser_issues'][0]
        assert issue['status'] == 'PENDING'
        window._resolve_parser_review(issue, 'FIXED', 'Reviewer', 'Correction checked against PDF')
        assert [i['message'] for i in window._drafts[key]['parser_issues'] if i['status'] == 'PENDING'] == ['Review organization']
        assert 'Review surname' not in window._drafts[key]['parser_warnings']

        node = window.session.affiliation_groups()[0][2][0]
        values = window.session.affiliation_form(node)
        values['organization'] = 'University 2'
        assert window.session.set_affiliation_form(node, values)
        window._refresh()
        # Changing the affiliation invalidates the earlier author acceptance.
        for issue in window._drafts[key]['parser_issues']:
            if issue['status'] == 'PENDING':
                window._resolve_parser_review(issue, 'FIXED', 'Reviewer', 'Correction checked against PDF')
        assert all(i['status'] == 'FIXED' for i in window._drafts[key]['parser_issues'])
        assert window._drafts[key]['parser_warnings'] == []
        assert window.parser_review.isHidden()
        for index in range(window.author_list.count()):
            item = window.author_list.item(index)
            assert 'Review:' not in item.text()
            assert item.background().style() == Qt.NoBrush
    finally:
        window.session.dirty = False
        window.close()


def test_parser_notes_target_groups_and_survive_draft_switch(qapp):
    authors = [Author(id='author_1', surname='Smith', affiliation_ids=['1', '2']),
               Author(id='author_2', surname='Jones', affiliation_ids=['3'])]
    affiliations = [Affiliation(id=str(i), text=f'University {i}') for i in range(1, 4)]
    linked = LinkedAuthors(authors, affiliations, issues=[
        LinkIssue('warning', 'Review surname', author_id='author_1'),
        LinkIssue('warning', 'Review organization', affiliation_id='2'),
        LinkIssue('warning', 'Review correspondence', author_id='author_1'),
        LinkIssue('warning', 'Review source selection'),
    ])
    xml = JATSGenerator().to_string(Document(authors=authors, affiliations=affiliations))
    window = XmlCorrectionWindow()
    try:
        assert window.load_xml_text(xml, Path('review.xml'))
        before = window.session.xml_text()
        key = window._draft_key
        window.set_parser_issues(linked)
        headings = [window.author_list.item(i) for i in range(window.author_list.count())
                    if window.author_list.item(i).data(Qt.UserRole + 2)]
        assert 'Review surname' in headings[0].text()
        assert 'Review organization' in headings[1].text()
        assert 'Review:' not in headings[2].text()
        assert headings[0].background().color().name() == '#54252b'
        assert 'Review source selection' in window.parser_review.text()
        assert 'Review correspondence' in window.correspondence_details.item(0).text()
        assert window.session.xml_text() == before
        assert window.load_xml_text(xml, Path('clean.xml'))
        assert window.parser_review.isHidden()
        window.activate_draft(key)
        assert 'Review source selection' in window.parser_review.text()
        assert window._drafts[key]['parser_issues'][0]['author_seq'] == '1'
    finally:
        window.deleteLater()


def test_review_log_persistence_reopening_and_failure(qapp, tmp_path, monkeypatch):
    import json
    import pytest
    from pdf_to_jats.core.draft_workspace import stage_workspace
    from pdf_to_jats.core.xml_validation import ExportMode
    from PySide6.QtWidgets import QMessageBox

    author = Author(id='author_1', surname='Smith', affiliation_ids=['1'])
    affiliation = Affiliation(id='1', text='University')
    linked = LinkedAuthors([author], [affiliation], issues=[
        LinkIssue('warning', 'Check name against PDF', author_id='author_1')])
    xml = JATSGenerator().to_string(Document(authors=[author], affiliations=[affiliation]))
    window = XmlCorrectionWindow()
    try:
        window.load_xml_text(xml, tmp_path / 'article.xml')
        window.set_parser_issues(linked)
        issue = window._review_records()[0]
        with pytest.raises(ValueError):
            window._resolve_parser_review(issue, 'FIXED', 'Reviewer', 'Checked')
        with pytest.raises(ValueError):
            window._resolve_parser_review(issue, 'PASSED', '', 'Checked')
        window._resolve_parser_review(issue, 'PASSED', 'Reviewer', 'Checked PDF', 'Name verified')
        log = tmp_path / 'article_review_log.txt'
        event = json.loads(log.read_text(encoding='utf-8'))
        assert event['action'] == 'PASSED'
        assert event['reviewer'] == 'Reviewer'
        assert event['review_id'] == issue['review_id']
        assert window.parser_review.isHidden()
        workspace = stage_workspace(json.loads(window._workspace_text()))
        retained = workspace['articles'][workspace['active']]
        assert retained['parser_issues'][0]['status'] == 'PASSED'
        assert retained['review_history'] == [event]
        assert 'Check name against PDF' not in window.session.xml_text()

        # An unrelated title change must not invalidate an author acceptance.
        window.session.set_title('Unrelated title correction')
        window._refresh()
        assert issue['status'] == 'PASSED'
        current_values = window._review_values(issue)
        assert current_values == issue['resolved_values']
        values = window.session.author_form(0)
        values['surname'] = 'Jones'
        window.session.set_author_form(0, values)
        window._refresh()
        assert issue['status'] == 'PENDING'
        assert len(window._drafts[window._draft_key]['review_history']) == 1

        original_open = Path.open
        def failed_open(path, *args, **kwargs):
            if path == log:
                raise OSError('Disk unavailable')
            return original_open(path, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(Path, 'open', failed_open)
            with pytest.raises(OSError):
                window._resolve_parser_review(issue, 'FIXED', 'Reviewer', 'Checked correction')
        assert issue['status'] == 'PENDING'
        assert len(log.read_text(encoding='utf-8').splitlines()) == 1
        monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
        monkeypatch.setattr(window, 'show_parser_reviews', lambda: None)
        assert window.save_copy(mode=ExportMode.VALIDATED) is False
        window._resolve_parser_review(issue, 'FIXED', 'Reviewer', 'Checked correction')
        events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        assert [e['action'] for e in events] == ['PASSED', 'FIXED']
        assert events[1]['previous_value'] != events[1]['updated_value']
    finally:
        window.deleteLater()
