"""Deterministic aggregation and exclusive report output."""
import csv
import json
from pathlib import Path
from .models import prf, ratio
from .metrics import CRITICAL


def aggregate(articles):
    scored = [a for a in articles if "metrics" in a]
    result = {"article_count": len(articles), "scored_articles": len(scored),
              "failed_articles": sum(a["status"] != "evaluated" for a in articles),
              "coverage_gate_passed": bool(articles) and all(a.get("coverage_gate_passed", False) for a in articles),
              "critical_errors": {k: sum(a["critical_errors"][k] for a in scored) for k in CRITICAL},
              "metrics": {}}
    total = sum(a["coverage"]["reference_characters"] for a in scored)
    matched = sum(a["coverage"]["matched_characters"] for a in scored)
    result["coverage"] = {"reference_characters": total, "matched_characters": matched,
                          "evaluated_fraction": ratio(matched, total),
                          "articles_with_unknown_denominator": len(articles) - len(scored)}
    for metric in ("characters", "normalized_characters", "tokens", "math_symbols"):
        values = [a["metrics"][metric] for a in scored]
        rates = [v["error_rate"] for v in values if v["error_rate"] is not None]
        errors = sum(v["errors"] for v in values)
        count = sum(v["reference_count"] for v in values)
        result["metrics"][metric] = {"errors": errors, "reference_count": count,
                                       "error_rate": ratio(errors, count),
                                       "macro_error_rate": ratio(sum(rates), len(rates)), "macro_articles": len(rates)}
    for metric in ("scripts", "affiliations"):
        counts = {k: sum(a["metrics"][metric][k] for a in scored) for k in ("tp", "fp", "fn")}
        result["metrics"][metric] = prf(**counts)
    result["metrics"]["scripts"]["by_type"] = {
        kind: prf(**{k: sum(a["metrics"]["scripts"]["by_type"][kind][k] for a in scored)
                     for k in ("tp", "fp", "fn")}) for kind in ("sup", "sub")}
    result["metrics"]["scripts"]["characters"] = prf(**{
        k: sum(a["metrics"]["scripts"]["characters"][k] for a in scored) for k in ("tp", "fp", "fn")})
    roles = sorted({r for a in scored for r in a["metrics"]["roles"]})
    result["metrics"]["roles"] = {r: prf(**{k: sum(a["metrics"]["roles"].get(r, {}).get(k, 0)
                                                     for a in scored) for k in ("tp", "fp", "fn")}) for r in roles}
    order = [a["metrics"]["reading_order"] for a in scored if "comparable_pairs" in a["metrics"]["reading_order"]]
    correct = sum(o["correct"] for o in order)
    comparable = sum(o["comparable_pairs"] for o in order)
    expected = sum(o["expected_pairs"] for o in order)
    result["metrics"]["reading_order"] = {"accuracy": ratio(correct, comparable), "correct": correct,
                                               "comparable_pairs": comparable, "expected_pairs": expected,
                                               "coverage": ratio(comparable, expected), "reviewed_articles": len(order)}
    exact = sum(a["metrics"]["exact_units"]["correct"] for a in scored)
    units = sum(a["metrics"]["exact_units"]["reference_count"] for a in scored)
    result["metrics"]["exact_units"] = {"correct": exact, "reference_count": units, "accuracy": ratio(exact, units)}
    counts = [a["metrics"]["xml_structure"]["difference_count"] for a in scored
              if a["metrics"]["xml_structure"]["difference_count"] is not None]
    result["metrics"]["xml_structure"] = {"difference_count": sum(counts) if counts else None,
                                              "comparable_articles": len(counts)}
    return result


def flatten(value, prefix=""):
    result = {}
    for key, child in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(flatten(child, name))
        elif child is None or isinstance(child, (str, int, float, bool)):
            result[name] = child
    return result


def write_csv(path, rows):
    fields = sorted({key for row in rows for key in row})
    with Path(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            # CSV is often opened in spreadsheets; preserve values without formula execution.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                             for k, v in row.items()})


def write_report(report, destination, formats=("json", "csv")):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    if "json" in formats:
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if "csv" in formats:
        write_csv(destination / "articles.csv", [flatten({k: v for k, v in article.items() if k not in {"differences", "xml_structure"}})
                                                 for article in report["articles"]])
        write_csv(destination / "aggregate.csv", [flatten(report["aggregate"])])
        rows = []
        for article in report["articles"]:
            for diff in article.get("differences", []):
                rows.append({"article_id": article["id"], **{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in diff.items()}})
        write_csv(destination / "differences.csv", rows)
