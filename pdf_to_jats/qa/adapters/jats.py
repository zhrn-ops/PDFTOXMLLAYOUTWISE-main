"""Supported JATS content and explicit contributor-to-affiliation references."""
from .base import JATS, build, local, namespace, plain


def adapt(root):
    if local(root) != "article" or namespace(root) not in JATS:
        raise ValueError("Expected a supported JATS article root")
    nodes = [n for n in root.iter() if namespace(n) in JATS]
    authors, affiliations, edges, consumed, warnings = {}, {}, set(), [], []
    for n in nodes:
        if local(n) == "aff":
            key = n.get("id") or root.getroottree().getpath(n)
            if key in affiliations:
                raise ValueError("Duplicate affiliation ID")
            # Printed affiliation markers identify links; they are not institution names.
            fragments = [n.text or ""]
            for child in n:
                if local(child) != "label" or namespace(child) not in JATS:
                    fragments.append("".join(child.itertext()))
                fragments.append(child.tail or "")
            affiliations[key] = " ".join("".join(fragments).split())
            consumed.append(n)
    for n in nodes:
        if local(n) != "contrib" or n.get("contrib-type", "author") != "author":
            continue
        key = n.get("id") or root.getroottree().getpath(n)
        if key in authors:
            raise ValueError("Duplicate author ID")
        names = [c for c in n if local(c) in {"name", "string-name", "collab"} and namespace(c) in JATS]
        if names and local(names[0]) == "name":
            parts = {local(c): plain(c) for c in names[0]}
            name = " ".join(filter(None, (parts.get("given-names"), parts.get("surname"))))
        else:
            name = plain(names[0]) if names else ""
        authors[key] = name
        consumed.append(n)
        for x in n.iter():
            if local(x) == "aff" and namespace(x) in JATS:
                edges.add((key, x.get("id") or root.getroottree().getpath(x)))
            if local(x) == "xref" and namespace(x) in JATS and x.get("ref-type") == "aff":
                for target in x.get("rid", "").split():
                    edges.add((key, target))
                    if target not in affiliations:
                        warnings.append(f"Unresolved affiliation reference: {target}")
    roles = {"article-title": "title", "trans-title": "title", "abstract": "abstract",
             "trans-abstract": "abstract", "title": "section", "p": "paragraph",
             "kwd": "keyword", "caption": "caption", "ref": "reference",
             "disp-formula": "formula"}
    return build(root, "JATS", roles, authors, affiliations, edges, consumed, warnings)
