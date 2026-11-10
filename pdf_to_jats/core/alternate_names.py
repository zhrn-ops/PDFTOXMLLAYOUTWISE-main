"""Whole captured names and explicit, user-selected author assignments."""

import unicodedata

from pdf_to_jats.models.author import AuthorName


def name_key(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


def is_native_name_block(block) -> bool:
    """Only wholly non-Latin author captures are alternate-name candidates."""
    letters = [char for char in block.text if char.isalpha()]
    return (block.role == 'author' and bool(letters)
            and not any('LATIN' in unicodedata.name(char, '') for char in letters))


def is_alternate_capture(block) -> bool:
    return is_native_name_block(block) and not block.metadata.get('keep_main_author', False)


def assigned_names(author, authors, blocks) -> list[AuthorName]:
    """Resolve only an exact, unique name selected by the user; never guess."""
    key = name_key(author.display_name)
    if not key or sum(name_key(item.display_name) == key for item in authors) != 1:
        return []
    return [AuthorName(text=block.text.strip()) for block in blocks
            if is_alternate_capture(block)
            and name_key(str(block.metadata.get('alternate_name_target', ''))) == key]


def apply_assignments(authors, blocks) -> None:
    for author in authors:
        seen = {name_key(name.text) for name in author.alternate_names}
        for name in assigned_names(author, authors, blocks):
            if name_key(name.text) not in seen:
                author.alternate_names.append(name)
                seen.add(name_key(name.text))
