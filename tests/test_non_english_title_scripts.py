from pathlib import Path

import pytest
from lxml import etree

from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.models.document import Document


def session(language='FAS'):
    return XmlDocumentSession.from_text(
        '<units xmlns="http://www.elsevier.com/xml/ani/ani" '
        'xmlns:ce="http://www.elsevier.com/xml/ani/common"><citation-title>'
        f'<titletext xml:lang="{language}" original="y">A<ce:sup>2</ce:sup>'
        ' B<ce:sub>3</ce:sub> C<ce:inf><ce:italic>4</ce:italic></ce:inf> end</titletext>'
        '</citation-title></units>', Path('title.xml'))


@pytest.mark.parametrize('language', ['FAS', 'ARA', 'FRA'])
def test_generated_non_english_title_has_no_scripts(language):
    document = Document(title='A2B', metadata={'title_language': language,
                        'title_script_runs': [{'start': 1, 'end': 2, 'text': '2', 'type': 'sup'}]})
    root = etree.fromstring(JATSGenerator().to_bytes(document))
    title = root.find('.//{http://www.elsevier.com/xml/ani/ani}titletext')
    assert title.text == 'A2B'
    assert len(title) == 0


def test_existing_title_export_preserves_all_text_and_other_markup():
    s = session()
    root = etree.fromstring(s.xml_bytes())
    title = root.find('.//{http://www.elsevier.com/xml/ani/ani}titletext')
    assert ''.join(title.itertext()) == 'A2 B3 C4 end'
    assert [etree.QName(child).localname for child in title.iter() if child is not title] == ['italic']
    assert title.get('original') == 'y'


def test_english_title_keeps_scripts():
    root = etree.fromstring(session('ENG').xml_bytes())
    assert root.find('.//{http://www.elsevier.com/xml/ani/common}sup') is not None


def test_formatting_non_english_title_is_rejected_without_changes():
    s = session()
    before = etree.tostring(s.tree)
    with pytest.raises(ValueError, match='only for English'):
        s.apply_script('title', 0, 1, 'sup')
    assert etree.tostring(s.tree) == before


def test_changing_english_title_language_removes_scripts():
    s = session('ENG')
    s.set_title_language('FAS')
    assert not any(s._local_name(node) in {'sup', 'sub', 'inf'} for node in s.title_node().iter())
    assert ''.join(s.title_node().itertext()) == 'A2 B3 C4 end'
