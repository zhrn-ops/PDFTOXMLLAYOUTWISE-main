from pathlib import Path

from PySide6.QtWidgets import QPushButton

from pdf_to_jats.core.grammar_check import check_grammar
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.grammar_review import GrammarReviewDialog
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


def test_common_errors_and_offsets():
    text = 'The the results is from a observational study ,with an significant effect.'
    suggestions = check_grammar(text)
    for issue in reversed(suggestions):
        text = text[:issue.start] + issue.replacement + text[issue.end:]
    assert text == 'The results are from an observational study, with a significant effect.'


def test_scientific_terms_and_article_exceptions_are_left_alone():
    suggestions = check_grammar('An MRI study at a university took an hour. IL-6 increased by 1.5%.')
    assert len(suggestions) == 1
    assert suggestions[0].message.startswith('Hyphenated word')


def test_typo_suggestions_preserve_case_and_exact_offsets():
    text = '😀 Teh paitents showed signficant resutls.'
    suggestions = check_grammar(text)
    assert len(suggestions) == 4
    assert all(issue.message == 'Possible typo' for issue in suggestions)
    for issue in reversed(suggestions):
        text = text[:issue.start] + issue.replacement + text[issue.end:]
    assert text == '😀 The patients showed significant results.'


def test_typo_check_leaves_identifiers_and_language_variants_alone():
    suggestions = check_grammar('TEH TeH IL-6 BRCA1 p53 immunohistochemistry randomised randomized '
                                'colour color dependant teh2')
    assert len(suggestions) == 1
    assert suggestions[0].message.startswith('Hyphenated word')


def test_hyphenated_words_and_pdf_line_breaks_are_optional_suggestions():
    text = 'A well-known inter-\nvention uses IL-6, café-based methods and 10-20 samples.'
    suggestions = check_grammar(text)
    assert [(text[s.start:s.end], s.replacement) for s in suggestions] == [
        ('well-known', 'wellknown'), ('inter-\nvention', 'intervention'),
        ('IL-6', 'IL6'), ('café-based', 'cafébased')]
    assert all('optional review' in s.message for s in suggestions)


def test_hyphen_review_allows_custom_replacement_and_ignore(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<article><abstract>😀 follow-up and well-known.</abstract></article>', Path('hyphen.xml'))
    window._refresh()
    original = window.session.xml_text()
    dialog = GrammarReviewDialog(window.abstract_edit, window._record_history, window)
    try:
        assert window.session.xml_text() == original
        dialog.replacement_edit.setText('follow up')
        dialog.apply_button.click()
        assert window.abstract_edit.toPlainText() == '😀 follow up and well-known.'
        after_apply = window.session.xml_text()
        dialog.ignore_button.click()
        assert window.session.xml_text() == after_apply
        assert not dialog.suggestions
        window._undo_field()
        assert window.session.xml_text() == original
    finally:
        dialog.close()
        window.session.dirty = False
        window.close()


def test_typo_review_apply_ignore_and_undo(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<article><abstract><p>😀 Teh resutls use cm<sup>2</sup>.</p></abstract></article>',
        Path('typos.xml'))
    window._refresh()
    original = window.session.xml_text()
    dialog = GrammarReviewDialog(window.abstract_edit, window._record_history, window)
    try:
        assert len(dialog.suggestions) == 2
        dialog.apply_button.click()
        assert '😀 The resutls' in window.session.abstract()
        assert '<sup>2</sup>' in window.session.xml_text()
        after_apply = window.session.xml_text()
        dialog.ignore_button.click()
        assert not dialog.suggestions
        assert window.session.xml_text() == after_apply
        window._undo_field()
        assert window.session.xml_text() == original
    finally:
        dialog.close()
        window.session.dirty = False
        window.close()


def test_grammar_review_applies_to_xml_preserving_scripts_and_undo(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<article><abstract><p>😀 Results is measured in cm<sup>2</sup>.</p></abstract></article>',
        Path('grammar.xml'))
    window._refresh()
    original = window.session.xml_text()
    dialog = GrammarReviewDialog(window.abstract_edit, window._record_history, window)
    try:
        assert window.findChild(QPushButton, 'check_abstract_grammar')
        assert len(dialog.suggestions) == 1
        assert window.session.xml_text() == original
        dialog.apply_button.click()
        assert 'Results are measured' in window.session.abstract()
        assert '<sup>2</sup>' in window.session.xml_text()
        assert not dialog.suggestions
        window._undo_field()
        assert window.session.xml_text() == original
    finally:
        dialog.close()
        window.session.dirty = False
        window.close()


def test_stale_suggestion_rechecks_instead_of_overwriting(qapp):
    window = XmlCorrectionWindow()
    window.session = XmlDocumentSession.from_text(
        '<article><abstract>Results is significant.</abstract></article>', Path('grammar.xml'))
    window._refresh()
    dialog = GrammarReviewDialog(window.abstract_edit, window._record_history, window)
    try:
        window.abstract_edit.setPlainText('Results are significant.')
        dialog.apply_suggestion()
        assert window.abstract_edit.toPlainText() == 'Results are significant.'
        assert not dialog.suggestions
    finally:
        dialog.close()
        window.session.dirty = False
        window.close()
