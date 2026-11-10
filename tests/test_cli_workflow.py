"""Regression tests for A05 and headless CLI workflow.

Covers:
- `collect_pdfs` matching files, directories, and glob patterns.
- `_load_pdf_path(path, wait=True)` synchronously completing extraction without raising TypeError.
- `Converter.convert` processing single and batch PDF inputs.
- `cli.main` exit code and error handling.
"""

from __future__ import annotations

from pathlib import Path
import pytest
import fitz

from pdf_to_jats.cli import Converter, build_parser, collect_pdfs, main
from pdf_to_jats.gui.main_window import MainWindow


@pytest.fixture
def synthetic_pdf(tmp_path: Path) -> Path:
    """Create a minimal real single-page PDF with text for extraction tests."""
    pdf_path = tmp_path / "sample_paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "A Novel Study on Enzyme Catalysis", fontsize=18)
    page.insert_text((72, 130), "John Doe and Jane Smith", fontsize=11)
    page.insert_text((72, 150), "Department of Biology, University of Science", fontsize=10)
    page.insert_text((72, 180), "Abstract", fontsize=12)
    page.insert_text((72, 200), "We examined the rate constant ka and Vmax under various conditions.", fontsize=10)
    page.insert_text((72, 240), "Introduction", fontsize=12)
    page.insert_text((72, 260), "Enzymes accelerate chemical reactions significantly.", fontsize=10)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def corrupt_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"this is not a PDF")
    return path


@pytest.mark.cli
def test_collect_pdfs_expands_files_and_directories(tmp_path: Path, synthetic_pdf: Path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Hello")
    p2 = sub / "paper2.pdf"
    doc.save(str(p2))
    doc.close()

    # Collect from file and dir
    collected = collect_pdfs([synthetic_pdf, sub])
    assert len(collected) == 2
    assert synthetic_pdf.resolve() in collected
    assert p2.resolve() in collected


@pytest.mark.cli
def test_load_pdf_path_wait_parameter_completes_extraction(qapp, synthetic_pdf: Path):
    """A05 regression: _load_pdf_path accepts wait=True and extracts the document synchronously."""
    window = MainWindow()
    try:
        # Before fix, this raised TypeError: unexpected keyword argument 'wait'
        window._load_pdf_path(str(synthetic_pdf), wait=True)
        assert window.document is not None
        assert len(window.document.blocks) > 0
        assert "Enzyme Catalysis" in window.document.blocks[0].text
    finally:
        window.close()


@pytest.mark.cli
def test_cli_converter_end_to_end(qapp, tmp_path: Path, synthetic_pdf: Path):
    """Converter.convert runs the full pipeline headless and writes article XML."""
    output_dir = tmp_path / "cli_out"
    converter = Converter(output_dir=output_dir)
    try:
        written = converter.convert(synthetic_pdf, isolate=True)
        assert len(written) >= 1
        assert all(p.is_file() for p in written)
        xml_content = written[0].read_text(encoding="utf-8")
        assert "Enzyme Catalysis" in xml_content
    finally:
        converter.window.close()


@pytest.mark.cli
def test_cli_main_exit_codes(tmp_path: Path, synthetic_pdf: Path):
    """Test CLI main entrypoint success and failure return codes."""
    out_dir = tmp_path / "batch_out"

    # Success case
    code = main([str(synthetic_pdf), "-o", str(out_dir), "--flat"])
    assert code == 0
    assert len(list(out_dir.glob("*.xml"))) >= 1

    # Failure case: no matching files
    code_empty = main(["non_existent_folder_xyz/*.pdf"])
    assert code_empty == 1


@pytest.mark.cli
def test_failed_load_clears_previous_document(qapp, synthetic_pdf: Path, corrupt_pdf: Path):
    """A failed replacement load must not leave the previous article active."""
    window = MainWindow(headless=True)
    try:
        assert window._load_pdf_path(str(synthetic_pdf), wait=True) is None
        assert window.document is not None

        error = window._load_pdf_path(str(corrupt_pdf), wait=True)
        assert error
        assert window.document is None
        assert window.current_xml_path is None
        assert window._generated_xml_paths == []
    finally:
        window.close()


@pytest.mark.cli
def test_cli_corrupt_pdf_returns_nonzero_without_dialog(
    tmp_path: Path, corrupt_pdf: Path, capsys
):
    """A corrupt input is a per-file failure, not a modal or a success line."""
    out_dir = tmp_path / "corrupt_out"
    code = main([str(corrupt_pdf), "-o", str(out_dir), "--flat"])
    captured = capsys.readouterr()
    assert code == 1
    assert "[FAIL]" in captured.err
    assert "[OK]" not in captured.out
    assert not list(out_dir.glob("*.xml"))


@pytest.mark.cli
def test_batch_two_pdfs_does_not_prompt_or_reuse_document(
    qapp, tmp_path: Path, synthetic_pdf: Path
):
    """The second batch input replaces the first without a draft prompt."""
    second = tmp_path / "second_paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Second Paper on Catalysis", fontsize=18)
    page.insert_text((72, 200), "Different body text for the second article.", fontsize=10)
    doc.save(str(second))
    doc.close()

    converter = Converter(output_dir=tmp_path / "batch_prompt_out")
    try:
        first_written = converter.convert(synthetic_pdf, isolate=True)
        second_written = converter.convert(second, isolate=True)
        assert first_written and second_written
        assert first_written[0].read_text(encoding="utf-8") != second_written[0].read_text(
            encoding="utf-8"
        )
        assert converter.window.document is not None
        assert converter.window.document.metadata["source_pdf"].endswith("second_paper.pdf")
    finally:
        converter.window.close()


@pytest.mark.cli
def test_converter_rejects_zero_output(qapp, tmp_path: Path, synthetic_pdf: Path, monkeypatch):
    """A pipeline that writes nothing is a conversion failure, not success."""
    converter = Converter(output_dir=tmp_path / "zero_out")
    try:
        monkeypatch.setattr(converter.window, "_documents_to_export", lambda _document: [])
        with pytest.raises(RuntimeError, match="No XML was produced"):
            converter.convert(synthetic_pdf, isolate=True)
    finally:
        converter.window.close()
