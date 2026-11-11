"""Detect and preserve inline superscript and subscript runs in PDF text."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable


_ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La "
    "Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi "
    "Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt "
    "Ds Rg Cn Nh Fl Mc Lv Ts Og".split()
)

# These are ordinary clinical/measurement tokens. Protecting the complete
# token prevents font-size variation inside a unit (for example kUA/L) from
# being interpreted as chemical script formatting.
_PROTECTED_UNITS = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:kUA/L|UA/L|IU/mL|mIU/mL|kU/L|U/L|mg/dL|g/dL|g/L|"
    r"mmol/L|umol/L|µmol/L|μmol/L|ng/mL|pg/mL|µg/mL|μg/mL|mmHg|mL/min|L/min|CFU/mL)"
    r"(?![A-Za-z0-9])"
)


# Script labels are not always a bare number: author affiliation markers
# (1,2 / a,b / 1-3), corresponding-author symbols (*, dagger) and charge
# suffixes (2+) all occur, and rejecting them threw away the geometry that
# proved they were raised or lowered.
_SCRIPT_TOKEN = re.compile(
    r"[0-9A-Za-z*\u2020\u2021\u00a7\u00b6#]+(?:[,\-\u2013\u2014;][0-9A-Za-z*\u2020\u2021\u00a7\u00b6#]+)*[+\-\u2212]?"
    r"|[+\-\u2212](?:[0-9]+|[*\u2020\u2021\u00a7\u00b6#])"
)


def normalize_inline_runs(
    text: str, runs: Iterable[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    """Collapse whitespace and remap runs; discard stale or mismatched offsets."""

    normalized_chars: list[str] = []
    old_to_new: list[int] = [-1] * len(text)
    for old_index, char in enumerate(text):
        if ord(char) < 0x20 and char not in "\t\n\r":
            continue
        if char.isspace():
            if normalized_chars:
                if normalized_chars[-1] != " ":
                    normalized_chars.append(" ")
                old_to_new[old_index] = len(normalized_chars) - 1
            continue
        normalized_chars.append(char)
        old_to_new[old_index] = len(normalized_chars) - 1
    if normalized_chars and normalized_chars[-1] == " ":
        normalized_chars.pop()
    normalized = "".join(normalized_chars)

    mapped: list[dict[str, Any]] = []
    for run in runs:
        try:
            start, end = int(run["start"]), int(run["end"])
            kind = str(run.get("type", run.get("kind", "")))
        except (KeyError, TypeError, ValueError):
            continue
        if kind not in {"sup", "sub"} or not (0 <= start < end <= len(text)):
            continue
        expected = run.get("text")
        if expected is not None and text[start:end] != str(expected):
            continue
        mapped_start = old_to_new[start]
        mapped_end = old_to_new[end - 1] + 1
        if mapped_start < 0 or mapped_end <= mapped_start:
            continue
        item = dict(run)
        item.update(start=mapped_start, end=mapped_end, type=kind, text=normalized[mapped_start:mapped_end])
        mapped.append(item)
    return normalized, _non_overlapping(mapped)


def join_text_and_runs(
    parts: Iterable[tuple[str, Iterable[dict[str, Any]]]], separator: str
) -> tuple[str, list[dict[str, Any]]]:
    """Join normalized text fragments and shift each fragment's inline runs."""

    texts: list[str] = []
    combined: list[dict[str, Any]] = []
    cursor = 0
    for text, runs in parts:
        normalized, normalized_runs = normalize_inline_runs(text, runs)
        if not normalized:
            continue
        if texts:
            texts.append(separator)
            cursor += len(separator)
        texts.append(normalized)
        for run in normalized_runs:
            item = dict(run)
            item["start"] = int(item["start"]) + cursor
            item["end"] = int(item["end"]) + cursor
            combined.append(item)
        cursor += len(normalized)
    return "".join(texts), _non_overlapping(combined)


def preserve_matching_runs(
    old_text: str, new_text: str, runs: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep only inline styles whose complete source text survives an edit."""

    equal_ranges = [
        (i1, i2, j1)
        for tag, i1, i2, j1, _j2 in SequenceMatcher(
            a=old_text, b=new_text, autojunk=False
        ).get_opcodes()
        if tag == "equal"
    ]
    mapped: list[dict[str, Any]] = []
    for run in runs:
        try:
            start, end = int(run["start"]), int(run["end"])
            expected = str(run.get("text", old_text[start:end]))
            kind = str(run.get("type", run.get("kind", "")))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if kind not in {"sup", "sub"} or not (0 <= start < end <= len(old_text)):
            continue
        if old_text[start:end] != expected:
            continue
        for old_start, old_end, new_start in equal_ranges:
            if old_start <= start and end <= old_end:
                item = dict(run)
                item.update(start=new_start + start - old_start, end=new_start + end - old_start)
                mapped.append(item)
                break
    return _non_overlapping(mapped)


def shift_trimmed_runs(
    text: str, runs: Iterable[dict[str, Any]], left_trim: int, right_end: int, offset: int
) -> list[dict[str, Any]]:
    """Copy runs that survive trimming a text fragment into a joined string."""

    result = []
    for run in runs:
        try:
            start, end = int(run["start"]), int(run["end"])
            kind = str(run.get("type", run.get("kind", "")))
        except (KeyError, TypeError, ValueError):
            continue
        if kind not in {"sup", "sub"} or start < left_trim or end > right_end or start >= end:
            continue
        expected = run.get("text")
        if expected is not None and text[start:end] != str(expected):
            continue
        item = dict(run)
        item.update(start=offset + start - left_trim, end=offset + end - left_trim, type=kind)
        item["text"] = text[start:end]
        result.append(item)
    return result


def _non_overlapping(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate identical annotations and keep the most trusted on overlaps."""

    priority = {"geometry": 0, "font_flag": 0, "lexicon": 1}
    unique: dict[tuple[int, int, str], dict[str, Any]] = {}
    for run in runs:
        key = (int(run["start"]), int(run["end"]), str(run["type"]))
        previous = unique.get(key)
        if previous is None or priority.get(str(run.get("source", "")), 2) < priority.get(str(previous.get("source", "")), 2):
            unique[key] = run
    ordered = sorted(unique.values(), key=lambda run: (int(run["start"]), int(run["end"])))
    kept: list[dict[str, Any]] = []
    for run in ordered:
        if kept and int(run["start"]) < int(kept[-1]["end"]):
            continue
        kept.append(run)
    return kept


class InlineScriptDetector:
    """Mark inline script runs using span geometry first and text rules second."""

    def detect(self, text: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not text:
            return []
        protected = [match.span() for match in _PROTECTED_UNITS.finditer(text)]

        def is_protected(start: int, end: int) -> bool:
            return any(start < right and end > left for left, right in protected)

        span_positions: list[tuple[dict[str, Any], int, int]] = []
        cursor = 0
        for span in spans:
            span_text = str(span.get("text", ""))
            if not span_text:
                continue
            start = text.find(span_text, cursor)
            if start < 0:
                continue
            end = start + len(span_text)
            span_positions.append((span, start, end))
            cursor = end

        ordinary_sizes = [
            float(span.get("size", 0.0) or 0.0)
            for span, start, end in span_positions
            if float(span.get("size", 0.0) or 0.0) > 0
            and not re.fullmatch(r"[\d+\-−]+", text[start:end].strip())
        ]
        reference_size = max(ordinary_sizes, default=max(
            (float(span.get("size", 0.0) or 0.0) for span, _, _ in span_positions), default=0.0
        ))
        def baseline_of(span: dict[str, Any]) -> float:
            origin = span.get("origin") or [0.0, (span.get("bbox") or [0, 0, 0, 0])[3]]
            return float(origin[1])

        # Only body-sized spans may define the baseline. A label that is only
        # slightly smaller (9.2pt on a 10pt line) used to qualify as "body",
        # so a one-span line took its raised baseline as the reference and
        # then matched itself as normal text.
        baselines = [
            baseline_of(span)
            for span, _, _ in span_positions
            if float(span.get("size", 0.0) or 0.0) >= reference_size * 0.98
        ]
        if not baselines:
            baselines = [baseline_of(span) for span, _, _ in span_positions]
        reference_baseline = sorted(baselines)[len(baselines) // 2] if baselines else 0.0

        runs: list[dict[str, Any]] = []
        for span, start, end in span_positions:
            value = text[start:end]
            script_text = value.strip()
            if not script_text:
                continue
            # Geometry can identify letter scripts too; protected units only
            # allow through spans with a pronounced vertical shift.
            if not _SCRIPT_TOKEN.fullmatch(script_text):
                continue
            size = float(span.get("size", 0.0) or 0.0)
            origin = span.get("origin") or [0.0, reference_baseline]
            baseline = float(origin[1]) if len(origin) > 1 else reference_baseline
            delta = baseline - reference_baseline
            flags = int(span.get("flags", 0) or 0)
            kind = ""
            source = "geometry"
            strong_geometric_shift = False
            if flags & 1:
                kind = "sup"
                source = "font_flag"
            elif size > 0 and size < reference_size * 0.95:
                # Publishers do not shrink every script by the same amount; a
                # 9.2pt label on a 10pt line is still raised. Close-to-body
                # sizes therefore demand a decisive baseline shift, while a
                # clear size drop is enough evidence together with a small one.
                if size < reference_size * 0.88:
                    threshold = max(0.8, reference_size * 0.12)
                else:
                    threshold = max(1.2, reference_size * 0.25)
                if delta < -threshold:
                    kind = "sup"
                elif delta > threshold:
                    kind = "sub"
                strong_geometric_shift = bool(kind and abs(delta) >= reference_size * 0.25)
            if is_protected(start, end) and not strong_geometric_shift:
                continue
            if kind:
                left = start + len(value) - len(value.lstrip())
                right = end - (len(value) - len(value.rstrip()))
                runs.append({"start": left, "end": right, "type": kind, "text": text[left:right], "source": source})

        runs.extend(self._lexical_runs(text, protected))
        return _non_overlapping(runs)

    def _lexical_runs(self, text: str, protected: list[tuple[int, int]]) -> list[dict[str, Any]]:
        def protected_overlap(start: int, end: int) -> bool:
            return any(start < right and end > left for left, right in protected)

        result: list[dict[str, Any]] = []

        def add(start: int, end: int, kind: str) -> None:
            if start < end and not protected_overlap(start, end):
                result.append({"start": start, "end": end, "type": kind, "text": text[start:end], "source": "lexicon"})

        def parts(value: str):
            found = list(re.finditer(r"([A-Z][a-z]?)(\d*)", value))
            if not found or "".join(item.group(0) for item in found) != value:
                return None
            return found if all(item.group(1) in _ELEMENTS for item in found) else None

        # In compact ionic notation the charge magnitude follows the formula
        # count (SO42- means SO4 with a 2- charge). Resolve common polyatomic
        # ions before the general formula matcher can consume both digits as a
        # single subscript.
        special_ions = re.compile(
            r"(?<![A-Za-z0-9])(Cr2O7|CrO4|SO4|CO3|PO4)([23])([+\-−])(?![\u00adA-Za-z0-9])"
        )
        special_ranges = []
        for match in special_ions.finditer(text):
            formula_parts = parts(match.group(1)) or []
            for element in formula_parts:
                if element.group(2):
                    add(match.start(1) + element.start(2), match.start(1) + element.end(2), "sub")
            add(match.start(2), match.end(3), "sup")
            special_ranges.append(match.span())

        def in_special_range(start: int, end: int) -> bool:
            return any(start < right and end > left for left, right in special_ranges)

        formula = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][a-z]?\d*){2,}(?![A-Za-z0-9])")
        for match in formula.finditer(text):
            if protected_overlap(*match.span()) or in_special_range(*match.span()):
                continue
            elements = parts(match.group())
            if elements:
                for element in elements:
                    if element.group(2):
                        add(match.start() + element.start(2), match.start() + element.end(2), "sub")

        # Clinical notation commonly writes these as a compact gas/oxygen
        # token; the prefix is not a chemical element sequence, but the final
        # numeral is still a subscript (FiO2, PaO2, PaCO2, SpO2, and EtCO2).
        clinical_formula = re.compile(
            r"(?<![A-Za-z0-9])(?:FiO|PaO|PaCO|SpO|SaO|EtCO)(\d+)(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        for match in clinical_formula.finditer(text):
            add(match.start(1), match.end(1), "sub")

        # Some PDF fonts expose titanium dioxide as all-caps TIO2 rather than
        # its conventional mixed-case spelling TiO2.
        for match in re.finditer(r"(?<![A-Za-z0-9])TIO(2)(?![A-Za-z0-9])", text):
            add(match.start(1), match.end(1), "sub")

        # Compact monatomic charges (Ca2+) and polyatomic charges (SO4-).
        # A soft hyphen (U+00AD) after the sign means the PDF broke a
        # hyphenated word ("TiO2-\u00adenriched"), not an ionic charge, so it
        # must not satisfy the word boundary.
        ion = re.compile(r"(?<![A-Za-z0-9])((?:[A-Z][a-z]?\d*)+)([+\-−])(?![\u00adA-Za-z0-9])")
        for match in ion.finditer(text):
            if in_special_range(*match.span()):
                continue
            elements = parts(match.group(1))
            if not elements or protected_overlap(*match.span()):
                continue
            if len(elements) == 1 and elements[-1].group(2):
                add(match.start(1) + elements[-1].start(2), match.end(2), "sup")
            else:
                for element in elements:
                    if element.group(2):
                        add(match.start(1) + element.start(2), match.start(1) + element.end(2), "sub")
                add(match.start(2), match.end(2), "sup")

        simple_ion = re.compile(r"(?<![A-Za-z0-9])([A-Z][a-z]?)([+\-−])(?![\u00adA-Za-z0-9])")
        for match in simple_ion.finditer(text):
            if match.group(1) in _ELEMENTS:
                add(match.start(2), match.end(2), "sup")

        # Superscript powers for units; do not style ordinary ranges such as
        # 10-3 unless a recognized measurement unit follows.
        for match in re.finditer(r"(?<![A-Za-z0-9])(?:mm|cm|km|mL|kg|m|L|s)([23])(?![A-Za-z0-9])", text):
            add(match.start(1), match.end(1), "sup")
        exponent = re.compile(
            r"(?<![A-Za-z0-9])10\s*([+\-−]\d+)"
            r"(?=\s*(?:mol(?:es?)?(?:\s*/\s*(?:L|kg|m3))?|mM|uM|µM|μM|M\b|"
            r"mg\s*/\s*(?:mL|dL)|g\s*/\s*L|k?Pa|mmHg|mL\s*/\s*min|L\s*/\s*min)(?![A-Za-z]))"
        )
        for match in exponent.finditer(text):
            add(match.start(1), match.end(1), "sup")
        return result
