"""Stable English-first ordering for ANI citation titles."""


def non_english_title(language):
    code = (language or '').strip().upper()
    return bool(code and code not in {'ENG', 'EN', 'UND'} and not code.startswith('EN-'))


def remove_title_scripts(node):
    """Unwrap scripts without losing text, tails, or other inline formatting."""
    changed = False
    for child in list(node):
        changed = remove_title_scripts(child) or changed
        if not isinstance(child.tag, str) or child.tag.rsplit('}', 1)[-1] not in {'sup', 'sub', 'inf'}:
            continue
        index = list(node).index(child)
        if index:
            previous = node[index - 1]
            previous.tail = (previous.tail or '') + (child.text or '')
        else:
            node.text = (node.text or '') + (child.text or '')
        nested = list(child)
        tail = child.tail or ''
        node.remove(child)
        for offset, descendant in enumerate(nested):
            child.remove(descendant)
            node.insert(index + offset, descendant)
        end = index + len(nested)
        if end:
            previous = node[end - 1]
            previous.tail = (previous.tail or '') + tail
        else:
            node.text = (node.text or '') + tail
        changed = True
    return changed


def english_titles_first(root):
    for container in root.iter():
        if not isinstance(container.tag, str) or container.tag.rsplit('}', 1)[-1] != 'citation-title':
            continue
        children = list(container)
        positions = [i for i, child in enumerate(children)
                     if isinstance(child.tag, str) and child.tag.rsplit('}', 1)[-1] == 'titletext']
        titles = [children[i] for i in positions]
        for title in titles:
            if non_english_title(title.get('{http://www.w3.org/XML/1998/namespace}lang')):
                remove_title_scripts(title)
        titles.sort(key=lambda node: (node.get('{http://www.w3.org/XML/1998/namespace}lang') or '').strip().upper() != 'ENG')
        for index, title in zip(positions, titles):
            children[index] = title
        container[:] = children
