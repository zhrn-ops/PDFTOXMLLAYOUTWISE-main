from pathlib import Path

import pytest
from lxml import etree

from pdf_to_jats.core.country_codes import COUNTRIES, country_code, normalize_country_elements
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.models.affiliation import Affiliation
from pdf_to_jats.models.document import Document


@pytest.mark.parametrize('value,expected', [
    ('Islamic Republic of Iran', 'IRN'), ('Iran (Islamic Republic of)', 'IRN'),
    ('ir', 'IRN'), ('IRN', 'IRN'), ('U.S.A.', 'USA'), (' U.K. ', 'GBR'),
    ('Viet Nam', 'VNM'), ('Vietnam', 'VNM'), ('Sri Lanka', 'LKA'),
    ('Côte d’Ivoire', 'CIV'), ('Ivory Coast', 'CIV'), ('Türkiye', 'TUR'),
    ('Bonaire', 'BES'), ('Saba', 'BES'), ('Saint Eustatius', 'BES'),
    ('England', 'GBR'), ('Scotland', 'GBR'), ('Wales', 'GBR'),
    ('Northern Ireland', 'GBR'), ('Deutschland', 'DEU'),
    ('The Netherlands', 'NLD'), ('the netherlands', 'NLD'),
])
def test_aliases_and_codes(value, expected):
    assert country_code(value) == expected


def test_pdf_table_is_complete_and_eu_is_funding_only():
    assert len(COUNTRIES) == 247
    for row in COUNTRIES:
        assert country_code(row['name'], funding=True) == row['alpha3']
        assert country_code(row['alpha2'], funding=True) == row['alpha3']
    assert country_code('European Union') == ''
    assert country_code('EU', funding=True) == 'EUE'


@pytest.mark.parametrize('value', ['Korea', 'Virgin Islands', 'Atlantis', 'UNK'])
def test_unknown_or_ambiguous_names_are_not_guessed(value):
    assert country_code(value) == ''


def test_structured_export_country_is_code_only():
    doc = Document(affiliations=[Affiliation(id='1', text='University, Tehran, Iran',
                   structured={'organization': ['University'], 'country': ['Islamic Republic of Iran']})])
    root = etree.fromstring(JATSGenerator().to_bytes(doc))
    country = root.find('.//{http://www.elsevier.com/xml/ani/ani}country')
    assert country.get('iso-code') == 'IRN'
    assert country.text is None and len(country) == 0


def test_unstructured_alias_is_recognized_only_at_end():
    generator = JATSGenerator()
    assert generator._split_affiliation('University, Tehran, Islamic Republic of Iran')[2] == 'Islamic Republic of Iran'
    assert generator._split_affiliation('University, IN, Indianapolis')[2] == ''


def test_existing_xml_normalizes_known_countries_and_preserves_source():
    s = XmlDocumentSession.from_text('<units><affiliation><country iso-code="ir">Iran</country>'
                                   '<source-text>University, Iran</source-text></affiliation></units>', Path('draft.xml'))
    root = etree.fromstring(s.xml_bytes())
    assert root.find('.//country').get('iso-code') == 'IRN'
    assert root.find('.//country').text is None
    assert root.find('.//source-text').text == 'University, Iran'


@pytest.mark.parametrize('xml', ['<country>Atlantis</country>', '<country iso-code="USA">Iran</country>'])
def test_export_rejects_unresolved_or_conflicting_country(xml):
    with pytest.raises(ValueError):
        normalize_country_elements(etree.fromstring('<units>' + xml + '</units>'))


def test_jats_country_is_not_rewritten():
    root = etree.fromstring('<article><aff><country>Iran</country></aff></article>')
    normalize_country_elements(root)
    assert root.find('.//country').text == 'Iran'


@pytest.mark.parametrize('encoding', [None, 'UTF-8'])
def test_saved_copy_contains_only_three_letter_country_code(tmp_path, encoding):
    s = XmlDocumentSession.from_text('<units><affiliation><country>Islamic Republic of Iran</country>'
                                   '</affiliation></units>', Path('source.xml'))
    s.validate()
    target = tmp_path / 'copy.xml'
    s.save_copy(target, encoding=encoding)
    country = etree.parse(str(target)).find('.//country')
    assert country.get('iso-code') == 'IRN' and country.text is None


def test_unresolved_country_is_reported_and_not_saved(tmp_path):
    s = XmlDocumentSession.from_text('<units><affiliation><country>Korea</country>'
                                   '</affiliation></units>', Path('source.xml'))
    assert any(issue.field == 'country' and issue.severity == 'error' for issue in s.validate())
    target = tmp_path / 'copy.xml'
    with pytest.raises(ValueError, match='needs review'):
        s.save_copy(target)
    assert not target.exists()


def test_constituent_country_alias_normalizes_in_strict_mode():
    root = etree.fromstring('<units><affiliation><country>England</country></affiliation></units>')
    normalize_country_elements(root, strict=True)
    country = root.find('.//country')
    assert country.get('iso-code') == 'GBR'
    assert country.text is None and len(country) == 0


def test_leading_the_is_ignored_for_country_names():
    root = etree.fromstring('<units><affiliation><country>The Netherlands</country></affiliation></units>')
    normalize_country_elements(root, strict=True)
    assert root.find('.//country').get('iso-code') == 'NLD'
