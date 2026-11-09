# Baseline test results and audit probes

Date: 2026-11-09. The baseline below is preserved from Phases 0–1. Approved Phase 2 verification is recorded in [phase_02_implementation.md](phase_02_implementation.md): **488 passed in 22.79 seconds**, including 36 new regression cases.

## Existing automated suite

`python -m compileall -q pdf_to_jats tests` completed with exit 0. No syntax errors were printed.

Successful PowerShell invocation (fresh GUID-named directory each run):

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$auditTemp = Join-Path (Get-Location) ('output\audit-tests-' + [guid]::NewGuid().ToString('N'))
python -m pytest -q tests -p no:cacheprovider --basetemp $auditTemp --tb=short
```

This run needed approved execution outside the restricted sandbox because Python-created pytest temporary directories were inaccessible inside it. It used the same installed Python/dependencies and unchanged tests.

**452 passed in 18.44 seconds; 0 failed, 0 errors, 0 skipped; no warnings reported; exit 0.**

Earlier attempts are recorded in `00_baseline_report.md`: default discovery had 1 collection error and 2 cache warnings; explicit `tests/` had 346 passes and 106 temp-directory setup errors; changing basetemp alone did not resolve sandbox permissions. These failures are retained as evidence, not reclassified as application assertions.

Tests added or changed: **none**. Existing failing tests deleted/skipped: **none**. Source fixes: **none**. A full per-file collected-test count and module listing is recorded in `repository_inventory.md`.

## Executed targeted audit probes

These short API-level experiments supplement the suite. They demonstrate current behavior; they are **not newly passing regression tests**. All XML and write-failure content was synthetic. No actual source XML was overwritten. The temporary audit XML file was removed after use.

| Probe | Observed result | Finding |
|---|---|---|
| Legacy validator with metadata-complete article and nonexistent XSD | `[]` | A01 |
| Same document through correction validation | `info: XML is well-formed`; `info: Schema validation unavailable...`; existing GUI status expression evaluates to `Valid` | A01 |
| Bind CLI's `wait=True` call to actual loader | `TypeError: MainWindow._load_pdf_path() got an unexpected keyword argument 'wait'` | A05 |
| ISO-8859-1 title through `xml_text()` then `from_text()` | `'Caf\xe9'` → `'Caf\xc3\xa9'` | A02 |
| Adjacent inline formula through session serialization | `'H2O'` → `'\nH\n2\nO\n'` | A03 |
| Space-separated inline text through session serialization | `'A B'` → `'\nA\nB\n'` | A03 |
| Generator with an accepted `xn` body paragraph and matching geometry `sub` run for `n` | 0 `ce:inf` elements | A06 |
| Generator write patched to write 10 bytes then raise disk-full OSError | Previous destination replaced by `b'<?xml vers'` | A04 |

The CLI probe establishes the signature defect without running extraction, network calls or GUI dialogs. The GUI status probe evaluates its exact status rule from produced issues; it is not a manual interactive UI acceptance test. The interrupted-write probe injects failure rather than filling the user's disk.

## Required follow-up validation

Promote the reproduction cases into regressions only with the approved fixes. Add secure profile-specific schema tests, strict vs draft export tests, non-UTF-8 workspace/history transitions, mixed-content structural comparisons, transport failures and cancellation. The existing passing suite already checks corrected draft retention, conflict refusal/archive, source protection, missing raw parse recovery, numeric scripts and external-entity non-resolution; preserve that coverage.

No official publisher validation, live provider integration, performance benchmark, vulnerability scan or cross-version build was executed. No claims are made for those gates.
