"""Documents carrying comments must not break the correction session."""

from pathlib import Path

from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


COMMENTED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<article>\n'
    '<!-- document comment -->\n'
    '<article-title>Old <!-- inline --> title</article-title>\n'
    '<contrib-group><!-- group --><contrib contrib-type="author">'
    '<name><surname>Smith</surname><given-names>Jane</given-names></name>'
    '</contrib></contrib-group>\n'
    '<abstract><?pi keep?><p>Body<!-- note --> text</p></abstract>\n'
    '<kwd-group><kwd>one</kwd></kwd-group>\n'
    '</article>\n'
)


def test_commented_xml_can_be_opened_in_the_workspace(qapp):
    window = XmlCorrectionWindow()
    assert window.load_xml_text(COMMENTED, Path('commented.xml'))
    try:
        session = window.session
        assert session.title() == 'Old title'
        assert session.abstract() == 'Body text'
        assert len(session.authors()) == 1
        assert session.author_name(session.authors()[0]) == 'Smith Jane'
        assert [node.text for node in session.keywords()] == ['one']
        assert window.preview.toPlainText() == session.xml_text()
        assert '<!-- document comment -->' in window.raw.toPlainText()
        # Validating reads the same fields, so it must survive comments too.
        assert session.validate()
    finally:
        window.deleteLater()


def test_adding_a_comment_in_the_xml_panes_is_refused(qapp):
    window = XmlCorrectionWindow()
    window.load_xml_text('<article><article-title>Title</article-title></article>', Path('clean.xml'))
    try:
        before = window.raw.toPlainText()
        window.raw.setPlainText(before + '<!-- note -->')
        assert window.raw.toPlainText() == before
        assert window.preview.toPlainText() == before
        assert 'comments are disabled' in window.status.text()
        assert window.session.xml_text() == before

        # Ordinary edits still go through afterwards.
        window.raw.setPlainText('<article>\n<article-title>Changed</article-title>\n</article>')
        assert window.preview.toPlainText() == window.raw.toPlainText()
        assert window.session.title() == 'Changed'
    finally:
        window.deleteLater()


def test_restoring_a_draft_keeps_its_existing_comments(qapp):
    window = XmlCorrectionWindow()
    window.load_xml_text('<article><article-title>T</article-title></article>', Path('a.xml'))
    try:
        window._drafts['draft:commented'] = {
            'xml': '<article><article-title>T</article-title></article>',
            'raw': '<article><!-- keep --><article-title>T</article-title></article>',
            'path': 'commented.xml', 'source': '', 'pdf': '', 'dirty': True,
            'history': ['<article><article-title>T</article-title></article>'],
            'history_index': 0,
        }
        assert window.activate_draft('draft:commented')
        assert '<!-- keep -->' in window.raw.toPlainText()
        assert window.preview.toPlainText() == window.raw.toPlainText()
    finally:
        window.deleteLater()


def test_commented_metadata_can_still_be_edited(qapp):
    window = XmlCorrectionWindow()
    window.load_xml_text(COMMENTED, Path('commented.xml'))
    try:
        window.title_edit.setPlainText('New title')
        assert window.session.title() == 'New title'
        # An abstract holding markup this form cannot rewrite is refused with a
        # message instead of crashing or silently dropping that markup.
        window.abstract_edit.setPlainText('New body')
        assert window.session.abstract() == 'Body text'
        assert 'cannot be safely replaced' in window.status.text()
        # Edits to fields leave unrelated comments in the document intact.
        assert '<!-- document comment -->' in window.session.xml_text()
        assert '<!-- group -->' in window.session.xml_text()
    finally:
        window.deleteLater()
