"""Conservative, role-blind unit alignment and exact bounded edit distance."""
from difflib import SequenceMatcher
from .normalization import normalized
from .models import Unit

MAX_EDIT_CELLS = 4_000_000


def group_units(units, groups):
    """Explicit reviewed split/merge correspondences; never silently merge units."""
    by_key = {u.key: i for i, u in enumerate(units)}
    replacements, consumed = {}, set()
    for group in groups or []:
        indices = [by_key[key] for key in group["units"]]
        if not indices or indices != list(range(indices[0], indices[0] + len(indices))) or consumed.intersection(indices):
            raise ValueError("Groups must be disjoint, contiguous, ordered units")
        if group["key"] in by_key or group["key"] in {u.key for u in replacements.values()}:
            raise ValueError("Group keys must be new and unique")
        members = [units[i] for i in indices]
        if len({(u.role, u.section) for u in members}) != 1:
            raise ValueError("Cannot group distinct roles or sections")
        separator = group.get("separator", " ")
        if separator not in {"", " ", "\n"}:
            raise ValueError("Unsupported group separator")
        text, scripts, math = "", [], []
        for member in members:
            if text:
                text += separator
            offset = len(text)
            scripts.extend((a + offset, b + offset, kind) for a, b, kind in member.scripts)
            math.extend((a + offset, b + offset) for a, b in member.math)
            text += member.text
        replacements[indices[0]] = Unit(group["key"], members[0].role, text, scripts, math, members[0].section)
        consumed.update(indices)
    return [replacements[i] if i in replacements else unit for i, unit in enumerate(units)
            if i not in consumed or i in replacements]


def edits(reference, candidate):
    """Levenshtein alignment with stable tie breaking: equal, replace, delete, add."""
    n, m = len(reference), len(candidate)
    if reference == candidate:
        return [("equal", i, i) for i in range(n)]
    if n * m > MAX_EDIT_CELLS:
        raise ValueError("Edit alignment exceeds cell limit; split long units with reviewed annotations")
    trace = [bytearray(m + 1) for _ in range(n + 1)]
    previous = list(range(m + 1))
    for j in range(1, m + 1):
        trace[0][j] = 3
    for i in range(1, n + 1):
        row = [i] + [0] * m
        trace[i][0] = 2
        for j in range(1, m + 1):
            same = reference[i - 1] == candidate[j - 1]
            costs = (previous[j - 1] + (not same), previous[j] + 1, row[j - 1] + 1)
            choice = min(range(3), key=lambda k: costs[k])
            row[j] = costs[choice]
            trace[i][j] = (0 if same else 1) if choice == 0 else choice + 1
        previous = row
    result, i, j = [], n, m
    while i or j:
        code = trace[i][j]
        if code in (0, 1):
            i -= 1
            j -= 1
            result.append(("equal" if code == 0 else "replace", i, j))
        elif code == 2:
            i -= 1
            result.append(("delete", i, j))
        else:
            j -= 1
            result.append(("insert", i, j))
    return list(reversed(result))


def align(reference, candidate, explicit=None):
    """Unique exact matches, then reciprocal unique fuzzy matches (>= .55).

    Repeated or tied text stays unmatched unless explicit correspondences exist.
    Roles and position are deliberately excluded from matching.
    """
    pairs, used_r, used_c = [], set(), set()
    rkeys = {u.key: i for i, u in enumerate(reference)}
    ckeys = {u.key: i for i, u in enumerate(candidate)}
    for pair in explicit or []:
        r, c = rkeys[pair[0]], ckeys[pair[1]]
        if r in used_r or c in used_c:
            raise ValueError("Correspondences must be one-to-one")
        pairs.append((r, c)); used_r.add(r); used_c.add(c)
    scores = {}
    if len(reference) * len(candidate) > 250_000:
        raise ValueError("Too many units for alignment")
    for r, ru in enumerate(reference):
        if r in used_r:
            continue
        for c, cu in enumerate(candidate):
            if c in used_c:
                continue
            a, b = normalized(ru.text), normalized(cu.text)
            if a and b:
                if a != b and len(a) * len(b) > MAX_EDIT_CELLS:
                    raise ValueError("Text matching exceeds cell limit; use reviewed smaller units")
                score = SequenceMatcher(None, a, b, autojunk=False).ratio()
                if score >= .55:
                    scores[r, c] = score
    def best(items):
        if not items:
            return None
        value = max(v for _, v in items)
        winners = [k for k, v in items if v == value]
        return winners[0] if len(winners) == 1 else None
    for r in range(len(reference)):
        c = best([(c, v) for (rr, c), v in scores.items() if rr == r])
        if c is not None and best([(rr, v) for (rr, cc), v in scores.items() if cc == c]) == r:
            pairs.append((r, c)); used_r.add(r); used_c.add(c)
    return sorted(pairs), sorted(set(range(len(reference))) - used_r), sorted(set(range(len(candidate))) - used_c)
