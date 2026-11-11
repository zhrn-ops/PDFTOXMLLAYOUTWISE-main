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
def test_generated_non_english_title_preserves_scripts(language):
    document = Document(title='A2B', metadata={'title_language': language,
                        'title_script_runs': [{'start': 1, 'end': 2, 'text': '2', 'type': 'sup'}]})
    root = etree.fromstring(JATSGenerator().to_bytes(document))
    title = root.find('.//{http://www.elsevier.com/xml/ani/ani}titletext')
    assert ''.join(title.itertext()) == 'A2B'
    assert title[0].tag == '{http://www.elsevier.com/xml/ani/common}sup'
    assert title[0].text == '2'


def test_existing_title_export_preserves_all_text_and_other_markup():
    s = session()
    root = etree.fromstring(s.xml_bytes())
    title = root.find('.//{http://www.elsevier.com/xml/ani/ani}titletext')
    assert ''.join(title.itertext()) == 'A2 B3 C4 end'
    assert [etree.QName(child).localname for child in title.iter() if child is not title] == ['sup', 'sub', 'inf', 'italic']
    assert title.get('original') == 'y'


def test_english_title_keeps_scripts():
    root = etree.fromstring(session('ENG').xml_bytes())
    assert root.find('.//{http://www.elsevier.com/xml/ani/common}sup') is not None


def test_formatting_non_english_title_preserves_scientific_meaning():
    s = session()
    s.set_title('H2O')
    s.apply_script('title', 1, 2, 'inf')
    assert ''.join(s.title_node().itertext()) == 'H2O'
    assert s.title_node()[0].text == '2'
    assert s._local_name(s.title_node()[0]) == 'inf'


def test_changing_english_title_language_preserves_scripts():
    s = session('ENG')
    s.set_title_language('FAS')
    assert [s._local_name(node) for node in s.title_node().iter()][1:] == ['sup', 'sub', 'inf', 'italic']
    assert ''.join(s.title_node().itertext()) == 'A2 B3 C4 end'
