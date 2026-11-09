"""JSON-compatible snapshots of a PDF conversion workspace."""
from dataclasses import asdict, is_dataclass
from copy import deepcopy
from typing import Any, get_args, get_origin, get_type_hints
from types import UnionType
import math

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
    return deepcopy(dict(document=asdict(window.document),
                state={name: getattr(window, name) for name in STATE_FIELDS},
                manual_links=sorted(window._manual_link_review_segments),
                linked_authors={key: asdict(value) for key, value in window._llm_links_by_segment.items()}))


def _typed(value: Any, expected: Any, location: str) -> Any:
    """Decode dataclasses only after validating nested JSON field types."""
    if expected is Any or expected is object:
        return deepcopy(value)
    origin = get_origin(expected)
    args = get_args(expected)
    if origin is UnionType:
        for candidate in args:
            try:
                return _typed(value, candidate, location)
            except ValueError:
                continue
        raise ValueError(f"Invalid {location}")
    if is_dataclass(expected):
        if not isinstance(value, dict):
            raise ValueError(f"{location} must be an object")
        hints = get_type_hints(expected)
        if value.keys() - hints.keys():
            raise ValueError(f"Unknown fields in {location}")
        try:
            return expected(**{key: _typed(item, hints[key], f"{location}.{key}")
                               for key, item in value.items()})
        except TypeError as exc:
            raise ValueError(f"Incomplete {location}: {exc}") from exc
    if origin is list:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{location} must be a list")
        return [_typed(item, args[0], location) for item in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"{location} must be an object")
        return {_typed(key, args[0], location): _typed(item, args[1], location)
                for key, item in value.items()}
    valid = (type(value) in (int, float) and math.isfinite(value)) if expected is float else type(value) is expected
    if not valid:
        raise ValueError(f"Invalid field type at {location}")
    return value


def decode_workflow(data: dict) -> tuple[Document, dict[str, LinkedAuthors]]:
    if not isinstance(data, dict) or not isinstance(data.get('state'), dict):
        raise ValueError('Workspace requires document and state objects')
    document = _typed(data.get('document'), Document, 'document')
    state = data['state']
    expected = {
        '_finished_segment_keys': list[str], '_deleted_segment_keys': list[str],
        '_current_segment_key': str | None, '_article_draft_keys': dict[str, str],
        '_startup_flow': bool, '_explicit_number_workflow': bool,
        '_html_preview_merges': list[list[str]],
        '_manual_document_author_links': dict[str, list[str]],
    }
    for name, kind in expected.items():
        if name not in state:
            raise ValueError(f'Missing workflow state: {name}')
        _typed(state[name], kind, name)
    _typed(data.get('manual_links', []), list[str], 'manual_links')
    for key in ('source_pdf', 'source_path'):
        if key in document.metadata and not isinstance(document.metadata[key], str):
            raise ValueError(f'{key} must be a path string')
    for collection in (document.blocks, document.raw_blocks, document.paragraphs, document.zones):
        ids = set()
        for item in collection:
            if not item.id or item.id in ids or item.page < 1:
                raise ValueError('Invalid or duplicate block/paragraph/zone identity')
            ids.add(item.id)
            if len(item.bbox) != 4 or item.bbox[2] < item.bbox[0] or item.bbox[3] < item.bbox[1]:
                raise ValueError('Invalid workspace bounding box')
    for block in document.blocks + document.raw_blocks:
        for key in ('reading_order', 'column'):
            value = block.metadata.get(key)
            if value is not None:
                _typed(value, float, f'block metadata {key}')
        if 'article_locked' in block.metadata:
            _typed(block.metadata['article_locked'], bool, 'article_locked')
    for key in ('article_segments', 'detected_article_segments'):
        for segment in _typed(document.metadata.get(key, []), list[dict[str, Any]], key):
            for field in ('index', 'start_page', 'end_page', 'start_order', 'end_order'):
                if segment.get(field) is not None:
                    _typed(segment[field], int, f'{key}.{field}')
            for field in ('block_ids', 'title_block_ids'):
                if field in segment:
                    _typed(segment[field], list[str], f'{key}.{field}')
            if 'columns' in segment and segment['columns'] is not None:
                _typed(segment['columns'], list[int], f'{key}.columns')
    links = _typed(data.get('linked_authors', {}), dict[str, LinkedAuthors], 'linked_authors')
    return document, links
