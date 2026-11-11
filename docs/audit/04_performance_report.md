# Phase 6 — Performance report

Snapshot: **2026-11-11**, commit baseline `612f395` plus the remediation changes in `05_final_engineering_review.md`.

Measurements were taken with `.bench/audit_bench.py`, which is reproducible:

```bash
python .bench/audit_bench.py
```

Timings are `time.perf_counter()` medians (5 runs for fast operations, 2 for extraction). Memory is `tracemalloc` peak for the Python side only; lxml/libmupdf C allocations are not fully represented. No optimization was applied before measuring, and **no speedup is claimed**.

## Environment and input

| Item | Value |
|---|---|
| OS | Windows, Git Bash |
| CPU / RAM | Not recorded by this audit |
| Python | 3.14.2 |
| PyMuPDF | 1.27.2.3 |
| lxml | 6.0.2 |
| Benchmark PDF | `.bench/big.pdf` — 319 KB, **12 pages**, 43,956 extracted characters |
| XML fixture | 400 body paragraphs, 40 authors, 12 affiliations, 1 title/abstract; 176 KB output |

The PDF is a small internal benchmark document, not a representative 50–500-page scientific corpus. Results are indicative only.

## Results

| Operation | Median | Notes |
|---|---|---|
| PDF open (`fitz.open`) | **0.69 ms** | 12 pages; file metadata only |
| Text extraction, all pages (`page.get_text()`) | **48.3 ms** | ~4.0 ms/page |
| Raster, first 5 pages at 3× (`Matrix(3,3)`) | **42.1 ms** | ~8.4 ms/page |
| Full extraction, `visible_text_only=False` | **0.129 s** | 804 blocks, traced peak **1.8 MB** |
| Full extraction, `visible_text_only=True` | **0.227 s** | 804 blocks, traced peak **10.0 MB** |
| XML generation (`to_bytes`, 400 paragraphs) | **50.4 ms** | 175,679 bytes; traced peak 0.2 MB |
| XML validation (`validate_xml`, no schema) | **2.1 ms** | `WELL_FORMED` + `SCHEMA_UNAVAILABLE` |
| Correction session parse | **0.67 ms** | 176 KB document |
| Correction session serialize | **4.5 ms** | 176 KB document |
| Generate + atomic write | **56.8 ms** | ~6 ms over in-memory generation |

## Observations

1. **PDF open and text extraction are not the bottleneck** on this document. Opening is sub-millisecond; text extraction is ~48 ms for 12 pages.
2. **The visible-ink check roughly doubles extraction time and increases traced peak memory about 5.5×** (0.129 s → 0.227 s; 1.8 MB → 10.0 MB). This is expected: `visible_text_only=True` rasterizes each page and inspects ink. The check removes hidden/OCR-layer text, so it is a correctness feature, not waste. It should not be changed without evidence from a reviewed corpus (R01); the measured absolute cost is small at this scale.
3. **Rasterization is ~8.4 ms/page at 3×** for this vector-text PDF. The page raster worker reopens the PDF per page (static inspection), but open costs only ~0.7 ms, so reopening is not the dominant term. This does not justify a shared raster service yet.
4. **XML generation dominates the export path**: ~50 ms for 400 paragraphs and 40 authors. Atomic write adds ~6 ms. Both are acceptable for interactive export; a 2,000-paragraph article would need re-measurement.
5. **Validation without a schema is cheap (~2 ms)** because it performs well-formedness, entity, and semantic checks only. **Schema-validation performance could not be measured**: no authoritative ANI/CAR schema is present (C11). Any claim about schema-validation cost would be unsupported.
6. **Traced XML peak (0.2 MB) understates real memory** because lxml allocates outside Python’s allocator. Do not treat it as peak RSS.

## Not measured

- GUI event-loop latency, frame paint time, or perceived responsiveness (including the synchronous Classify call, C08).
- Peak process RSS (`psutil`) and memory growth over repeated loads; no leak conclusion is possible.
- 50–500-page documents, scanned/image-only PDFs, or table-heavy papers.
- GROBID, Ollama, and OpenRouter latency (no live calls were made; network is denied in tests).
- Schema-validation time against a real publisher schema.
- Repeated-load caching behavior of the viewer’s LRU cache under real scrolling.

## Recommendations

- **Do not optimize the ink-visibility path** without a corpus proving hidden-text removal is dispensable. Its cost is measurable but modest and it protects scientific accuracy.
- **Measure before changing raster scheduling.** The 3× matrix and per-page reopen are candidates, but open overhead is ~0.7 ms and raster is ~8 ms/page here.
- **Re-run this benchmark on representative 50–500-page papers and record peak RSS** before any caching or shared-render-service work (R02).
- **Add schema benchmarks only after C11** supplies a pinned ANI/CAR schema.
- If GUI responsiveness work (C08) is approved, add frame-latency measurement around the Classify action; this report does not cover it.
