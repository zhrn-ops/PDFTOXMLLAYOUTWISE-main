"""Reproducible performance measurements for docs/audit/04_performance_report.md.

Run from the project root:
    python .bench/audit_bench.py
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.core.pdf_extractor import PDFExtractor
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.core.xml_validation import validate_xml
from pdf_to_jats.models.affiliation import Affiliation
from pdf_to_jats.models.author import Author
from pdf_to_jats.models.document import Document
from pdf_to_jats.models.paragraph import Paragraph

PDF = Path(".bench/big.pdf")


def median_seconds(fn, repeat: int) -> tuple[float, object]:
    timings: list[float] = []
    result = None
    for _ in range(repeat):
        started = time.perf_counter()
        result = fn()
        timings.append(time.perf_counter() - started)
    return statistics.median(timings), result


def peak_mb(fn) -> tuple[float, object]:
    tracemalloc.start()
    result = fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / (1024 * 1024), result


def build_document(paragraphs: int = 400) -> Document:
    authors = [
        Author(
            id=f"a{i}",
            display_name=f"Author {i}",
            given_names=f"Author {i}",
            surname=f"Family{i}",
            initials=f"A{i}.",
            affiliation_ids=[f"aff{i % 12}"],
        )
        for i in range(40)
    ]
    affiliations = [
        Affiliation(id=f"aff{i}", text=f"Department {i}, University {i}, City {i}, Germany")
        for i in range(12)
    ]
    body = ("Steady-state kinetics were measured at 25 C with H2O and TiO2. " * 6).strip()
    return Document(
        title="Kinetic Analysis of Ca2+-ATPase and H2O Transport at Vmax",
        abstract="Inhibition by TiO2 and SO42- was monitored. The constant ka reached 10-3 s-1.",
        authors=authors,
        corresponding_author=authors[0],
        affiliations=affiliations,
        paragraphs=[
            Paragraph(
                id=f"p{i}",
                page=1 + i // 20,
                column=i % 2,
                status="accepted",
                role="body",
                text=body,
                bbox=[0.0, 0.0, 500.0, 14.0],
            )
            for i in range(paragraphs)
        ],
        metadata={
            "unit_id": "00000001",
            "order_id": "ORD001",
            "parcel_id": "PARCEL1",
            "supplier_id": "4",
            "abstract_number": "P-101",
        },
    )


def main() -> None:
    print(f"PDF: {PDF} ({PDF.stat().st_size / 1024:.0f} KB)")
    document = build_document()
    generator = JATSGenerator()

    open_ms, pdf = median_seconds(lambda: fitz.open(PDF), 5)
    try:
        print(f"pdf_open_ms={open_ms * 1000:.2f}")
        print(f"pdf_pages={pdf.page_count}")
        text_ms, _ = median_seconds(lambda: sum(len(page.get_text()) for page in pdf), 3)
        print(f"pdf_text_extract_all_pages_ms={text_ms * 1000:.2f}")
        raster_ms, _ = median_seconds(
            lambda: [page.get_pixmap(matrix=fitz.Matrix(3, 3)) for page in list(pdf)[:5]], 3
        )
        print(f"pdf_raster_5_pages_3x_ms={raster_ms * 1000:.2f}")
    finally:
        pdf.close()

    for visible in (False, True):
        extract_seconds, extracted = median_seconds(
            lambda v=visible: PDFExtractor(use_docling=False, visible_text_only=v).extract(PDF),
            2,
        )
        print(f"extract_visible_only_{visible}_s={extract_seconds:.3f} blocks={len(extracted.blocks)}")
        peak, _ = peak_mb(
            lambda v=visible: PDFExtractor(use_docling=False, visible_text_only=v).extract(PDF)
        )
        print(f"extract_visible_only_{visible}_peak_mb={peak:.1f}")

    gen_seconds, data = median_seconds(lambda: generator.to_bytes(document), 5)
    print(f"xml_generate_ms={gen_seconds * 1000:.2f} bytes={len(data)}")
    from pdf_to_jats.models.document import Document as _Document

    assert isinstance(document, _Document)

    validate_seconds, result = median_seconds(lambda: validate_xml(data, None), 5)
    print(f"xml_validate_ms={validate_seconds * 1000:.2f} status={result.schema_status.value}")

    text = data.decode("utf-8")
    session_seconds, session = median_seconds(
        lambda: XmlDocumentSession.from_text(text, Path("bench.xml")), 5
    )
    print(f"session_parse_ms={session_seconds * 1000:.2f}")
    serialize_seconds, _ = median_seconds(lambda: session.xml_bytes(), 5)
    print(f"session_serialize_ms={serialize_seconds * 1000:.2f}")

    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / "out.xml"
        write_seconds, _ = median_seconds(lambda: generator.generate(document, target), 5)
        print(f"xml_atomic_write_ms={write_seconds * 1000:.2f}")

    gen_peak, _ = peak_mb(lambda: generator.to_bytes(document))
    print(f"xml_generate_peak_mb={gen_peak:.1f}")


if __name__ == "__main__":
    main()
