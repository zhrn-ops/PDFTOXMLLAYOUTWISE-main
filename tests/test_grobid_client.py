from lxml import etree
import pytest

from pdf_to_jats.core.grobid_client import GrobidClient
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.models.document import Document


@pytest.mark.parametrize('entry_count', [0, 2])
@pytest.mark.parametrize('inline', [False, True])
def test_ambiguous_affiliation_preserves_draft_and_continues(monkeypatch, entry_count, inline):
    source = 'Department X, University Y, London, UK'
    calls = []
    progress = []

    def parse(self, endpoint, field, text):
        calls.append(text)
        root = etree.Element('results')
        if field == 'names':
            first, last = text.split()
            person = etree.SubElement(root, 'persName')
            etree.SubElement(person, 'forename').text = first
            etree.SubElement(person, 'surname').text = last
        elif text == source:
            for _ in range(entry_count):
                affiliation = etree.SubElement(root, 'affiliation')
                etree.SubElement(affiliation, 'orgName').text = 'Partial organization'
        else:
            affiliation = etree.SubElement(root, 'affiliation')
            etree.SubElement(affiliation, 'orgName').text = 'University Z'
        return root

    monkeypatch.setattr(GrobidClient, '_parse', parse)
    payload = ({'author_blocks': [{'text': f'Jane Smith ({source}), Joe Jones (University Z)'}]}
               if inline else {
                   'author_blocks': [{'text': 'Jane Smith1; Joe Jones2'}],
                   'affiliation_blocks': [{'text': f'1 {source}'}, {'text': '2 University Z'}],
               })
    linked = GrobidClient().classify('', payload, progress=progress.append)
    first, second = linked.affiliations
    assert first.text == source
    assert first.structured == {'organization': [source]}
    assert second.structured['organization'] == ['University Z']
    assert calls[-2:] == [source, 'University Z']
    assert [author.affiliation_ids for author in linked.authors] == [[first.id], [second.id]]
    warnings = [issue for issue in linked.issues if issue.affiliation_id == first.id]
    assert len(warnings) == 1
    assert warnings[0].severity == 'warning'
    assert f'returned {entry_count} affiliation entries' in warnings[0].message
    assert warnings[0].message in progress
    root = etree.fromstring(JATSGenerator().to_string(Document(
        title='Test', authors=linked.authors, affiliations=linked.affiliations)).encode())
    assert source in root.xpath('//*[local-name()="source-text"]/text()')
    assert source in root.xpath('//*[local-name()="organization"]/text()')


def test_uppercase_author_reaches_grobid_and_xml(monkeypatch):
    calls = []

    def parse(self, endpoint, field, text):
        calls.append((endpoint, text))
        if endpoint == 'processHeaderNames':
            return etree.fromstring(
                b'<results><persName><forename>KIRSTEN</forename>'
                b'<forename>E.</forename><surname>PETERS</surname></persName></results>')
        return etree.fromstring(
            b'<results><affiliation><settlement>Perth</settlement>'
            b'<country>Australia</country></affiliation></results>')

    monkeypatch.setattr(GrobidClient, '_parse', parse)
    linked = GrobidClient().classify('', {
        'author_blocks': [{'text': 'KIRSTEN E. PETERS'}],
        'affiliation_blocks': [{'text': 'Perth, Australia, Fremantle, Australia'}],
    })
    assert calls[0] == ('processHeaderNames', 'KIRSTEN E. PETERS')
    assert len(linked.authors) == 1
    assert linked.authors[0].affiliation_ids == [linked.affiliations[0].id]
    root = etree.fromstring(JATSGenerator().to_string(Document(
        title='Test', authors=linked.authors, affiliations=linked.affiliations)).encode())
    assert root.xpath('//*[local-name()="author"]/*[local-name()="surname"]/text()') == ['PETERS']


def test_grobid_keeps_markers_and_emits_structured_affiliation(monkeypatch):
    calls = []
    def parse(self, endpoint, field, text):
        calls.append((endpoint, field, text))
        if endpoint == 'processHeaderNames':
            return etree.fromstring(b'<results><persName><forename>Karen</forename>'
                                    b'<forename>Liceth</forename><surname>Melo</surname></persName></results>')
        return etree.fromstring(b'<results><affiliation><orgName type="department">Department X</orgName>'
                                b'<orgName>Universidad de los Andes</orgName><address>'
                                b'<settlement>Bogota</settlement><country key="CO">Colombia</country>'
                                b'</address></affiliation></results>')
    monkeypatch.setattr(GrobidClient, '_parse', parse)
    linked = GrobidClient().classify('', {
        'author_blocks': [{'text': 'Karen Liceth Melo2'}],
        'affiliation_blocks': [{'text': '2 Universidad de los Andes, Bogota, Colombia'}],
    })
    assert linked.authors[0].given_names == 'Karen Liceth'
    assert linked.authors[0].affiliation_ids == [linked.affiliations[0].id]
    assert calls[0][2] == 'Karen Liceth Melo'
    root = etree.fromstring(JATSGenerator().to_string(Document(
        title='Test', authors=linked.authors, affiliations=linked.affiliations)).encode())
    assert root.xpath('//*[local-name()="organization"]/text()') == ['Department X', 'Universidad de los Andes']
    assert root.xpath('//*[local-name()="country"]/@iso-code') == ['COL']
    assert root.xpath('//*[local-name()="source-text"]/text()') == ['Universidad de los Andes, Bogota, Colombia']


def test_ambiguous_grobid_names_preserve_source_author_and_flag_review(monkeypatch):
    monkeypatch.setattr(GrobidClient, '_parse', lambda *args: etree.fromstring(
        b'<results><persName/><persName/></results>'))
    result = GrobidClient().classify('', {'author_blocks': [{'text': 'Jane Smith1'}]})
    assert len(result.authors) == 1
    assert result.authors[0].given_names == 'Jane'
    assert result.authors[0].surname == 'Smith'
    assert result.authors[0].markers == ['1']
    assert any('Kept the local parser' in issue.message for issue in result.issues)


@pytest.mark.parametrize('explicit', [True, False])
def test_grobid_emits_correspondence_and_uses_tagged_author(monkeypatch, explicit):
    def parse(self, endpoint, field, text):
        root = etree.Element('results')
        if field == 'names':
            first, last = text.split()
            person = etree.SubElement(root, 'persName')
            etree.SubElement(person, 'forename').text = first
            etree.SubElement(person, 'surname').text = last
        else:
            affiliation = etree.SubElement(root, 'affiliation')
            etree.SubElement(affiliation, 'orgName').text = text
        return root

    monkeypatch.setattr(GrobidClient, '_parse', parse)
    blocks = [{'text': 'Jane Smith; Joe Jones', 'role': 'author'}]
    if explicit:
        blocks.append({'text': 'Corresponding author: Joe Jones', 'role': 'corresponding_author'})
    linked = GrobidClient().classify('', {
        'author_blocks': blocks, 'affiliation_blocks': [{'text': 'University X'}]})
    assert len(linked.authors) == 2
    assert linked.corresponding_author is linked.authors[1 if explicit else 0]
    assert any('used the first author' in issue.message for issue in linked.issues) == (not explicit)
    root = etree.fromstring(JATSGenerator().to_string(Document(
        title='Test', authors=linked.authors, affiliations=linked.affiliations,
        corresponding_author=linked.corresponding_author)).encode())
    assert root.xpath('//*[local-name()="correspondence"]/*[local-name()="person"]/*[local-name()="surname"]/text()') == [
        'Jones' if explicit else 'Smith']
    assert root.xpath('//*[local-name()="correspondence"]/*[local-name()="affiliation"]')
