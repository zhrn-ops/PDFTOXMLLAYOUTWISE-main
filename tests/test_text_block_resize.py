"""Text block geometry editing must preserve content and undo a whole gesture."""

from copy import deepcopy
from dataclasses import asdict

import pytest
import fitz
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QMessageBox

from pdf_to_jats.gui.main_window import MainWindow
from pdf_to_jats.gui.pdf_viewer import PdfPageLabel
from pdf_to_jats.models.block import TextBlock
from pdf_to_jats.models.document import Document
from pdf_to_jats.utils.config import AppConfig
from pdf_to_jats.core.pdf_extractor import PDFExtractor
from pdf_to_jats.core.block_resize import split_resized_block


@pytest.fixture
def resize_window(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "pdf_to_jats.gui.main_window.load_config",
        lambda: AppConfig(output_dir=tmp_path, generated_xml_dir=tmp_path,
                          openrouter_settings_path=tmp_path / "settings.json"),
    )
    window = MainWindow()
    block = TextBlock(
        id="block_1", page=1, text="Original text", role="abstract",
        bbox=[20, 20, 100, 60], x=20, y=20, width=80, height=40,
        metadata={"visible_area": [0, 0, 300, 400], "reading_order": 0},
        inline_runs=[{"start": 0, "end": 1, "kind": "sup"}],
    )
    window.document = Document(blocks=[block], raw_blocks=[deepcopy(block)])
    window.viewer.set_blocks([asdict(block)])
    yield window, block
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Discard)
    window.close()


def test_signal_updates_geometry_and_undo_restores_one_gesture(resize_window):
    window, block = resize_window
    original = asdict(block)
    window.viewer.label.blockMoved.emit(block.id, [20, 20, 120, 80])
    window.viewer.label.blockMoved.emit(block.id, [20, 20, 150, 90])
    window.viewer.label.blockEditFinished.emit(block.id)
    assert block.bbox == [20, 20, 150, 90]
    assert (block.x, block.y, block.width, block.height) == (20, 20, 130, 70)
    assert len(window._undo_stack) == 1
    for field in ("text", "role", "metadata", "inline_runs"):
        assert asdict(block)[field] == original[field]
    assert asdict(window.document.raw_blocks[0]) == original
    assert window.document.zones == []
    window.undo_last_action()
    assert asdict(block) == original
    assert window.viewer._blocks_by_id[block.id]["bbox"] == original["bbox"]


def test_bounds_invalid_geometry_and_locked_blocks(resize_window):
    window, block = resize_window
    for bbox in ([20, 20, 21, 21], [20, 20, float("nan"), 80]):
        window.viewer.label.blockMoved.emit(block.id, bbox)
    assert not window._undo_stack
    window.viewer.label.blockMoved.emit(block.id, [-10, -10, 350, 450])
    window.viewer.label.blockEditFinished.emit(block.id)
    assert block.bbox == [0, 0, 300, 400]
    block.metadata["article_locked"] = True
    window.viewer.set_blocks([asdict(block)])
    assert not window.viewer._block_is_adjustable(block.id)
    assert not window.viewer.label._block_is_adjustable(block.id)
    window.viewer.label.blockMoved.emit(block.id, [20, 20, 150, 90])
    assert block.bbox == [0, 0, 300, 400]
    assert len(window._undo_stack) == 1


def test_later_page_edits_are_relayed_and_each_gesture_has_undo(resize_window):
    window, block = resize_window
    block.page = 2
    label = PdfPageLabel()
    window.viewer._forward_page_signals(label, 1)
    for bbox in ([20, 20, 130, 80], [30, 30, 140, 90]):
        label.blockMoved.emit(block.id, bbox)
        label.blockEditFinished.emit(block.id)
    assert block.bbox == [30, 30, 140, 90]
    assert len(window._undo_stack) == 2
    window.undo_last_action()
    assert block.bbox == [20, 20, 130, 80]
    window.undo_last_action()
    assert block.bbox == [20, 20, 100, 60]
    label.close()


@pytest.mark.parametrize("modifiers", [Qt.ControlModifier, Qt.ControlModifier | Qt.ShiftModifier])
def test_adjusted_blocks_can_be_selected_under_handles_and_merged(resize_window, modifiers):
    window, first = resize_window
    second = deepcopy(first)
    second.id = "block_2"
    second.text = "Second text"
    second.bbox = [20, 82, 130, 110]
    second.x, second.y, second.width, second.height = 20, 82, 110, 28
    second.metadata["reading_order"] = 1
    window.document.blocks.append(second)
    window._on_viewer_block_moved(first.id, [20, 20, 130, 80])
    window._on_viewer_block_edit_finished(first.id)
    window._on_viewer_block_selected(first.id, False)
    label = window.viewer.label
    label.resize(600, 800)
    label.setProperty("blockRegions", [
        {"id": first.id, "kind": "block", "rect": first.bbox},
        {"id": second.id, "kind": "block", "rect": second.bbox},
        {"id": f"{first.id}:top_left", "kind": "block_handle", "rect": [8, 8, 32, 32]},
        {"id": f"{first.id}:bottom_right", "kind": "block_handle", "rect": [118, 68, 142, 92]},
        {"id": "zone_overlay", "kind": "zone", "rect": [0, 0, 160, 130]},
        {"id": "zone_overlay:bottom_right", "kind": "handle", "rect": [118, 68, 142, 92]},
    ])
    window._selected_zone_id = "zone_overlay"
    window._selected_zone_ids = {"zone_overlay"}
    window.viewer.set_selected_zones({"zone_overlay"}, "zone_overlay")
    QTest.mouseClick(label, Qt.LeftButton, modifiers, QPoint(125, 85))
    assert window._selected_block_ids == {first.id, second.id}
    assert not window._selected_zone_ids
    assert label._block_drag_id is None
    window.merge_selected_blocks()
    assert len(window.document.blocks) == 1
    merged = window.document.blocks[0]
    assert merged.text == "Original text\r\nSecond text"
    assert merged.bbox == [20, 20, 130, 110]
    assert window.viewer._block_is_adjustable(merged.id)


def test_plain_click_selects_text_instead_of_selected_zone_handle(resize_window):
    window, block = resize_window
    label = window.viewer.label
    label.resize(600, 800)
    window._selected_zone_ids = {"zone_overlay"}
    window._selected_zone_id = "zone_overlay"
    window.viewer.set_selected_zones({"zone_overlay"}, "zone_overlay")
    label.setProperty("blockRegions", [
        {"id": block.id, "kind": "block", "rect": block.bbox},
        {"id": "zone_overlay", "kind": "zone", "rect": block.bbox},
        {"id": "zone_overlay:top_left", "kind": "handle", "rect": [8, 8, 32, 32]},
    ])
    QTest.mouseClick(label, Qt.LeftButton, pos=QPoint(25, 25))
    assert window._selected_block_ids == {block.id}
    assert not window._selected_zone_ids
    assert label._zone_drag_id is None


def test_converter_renders_only_text_boxes_even_after_zone_refresh(resize_window):
    window, block = resize_window
    viewer = window.viewer
    zone = {"id": "zone_auto_1", "page": 1, "bbox": [15, 15, 110, 70],
            "label": "title", "source": "auto"}
    viewer.set_document_overlays([asdict(block)], [zone])
    viewer.set_zones([dict(zone, source="user")])
    viewer.set_selected_zones({zone["id"]}, zone["id"])
    viewer.set_selected_blocks({block.id}, block.id)
    viewer._page_count = 1
    try:
        canvas = QPixmap(600, 800)
        canvas.fill(Qt.white)
        viewer._paint_overlays(canvas, viewer.label, 0)
        assert viewer._zones_by_page == {}
        assert viewer.label.property("zones") == []
        assert viewer._selected_zone_ids == set()
        assert {region["kind"] for region in viewer._regions} == {"block", "block_handle"}
        assert len([r for r in viewer._regions if r["kind"] == "block_handle"]) == 4
    finally:
        viewer._page_count = 0


def test_shrink_creates_leftovers_preserves_all_text_and_undo(resize_window, tmp_path):
    window, _ = resize_window
    path = tmp_path / "title-authors.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 80), "P-123 Optical Spectroscopy J. Smith, M. Jones")
        title_rect = page.search_for("Optical Spectroscopy")[0]
        pdf.save(path)
    document = PDFExtractor(use_docling=False).extract(path)
    assert len(document.blocks) == 1
    window.document = document
    original = deepcopy(document.blocks[0])
    original.role = document.blocks[0].role = "title"
    window.viewer.set_blocks([asdict(original)])
    window._on_viewer_block_moved(original.id, list(title_rect))
    window._on_viewer_block_edit_finished(original.id)
    assert len(document.blocks) == 3
    assert "".join(b.text for b in document.blocks) == original.text
    assert [b.text.strip() for b in document.blocks] == ["P-123", "Optical Spectroscopy", "J. Smith, M. Jones"]
    assert [b.role for b in document.blocks] == ["unclassified", "title", "unclassified"]
    assert window._selected_block_ids == {document.blocks[1].id}
    assert len(window._undo_stack) == 1
    window._selected_block_ids = {b.id for b in document.blocks}
    window.merge_selected_blocks()
    assert len(document.blocks) == 1
    assert " ".join(document.blocks[0].text.split()) == original.text
    window.undo_last_action()
    assert len(document.blocks) == 3
    window.undo_last_action()
    assert len(document.blocks) == 1
    assert asdict(document.blocks[0]) == asdict(original)
    assert document.raw_blocks[0].text == original.text


def test_split_refuses_unmatched_text_and_keeps_inline_runs(tmp_path):
    path = tmp_path / "names.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 80), "Title Author")
        rect = page.search_for("Title")[0]
        pdf.save(path)
    block = PDFExtractor(use_docling=False).extract(path).blocks[0]
    block.inline_runs = [{"start": 6, "end": 12, "type": "sup", "text": "Author"}]
    fragments, _ = split_resized_block(block, list(rect), path)
    assert fragments[1].inline_runs[0]["text"] == "Author"
    assert fragments[1].text[fragments[1].inline_runs[0]["start"]:fragments[1].inline_runs[0]["end"]] == "Author"
    block.text = "Edited text absent from PDF"
    assert split_resized_block(block, list(rect), path) is None


def test_merge_keeps_separate_outlines_and_gap_is_not_clickable(resize_window):
    window, first = resize_window
    second = deepcopy(first)
    second.id = "second"
    second.text = "Second author"
    second.bbox = [150, 90, 250, 130]
    second.x, second.y, second.width, second.height = 150, 90, 100, 40
    second.metadata["reading_order"] = 1
    window.document.blocks.append(second)
    window._selected_block_ids = {first.id, second.id}
    window.merge_selected_blocks()
    merged = window.document.blocks[0]
    assert merged.metadata["merged_regions"] == [
        {"page": 1, "bbox": first.bbox}, {"page": 1, "bbox": second.bbox},
    ]
    viewer = window.viewer
    viewer._page_scale = 1
    viewer._page_count = 1
    try:
        canvas = QPixmap(600, 800)
        canvas.fill(Qt.white)
        viewer._paint_overlays(canvas, viewer.label, 0)
        outlines = [r for r in viewer._regions if r["kind"] == "block"]
        assert [r["rect"] for r in outlines] == [first.bbox, second.bbox]
        assert {r["id"] for r in outlines} == {merged.id}
        assert viewer.label._hit_test(QPointF(125, 75)) is None
        for point in (QPointF(60, 40), QPointF(200, 110)):
            assert viewer.label._hit_test(point) == f"block:{merged.id}"
    finally:
        viewer._page_count = 0
    original_regions = deepcopy(merged.metadata["merged_regions"])
    viewer.label.resize(600, 800)
    viewer.label.setProperty("pageScale", 1.0)
    QTest.mousePress(viewer.label, Qt.LeftButton, pos=QPoint(250, 130))
    QTest.mouseMove(viewer.label, QPoint(270, 140))
    QTest.mouseRelease(viewer.label, Qt.LeftButton, pos=QPoint(270, 140))
    assert merged.metadata["merged_regions"][0] == original_regions[0]
    assert merged.metadata["merged_regions"][1]["bbox"] == [150, 90, 270, 140]
    window.undo_last_action()
    assert merged.metadata["merged_regions"] == original_regions
    third = deepcopy(second)
    third.id = "third"
    third.page = 2
    window.document.blocks.append(third)
    window._selected_block_ids = {merged.id, third.id}
    window.merge_selected_blocks()
    combined = window.document.blocks[0]
    assert len(combined.metadata["merged_regions"]) == 3
    assert len(viewer._blocks_by_page[1]) == 2
    assert len(viewer._blocks_by_page[2]) == 1
    window.undo_last_merge()
    assert window.document.blocks[0].metadata["merged_regions"] == original_regions


@pytest.mark.parametrize("role", ["title", "author", "affiliation", "abstract"])
@pytest.mark.parametrize("explicit", [True, False])
def test_apply_role_to_merged_group_in_active_article(resize_window, monkeypatch, role, explicit):
    window, first = resize_window
    window._startup_flow = explicit
    window._explicit_number_workflow = explicit
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    second = deepcopy(first)
    second.id = "second"
    second.text = "Second text"
    second.metadata["reading_order"] = 1
    window.document.blocks.append(second)
    window._selected_block_ids = {first.id, second.id}
    assert window._start_article_from_number("P-123")
    window.merge_selected_blocks()
    merged = window.document.blocks[0]
    window._on_viewer_block_selected(merged.id, False)
    assert window.props.apply_role_btn.isEnabled()
    window.props.role_editor.setCurrentText(role)
    window.props.apply_role_btn.click()
    assert not messages
    assert merged.role == role
    assert merged.metadata["role_source"] == "manual"
    window.auto_refiner.refine([merged])
    assert merged.role == role
    assert window._article_owning(merged.id) is not None
    assert window._current_segment() is not None
    assert window._selected_block_ids == {merged.id}
    assert window.props.fields["Detected Role"].text() == role
    assert len(window.viewer._blocks_by_page[1]) == 2
    window.undo_last_merge()
    assert window._current_segment() is not None
    assert window._article_owning(first.id) is not None
    assert window._article_owning(second.id) is not None
    window.redo_last_merge()
    assert window._current_segment() is not None
    assert window._article_owning(merged.id) is not None
    restored = next(b for b in window.document.blocks if b.id == merged.id)
    assert restored.role == role
    assert restored.metadata["role_source"] == "manual"


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_corner_drag_converts_screen_coordinates_to_pdf(resize_window, scale):
    window, block = resize_window
    label = window.viewer.label
    # Isolate the gesture from selection navigation; the real geometry signals
    # remain connected to the main window.
    label.blockSelected.disconnect(window._on_viewer_block_selected)
    label.setProperty("pageScale", scale)
    label.setProperty("blockRegions", [
        {"id": f"{block.id}:top_left", "kind": "block_handle",
         "rect": [20 * scale - 5, 20 * scale - 5, 20 * scale + 5, 20 * scale + 5]},
        {"id": f"{block.id}:bottom_right", "kind": "block_handle",
         "rect": [100 * scale - 5, 60 * scale - 5, 100 * scale + 5, 60 * scale + 5]},
    ])
    label.resize(600, 800)
    start = QPoint(int(100 * scale), int(60 * scale))
    end = QPoint(int(130 * scale), int(80 * scale))
    QTest.mousePress(label, Qt.LeftButton, pos=start)
    QTest.mouseMove(label, end)
    QTest.mouseRelease(label, Qt.LeftButton, pos=end)
    assert block.bbox == [20, 20, 130, 80]
    assert len(window._undo_stack) == 1
    assert window._active_block_move_undo_id is None
