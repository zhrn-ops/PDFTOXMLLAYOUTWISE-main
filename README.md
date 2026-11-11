# PDF to XML (Elsevier ANI/CAR) converter

Desktop and headless conversion of scientific PDFs into Elsevier ANI/CAR XML.
The desktop app lets reviewers correct block roles, article boundaries, authors,
affiliations, and the generated XML before export.

Despite the `pdf_to_jats` package name, the generator emits **Elsevier ANI/CAR**,
not JATS. See `docs/xml_export.md` for the validation and export contract.

## Requirements

- Python 3.11+ (developed and tested on 3.14)
- Windows is the primary desktop target; the core and CLI are platform-neutral
- Runtime: `PySide6`, `PyMuPDF`, `lxml` (installed from `requirements.txt`)
- Optional: `docling` for structural enrichment. The extractor falls back to
  PyMuPDF alone when Docling is absent.

```bash
python -m pip install -r requirements.txt
# or, without the optional Docling backend:
python -m pip install "PySide6>=6.6,<7" "PyMuPDF>=1.24,<2" "lxml>=5,<7"
```

## Run the desktop app

```bash
python pdf_to_jats/main.py
```

`run.ps1` and `run.bat` locate a Python interpreter and launch the same entry
point. `run.ps1` prefers `C:\venvs\p313`; edit it if your environment differs.

OpenRouter credentials are read only from `OPENROUTER_API_KEY`. File-stored
keys are ignored with a migration warning; remove any old `api_key` entry from
`output/openrouter_settings.json` after configuring the environment variable.
Settings saves never write credentials, including through the legacy opt-in.

## Batch conversion

```bash
python pdf_to_jats/cli.py paper.pdf -o output/batch
python pdf_to_jats/cli.py "papers/*.pdf" --flat
python pdf_to_jats/cli.py C:/path/to/folder
```

Each PDF gets its own output folder unless `--flat` is given. A conversion that
writes no XML is reported as a failure and exits nonzero. Batch mode never
opens a modal dialog.

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Tests deny external network access by default (`tests/conftest.py`). No test
requires a live LLM, GROBID, or publisher service. `pytest-timeout` enforces a
180-second per-test limit so a modal regression fails instead of hanging CI.

Install test dependencies with:

```bash
python -m pip install -e ".[test]"
```

## XML validation and schema status

The application reports XML syntax, schema, and semantic results separately:
`WELL_FORMED` / `NOT_WELL_FORMED` and `SCHEMA_VALID` / `SCHEMA_INVALID` /
`SCHEMA_UNAVAILABLE`.

**No authoritative publisher schema is bundled.** Draft Export may write
provisional XML and states that publisher validation is incomplete. Validated
Export requires an explicitly selected local schema bundle and refuses to write
otherwise. A missing schema is never reported as valid.

## Repository layout

- `pdf_to_jats/core/` — extraction, layout, classification, linking, XML
  generation/validation/correction, atomic I/O, revisions
- `pdf_to_jats/gui/` — PySide6 desktop application
- `pdf_to_jats/llm/` — local Ollama first, OpenRouter fallback
- `pdf_to_jats/models/` — domain models
- `tests/` — unit, integration, GUI, schema, scientific, and recovery tests
- `docs/` — export contract and audit reports

## Known limitations

- Real-paper extraction/layout accuracy is not measured by the synthetic test
  suite; a reviewed PDF corpus is still needed.
- The Classify button has been removed. See
  `docs/audit/06_remediation.md` for the updated audit status.
- Country normalization covers ISO names/codes and a curated alias table; it
  now includes UK constituent countries, but genuinely unknown values still
  require review.

## Scientific quality assurance

The independent offline evaluator compares saved XML with approved references,
reports accuracy and coverage, and compares benchmark runs. See
[Scientific QA](docs/scientific_qa.md) for corpus review, CLI commands, metric
definitions, synthetic examples, and limitations. No real reviewed corpus is
bundled, so the examples make no real-world accuracy claim.
