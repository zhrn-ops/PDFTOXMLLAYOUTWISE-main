"""Read-only adapter dispatch with explicit format declarations."""
from ..readers import parse_xml
from . import jats, ani


def adapt(data, family, selector=None):
    root = parse_xml(data)
    if selector:
        found = root.xpath(selector, namespaces={"ani": ani.ANI})
        if len(found) != 1 or not hasattr(found[0], "tag"):
            raise ValueError("Article selector must identify exactly one element")
        root = found[0]
    if family == "JATS":
        return jats.adapt(root)
    if family == "ANI":
        return ani.adapt(root)
    raise ValueError("Unsupported XML family")
