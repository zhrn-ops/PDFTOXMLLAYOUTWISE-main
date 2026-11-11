"""Geometry tests for inline superscript and subscript detection.

The detector works on PyMuPDF span geometry, so these tests build spans by
hand: ``size`` is the glyph size, ``dy`` the shift of the baseline (negative is
lower), and ``flags`` bit 1 marks a superscript span.
"""

from __future__ import annotations

import fitz
import pytest

from pdf_to_jats.core.inline_script_detector import InlineScriptDetector
from pdf_to_jats.core.pdf_extractor import PDFExtractor


def _spans(spec, baseline: float = 100.0) -> list[dict]:
    return [
        {
            "text": text,
            "size": size,
            "flags": flags,
            "bbox": [0.0, baseline - dy - size, 10.0 * len(text), baseline - dy],
            "origin": [0.0, baseline - dy],
        }
        for text, size, dy, flags in spec
    ]


def _detect(spec) -> list[tuple[str, str, str]]:
    text = "".join(item[0] for item in spec)
    runs = InlineScriptDetector().detect(text, _spans(spec))
    return [(run["type"], run["text"], run["source"]) for run in runs]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("1,2", "1,2"),
        ("a,b", "a,b"),
        ("1\u20133", "1\u20133"),
        ("*", "*"),
        ("\u2020", "\u2020"),
        ("1a", "1a"),
    ],
)
def test_raised_affiliation_labels_are_superscripts(label: str, expected: str):
    assert _detect([("Mice were fed", 10.0, 0.0, 4), (label, 6.0, 4.0, 0)]) == [
        ("sup", expected, "geometry")
    ]


def test_slightly_smaller_raised_label_is_superscript():
    """A 9.2pt label on a 10pt line used to fall outside the 12% size cut-off."""
    assert _detect([("Table", 10.0, 0.0, 4), ("a", 9.2, 4.0, 0)]) == [
        ("sup", "a", "geometry")
    ]


def test_slightly_smaller_lowered_label_is_subscript():
    assert _detect([("H", 10.0, 0.0, 4), ("2", 9.2, -3.5, 0)]) == [
        ("sub", "2", "geometry")
    ]


def test_slightly_smaller_label_with_small_offset_is_not_a_script():
    """Near-body sizes need a decisive shift; 1.5pt is normal baseline noise."""
    assert _detect([("Table", 10.0, 0.0, 4), ("a", 9.2, 1.5, 0)]) == []


def test_mixed_size_text_on_one_baseline_is_left_alone():
    assert _detect([("Body", 10.0, 0.0, 4), ("text", 9.3, 0.0, 0)]) == []


def test_unstyled_value_ranges_stay_plain_text():
    assert _detect([("from 10-3 to 10-5", 10.0, 0.0, 4)]) == []


def test_protected_units_need_a_strong_shift():
    weak = [("kUA/", 10.0, 0.0, 4), ("L", 8.0, 2.2, 0)]
    assert _detect(weak) == []

    strong = [("kUA/", 10.0, 0.0, 4), ("L", 8.0, 3.2, 0)]
    assert _detect(strong) == [("sup", "L", "geometry")]


def test_font_flag_still_wins_over_geometry():
    assert _detect([("mc", 10.0, 0.0, 4), ("2", 9.8, -2.0, 1)]) == [
        ("sup", "2", "font_flag")
    ]


def test_extraction_leaves_body_lines_unscripted(tmp_path):
    """Only title and abstract are scripted, so extraction must not tag body text."""
    path = tmp_path / "body.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text(
            (72, 100),
            "Inhibition by SO42- and Ca2+ was monitored at 10-3 mol/L.",
            fontsize=10,
        )
        pdf.save(path)

    blocks = PDFExtractor(use_docling=False).extract(path).blocks

    assert [block.inline_runs for block in blocks] == [[]]
    # Span geometry survives for the later title/abstract projection.
    assert blocks[0].metadata["text_spans"]


def test_soft_hyphen_after_formula_is_not_a_charge():
    """A line-broken formula ("TiO2-enriched") must not gain a superscript hyphen."""
    text = "fg-\u00adTiO2-\u00adenriched diet at a human relevant level"
    spans = _spans([(text, 9.5, 0.0, 4)])
    assert [(r["type"], r["text"]) for r in InlineScriptDetector().detect(text, spans)] == [
        ("sub", "2")
    ]
