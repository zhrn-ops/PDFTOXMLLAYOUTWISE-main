"""Recover explicit author/affiliation pairs without splitting internal commas."""
from dataclasses import dataclass
import re

from pdf_to_jats.core.author_linker import AuthorLinker, LinkedAuthors
from pdf_to_jats.models.affiliation import Affiliation


@dataclass
class AuthorAffiliationRecord:
    entry_id: str
    author_text: str
    affiliation_text: str
    source_block_ids: list[str]
    source_text: str


def split_parenthesized_authors(blocks):
    """Return records, or None for a non-parenthesized/numbered byline.

    Once an inline-affiliation pattern is detected, malformed or mixed entries
    are rejected rather than silently losing part of the source.
    """
    text = '\n'.join(str(block.get('text', '')) for block in blocks)
    opening = text.find('(')
    if opening < 0:
        return None
    first_content = text[opening + 1:].split(')', 1)[0]
    if len(re.findall(r'[^\W\d_]', first_content, re.UNICODE)) < 4:
        return None  # Numeric markers and short credentials use the old path.
    ranges, offset = [], 0
    for block in blocks:
        end = offset + len(str(block.get('text', '')))
        ranges.append((offset, end, str(block.get('block_id', ''))))
        offset = end + 1
    records = []
    start = 0
    while start < len(text):
        while start < len(text) and (text[start].isspace() or text[start] in ',;|'):
            start += 1
        if start == len(text):
            break
        opening = text.find('(', start)
        if opening < 0 or ')' in text[start:opening] or '|' in text[start:opening]:
            raise ValueError(f'Incomplete parenthesized author entry: {text[start:start + 100]!r}')
        depth, end = 1, opening + 1
        while end < len(text) and depth:
            depth += (text[end] == '(') - (text[end] == ')')
            end += 1
        if depth:
            raise ValueError(f'Unmatched parentheses for author {text[start:opening].strip()!r}; correct the source selection')
        name = ' '.join(text[start:opening].split()).strip(' ,;')
        affiliation = ' '.join(text[opening + 1:end - 1].split())
        if not name or not affiliation:
            raise ValueError('Each parenthesized entry needs an author and an affiliation')
        records.append(AuthorAffiliationRecord(
            f'entry_{len(records) + 1}', name, affiliation,
            [block_id for left, right, block_id in ranges if left < end and right > start and block_id],
            text[start:end]))
        start = end
    return records


def split_affiliation_entries(text):
    """Split pipes or semicolons inside an extracted parenthesized affiliation.

    Preserve separators within nested parenthetical descriptions.
    """
    parts, start, depth = [], 0, 0
    for index, character in enumerate(text):
        if character == '(':
            depth += 1
        elif character == ')':
            depth -= 1
        elif character in '|;' and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    if not all(parts):
        raise ValueError('Empty affiliation between pipe or semicolon separators; correct the source selection')
    return parts


def link_parenthesized_records(records):
    linker = AuthorLinker()
    authors, affiliations, by_text = [], [], {}
    for record in records:
        parsed = linker.link_from_texts([record.author_text], []).authors
        if len(parsed) != 1:
            raise ValueError(f'Expected one author before parentheses: {record.author_text!r}')
        author = parsed[0]
        author.id = record.entry_id
        author.affiliation_ids = []
        for text in split_affiliation_entries(record.affiliation_text):
            key = ' '.join(text.split()).casefold()
            affiliation = by_text.get(key)
            if affiliation is None:
                affiliation = Affiliation(id=f'aff_{len(affiliations) + 1}', text=text)
                affiliations.append(affiliation)
                by_text[key] = affiliation
            if affiliation.id not in author.affiliation_ids:
                author.affiliation_ids.append(affiliation.id)
        authors.append(author)
    return LinkedAuthors(authors=authors, affiliations=affiliations)
