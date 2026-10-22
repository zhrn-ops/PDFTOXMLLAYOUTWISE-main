"""JSON-compatible snapshots of a PDF conversion workspace."""
from dataclasses import asdict

from pdf_to_jats.models.document import Document, DocumentZone
from pdf_to_jats.models.block import TextBlock
from pdf_to_jats.models.paragraph import Paragraph
from pdf_to_jats.models.author import Author
from pdf_to_jats.models.affiliation import Affiliation
from pdf_to_jats.core.author_linker import LinkedAuthors, LinkIssue


STATE_FIELDS = (
    '_finished_segment_keys', '_deleted_segment_keys', '_current_segment_key',
    '_article_draft_keys', '_startup_flow', '_explicit_number_workflow',
    '_html_preview_merges', '_manual_document_author_links',
)


def capture_workflow(window):
    if window.document is None:
        return None
    return dict(document=asdict(window.document),
                state={name: getattr(window, name) for name in STATE_FIELDS},
                manual_links=sorted(window._manual_link_review_segments),
                linked_authors={key: asdict(value) for key, value in window._llm_links_by_segment.items()})


def decode_workflow(data):
    values = dict(data['document'])
    for name, model in (('blocks', TextBlock), ('raw_blocks', TextBlock),
                        ('paragraphs', Paragraph), ('zones', DocumentZone),
                        ('authors', Author), ('affiliations', Affiliation)):
        values[name] = [model(**item) for item in values.get(name, [])]
    if values.get('corresponding_author'):
        values['corresponding_author'] = Author(**values['corresponding_author'])
    document = Document(**values)
    links = {}
    for key, item in data.get('linked_authors', {}).items():
        links[key] = LinkedAuthors(
            authors=[Author(**a) for a in item['authors']],
            affiliations=[Affiliation(**a) for a in item['affiliations']],
            corresponding_author=Author(**item['corresponding_author']) if item.get('corresponding_author') else None,
            issues=[LinkIssue(**issue) for issue in item.get('issues', [])],
        )
    return document, links
