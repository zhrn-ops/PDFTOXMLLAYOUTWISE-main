"""Bounded local readers. No DTD/entity resolution, network, or path escape."""
import hashlib
import json
from pathlib import Path
from lxml import etree

MAX_BYTES = 32 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def local_path(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ":" in name:
        raise ValueError("Paths must be relative local paths")
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path escapes the input directory")
    return path


def read_bytes(path, limit=MAX_BYTES):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input exceeds the size limit")
    return data


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(read_bytes(path), object_pairs_hook=_unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON number")))


def read_artifact(root, record):
    data = read_bytes(local_path(root, record["path"]), limit=256 * 1024 * 1024)
    if sha256(data) != record["sha256"]:
        raise ValueError(f"Hash mismatch: {record['path']}")
    return data


def parse_xml(data):
    if len(data) > MAX_BYTES:
        raise ValueError("XML exceeds size limit")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                             recover=False, huge_tree=False, remove_blank_text=False)
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype or any(isinstance(n, etree._Entity) for n in root.iter()):
        raise ValueError("DTD/entity declarations are not accepted by the evaluator")
    return root
