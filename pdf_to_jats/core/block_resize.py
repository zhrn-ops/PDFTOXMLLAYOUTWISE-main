"""Partition reviewed text at word boundaries using actual PDF character positions."""

from copy import deepcopy
from dataclasses import replace
from difflib import SequenceMatcher
import re
import uuid

import fitz

from pdf_to_jats.core.inline_script_detector import shift_trimmed_runs


def split_resized_block(block, bbox, pdf_path):
    """Return (fragments, selected_id), or None when no safe split is possible.

    Never infer character positions from font widths. Every nonspace character
    must match the PDF before any text can be partitioned.
    """
    with fitz.open(pdf_path) as pdf:
        page = pdf[block.page - 1]
        raw = page.get_text("rawdict")
    original = fitz.Rect(block.bbox)
    chars = []
    for entry in raw["blocks"]:
        for line in entry.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    rect = fitz.Rect(char["bbox"])
                    if original.contains((rect.tl + rect.br) / 2):
                        chars.append((char["c"], list(rect)))
    # Whitespace differs between PDF lines and manually merged paragraphs.
    source = [(c, box) for c, box in chars if not c.isspace()]
    target = [(i, c) for i, c in enumerate(block.text) if not c.isspace()]
    mapping = {}
    matcher = SequenceMatcher(None, "".join(c for c, _ in source),
                              "".join(c for _, c in target), autojunk=False)
    for match in matcher.get_matching_blocks():
        for offset in range(match.size):
            mapping[target[match.b + offset][0]] = source[match.a + offset][1]
    if len(mapping) != len(target) or not target:
        return None
    selected = fitz.Rect(bbox)
    words = list(re.finditer(r"\S+", block.text))
    groups = []
    for word in words:
        boxes = [mapping[i] for i in range(word.start(), word.end())]
        rect = fitz.Rect(boxes[0])
        for box in boxes[1:]:
            rect |= fitz.Rect(box)
        inside = selected.contains((rect.tl + rect.br) / 2)
        if groups and groups[-1][2] == inside:
            groups[-1][1] = word.end()
            groups[-1][3] |= rect
        else:
            groups.append([word.start(), word.end(), inside, rect])
    if len(groups) < 2 or not any(group[2] for group in groups):
        return None
    fragments = []
    selected_id = None
    for index, (start, end, inside, rect) in enumerate(groups):
        # Assign intervening whitespace once, retaining the original text exactly.
        start = 0 if index == 0 else groups[index - 1][1]
        if index == len(groups) - 1:
            end = len(block.text)
        fragment_id = block.id if index == 0 else f"{block.id}_split_{uuid.uuid4().hex[:12]}"
        metadata = deepcopy(block.metadata)
        metadata["resize_split_from"] = block.id
        metadata["source_line_ids"] = [fragment_id]
        metadata.pop("text_spans", None)
        metadata.pop("merged_block_ids", None)
        metadata.pop("merged_regions", None)
        # Fractional positions retain the parent's integer article bounds and
        # the text order, including a second split of an existing fragment.
        if metadata.get("reading_order") is not None:
            step = float(metadata.get("resize_order_step", 1.0)) / len(groups)
            metadata["reading_order"] = float(metadata["reading_order"]) + index * step
            metadata["resize_order_step"] = step
        fragment_bbox = list(rect)
        if inside and selected_id is None:
            selected_id = fragment_id
        fragments.append(replace(
            block, id=fragment_id, text=block.text[start:end], bbox=fragment_bbox,
            x=rect.x0, y=rect.y0, width=rect.width, height=rect.height,
            role=block.role if inside else "unclassified", metadata=metadata,
            inline_runs=shift_trimmed_runs(block.text, block.inline_runs, start, end, 0),
        ))
    return fragments, selected_id
