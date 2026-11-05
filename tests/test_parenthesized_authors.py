import pytest
from lxml import etree

from pdf_to_jats.core.parenthesized_authors import split_parenthesized_authors, link_parenthesized_records
from pdf_to_jats.core.grobid_client import GrobidClient
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.models.document import Document


@pytest.mark.parametrize('separator', [' | ', '|', '\n|\n'])
def test_pipe_separates_authors_but_preserves_affiliation_content(separator):
    records = split_parenthesized_authors([{'text': separator.join([
        'Jane Smith (Department (Clinical | Research), University X)',
        'Joe Jones (University Y)',
        'Ann Brown (University Y)',
    ])}])
    assert [record.author_text for record in records] == ['Jane Smith', 'Joe Jones', 'Ann Brown']
    assert records[0].affiliation_text == 'Department (Clinical | Research), University X'
    linked = link_parenthesized_records(records)
    assert [a.affiliation_ids for a in linked.authors] == [['aff_1'], ['aff_2'], ['aff_2']]


def test_pipe_does_not_attach_another_authors_affiliation_to_missing_entry():
    with pytest.raises(ValueError, match='Incomplete'):
        split_parenthesized_authors([{'text':
            'Jane Smith (University X) | Joe Jones | Ann Brown (University Y)'}])


@pytest.mark.parametrize('separator', ['|', ';'])
def test_inside_separator_links_one_author_to_multiple_affiliations(separator):
    records = split_parenthesized_authors([{'text':
        f'Jane Smith (Department (Clinical {separator} Research), University X {separator} Hospital Y), '
        f'Joe Jones (Hospital Y {separator} hospital y)'}])
    linked = link_parenthesized_records(records)
    assert len(linked.authors) == 2
    assert [aff.text for aff in linked.affiliations] == [
        f'Department (Clinical {separator} Research), University X', 'Hospital Y']
    assert [a.affiliation_ids for a in linked.authors] == [['aff_1', 'aff_2'], ['aff_2']]
    groups = JATSGenerator()._author_groups(Document(authors=linked.authors, affiliations=linked.affiliations))
    assert [[a.display_name for a in authors] for _, authors in groups] == [
        ['Jane Smith'], ['Jane Smith', 'Joe Jones']]


@pytest.mark.parametrize('text', [
    'University X |', '| University X', 'University X || Hospital Y',
    'University X ;', '; University X', 'University X ;; Hospital Y',
    'University X |; Hospital Y',
])
def test_empty_pipe_affiliations_require_review(text):
    records = split_parenthesized_authors([{'text': f'Jane Smith ({text})'}])
    with pytest.raises(ValueError, match='Empty affiliation'):
        link_parenthesized_records(records)


def test_nested_wrapped_records_preserve_provenance_and_links():
    records = split_parenthesized_authors([
        {'block_id': 'b1', 'text': 'Aya Ermis (School of Nursing, Emory University), Heidi'},
        {'block_id': 'b2', 'text': 'Schmidt (Department (Clinical Division), Hospital; University), Corey Williams (school of nursing, Emory University)'},
    ])
    assert len(records) == 3
    assert records[1].author_text == 'Heidi Schmidt'
    assert records[1].source_block_ids == ['b1', 'b2']
    assert records[1].affiliation_text == 'Department (Clinical Division), Hospital; University'
    linked = link_parenthesized_records(records)
    assert len(linked.affiliations) == 3
    assert [author.affiliation_ids for author in linked.authors] == [['aff_1'], ['aff_2', 'aff_3'], ['aff_1']]


@pytest.mark.parametrize('text', [
    'Jane Smith (Department of Medicine, University',
    'Jane Smith (Department of Medicine)), Joe Jones (University X)',
    'Jane Smith (Department of Medicine), Joe Jones',
])
def test_malformed_entries_are_not_silently_discarded(text):
    with pytest.raises(ValueError):
        split_parenthesized_authors([{'text': text}])


@pytest.mark.parametrize('text', ['Jane Smith1; Joe Jones2', 'Jane Smith (1), Joe Jones (2)'])
def test_numbered_byline_uses_existing_path(text):
    assert split_parenthesized_authors([{'text': text}]) is None


def test_grobid_inline_path_preserves_nested_affiliations_in_output(monkeypatch):
    calls = []
    def parse(self, endpoint, field, text):
        calls.append(text)
        root = etree.Element('results')
        if field == 'names':
            person = etree.SubElement(root, 'persName')
            first, surname = text.rsplit(' ', 1)
            etree.SubElement(person, 'forename').text = first
            etree.SubElement(person, 'surname').text = surname
        else:
            aff = etree.SubElement(root, 'affiliation')
            etree.SubElement(aff, 'orgName').text = text
        return root
    monkeypatch.setattr(GrobidClient, '_parse', parse)
    linked = GrobidClient().classify('', {'author_blocks': [{'text':
        'Aya Ermis (School of Nursing, Emory University), '
        'Corey Williams (School of Nursing, Emory University), '
        'Jane Smith (Department (Clinical Division), Emory University)'}]})
    assert len(calls) == 5
    root = etree.fromstring(JATSGenerator().to_string(Document(
        title='Test', authors=linked.authors, affiliations=linked.affiliations)).encode())
    groups = root.xpath('//*[local-name()="author-group"]')
    assert [len(group.xpath('./*[local-name()="author"]')) for group in groups] == [2, 1]
    assert len(linked.authors) == 3
