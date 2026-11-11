"""Deterministic metrics with counts, coverage, and localized critical errors."""
from collections import Counter
from dataclasses import replace
import unicodedata
from lxml import etree
from .alignment import align, edits, group_units
from .models import prf, ratio
from .normalization import normalized

CRITICAL = ("missing_scientific_content", "incorrect_author_affiliation", "corrupted_math_symbol",
            "lost_script", "missing_section")


def text_metric(a, b):
    operations = edits(a, b)
    counts = Counter(op for op, _, _ in operations)
    return {"reference_count": len(a), "candidate_count": len(b),
            "substitutions": counts["replace"], "deletions": counts["delete"],
            "insertions": counts["insert"], "errors": len(operations) - counts["equal"],
            "error_rate": ratio(len(operations) - counts["equal"], len(a))}, operations


def reading_order(pairs, expected=None):
    mapping = dict(pairs)
    eligible = expected if expected is not None else [(a, b) for a in sorted(mapping) for b in sorted(mapping) if a < b]
    evaluated = [(a, b) for a, b in eligible if a in mapping and b in mapping]
    correct = sum(mapping[a] < mapping[b] for a, b in evaluated)
    return {"correct": correct, "comparable_pairs": len(evaluated), "expected_pairs": len(eligible),
            "accuracy": ratio(correct, len(evaluated)), "inversions": len(evaluated) - correct,
            "coverage": ratio(len(evaluated), len(eligible))}


def entity_map(reference, candidate, explicit=None):
    result = dict(explicit or [])
    if len(result) != len(explicit or []) or len(set(result.values())) != len(result) or any(a not in reference or b not in candidate for a, b in result.items()):
        raise ValueError("Invalid entity correspondence")
    for key, value in reference.items():
        if key in result:
            continue
        matches = [k for k, v in candidate.items() if normalized(v) == normalized(value) and value.strip()]
        if len(matches) == 1 and sum(normalized(v) == normalized(value) for v in reference.values()) == 1:
            if matches[0] not in result.values():
                result[key] = matches[0]
    return result


def affiliation_metric(reference, candidate, annotations=None):
    annotations = annotations or {}
    authors = entity_map(reference.authors, candidate.authors, annotations.get("authors"))
    affs = entity_map(reference.affiliations, candidate.affiliations, annotations.get("affiliations"))
    matched = {(authors[a], affs[f]) for a, f in reference.edges if a in authors and f in affs} & candidate.edges
    tp = len(matched)
    return {**prf(tp, len(candidate.edges) - tp, len(reference.edges) - tp),
            "author_coverage": ratio(len(authors), len(reference.authors)),
            "affiliation_coverage": ratio(len(affs), len(reference.affiliations)),
            "unmatched_reference_authors": sorted(set(reference.authors) - authors.keys()),
            "unmatched_reference_affiliations": sorted(set(reference.affiliations) - affs.keys()),
            "missing_edges": sorted((a, f) for a, f in reference.edges if (authors.get(a), affs.get(f)) not in candidate.edges),
            "added_edges": sorted(candidate.edges - matched)}


def script_metric(a, b, operations):
    equal = {i: j for op, i, j in operations if op == "equal"}
    mapped = set()
    for start, end, kind in a.scripts:
        indices = [equal.get(i) for i in range(start, end)]
        if indices and None not in indices and indices == list(range(indices[0], indices[0] + len(indices))):
            mapped.add((indices[0], indices[-1] + 1, kind))
    expected, actual = set(a.scripts), set(b.scripts)
    tp = len(mapped & actual)
    result = prf(tp, len(actual) - tp, len(expected) - tp)
    result["by_type"] = {kind: prf(len({s for s in mapped & actual if s[2] == kind}),
                                    len({s for s in actual - mapped if s[2] == kind}),
                                    sum(s[2] == kind for s in expected) - len({s for s in mapped & actual if s[2] == kind}))
                         for kind in ("sup", "sub")}
    rchars = {(i, kind) for start, end, kind in a.scripts for i in range(start, end)}
    cchars = {(i, kind) for start, end, kind in b.scripts for i in range(start, end)}
    mapped_chars = {(equal[i], kind) for i, kind in rchars if i in equal}
    char_tp = len(mapped_chars & cchars)
    result["characters"] = prf(char_tp, len(cchars) - char_tp, len(rchars) - char_tp)
    return result


def symbol_indices(unit):
    return {i for i, char in enumerate(unit.text) if unicodedata.category(char) == "Sm"
            or "GREEK" in unicodedata.name(char, "")
            or any(a <= i < b for a, b in unit.math) and not char.isspace()}


def structural_diff(a, b):
    differences = []
    def walk(x, y, path):
        def tag(node):
            return node.tag if isinstance(node.tag, str) else "#comment" if isinstance(node, etree._Comment) else "#pi:" + node.target
        if tag(x) != tag(y):
            differences.append({"kind": "element", "path": path, "reference": tag(x), "candidate": tag(y)})
        if dict(x.attrib) != dict(y.attrib):
            differences.append({"kind": "attributes", "path": path, "reference": dict(x.attrib), "candidate": dict(y.attrib)})
        for field in ("text", "tail"):
            left, right = getattr(x, field), getattr(y, field)
            # All inline whitespace is retained; indentation is also visible here.
            if (left or "") != (right or ""):
                differences.append({"kind": field, "path": path, "reference": left, "candidate": right})
        for i in range(max(len(x), len(y))):
            child_path = f"{path}/{i + 1}"
            if i >= len(x) or i >= len(y):
                differences.append({"kind": "added_node" if i >= len(x) else "missing_node", "path": child_path})
            else:
                walk(x[i], y[i], child_path)
    walk(a, b, "/")
    return differences


def evaluate(reference, candidate, annotations=None):
    annotations = annotations or {}
    reference = replace(reference, units=group_units(reference.units, annotations.get("reference_groups")))
    candidate = replace(candidate, units=group_units(candidate.units, annotations.get("candidate_groups")))
    for document, field in ((reference, "math_spans"), (candidate, "candidate_math_spans")):
        units = {u.key: u for u in document.units}
        # Copy units before adding annotations; callers can reuse parsed documents.
        updated = {key: replace(unit, math=list(unit.math)) for key, unit in units.items()}
        for span in annotations.get(field, []):
            unit = updated[span["unit"]]
            start, end = span["start"], span["end"]
            if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(unit.text):
                raise ValueError("Invalid reviewed mathematical span")
            unit.math.append((start, end))
        document.units = [updated[u.key] for u in document.units]
    pairs, missing, added = align(reference.units, candidate.units, annotations.get("matches"))
    ledger, critical = [], dict.fromkeys(CRITICAL, 0)
    totals = {name: Counter() for name in ("characters", "normalized_characters", "tokens")}
    scripts = Counter(tp=0, fp=0, fn=0)
    script_types = {kind: Counter(tp=0, fp=0, fn=0) for kind in ("sup", "sub")}
    script_characters = Counter(tp=0, fp=0, fn=0)
    roles = {}
    confusion = Counter()
    math_ref = math_errors = 0
    def difference(kind, r, c, **extra):
        ledger.append({"kind": kind, "reference_path": r.key if r else None,
                       "candidate_path": c.key if c else None, **extra})
    all_pairs = [(reference.units[r], candidate.units[c]) for r, c in pairs]
    from .models import Unit
    all_pairs += [(reference.units[r], Unit("", "missing", "")) for r in missing]
    all_pairs += [(Unit("", "added", ""), candidate.units[c]) for c in added]
    for r, c in all_pairs:
        operations = None
        for name, a, b in (("characters", r.text, c.text),
                           ("normalized_characters", normalized(r.text), normalized(c.text)),
                           ("tokens", normalized(r.text).split(), normalized(c.text).split())):
            metric, ops = text_metric(a, b)
            totals[name].update({k: v for k, v in metric.items() if k != "error_rate"})
            if name == "characters":
                operations = ops
        if r.role != "added" or c.role != "missing":
            confusion[r.role, c.role] += 1
        for role in {r.role, c.role} - {"missing", "added"}:
            counts = roles.setdefault(role, Counter(tp=0, fp=0, fn=0))
            if r.role == c.role:
                counts["tp"] += 1
            elif role == r.role:
                counts["fn"] += 1
            else:
                counts["fp"] += 1
        sm = script_metric(r, c, operations)
        scripts.update({k: sm[k] for k in ("tp", "fp", "fn")})
        for kind in script_types:
            script_types[kind].update({k: sm["by_type"][kind][k] for k in ("tp", "fp", "fn")})
        script_characters.update({k: sm["characters"][k] for k in ("tp", "fp", "fn")})
        critical["lost_script"] += sm["fn"]
        ri, ci = symbol_indices(r), symbol_indices(c)
        math_ref += len(ri)
        for op, i, j in operations:
            if op == "equal":
                continue
            before = r.text[i] if op != "insert" else ""
            after = c.text[j] if op != "delete" else ""
            difference(op, r, c, reference_offset=i, candidate_offset=j, reference=before, candidate=after)
            if op == "delete" and before.strip():
                critical["missing_scientific_content"] += 1
            if op != "insert" and i in ri or op != "delete" and j in ci:
                math_errors += 1
                difference("math_symbol", r, c, reference=before, candidate=after)
        if sm["fn"] or sm["fp"]:
            difference("script", r, c, reference=r.scripts, candidate=c.scripts)
        if r.key and not c.key:
            difference("missing_unit", r, None, reference=r.text)
            if r.role in {"section", "title", "abstract"}:
                critical["missing_section"] += 1
        if c.key and not r.key:
            difference("added_unit", None, c, candidate=c.text)
        if r.key and c.key and r.section != c.section:
            difference("section_hierarchy", r, c, reference=r.section, candidate=c.section)
    for name, counts in totals.items():
        counts = dict(counts)
        counts["error_rate"] = ratio(counts.get("errors", 0), counts.get("reference_count", 0))
        totals[name] = counts
    aff = affiliation_metric(reference, candidate, annotations.get("entities"))
    for kind, edges in (("missing_author_affiliation", aff["missing_edges"]), ("added_author_affiliation", aff["added_edges"])):
        ledger.extend({"kind": kind, "author_id": a, "affiliation_id": f} for a, f in edges)
    for side, items in (("reference", reference.unsupported), ("candidate", candidate.unsupported)):
        ledger.extend({"kind": "unsupported_" + side, "path": item["path"], "text": item["text"], "scored": False} for item in items)
    critical["incorrect_author_affiliation"] = aff["fp"] + aff["fn"]
    critical["corrupted_math_symbol"] = math_errors
    supported = sum(len(u.text) for u in reference.units)
    unsupported = sum(len(u["text"]) for u in reference.unsupported)
    matched = sum(len(reference.units[r].text) for r, c in pairs)
    keys = {u.key: i for i, u in enumerate(reference.units)}
    expected = annotations.get("order_pairs")
    if expected is not None:
        expected = [(keys[a], keys[b]) for a, b in expected]
        if len(set(expected)) != len(expected) or any(a == b for a, b in expected):
            raise ValueError("Duplicate/self reading-order constraint")
        remaining = set(keys.values())
        while remaining:
            ready = {n for n in remaining if not any(b == n and a in remaining for a, b in expected)}
            if not ready:
                raise ValueError("Cyclic reading-order constraints")
            remaining -= ready
    elif annotations.get("xml_order_reviewed"):
        expected = [(a, b) for a in range(len(reference.units)) for b in range(a + 1, len(reference.units))]
    order = reading_order(pairs, expected) if expected is not None else {"accuracy": None, "coverage": None, "reason": "Reading order not reviewed"}
    for a, b in pairs:
        if a != b:
            difference("position_changed", reference.units[a], candidate.units[b], reference_position=a, candidate_position=b)
    structure = structural_diff(reference.tree, candidate.tree) if reference.format == candidate.format else None
    exact_units = sum(reference.units[r].text == candidate.units[c].text for r, c in pairs)
    return {"metrics": {**totals, "roles": {k: prf(**v) for k, v in sorted(roles.items())},
                        "exact_units": {"correct": exact_units, "reference_count": len(reference.units),
                                        "accuracy": ratio(exact_units, len(reference.units))},
                        "xml_structure": {"difference_count": len(structure) if structure is not None else None},
                        "confusion": [{"reference": a, "candidate": b, "count": n} for (a, b), n in sorted(confusion.items())],
                        "scripts": {**prf(**scripts), "by_type": {k: prf(**v) for k, v in script_types.items()},
                                    "characters": prf(**script_characters)}, "affiliations": aff, "reading_order": order,
                        "math_symbols": {"reference_count": math_ref, "errors": math_errors, "error_rate": ratio(math_errors, math_ref)}},
            "coverage": {"reference_characters": supported + unsupported, "supported_characters": supported,
                         "matched_characters": matched, "evaluated_fraction": ratio(matched, supported + unsupported),
                         "supported_fraction": ratio(supported, supported + unsupported),
                         "matched_units": len(pairs), "reference_units": len(reference.units)},
            "critical_errors": critical, "differences": ledger,
            "unsupported_reference": reference.unsupported, "unsupported_candidate": candidate.unsupported,
            "warnings": reference.warnings + candidate.warnings,
            "xml_structure": {"comparable": reference.format == candidate.format,
                              "differences": structure or [],
                              "reason": None if reference.format == candidate.format else "Different XML families; use semantic metrics"}}
