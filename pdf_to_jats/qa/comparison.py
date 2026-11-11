"""Compare only compatible, integrity-checked evaluation reports."""
from .readers import canonical, sha256
from .reporting import flatten


def verify(report):
    copy = dict(report)
    digest = copy.pop("run_id", None)
    if digest != sha256(canonical(copy)):
        raise ValueError("Report integrity check failed")


def deltas(before, after):
    a, b = flatten(before), flatten(after)
    rows = []
    for key in sorted(a.keys() | b.keys()):
        x, y = a.get(key), b.get(key)
        if isinstance(x, bool) or isinstance(y, bool):
            continue
        numeric = isinstance(x, (float, int)) and isinstance(y, (float, int))
        if not numeric and x is not None and y is not None:
            continue
        direction = "lower" if key.startswith("critical_errors.") or key.endswith(("error_rate", ".errors", ".fp", ".fn", ".inversions", "difference_count", "conversion_seconds", "peak_rss_bytes")) else "higher" if key.endswith((".precision", ".recall", ".f1", ".accuracy", ".coverage", "evaluated_fraction", "supported_fraction")) else None
        delta = y - x if numeric else None
        change = "not_comparable" if delta is None else "unchanged" if delta == 0 else "changed"
        if delta and direction:
            change = "improved" if (delta < 0) == (direction == "lower") else "regressed"
        rows.append({"metric": key, "before": x, "after": y, "delta": delta, "change": change})
    return rows


def compare(before, after):
    verify(before); verify(after)
    for key in ("contract_version", "corpus_id", "manifest_version", "manifest_sha256", "evaluator_version", "evaluator_sha256", "normalization_policy"):
        if before[key] != after[key]:
            raise ValueError(f"Incompatible benchmark runs: {key}")
    old, new = ({a["id"]: a for a in r["articles"]} for r in (before, after))
    if old.keys() != new.keys():
        raise ValueError("Article sets differ")
    articles = []
    for key in sorted(old):
        a, b = old[key], new[key]
        old_perf, new_perf = a.get("performance", {}), b.get("performance", {})
        perf_comparable = bool(old_perf and new_perf and old_perf.get("measurement_method") == new_perf.get("measurement_method"))
        articles.append({"id": key, "before_status": a["status"], "after_status": b["status"],
                         "performance_changes": deltas({k: old_perf.get(k) for k in ("conversion_seconds", "peak_rss_bytes")},
                                                       {k: new_perf.get(k) for k in ("conversion_seconds", "peak_rss_bytes")}) if perf_comparable else [],
                         "performance_comparable": perf_comparable,
                         "coverage_gate_before": a["coverage_gate_passed"], "coverage_gate_after": b["coverage_gate_passed"],
                         "changes": deltas({k: a.get(k, {}) for k in ("metrics", "coverage", "critical_errors")},
                                           {k: b.get(k, {}) for k in ("metrics", "coverage", "critical_errors")})})
    aggregate_changes = deltas(before["aggregate"], after["aggregate"])
    return {"before_run": before["run_id"], "after_run": after["run_id"],
            "before_converter": before["converter"], "after_converter": after["converter"],
            "aggregate_changes": aggregate_changes, "articles": articles,
            "performance_regression_detected": any(c["change"] == "regressed" for a in articles for c in a["performance_changes"]),
            "regression_detected": any(c["change"] == "regressed" for c in aggregate_changes)
                or any(c["change"] == "regressed" for a in articles for c in a["changes"])
                or any(a["coverage_gate_before"] and not a["coverage_gate_after"]
                       or a["before_status"] == "evaluated" and a["after_status"] != "evaluated" for a in articles)}
