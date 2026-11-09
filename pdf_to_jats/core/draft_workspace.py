"""Validate and stage portable draft records before any live workspace changes."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from pdf_to_jats.core.workflow_state import decode_workflow
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.core.xml_revisions import XmlRevision
from pdf_to_jats.core.xml_validation import ValidationStatus


def canonical_history(text: str, path: Path) -> str:
    return XmlDocumentSession.from_text(text, path).xml_text()


def session_from_record(record: dict[str, Any]) -> XmlDocumentSession:
    path = Path(record['path'])
    if record.get('current_revision') is not None:
        session = XmlDocumentSession(path, XmlRevision.from_record(record['current_revision']).data)
        if session.xml_text() != record['xml']:
            raise ValueError('Current XML does not match its revision snapshot')
    else:
        session = XmlDocumentSession.from_text(record['xml'], path)
    session.source_path = Path(record['source']) if record.get('source') else None
    for key, attribute in (('source_revision', 'source_bytes'), ('saved_revision', 'original_bytes')):
        if record.get(key) is not None:
            setattr(session, attribute, XmlRevision.from_record(record[key]).data)
    session.last_validated = deepcopy(record.get('last_validated'))
    session.last_export = deepcopy(record.get('last_export'))
    # Portable files can record history but never grant a fresh validation result.
    session.validation = []
    return session


def _validation_snapshot(value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError('Invalid validation provenance')
    XmlRevision.from_record(value.get('revision'))
    if value.get('well_formedness') != ValidationStatus.WELL_FORMED.value:
        raise ValueError('Invalid validated revision syntax status')
    if value.get('schema_status') not in {s.value for s in (
        ValidationStatus.SCHEMA_VALID, ValidationStatus.SCHEMA_INVALID, ValidationStatus.SCHEMA_UNAVAILABLE)}:
        raise ValueError('Invalid schema provenance status')
    profile = value.get('profile')
    if profile is not None and (not isinstance(profile, dict) or any(
        not isinstance(profile.get(key), str) for key in ('name', 'format', 'schema_path'))):
        raise ValueError('Invalid validation profile provenance')
    resources = value.get('schema_resources', [])
    if not isinstance(resources, list) or any(not isinstance(item, list) or len(item) != 2
        or not all(isinstance(part, str) for part in item) for item in resources):
        raise ValueError('Invalid schema resource provenance')
    issues = value.get('issues', [])
    if not isinstance(issues, list) or any(not isinstance(issue, dict)
        or not isinstance(issue.get('message'), str) for issue in issues):
        raise ValueError('Invalid validation issues')


def stage_workspace(value: object) -> dict[str, Any]:
    """Read version-1 workspaces, including older records without provenance."""
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Unsupported workspace version')
    data = deepcopy(value)
    articles = data.get('articles')
    active = data.get('active')
    if not isinstance(articles, dict) or (active is not None and (
        not isinstance(active, str) or active not in articles)) or (not articles and not data.get('workflow')):
        raise ValueError('Unsupported or empty article draft file')
    for key, record in articles.items():
        if not isinstance(key, str) or not isinstance(record, dict):
            raise ValueError('Invalid article draft record')
        for field in ('xml', 'path'):
            if not isinstance(record.get(field), str):
                raise ValueError(f'Invalid draft {field}')
        for field in ('source', 'pdf', 'raw', 'generated_xml', 'original_generated_xml',
                      'pending_generated', 'exported_xml', 'export_path'):
            if field in record and not isinstance(record[field], str):
                raise ValueError(f'Invalid draft {field}')
        if 'dirty' in record and type(record['dirty']) is not bool:
            raise ValueError('Invalid draft dirty flag')
        session = session_from_record(record)
        for field in ('generated_xml', 'original_generated_xml', 'pending_generated', 'exported_xml'):
            if field in record:
                canonical_history(record[field], session.path)
        history = record.get('history', [record['xml']])
        index = record.get('history_index', len(history) - 1 if isinstance(history, list) else -1)
        if not isinstance(history, list) or not history or type(index) is not int or not 0 <= index < len(history):
            raise ValueError('Invalid draft history')
        if not all(isinstance(text, str) for text in history):
            raise ValueError('Invalid draft history text')
        record['history'] = [canonical_history(text, session.path) for text in history]
        record['history_index'] = index
        if record['history'][index] != canonical_history(record['xml'], session.path):
            raise ValueError('Draft history does not match the current accepted XML')
        if record.get('last_validated') is not None:
            _validation_snapshot(record['last_validated'])
        export = record.get('last_export')
        if export is not None:
            if not isinstance(export, dict) or export.get('mode') not in {'draft', 'validated'} or not isinstance(export.get('path'), str):
                raise ValueError('Invalid export provenance')
            revision = XmlRevision.from_record(export.get('revision'))
            _validation_snapshot(export.get('validation'))
            if revision.id != export['validation']['revision']['sha256']:
                raise ValueError('Export does not match its validation snapshot')
    if data.get('workflow') is not None:
        decode_workflow(data['workflow'])
    return data
