from pathlib import Path

from lxml import etree

from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.models.document import Document
from pdf_to_jats.models.author import Author


NS = {'ani': JATSGenerator.ANI_NS, 'ce': JATSGenerator.CE_NS}


def generated(document):
    return etree.fromstring(JATSGenerator().to_bytes(document))


def test_populated_sections_follow_template_order_and_namespaces():
    author = Author(initials='A.', degrees='PhD', surname='Smith', given_names='Alice')
    document = Document(title='A study', abstract='Text', authors=[author], corresponding_author=author,
        references=['Smith A. Source & evidence.'], metadata={
            'keywords': ['biology'], 'pii': 'PII-1', 'doi': '10.1234/example', 'ern': 'ERN-1',
            'related_item': {'doi': '10.1234/related'},
            'grants': [{'grant_id': 'G1', 'agency': 'Funding organization'}],
            'publisher_name': 'Publisher', 'journal_title': 'Journal', 'article_number': 'A4',
            'isbns': [{'value': '1234567890', 'type': 'print', 'length': '10'}],
            'publisher_copyright': 'Copyright holder', 'website': 'https://example.org',
            'conference_event_id': 'C1', 'report_number': 'R1',
        })
    root = generated(document)
    template = etree.parse(str(Path(__file__).parents[1] / 'pdf_to_jats/templates/Template_CAR.xml'))
    for path in ('ani:unit/ani:unit-content/ani:bibrecord',
                 'ani:unit/ani:unit-content/ani:bibrecord/ani:head',
                 './/ani:author', './/ani:person', './/ani:source'):
        actual = root.find(path, NS)
        expected = template.getroot().find(path, NS)
        order = [child.tag for child in expected]
        positions = [order.index(child.tag) for child in actual]
        assert positions == sorted(positions)
    assert root.find('.//ani:head/ani:author-keywords', NS) is None
    assert root.find('.//ani:citation-info/ani:author-keywords/ani:author-keyword', NS).text == 'biology'
    assert root.find('.//ani:bibrecord/ani:tail/ani:bibliography', NS).get('refcount') == '1'
    assert root.find('.//ani:reference/ani:ref-fulltext', NS).text == document.references[0]
    assert root.find('ani:unit', NS).get('type') is None
    assert root.find('.//ani:source', NS).get('type') is None


def test_missing_metadata_is_flagged_without_fabricating_values():
    output = JATSGenerator().to_string(Document())
    for invented in ('00000000', 'Unknown Journal', 'Untitled', 'OSIN'):
        assert invented not in output
    root = etree.fromstring(output.encode())
    for tag in ('related-item', 'grantlist', 'tail', 'publisher'):
        assert root.find(f'.//ani:{tag}', NS) is None
    session = XmlDocumentSession.from_text(output, Path('draft.xml'))
    messages = [issue.message for issue in session.validate()]
    assert any('Unit ID' in message for message in messages)
    assert any('Journal/source title' in message for message in messages)
    assert any('provisionally' in message for message in messages)


def test_ani_keywords_remain_editable_in_correction_workspace():
    session = XmlDocumentSession.from_text(JATSGenerator().to_string(Document(title='Title')), Path('draft.xml'))
    session.add_keyword('First')
    session.add_keyword('Second')
    session.set_keyword(0, 'Corrected')
    assert [node.text for node in session.keywords()] == ['Corrected', 'Second']
    assert session.keywords()[0].getparent().getparent().tag == f'{{{JATSGenerator.ANI_NS}}}citation-info'


def test_issue_number_is_not_written_as_supplement():
    root = generated(Document(title='Title', metadata={'volume': '10', 'issue': '2'}))
    assert root.find('.//ani:iss-first', NS).text == '2'
    assert root.find('.//ani:suppl', NS) is None
