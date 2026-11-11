"""ANI semantics established by the repository's generator, not a publisher schema."""
from .base import ANI, CE, build, local, namespace, plain


def adapt(root):
    if namespace(root) != ANI or local(root) not in {"units", "unit"}:
        raise ValueError("Expected an ANI units/unit root")
    units = [n for n in root.iter() if namespace(n) == ANI and local(n) == "unit"]
    if len(units) > 1:
        raise ValueError("Select one ANI unit per article")
    authors, affiliations, edges, consumed, warnings = {}, {}, set(), [], []
    for group in root.iter():
        if namespace(group) != ANI or local(group) != "author-group":
            continue
        group_authors, group_affs = [], []
        for node in group:
            if namespace(node) != ANI:
                continue
            if local(node) == "author":
                parts = {local(c): plain(c) for c in node if namespace(c) == CE}
                name = " ".join(filter(None, (parts.get("given-name") or parts.get("initials"), parts.get("surname"))))
                key = node.get("seq") or root.getroottree().getpath(node)
                if key in authors and authors[key] != name:
                    raise ValueError("Conflicting repeated ANI author sequence")
                authors[key] = name
                group_authors.append(key)
                consumed.append(node)
            elif local(node) == "affiliation":
                # Group-local affiliations are distinct until semantic matching.
                key = root.getroottree().getpath(node)
                source = next((c for c in node if namespace(c) == CE and local(c) == "source-text"), None)
                affiliations[key] = plain(source) if source is not None else " ".join(plain(c) for c in node)
                group_affs.append(key)
                consumed.append(node)
        edges.update((a, f) for a in group_authors for f in group_affs)
    roles = {"titletext": "title", "abstract": "abstract", "para": "paragraph",
             "author-keyword": "keyword", "reference": "reference"}
    return build(root, "ANI", roles, authors, affiliations, edges, consumed, warnings)
