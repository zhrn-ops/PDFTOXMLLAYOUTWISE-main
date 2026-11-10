from dataclasses import asdict
import json

from lxml import etree

from pdf_to_jats.core.alternate_names import is_alternate_capture
from pdf_to_jats.core.author_linker import AuthorLinker
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.gui.alternate_names_dialog import AlternateNamesDialog
from pdf_to_jats.gui.main_window import MainWindow
from pdf_to_jats.models.author import Author
from pdf_to_jats.models.block import TextBlock
from pdf_to_jats.models.document import Document


def block(text, identifier='native'):
    return TextBlock(identifier, 1, text, [0, 0, 100, 20], 0, 0, 100, 20, role='author')


def test_shared_markers_never_auto_assign_and_whole_text_is_preserved():
    native = block('علی رضایی1، سارا محمدی1')
    linked = AuthorLinker().link_from_blocks([native, block('Ali Rezaei1', 'latin')], [])
    assert len(linked.authors) == 1
    assert linked.authors[0].alternate_names == []
    assert native.text == 'علی رضایی1، سارا محمدی1'
    assert any('Unassigned alternate name' in issue.message for issue in linked.issues)


def test_accented_latin_is_a_main_author():
    assert not is_alternate_capture(block('José Müller'))
    assert is_alternate_capture(block('علی رضایی'))


def test_assignment_roundtrip_and_reassignment_do_not_depend_on_author_order():
    native = block('علی رضایی')
    native.metadata['alternate_name_target'] = 'Ali Rezaei'
    native = TextBlock(**json.loads(json.dumps(asdict(native))))
    authors = [block('Sara Mohammadi', 'sara'), native, block('Ali Rezaei', 'ali')]
    linked = AuthorLinker().link_from_blocks(authors, [])
    assert [[name.text for name in author.alternate_names] for author in linked.authors] == [[], ['علی رضایی']]
    native.metadata['alternate_name_target'] = 'Sara Mohammadi'
    linked = AuthorLinker().link_from_blocks(authors, [])
    assert [[name.text for name in author.alternate_names] for author in linked.authors] == [['علی رضایی'], []]


def test_missing_target_stays_unassigned():
    native = block('علی رضایی')
    native.metadata['alternate_name_target'] = 'Removed Author'
    linked = AuthorLinker().link_from_blocks([native, block('Ali Rezaei', 'ali')], [])
    assert not linked.authors[0].alternate_names
    assert any('Unassigned alternate name' in issue.message for issue in linked.issues)


def test_native_only_requires_explicit_keep_as_main_author():
    native = block('علی رضایی')
    assert not AuthorLinker().link_from_blocks([native], []).authors
    native.metadata['keep_main_author'] = True
    assert len(AuthorLinker().link_from_blocks([native], []).authors) == 1


def test_parser_payload_excludes_pending_and_assigned_captures():
    native = block('علی رضایی')
    latin = block('Ali Rezaei', 'latin')
    document = Document(blocks=[native, latin])
    for target in ('', 'Ali Rezaei'):
        native.metadata['alternate_name_target'] = target
        payload = MainWindow._author_affiliation_payload(document)
        assert [entry['block_id'] for entry in payload['author_blocks']] == ['latin']
    native.metadata['keep_main_author'] = True
    assert len(MainWindow._author_affiliation_payload(document)['author_blocks']) == 2


def test_export_resolves_manual_assignment_after_parser_replaces_authors():
    native = block('علی رضایی')
    native.metadata['alternate_name_target'] = 'Ali Rezaei'
    author = Author(display_name='Ali Rezaei', given_names='Ali', surname='Rezaei')
    document = Document(authors=[author], blocks=[native])
    root = etree.fromstring(JATSGenerator().to_bytes(document))
    assert root.findtext(f'.//{{{JATSGenerator.CE_NS}}}alt-name') == native.text
    assert not author.alternate_names  # exporting does not mutate the source model


def test_dialog_stages_changes_and_supports_unassign_and_keep(qapp):
    native = block('علی رضایی')
    author = Author(display_name='Ali Rezaei')
    dialog = AlternateNamesDialog([native], [author])
    dialog.choices[0].setCurrentIndex(2)
    assert native.metadata == {}
    dialog.apply()
    assert native.metadata['alternate_name_target'] == 'Ali Rezaei'
    dialog.choices[0].setCurrentIndex(1)
    dialog.apply()
    assert native.metadata == {'keep_main_author': True}
    dialog.choices[0].setCurrentIndex(0)
    dialog.apply()
    assert native.metadata == {}
    dialog.close()


def test_dialog_does_not_offer_ambiguous_duplicate_targets(qapp):
    dialog = AlternateNamesDialog([block('علی رضایی')],
                                  [Author(display_name='Ali Rezaei'), Author(display_name='Ali Rezaei')])
    assert dialog.choices[0].count() == 2
    dialog.close()
