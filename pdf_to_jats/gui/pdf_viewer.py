"""PDF preview widget."""

from __future__ import annotations

from pathlib import Path
from collections import OrderedDict
from bisect import bisect_left, bisect_right
from typing import Any

import fitz
from PySide6.QtCore import QObject, QPointF, QRect, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QBrush, QImage, QPainter, QPen, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QHBoxLayout, QLabel, QPushButton, QRubberBand, QScrollArea, QVBoxLayout, QWidget


class _PageRasterWorker(QObject):
    rendered = Signal(str, int, float, int, object, object)

    def __init__(self, path: str, page_index: int, scale: float, generation: int) -> None:
        super().__init__()
        self.path = path
        self.page_index = page_index
        self.scale = scale
        self.generation = generation

    @Slot()
    def run(self) -> None:
        try:
            with fitz.open(self.path) as document:
                page = document.load_page(self.page_index)
                pix = page.get_pixmap(matrix=fitz.Matrix(self.scale, self.scale), alpha=False)
                self.rendered.emit(
                    self.path, self.page_index, self.scale, self.generation,
                    (pix.width, pix.height, pix.stride, bytes(pix.samples)),
                    None,
                )
        except Exception as exc:
            self.rendered.emit(self.path, self.page_index, self.scale, self.generation, None, exc)


class PdfPageLabel(QLabel):
    """Clickable page renderer with block and zone interaction."""

    blockSelected = Signal(str, bool)
    blockRangeSelected = Signal(str)
    blocksRectSelected = Signal(list)
    blockContextRequested = Signal(str, object)
    blockMoved = Signal(str, list)
    blockPieceMoved = Signal(str, int, list)
    blockEditFinished = Signal(str)
    zoneSelected = Signal(str, bool)
    zoneMoved = Signal(str, list)
    zoneCreated = Signal(list)
    zoneEditFinished = Signal(str)
    textRectSelected = Signal(list)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._zone_drag_id: str | None = None
        self._zone_drag_start: QPointF | None = None
        self._zone_drag_bbox: list[float] | None = None
        self._zone_drag_handle: str | None = None
        self._block_drag_id: str | None = None
        self._block_drag_start: QPointF | None = None
        self._block_drag_bbox: list[float] | None = None
        self._block_drag_handle: str | None = None
        self._block_drag_piece: int | None = None
        self._draw_start: QPointF | None = None
        self._draw_current: QPointF | None = None
        self._drawing_zone = False
        self._selection_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._selection_band.setStyleSheet("QRubberBand { border: 1px solid #4ea1ff; background: rgba(78, 161, 255, 45); }")
        self.setMouseTracking(True)
        # Article actions are offered on the line under the cursor, which is far
        # easier to hit than selecting exactly one block and using the button.
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu_requested)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        modifiers = event.modifiers()
        if self.property('textSelectable'):
            self.setFocus()
        range_select = bool(modifiers & Qt.ControlModifier and modifiers & Qt.ShiftModifier)
        additive = bool(modifiers & Qt.ControlModifier) and not range_select
        hit = self._hit_test(event.position() if hasattr(event, "position") else event.pos(), prefer_blocks=additive or range_select)
        if hit:
            kind, item_id = hit.split(":", 1)
            if kind == "handle":
                owner_id, handle_name = item_id.split(":", 1)
                if self._is_block_handle(owner_id):
                    if additive or range_select:
                        if range_select:
                            self.blockRangeSelected.emit(owner_id)
                        else:
                            self.blockSelected.emit(owner_id, True)
                        event.accept()
                        return
                    if range_select:
                        self.blockRangeSelected.emit(owner_id)
                    else:
                        self.blockSelected.emit(owner_id, additive)
                    self._block_drag_handle = handle_name
                    self._block_drag_piece = int(handle_name.split("@")[1]) if "@" in handle_name else None
                    self._block_drag_id = owner_id
                    self._block_drag_start = event.position() if hasattr(event, "position") else event.pos()
                    self._block_drag_bbox = self._current_block_bbox(owner_id, self._block_drag_piece)
                else:
                    self.zoneSelected.emit(owner_id, additive)
                    self._zone_drag_handle = handle_name
                    self._zone_drag_id = owner_id
                    self._zone_drag_start = event.position() if hasattr(event, "position") else event.pos()
                    self._zone_drag_bbox = self._current_zone_bbox(owner_id)
                event.accept()
                return
            if kind == "zone":
                self.zoneSelected.emit(item_id, additive)
                self._zone_drag_handle = self._zone_handle_hit_test(item_id, event.position() if hasattr(event, "position") else event.pos())
                self._zone_drag_id = item_id
                self._zone_drag_start = event.position() if hasattr(event, "position") else event.pos()
                self._zone_drag_bbox = self._current_zone_bbox(item_id)
            else:
                if range_select:
                    self.blockRangeSelected.emit(item_id)
                else:
                    self.blockSelected.emit(item_id, additive)
                if self._block_is_adjustable(item_id) and not (additive or range_select):
                    self._block_drag_id = item_id
                    self._block_drag_start = event.position() if hasattr(event, "position") else event.pos()
                    self._block_drag_bbox = self._current_block_bbox(item_id)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._draw_start = event.position() if hasattr(event, "position") else event.pos()
            self._draw_current = self._draw_start
            self._drawing_zone = True
            self._selection_band.setGeometry(QRect(int(self._draw_start.x()), int(self._draw_start.y()), 1, 1))
            self._selection_band.show()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._block_drag_id and self._block_drag_start and self._block_drag_bbox:
            current = event.position() if hasattr(event, "position") else event.pos()
            dx = current.x() - self._block_drag_start.x()
            dy = current.y() - self._block_drag_start.y()
            scale = float(self.property("pageScale") or 1.0)
            x0, y0, x1, y1 = self._block_drag_bbox
            if self._block_drag_handle:
                if "left" in self._block_drag_handle:
                    x0 = min(x0 + dx / scale, x1 - 5)
                if "right" in self._block_drag_handle:
                    x1 = max(x1 + dx / scale, x0 + 5)
                if "top" in self._block_drag_handle:
                    y0 = min(y0 + dy / scale, y1 - 5)
                if "bottom" in self._block_drag_handle:
                    y1 = max(y1 + dy / scale, y0 + 5)
            else:
                x0, x1 = x0 + dx / scale, x1 + dx / scale
                y0, y1 = y0 + dy / scale, y1 + dy / scale
            if self._block_drag_piece is not None:
                self.blockPieceMoved.emit(self._block_drag_id, self._block_drag_piece, [x0, y0, x1, y1])
            else:
                self.blockMoved.emit(self._block_drag_id, [x0, y0, x1, y1])
            event.accept()
            return
        if self._zone_drag_id and self._zone_drag_start and self._zone_drag_bbox:
            current = event.position() if hasattr(event, "position") else event.pos()
            dx = current.x() - self._zone_drag_start.x()
            dy = current.y() - self._zone_drag_start.y()
            scale = float(self.property("pageScale") or 1.0)
            x0, y0, x1, y1 = self._zone_drag_bbox
            if self._zone_drag_handle:
                nx0, ny0, nx1, ny1 = x0, y0, x1, y1
                if "left" in self._zone_drag_handle:
                    nx0 = min(x0 + (dx / scale), x1 - 5)
                if "right" in self._zone_drag_handle:
                    nx1 = max(x1 + (dx / scale), x0 + 5)
                if "top" in self._zone_drag_handle:
                    ny0 = min(y0 + (dy / scale), y1 - 5)
                if "bottom" in self._zone_drag_handle:
                    ny1 = max(y1 + (dy / scale), y0 + 5)
                self.zoneMoved.emit(self._zone_drag_id, [nx0, ny0, nx1, ny1])
            else:
                self.zoneMoved.emit(
                    self._zone_drag_id,
                    [x0 + (dx / scale), y0 + (dy / scale), x1 + (dx / scale), y1 + (dy / scale)],
                )
            event.accept()
            return
        if self._drawing_zone and self._draw_start:
            self._draw_current = event.position() if hasattr(event, "position") else event.pos()
            x0 = min(self._draw_start.x(), self._draw_current.x())
            y0 = min(self._draw_start.y(), self._draw_current.y())
            x1 = max(self._draw_start.x(), self._draw_current.x())
            y1 = max(self._draw_start.y(), self._draw_current.y())
            self._selection_band.setGeometry(QRect(int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0))))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self.property('textSelectable') and event.button() == Qt.LeftButton:
            if self._draw_start is not None:
                end = event.position()
                scale = float(self.property('pageScale') or 1)
                rect = [min(self._draw_start.x(), end.x()) / scale,
                        min(self._draw_start.y(), end.y()) / scale,
                        max(self._draw_start.x(), end.x()) / scale,
                        max(self._draw_start.y(), end.y()) / scale]
                self.textRectSelected.emit(rect if rect[2] - rect[0] > 2 and rect[3] - rect[1] > 2 else [])
            self._drawing_zone = False
            self._draw_start = self._draw_current = None
            event.accept()
            return
        finished_block_id = self._block_drag_id
        self._block_drag_id = None
        self._block_drag_start = None
        self._block_drag_bbox = None
        self._block_drag_handle = None
        self._block_drag_piece = None
        if finished_block_id:
            self.blockEditFinished.emit(finished_block_id)
        finished_zone_id = self._zone_drag_id
        self._zone_drag_id = None
        self._zone_drag_start = None
        self._zone_drag_bbox = None
        self._zone_drag_handle = None
        if finished_zone_id:
            self.zoneEditFinished.emit(finished_zone_id)
        if self._drawing_zone and self._draw_start and self._draw_current:
            scale = float(self.property("pageScale") or 1.0)
            x0 = min(self._draw_start.x(), self._draw_current.x()) / scale
            y0 = min(self._draw_start.y(), self._draw_current.y()) / scale
            x1 = max(self._draw_start.x(), self._draw_current.x()) / scale
            y1 = max(self._draw_start.y(), self._draw_current.y()) / scale
            if abs(x1 - x0) > 2 and abs(y1 - y0) > 2:
                selected_ids = []
                display_rect = [
                    min(self._draw_start.x(), self._draw_current.x()),
                    min(self._draw_start.y(), self._draw_current.y()),
                    max(self._draw_start.x(), self._draw_current.x()),
                    max(self._draw_start.y(), self._draw_current.y()),
                ]
                for region in self.property("blockRegions") or []:
                    rect = region.get("rect")
                    if region.get("kind") != "block" or not rect:
                        continue
                    if rect[0] <= display_rect[2] and rect[2] >= display_rect[0] and rect[1] <= display_rect[3] and rect[3] >= display_rect[1]:
                        selected_ids.append(str(region.get("id")))
                self.blocksRectSelected.emit(selected_ids)
            else:
                self.blocksRectSelected.emit([])
        self._selection_band.hide()
        self._drawing_zone = False
        self._draw_start = None
        self._draw_current = None
        super().mouseReleaseEvent(event)

    def _block_id_at(self, pos) -> str | None:
        """Return the block drawn under a point, if any."""

        x = float(pos.x())
        y = float(pos.y())
        for region in reversed(self.property("blockRegions") or []):
            rect = region.get("rect")
            if region.get("kind") != "block" or not rect:
                continue
            if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                return str(region.get("id"))
        return None

    def _on_context_menu_requested(self, pos) -> None:
        """Offer the block menu for a right-click, ignoring empty page areas."""

        if self.property('textSelectable'):
            menu = QMenu(self)
            action = menu.addAction('Copy')
            text = self.property('selectedPdfText') or ''
            action.setEnabled(bool(text))
            action.triggered.connect(lambda: QApplication.clipboard().setText(text))
            menu.exec(self.mapToGlobal(pos))
            return
        block_id = self._block_id_at(pos)
        if block_id:
            self.blockContextRequested.emit(block_id, self.mapToGlobal(pos))

    def _hit_test(self, pos: QPointF, prefer_blocks: bool = False) -> str | None:
        regions = self.property("blockRegions") or []
        x = float(pos.x())
        y = float(pos.y())
        # Selection modifiers must reach the text under a resize handle. A
        # selected block's generous corner hit area can overlap its neighbour.
        if prefer_blocks:
            for region in reversed(regions):
                rect = region.get("rect")
                if (
                    region.get("kind") == "block"
                    and rect
                    and rect[0] <= x <= rect[2]
                    and rect[1] <= y <= rect[3]
                ):
                    return f"block:{region.get('id')}"
        for region in reversed(regions):
            rect = region.get("rect")
            if (
                region.get("kind") == "block_handle"
                and rect
                and rect[0] <= x <= rect[2]
                and rect[1] <= y <= rect[3]
            ):
                return f"handle:{region.get('id')}"
        # Text selection and text resize handles always outrank zone overlays,
        # including a previously selected zone and its overlapping handles.
        for region in reversed(regions):
            rect = region.get("rect")
            if (
                region.get("kind") == "block"
                and rect
                and rect[0] <= x <= rect[2]
                and rect[1] <= y <= rect[3]
            ):
                return f"block:{region.get('id')}"
        for region in reversed(regions):
            rect = region.get("rect")
            if (region.get("kind") == "handle" and rect
                    and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
                return f"handle:{region.get('id')}"
        for region in reversed(regions):
            rect = region.get("rect")
            if (
                region.get("kind") == "zone"
                and rect
                and rect[0] <= x <= rect[2]
                and rect[1] <= y <= rect[3]
            ):
                return f"zone:{region.get('id')}"
        return None

    def _current_zone_bbox(self, zone_id: str) -> list[float] | None:
        zones = self.property("zones") or []
        for zone in zones:
            if str(zone.get("id")) == zone_id:
                bbox = zone.get("bbox")
                if isinstance(bbox, list) and len(bbox) == 4:
                    return [float(v) for v in bbox]
        return None

    def _current_block_bbox(self, block_id: str, piece: int | None = None) -> list[float] | None:
        for block in self.property("blocks") or []:
            if str(block.get("id")) == block_id:
                bbox = block.get("bbox")
                if piece is not None:
                    bbox = block["metadata"]["merged_regions"][piece]["bbox"]
                if isinstance(bbox, list) and len(bbox) == 4:
                    return [float(value) for value in bbox]
        return None

    def _is_block_handle(self, owner_id: str) -> bool:
        return self._block_is_adjustable(owner_id) and any(
            str(region.get("id", "")).startswith(f"{owner_id}:") and region.get("kind") == "block_handle"
            for region in self.property("blockRegions") or []
        )

    def _block_is_adjustable(self, block_id: str) -> bool:
        """Allow ordinary and grouped text blocks to be adjusted unless locked."""

        for block in self.property("blocks") or []:
            if str(block.get("id")) == block_id:
                metadata = block.get("metadata") or {}
                return not bool(metadata.get("article_locked"))
        return False

    def _zone_handle_hit_test(self, zone_id: str, pos: QPointF) -> str | None:
        zones = self.property("zones") or []
        scale = float(self.property("pageScale") or 1.0)
        x = float(pos.x())
        y = float(pos.y())
        handle_size = 12.0
        for zone in zones:
            if str(zone.get("id")) != zone_id:
                continue
            bbox = zone.get("bbox")
            if not (isinstance(bbox, list) and len(bbox) == 4):
                return None
            rect = fitz.Rect(bbox)
            scaled = fitz.Rect(rect.x0 * scale, rect.y0 * scale, rect.x1 * scale, rect.y1 * scale)
            corners = {
                "top_left": (scaled.x0, scaled.y0),
                "top_right": (scaled.x1, scaled.y0),
                "bottom_left": (scaled.x0, scaled.y1),
                "bottom_right": (scaled.x1, scaled.y1),
            }
            for name, (hx, hy) in corners.items():
                if abs(x - hx) <= handle_size and abs(y - hy) <= handle_size:
                    return name
        return None


class PDFViewer(QWidget):
    """Render one PDF page at a time and draw block and zone overlays."""

    pageChanged = Signal(int, int)

    def __init__(self, parent: QWidget | None = None, *, text_blocks_only: bool = False, text_selectable: bool = False) -> None:
        super().__init__(parent)
        self._text_blocks_only = text_blocks_only
        self._pdf_path: Path | None = None
        self._text_selectable = text_selectable
        self._selected_pdf_text = ''
        self._page_count = 0
        self._page_sizes: list[tuple[float, float]] = []
        self._page_offsets: list[int] = []
        self._page_bottoms: list[int] = []
        self._canvas_page_width = 1
        self._generation = 0
        self._page_index = 0
        self._page_scale = 1.6
        self._page_labels: dict[int, PdfPageLabel] = {}
        self._base_page_pixmap: QPixmap | None = None
        self._base_page_key: tuple[int, float] | None = None
        self._page_pixmaps: OrderedDict[tuple[str, int, float], QPixmap] = OrderedDict()
        self._page_cache_bytes = 0
        self._page_cache_limit = 96 * 1024 * 1024
        self._pending_page_renders: set[tuple[str, int, float, int]] = set()
        self._queued_page_renders: list[tuple[str, int, float, int]] = []
        self._max_concurrent_page_renders = 3
        self._overlay_revision = 0
        self._page_render_threads: list[QThread] = []
        self._page_render_workers: dict[QThread, _PageRasterWorker] = {}
        self._page_gap = 12
        self._relaying_page_signal = False
        self._blocks: list[dict[str, Any]] = []
        self._zones: list[dict[str, Any]] = []
        self._blocks_by_page: dict[int, list[dict[str, Any]]] = {}
        self._blocks_by_id: dict[str, dict[str, Any]] = {}
        self._zones_by_page: dict[int, list[dict[str, Any]]] = {}
        self._regions: list[dict[str, Any]] = []
        self._selected_block_id: str | None = None
        self._selected_block_ids: set[str] = set()
        self._deleted_block_ids: set[str] = set()
        self._selected_zone_id: str | None = None
        self._selected_zone_ids: set[str] = set()
        self._draft_zone_rect: list[float] | None = None
        self._continuation_links: list[tuple[str, str]] = []
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.prev_btn = QPushButton("Prev Page")
        self.next_btn = QPushButton("Next Page")
        self.zoom_out_btn = QPushButton("Zoom -")
        self.zoom_in_btn = QPushButton("Zoom +")
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.next_btn)
        controls.addWidget(self.zoom_out_btn)
        controls.addWidget(self.zoom_in_btn)
        self.page_indicator = QLabel("Page 0 of 0")
        controls.addWidget(self.page_indicator)
        self.copy_text_btn = QPushButton('Copy selected text')
        self.copy_text_btn.setVisible(text_selectable)
        self.copy_text_btn.setEnabled(False)
        self.copy_text_btn.setToolTip('Drag a rectangle around PDF text, then copy it (Ctrl+C)')
        self.copy_text_btn.clicked.connect(self.copy_selected_text)
        controls.addWidget(self.copy_text_btn)
        self._copy_shortcut = QShortcut(QKeySequence.Copy, self)
        self._copy_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._copy_shortcut.setEnabled(text_selectable)
        self._copy_shortcut.activated.connect(self.copy_selected_text)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.label = PdfPageLabel("Drop a PDF to preview it here.")
        self.label.setWordWrap(True)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.page_container = QWidget()
        self.page_layout = QVBoxLayout(self.page_container)
        self.page_layout.setContentsMargins(8, 8, 8, 8)
        self.page_layout.setSpacing(12)
        self._page_gap = self.page_layout.spacing()
        # Page labels are materialized only near the viewport and positioned
        # on a virtual canvas sized to represent the complete document.
        self.label.setParent(self.page_container)
        self.scroll_area.setWidget(self.page_container)
        layout.addWidget(self.scroll_area)
        self.prev_btn.clicked.connect(self.previous_page)
        self.next_btn.clicked.connect(self.next_page)
        self.zoom_out_btn.clicked.connect(lambda: self.set_zoom(max(self._page_scale - 0.2, 0.6)))
        self.zoom_in_btn.clicked.connect(lambda: self.set_zoom(min(self._page_scale + 0.2, 4.0)))
        self.label.setProperty("pageScale", self._page_scale)
        self._page_labels = {0: self.label}
        self._forward_page_signals(self.label, 0)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

    def _forward_page_signals(self, page_label: PdfPageLabel, page_index: int) -> None:
        """Relay clicks and edits from every page through the original label."""

        if self._text_selectable:
            page_label.setProperty('textSelectable', True)
            page_label.setFocusPolicy(Qt.StrongFocus)
            page_label.setCursor(Qt.IBeamCursor)
            page_label.textRectSelected.connect(
                lambda rect, index=page_index: self._select_pdf_text(index, rect))
        for name in (
            "blockSelected", "blockRangeSelected", "blocksRectSelected",
            "blockContextRequested", "blockMoved", "blockPieceMoved", "blockEditFinished",
            "zoneSelected", "zoneMoved", "zoneCreated", "zoneEditFinished",
        ):
            signal = getattr(page_label, name)
            if page_label is self.label:
                signal.connect(
                    lambda *_args: self._set_active_page(0)
                    if not self._relaying_page_signal else None
                )
            else:
                signal.connect(
                    lambda *args, index=page_index, signal_name=name:
                    self._relay_page_signal(index, signal_name, *args)
                )

    def copy_selected_text(self) -> None:
        if self._selected_pdf_text:
            QApplication.clipboard().setText(self._selected_pdf_text)

    def _select_pdf_text(self, page_index: int, rect: list) -> None:
        self._selected_pdf_text = ''
        if self._pdf_path and rect:
            with fitz.open(self._pdf_path) as document:
                page = document[page_index]
                clip = fitz.Rect(rect) * page.derotation_matrix
                self._selected_pdf_text = page.get_text('text', clip=clip, sort=True).strip()
        for index, label in self._page_labels.items():
            label.setProperty('selectedPdfText', self._selected_pdf_text if index == page_index else '')
            if index != page_index:
                label._selection_band.hide()
        self.copy_text_btn.setEnabled(bool(self._selected_pdf_text))
        self.copy_text_btn.setToolTip('Copy selected text (Ctrl+C)' if self._selected_pdf_text
                                     else 'No text selected. Drag around text; scanned pages require OCR.')

    def _relay_page_signal(self, page_index: int, signal_name: str, *args) -> None:
        self._set_active_page(page_index)
        self._relaying_page_signal = True
        try:
            getattr(self.label, signal_name).emit(*args)
        finally:
            self._relaying_page_signal = False

    def _set_active_page(self, page_index: int) -> None:
        self._page_index = page_index
        if self._page_count:
            self.page_indicator.setText(f"Page {page_index + 1} of {self._page_count}")
            self._update_page_controls()
            self.pageChanged.emit(page_index, self._page_count)

    def _update_page_controls(self) -> None:
        has_multiple_pages = self._page_count > 1
        self.prev_btn.setVisible(has_multiple_pages)
        self.next_btn.setVisible(has_multiple_pages)
        self.prev_btn.setEnabled(has_multiple_pages and self._page_index > 0)
        self.next_btn.setEnabled(has_multiple_pages and self._page_index < self._page_count - 1)

    def _resize_page_labels(self) -> None:
        if not self._page_sizes:
            return
        margins = self.page_layout.contentsMargins()
        max_width = max((round(width * self._page_scale) for width, _ in self._page_sizes), default=1)
        self._canvas_page_width = max_width
        page_top = margins.top()
        self._page_offsets = []
        self._page_bottoms = []
        for _page_width, page_height in self._page_sizes:
            self._page_offsets.append(page_top)
            page_bottom = page_top + max(1, round(page_height * self._page_scale))
            self._page_bottoms.append(page_bottom)
            page_top = page_bottom + self._page_gap
        total_height = self._page_bottoms[-1] + margins.bottom()
        total_width = max_width + margins.left() + margins.right()
        self.page_container.setMinimumSize(total_width, total_height)
        self.page_container.resize(total_width, total_height)
        for index, label in self._page_labels.items():
            page_width, page_height = self._page_sizes[index]
            width = max(1, round(page_width * self._page_scale))
            height = max(1, round(page_height * self._page_scale))
            label.setFixedSize(width, height)
            label.setProperty("pageScale", self._page_scale)
            label.move(margins.left() + (max_width - width) // 2, self._page_offsets[index])

    def _fit_page_to_width(self) -> None:
        """Choose a readable scale that keeps the full page inside the pane."""
        if not self._page_count:
            return
        page_width = self._page_sizes[self._page_index][0]
        available_width = max(1, self.scroll_area.viewport().width() - 24)
        self._page_scale = min(1.8, max(0.4, available_width / max(1.0, page_width)))

    def _sync_page_properties(self) -> None:
        for label in self._page_labels.values():
            label.setProperty("pageScale", self._page_scale)
            label.setProperty("blocks", self._blocks)
            label.setProperty("zones", self._zones)
            label.setProperty("selectedZoneId", self._selected_zone_id)
            label.setProperty("selectedZoneIds", self._selected_zone_ids)

    def _materialize_pages_near_viewport(self) -> set[int]:
        if not self._page_count or not self._page_offsets:
            return set()
        scroll_top = self.scroll_area.verticalScrollBar().value()
        viewport_height = max(1, self.scroll_area.viewport().height())
        visible_top = max(0, scroll_top - viewport_height)
        visible_bottom = scroll_top + viewport_height
        first = min(self._page_count - 1, bisect_left(self._page_bottoms, visible_top))
        last = min(self._page_count - 1, max(0, bisect_right(self._page_offsets, visible_bottom) - 1))
        keep = set(range(first, last + 1))
        keep.add(0)  # The original label remains the signal hub for page interactions.
        for index in sorted(keep):
            self._ensure_page_label(index)
        for index, label in list(self._page_labels.items()):
            if index in keep:
                continue
            self._page_labels.pop(index, None)
            label.hide()
            label.deleteLater()
        self._queued_page_renders = [
            key for key in self._queued_page_renders
            if key[3] == self._generation and key[1] in keep
        ]
        return keep

    def _render_visible_pages(self, force: bool = False, repaint_overlays: bool = False) -> None:
        if not self._pdf_path:
            return
        if repaint_overlays:
            self._overlay_revision += 1
        self._sync_page_properties()
        scroll_top = self.scroll_area.verticalScrollBar().value()
        viewport_height = max(1, self.scroll_area.viewport().height())
        visible_top = scroll_top - viewport_height
        visible_bottom = scroll_top + viewport_height
        for index, label in self._page_labels.items():
            label_top = label.y()
            label_bottom = label_top + label.height()
            if label_bottom < visible_top or label_top > visible_bottom:
                continue
            key = (str(self._pdf_path), index, self._page_scale)
            cached = self._page_pixmaps.get(key)
            if force or cached is None:
                self._queue_page_raster(index)
                continue
            self._page_pixmaps.move_to_end(key)
            if not repaint_overlays and label.property("overlayRevision") == self._overlay_revision:
                continue
            self._paint_overlays(cached.copy(), label, index)
            label.setProperty("renderedPageScale", self._page_scale)
            label.setProperty("overlayRevision", self._overlay_revision)

    def _queue_page_raster(self, page_index: int) -> None:
        key = (str(self._pdf_path), page_index, self._page_scale, self._generation)
        cache_key = (key[0], page_index, self._page_scale)
        if (
            key in self._pending_page_renders
            or key in self._queued_page_renders
            or cache_key in self._page_pixmaps
        ):
            return
        self._queued_page_renders.append(key)
        self._start_queued_page_renders()

    def _start_queued_page_renders(self) -> None:
        while (
            self._queued_page_renders
            and len(self._pending_page_renders) < self._max_concurrent_page_renders
        ):
            key = self._queued_page_renders.pop(0)
            path, page_index, scale, generation = key
            if (
                generation != self._generation
                or path != str(self._pdf_path)
                or scale != self._page_scale
                or page_index not in self._page_labels
            ):
                continue
            if (path, page_index, scale) in self._page_pixmaps:
                continue
            self._pending_page_renders.add(key)
            label = self._page_labels[page_index]
            label.setText("Rendering page...")
            label.setAlignment(Qt.AlignCenter)
            thread = QThread(self)
            worker = _PageRasterWorker(path, page_index, scale, generation)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.rendered.connect(self._on_page_raster_ready, Qt.QueuedConnection)
            worker.rendered.connect(thread.quit, Qt.DirectConnection)
            worker.rendered.connect(worker.deleteLater)
            thread.finished.connect(lambda current=thread: self._forget_page_render(current))
            thread.finished.connect(thread.deleteLater)
            self._page_render_threads.append(thread)
            self._page_render_workers[thread] = worker
            thread.start()

    def _forget_page_render(self, thread: QThread) -> None:
        if thread in self._page_render_threads:
            self._page_render_threads.remove(thread)
        # The worker is connected to deleteLater when it emits its result, so
        # do not call into its Shiboken wrapper during thread cleanup.
        self._page_render_workers.pop(thread, None)

    @Slot(str, int, float, int, object, object)
    def _on_page_raster_ready(self, path: str, page_index: int, scale: float, generation: int, raster, error) -> None:
        key = (path, page_index, scale, generation)
        self._pending_page_renders.discard(key)
        self._start_queued_page_renders()
        if path != str(self._pdf_path) or generation != self._generation:
            return
        if error is not None:
            label = self._page_labels.get(page_index)
            if label is not None:
                label.setText("Could not render this page")
            return
        width, height, stride, samples = raster
        image = QImage(samples, width, height, stride, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)
        cache_key = (path, page_index, scale)
        previous = self._page_pixmaps.pop(cache_key, None)
        if previous is not None:
            self._page_cache_bytes -= previous.width() * previous.height() * 4
        self._page_pixmaps[cache_key] = pixmap
        self._page_cache_bytes += pixmap.width() * pixmap.height() * 4
        while self._page_cache_bytes > self._page_cache_limit and len(self._page_pixmaps) > 1:
            _old_key, old_pixmap = self._page_pixmaps.popitem(last=False)
            self._page_cache_bytes -= old_pixmap.width() * old_pixmap.height() * 4
        if scale != self._page_scale or page_index not in self._page_labels:
            return
        self._sync_page_properties()
        label = self._page_labels[page_index]
        self._paint_overlays(pixmap.copy(), label, page_index)
        label.setProperty("renderedPageScale", scale)
        label.setProperty("overlayRevision", self._overlay_revision)

    def _on_scroll_changed(self, _value: int) -> None:
        if not self._page_count or not self._page_offsets:
            return
        scroll_top = self.scroll_area.verticalScrollBar().value()
        viewport_height = max(1, self.scroll_area.viewport().height())
        marker = scroll_top + max(1, viewport_height // 3)
        current = max(0, min(self._page_count - 1, bisect_right(self._page_offsets, marker) - 1))
        if current != self._page_index:
            self._page_index = current
            self.page_indicator.setText(f"Page {current + 1} of {self._page_count}")
            self._update_page_controls()
            self.pageChanged.emit(current, self._page_count)
        self._materialize_pages_near_viewport()
        self._render_visible_pages(force=False)

    def load_pdf(
        self,
        pdf_path: str | Path,
        document: fitz.Document | None = None,
        preview: tuple[int, int, int, bytes] | None = None,
        *, page_count: int | None = None, page_sizes: list[tuple[float, float]] | None = None,
    ) -> None:
        self._generation += 1
        self._pdf_path = Path(pdf_path)
        self._select_pdf_text(-1, [])
        # Compatibility for existing callers; the viewer keeps only detached
        # metadata, never a live PyMuPDF document handle.
        if document is not None:
            page_count = document.page_count
            page_sizes = [(float(p.rect.width), float(p.rect.height)) for p in document]
            document.close()
        if page_count is None or page_sizes is None:
            with fitz.open(self._pdf_path) as opened:
                page_count = opened.page_count
                page_sizes = [(float(p.rect.width), float(p.rect.height)) for p in opened]
        self._page_count = page_count
        self._page_sizes = page_sizes
        self._page_index = 0
        self._base_page_pixmap = None
        self._base_page_key = None
        self._page_pixmaps.clear()
        self._page_cache_bytes = 0
        self._queued_page_renders.clear()
        self._fit_page_to_width()
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.label:
                widget.deleteLater()
        for index, widget in list(self._page_labels.items()):
            if index != 0:
                widget.hide()
                widget.deleteLater()
        self.label.clear()
        self.label.show()
        self._page_labels = {0: self.label}
        self._resize_page_labels()
        self.page_indicator.setText(f"Page 1 of {self._page_count}")
        self._update_page_controls()
        self.pageChanged.emit(0, self._page_count)
        self.scroll_area.verticalScrollBar().setValue(0)
        self._materialize_pages_near_viewport()
        if preview is not None and abs(self._page_scale - 1.6) < 0.001:
            width, height, stride, samples = preview
            image = QImage(samples, width, height, stride, QImage.Format_RGB888).copy()
            self._base_page_pixmap = QPixmap.fromImage(image)
            self._base_page_key = (0, self._page_scale)
            cache_key = (str(self._pdf_path), 0, self._page_scale)
            self._page_pixmaps[cache_key] = self._base_page_pixmap
            self._page_cache_bytes = self._base_page_pixmap.width() * self._base_page_pixmap.height() * 4
        # Always request the opening page explicitly. The viewport can still
        # be settling when a document is attached, which can otherwise leave
        # the page label blank until a scroll or resize event arrives.
        if self._page_count and (str(self._pdf_path), 0, self._page_scale) not in self._page_pixmaps:
            self._queue_page_raster(0)
        self._render_visible_pages(force=False)

    def render_page(self, page_index: int) -> None:
        if self._page_count == 0:
            return
        page_index = max(0, min(page_index, self._page_count - 1))
        self._page_index = page_index
        label = self._ensure_page_label(page_index)
        cache_key = (str(self._pdf_path), page_index, self._page_scale)
        if cache_key not in self._page_pixmaps:
            self._queue_page_raster(page_index)
        self.page_indicator.setText(f"Page {self._page_index + 1} of {self._page_count}")
        self._update_page_controls()
        self.pageChanged.emit(page_index, self._page_count)
        # Let QScrollArea recalculate its range after resizing the page
        # container; otherwise a jump to a later page can clamp to the old
        # range and leave only a small part of that page visible.
        generation = self._generation
        QTimer.singleShot(
            0,
            lambda index=page_index, current_generation=generation:
                self._position_page_at_top(index, current_generation),
        )
        self._render_visible_pages(force=False)

    def _position_page_at_top(self, page_index: int, generation: int) -> None:
        if generation != self._generation or page_index != self._page_index:
            return
        label = self._page_labels.get(page_index)
        if label is None:
            return
        target_top = self._page_offsets[page_index]
        self.scroll_area.verticalScrollBar().setValue(target_top)
        self._materialize_pages_near_viewport()
        self._render_visible_pages(force=False)

    def _ensure_page_label(self, page_index: int) -> PdfPageLabel:
        label = self._page_labels.get(page_index)
        if label is not None:
            return label
        label = PdfPageLabel(parent=self.page_container)
        self._page_labels[page_index] = label
        self._forward_page_signals(label, page_index)
        if self._page_offsets:
            page_width, page_height = self._page_sizes[page_index]
            width = max(1, round(page_width * self._page_scale))
            height = max(1, round(page_height * self._page_scale))
            label.setFixedSize(width, height)
            label.setProperty("pageScale", self._page_scale)
            label.move(
                self.page_layout.contentsMargins().left() + (self._canvas_page_width - width) // 2,
                self._page_offsets[page_index],
            )
        label.show()
        return label

    def is_document_current(self, path: str) -> bool:
        """Return whether delayed UI work still belongs to this PDF."""
        return bool(self._pdf_path and str(self._pdf_path) == str(Path(path)))

    def set_zoom(self, scale: float) -> None:
        self._select_pdf_text(-1, [])
        self._page_scale = scale
        self._resize_page_labels()
        self.render_page(self._page_index)

    def next_page(self) -> None:
        if not self._page_count:
            return
        self.render_page(self._page_index + 1)

    def previous_page(self) -> None:
        if not self._page_count:
            return
        self.render_page(self._page_index - 1)

    def set_blocks(self, blocks: list[dict[str, Any]]) -> None:
        self._blocks = blocks
        self._index_overlay_data()
        self.label.setProperty("blocks", self._blocks)
        if self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def set_document_overlays(
        self,
        blocks: list[dict[str, Any]],
        zones: list[dict[str, Any]],
    ) -> None:
        """Install extracted overlays together and repaint the visible page once."""
        self._blocks = blocks
        self._zones = [] if self._text_blocks_only else zones
        self._index_overlay_data()
        self.label.setProperty("blocks", self._blocks)
        self.label.setProperty("zones", self._zones)
        if self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def _index_overlay_data(self) -> None:
        self._blocks_by_page = {}
        self._blocks_by_id = {}
        for block in self._blocks:
            page = int(block.get("page", 0))
            block_id = str(block.get("id", ""))
            pieces = (block.get("metadata") or {}).get("merged_regions")
            if pieces:
                for index, piece in enumerate(pieces):
                    self._blocks_by_page.setdefault(int(piece["page"]), []).append(
                        dict(block, bbox=piece["bbox"], _piece_index=index)
                    )
            else:
                self._blocks_by_page.setdefault(page, []).append(block)
            if block_id:
                self._blocks_by_id[block_id] = block
        self._zones_by_page = {}
        for zone in self._zones:
            self._zones_by_page.setdefault(int(zone.get("page", 0)), []).append(zone)

    def set_zones(self, zones: list[dict[str, Any]]) -> None:
        self._zones = [] if self._text_blocks_only else zones
        self._index_overlay_data()
        self.label.setProperty("zones", self._zones)
        if self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def set_selected_zone(self, zone_id: str | None) -> None:
        if self._text_blocks_only:
            zone_id = None
        self._selected_zone_id = zone_id
        self._selected_zone_ids = {zone_id} if zone_id else set()
        for label in self._page_labels.values():
            label.setProperty("selectedZoneId", self._selected_zone_id)
            label.setProperty("selectedZoneIds", self._selected_zone_ids)
        if self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def set_selected_zones(self, zone_ids: set[str], primary_zone_id: str | None = None) -> None:
        if self._text_blocks_only:
            zone_ids = set()
        self._selected_zone_ids = set(zone_ids)
        self._selected_zone_id = primary_zone_id if primary_zone_id in self._selected_zone_ids else next(iter(self._selected_zone_ids), None)
        for label in self._page_labels.values():
            label.setProperty("selectedZoneId", self._selected_zone_id)
            label.setProperty("selectedZoneIds", self._selected_zone_ids)
        if self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def set_deleted_block_ids(self, block_ids: set[str]) -> None:
        """Blocks of deleted articles, drawn dotted and faint until cleared."""

        changed = block_ids != self._deleted_block_ids
        self._deleted_block_ids = set(block_ids)
        if changed and self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def set_selected_blocks(
        self,
        block_ids: set[str],
        primary_block_id: str | None = None,
        *,
        navigate_to_primary: bool = True,
    ) -> None:
        """Update highlighted blocks and optionally navigate to the primary block."""

        self._selected_block_ids = set(block_ids)
        self._selected_block_id = primary_block_id
        if self._continuation_links:
            selected = {str(block_id) for block_id in self._selected_block_ids}
            link_ids = {block_id for link in self._continuation_links for block_id in link}
            if not link_ids.issubset(selected):
                self._continuation_links = []
        if navigate_to_primary and primary_block_id:
            target = self._blocks_by_id.get(str(primary_block_id))
            if target is not None:
                target_page = max(
                    0,
                    min(int(target.get("page", 1)) - 1, self._page_count - 1),
                )
                scroll_top = self.scroll_area.verticalScrollBar().value()
                viewport_bottom = scroll_top + self.scroll_area.viewport().height()
                page_is_visible = (
                    target_page < len(self._page_offsets)
                    and target_page < len(self._page_bottoms)
                    and self._page_offsets[target_page] < viewport_bottom
                    and self._page_bottoms[target_page] > scroll_top
                )
                # Selection often originates from clicking a block on the page
                # already in view. Calling render_page for that same page
                # schedules a scroll to its top, discarding the user's position.
                if not page_is_visible:
                    self.render_page(target_page)
                    return
        if self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def set_draft_zone(self, bbox: list[float] | None) -> None:
        self._draft_zone_rect = bbox
        if self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def set_continuation_links(self, links: list[tuple[str, str]]) -> None:
        """Show paragraph continuation arrows from source block to next block."""

        self._continuation_links = [(str(source), str(target)) for source, target in links]
        if self._page_count:
            self._render_visible_pages(repaint_overlays=True)

    def selected_zone_id(self) -> str | None:
        return self._selected_zone_id

    def _block_is_adjustable(self, block_id: str) -> bool:
        """Allow ordinary and grouped text blocks to be adjusted unless locked."""

        block = self._blocks_by_id.get(block_id)
        metadata = (block or {}).get("metadata") or {}
        return block is not None and not bool(metadata.get("article_locked"))

    def _paint_overlays(self, pixmap: QPixmap, label: PdfPageLabel, page_index: int) -> None:
        if not self._page_count:
            return
        self._regions = []
        painter = QPainter(pixmap)
        base_pen = QPen(QColor(220, 38, 38), 2)
        selected_pen = QPen(QColor(34, 197, 94), 3)
        multi_selected_pen = QPen(QColor(37, 99, 235), 3)
        locked_pen = QPen(QColor(130, 130, 130), 2, Qt.DashLine)
        locked_selected_pen = QPen(QColor(160, 160, 160), 3, Qt.DashLine)
        deleted_pen = QPen(QColor(120, 120, 120), 2, Qt.DotLine)
        deleted_fill = QColor(110, 110, 110, 40)
        zone_pen = QPen(QColor(245, 158, 11), 2, Qt.DashLine)
        selected_zone_pen = QPen(QColor(234, 88, 12), 3)
        draft_pen = QPen(QColor(168, 85, 247), 2, Qt.DotLine)
        continuation_pen = QPen(QColor(220, 38, 38), 4)
        handle_brush = QColor(234, 88, 12, 150)
        visible_block_rects: dict[str, fitz.Rect] = {}
        for block in self._blocks_by_page.get(page_index + 1, []):
            bbox = block.get("bbox") or [0, 0, 0, 0]
            rect = fitz.Rect(bbox)
            scaled = fitz.Rect(rect.x0 * self._page_scale, rect.y0 * self._page_scale, rect.x1 * self._page_scale, rect.y1 * self._page_scale)
            block_id = str(block.get("id"))
            block_locked = bool((block.get("metadata") or {}).get("article_locked"))
            if (
                block_id in self._deleted_block_ids
                and block_id not in self._selected_block_ids
                and block_id != self._selected_block_id
            ):
                # A deleted article's blocks stay visible but recede: dotted
                # outline and a faint fill, so they read as present-but-skipped.
                painter.setPen(deleted_pen)
                painter.setBrush(deleted_fill)
            elif block_locked:
                painter.setPen(locked_selected_pen if block_id in self._selected_block_ids or block_id == self._selected_block_id else locked_pen)
            elif block_id == self._selected_block_id:
                painter.setPen(selected_pen)
            elif block_id in self._selected_block_ids:
                painter.setPen(multi_selected_pen)
            else:
                painter.setPen(base_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(int(scaled.x0), int(scaled.y0), int(scaled.width), int(scaled.height))
            visible_block_rects[block_id] = scaled
            self._regions.append({"id": block_id, "kind": "block", "rect": [scaled.x0, scaled.y0, scaled.x1, scaled.y1]})
            if block_id == self._selected_block_id and self._block_is_adjustable(block_id):
                painter.setBrush(handle_brush)
                handles = {
                    "top_left": (scaled.x0, scaled.y0),
                    "top_right": (scaled.x1, scaled.y0),
                    "bottom_left": (scaled.x0, scaled.y1),
                    "bottom_right": (scaled.x1, scaled.y1),
                }
                for handle_name, (hx, hy) in handles.items():
                    if "_piece_index" in block:
                        handle_name += f"@{block['_piece_index']}"
                    painter.drawRect(int(hx - 5), int(hy - 5), 10, 10)
                    self._regions.append(
                        {
                            "id": f"{block_id}:{handle_name}",
                            "kind": "block_handle",
                            "rect": [hx - 12, hy - 12, hx + 12, hy + 12],
                        }
                    )
        for zone in self._zones_by_page.get(page_index + 1, []):
            bbox = zone.get("bbox") or [0, 0, 0, 0]
            zone_id = str(zone.get("id"))
            zone_bboxes = zone.get("bboxes") or [bbox]
            scaled_union = fitz.Rect(bbox)
            scaled_union = fitz.Rect(
                scaled_union.x0 * self._page_scale,
                scaled_union.y0 * self._page_scale,
                scaled_union.x1 * self._page_scale,
                scaled_union.y1 * self._page_scale,
            )
            painter.setPen(selected_zone_pen if zone_id in self._selected_zone_ids else zone_pen)
            painter.setBrush(Qt.NoBrush)
            for zone_bbox in zone_bboxes:
                rect = fitz.Rect(zone_bbox)
                scaled = fitz.Rect(
                    rect.x0 * self._page_scale,
                    rect.y0 * self._page_scale,
                    rect.x1 * self._page_scale,
                    rect.y1 * self._page_scale,
                )
                painter.drawRect(int(scaled.x0), int(scaled.y0), int(scaled.width), int(scaled.height))
                self._regions.append(
                    {
                        "id": zone_id,
                        "kind": "zone",
                        "source": str(zone.get("source", "auto")),
                        "rect": [scaled.x0, scaled.y0, scaled.x1, scaled.y1],
                    }
                )
            if zone_id == self._selected_zone_id:
                painter.setBrush(handle_brush)
                handles = {
                    "top_left": (scaled_union.x0, scaled_union.y0),
                    "top_right": (scaled_union.x1, scaled_union.y0),
                    "bottom_left": (scaled_union.x0, scaled_union.y1),
                    "bottom_right": (scaled_union.x1, scaled_union.y1),
                }
                for handle_name, (hx, hy) in handles.items():
                    painter.drawRect(int(hx - 5), int(hy - 5), 10, 10)
                    self._regions.append(
                        {
                            "id": f"{zone_id}:{handle_name}",
                            "kind": "handle",
                            "rect": [hx - 12, hy - 12, hx + 12, hy + 12],
                        }
                    )
        if self._draft_zone_rect:
            rect = fitz.Rect(self._draft_zone_rect)
            scaled = fitz.Rect(rect.x0 * self._page_scale, rect.y0 * self._page_scale, rect.x1 * self._page_scale, rect.y1 * self._page_scale)
            painter.setPen(draft_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(int(scaled.x0), int(scaled.y0), int(scaled.width), int(scaled.height))
        if self._continuation_links:
            painter.setPen(continuation_pen)
            painter.setBrush(QBrush(QColor(220, 38, 38)))
            for source_id, target_id in self._continuation_links:
                source = visible_block_rects.get(source_id)
                target = visible_block_rects.get(target_id)
                if source is None or target is None:
                    continue
                start_x = source.x1
                start_y = source.y0 + source.height / 2
                end_x = target.x0
                end_y = target.y0 + target.height / 2
                if target.x0 <= source.x0:
                    start_x = source.x0 + source.width / 2
                    start_y = source.y1
                    end_x = target.x0 + target.width / 2
                    end_y = target.y0
                painter.drawLine(int(start_x), int(start_y), int(end_x), int(end_y))
                direction_x = 1 if end_x >= start_x else -1
                arrow_size = 12
                points = [
                    QPointF(end_x, end_y),
                    QPointF(end_x - direction_x * arrow_size, end_y - arrow_size / 2),
                    QPointF(end_x - direction_x * arrow_size, end_y + arrow_size / 2),
                ]
                painter.drawPolygon(points)
        painter.end()
        label.setProperty("blockRegions", self._regions)
        label.setPixmap(pixmap)
