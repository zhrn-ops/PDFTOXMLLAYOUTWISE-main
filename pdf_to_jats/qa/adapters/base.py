"""Shared mixed-content handling; XML locations remain attached to all units."""
from lxml import etree
from ..models import Document, Unit

ANI = "http://www.elsevier.com/xml/ani/ani"
CE = "http://www.elsevier.com/xml/ani/common"
MATH = "http://www.w3.org/1998/Math/MathML"
JATS = {None, "http://jats.nlm.nih.gov"}


def local(node):
    return etree.QName(node).localname if isinstance(node.tag, str) else ""


def namespace(node):
    return etree.QName(node).namespace if isinstance(node.tag, str) else None


def plain(node):
    return " ".join("".join(node.itertext()).split())


def extract(node, family):
    pieces, scripts, math = [], [], []
    offset = 0

    def append(text):
        nonlocal offset
        if text:
            pieces.append(text)
            offset += len(text)

    def walk(element):
        start = offset
        append(element.text)
        for child in element:
            if isinstance(child.tag, str):
                walk(child)
            append(child.tail)
        tag, ns = local(element), namespace(element)
        if (family == "JATS" and ns in JATS or family == "ANI" and ns == CE):
            if tag in {"sup", "sub", "inf"}:
                scripts.append((start, offset, "sup" if tag == "sup" else "sub"))
        if ns == MATH and tag == "math" or tag in {"inline-formula", "disp-formula"} and ns in JATS:
            math.append((start, offset))
    walk(node)
    return "".join(pieces), scripts, math


def build(root, family, roles, authors, affiliations, edges, metadata_nodes, warnings):
    tree = root.getroottree()
    units, consumed = [], set()
    allowed = JATS if family == "JATS" else {ANI, CE}
    candidates = [n for n in root.iter() if namespace(n) in allowed and local(n) in roles]
    # Keep deepest logical blocks; use abstract/caption/title containers only when
    # they have no separately mapped descendants. Nested inline scripts stay inline.
    selected = [n for n in candidates if not any(c is not n and c in candidates for c in n.iter())]
    for node in selected:
        role = roles[local(node)]
        ancestors = list(node.iterancestors())
        if role == "paragraph":
            if any(local(a) in {"abstract", "trans-abstract", "abstracts"} for a in ancestors):
                role = "abstract"
            elif any(local(a) == "caption" for a in ancestors):
                role = "caption"
            else:
                role = "body"
        text, scripts, math = extract(node, family)
        section = tuple(next((plain(c) for c in a if local(c) == "title" and namespace(c) in allowed), a.get("id", ""))
                        for a in reversed(ancestors) if local(a) == "sec" and namespace(a) in allowed)
        units.append(Unit(tree.getpath(node), role, text, scripts, math, section))
        consumed.update(node.iter())
    for node in metadata_nodes:
        consumed.update(node.iter())
    unsupported = []
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        # Text slots, rather than recursive itertext, prevent duplicate counting.
        if node not in consumed and node.text and node.text.strip():
            unsupported.append({"path": tree.getpath(node), "text": node.text})
        if node.getparent() not in consumed and node.tail and node.tail.strip():
            unsupported.append({"path": tree.getpath(node) + "/tail()", "text": node.tail})
    return Document(family, units, authors, affiliations, edges, unsupported, root, warnings)
