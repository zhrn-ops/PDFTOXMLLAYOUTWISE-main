"""Offline corpus freezing, evaluation, and run comparison."""
import argparse
import json
from pathlib import Path
import sys
from .corpus import freeze_manifest
from .evaluator import run
from .comparison import compare
from .readers import read_json
from .reporting import write_report, write_csv


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m pdf_to_jats.qa")
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze", help="Validate and seal a new immutable corpus manifest")
    freeze.add_argument("source", type=Path); freeze.add_argument("destination", type=Path)
    evaluate = sub.add_parser("evaluate", help="Evaluate existing candidate XML; never runs conversion")
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--predictions", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--formats", default="json,csv", choices=("json", "csv", "json,csv"))
    comparison = sub.add_parser("compare", help="Compare compatible benchmark reports")
    comparison.add_argument("before", type=Path); comparison.add_argument("after", type=Path)
    comparison.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            print(freeze_manifest(args.source, args.destination))
            return 0
        if args.command == "evaluate":
            report = run(args.manifest, args.predictions)
            write_report(report, args.output, args.formats.split(","))
            print(json.dumps({"run_id": report["run_id"], "articles": len(report["articles"]),
                              "failed": report["aggregate"]["failed_articles"],
                              "coverage_gate_passed": report["aggregate"]["coverage_gate_passed"]}))
            return 0 if report["aggregate"]["coverage_gate_passed"] and not report["aggregate"]["failed_articles"] else 1
        result = compare(read_json(args.before), read_json(args.after))
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        rows = [{"article_id": "__aggregate__", **c} for c in result["aggregate_changes"]]
        rows += [{"article_id": a["id"], **c} for a in result["articles"] for c in a["changes"]]
        rows += [{"article_id": a["id"], "category": "external_performance", **c} for a in result["articles"] for c in a["performance_changes"]]
        write_csv(args.output / "comparison.csv", rows)
        print(json.dumps({"regression_detected": result["regression_detected"]}))
        return 1 if result["regression_detected"] else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"QA input/output error: {exc}", file=sys.stderr)
        return 2
