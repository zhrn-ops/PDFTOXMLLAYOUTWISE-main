"""Read-only evaluation of pinned artifacts; conversion is never invoked."""
import json
import math
from datetime import date
from pathlib import Path
from lxml import etree
from . import __version__, CONTRACT_VERSION
from .adapters import adapt
from .corpus import load_release, require, artifact
from .metrics import evaluate
from .normalization import POLICY
from .readers import read_json, read_artifact, sha256, canonical, local_path
from .reporting import aggregate


def validate_annotations(value, alignment=False):
    require(isinstance(value, dict), "Annotations must be an object")
    allowed = {"matches", "candidate_groups", "entities", "candidate_math_spans", "reviewer", "date", "reference_sha256", "candidate_sha256"} if alignment else {"reference_groups", "math_spans", "order_pairs", "xml_order_reviewed", "note"}
    require(set(value) <= allowed, "Unsupported annotation field")
    if "xml_order_reviewed" in value:
        require(isinstance(value["xml_order_reviewed"], bool), "Order approval must be boolean")
    for key in ("matches", "order_pairs"):
        if key in value:
            require(isinstance(value[key], list) and all(isinstance(p, list) and len(p) == 2 and
                    all(isinstance(k, str) for k in p) for p in value[key]), "Invalid annotation pairs")
    for key in ("reference_groups", "candidate_groups"):
        if key in value:
            require(isinstance(value[key], list), "Groups must be a list")
            for group in value[key]:
                require(isinstance(group, dict) and isinstance(group.get("key"), str)
                        and isinstance(group.get("units"), list) and all(isinstance(k, str) for k in group["units"]), "Invalid group")
    for key in ("math_spans", "candidate_math_spans"):
        if key in value:
            require(isinstance(value[key], list) and all(isinstance(s, dict) and isinstance(s.get("unit"), str)
                    and isinstance(s.get("start"), int) and isinstance(s.get("end"), int) for s in value[key]), "Invalid math spans")
    if "entities" in value:
        require(isinstance(value["entities"], dict) and set(value["entities"]) <= {"authors", "affiliations"}, "Invalid entity mapping")
        for pairs in value["entities"].values():
            require(isinstance(pairs, list) and all(isinstance(p, list) and len(p) == 2 and
                    all(isinstance(k, str) for k in p) for p in pairs), "Invalid entity pairs")
    return value


def evaluator_hash():
    root = Path(__file__).parent
    return sha256(b"".join(str(p.relative_to(root)).replace("\\", "/").encode() + b"\0" + p.read_bytes()
                          for p in sorted(root.rglob("*.py"))))


def performance(record, article, prediction, converter):
    require(record.get("source") == "external_conversion_benchmark", "Performance must come from a separate conversion benchmark")
    require(record.get("pdf_sha256") == article["pdf"]["sha256"] and
            record.get("candidate_sha256") == prediction["xml"]["sha256"], "Performance artifact hashes differ")
    require(record.get("converter") == converter, "Performance converter identity differs")
    require(isinstance(record.get("measurement_method"), str) and record["measurement_method"], "Performance method required")
    for field in ("conversion_seconds", "peak_rss_bytes"):
        value = record.get(field)
        require(value is None or isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value >= 0, "Invalid performance measurement")
    return record


def schema_check(data, record, base):
    if record is None:
        return {"well_formedness": "WELL_FORMED", "schema_status": "SCHEMA_UNAVAILABLE"}
    from pdf_to_jats.core.xml_validation import SchemaProfile, validate_xml
    artifact(record)
    read_artifact(base, record)
    pinned = {str(local_path(base, record["path"])): record["sha256"]}
    for dependency in record.get("resources", []):
        artifact(dependency)
        read_artifact(base, dependency)
        pinned[str(local_path(base, dependency["path"]))] = dependency["sha256"]
    require(record.get("format") in {"JATS", "ANI"}, "Invalid schema format")
    result = validate_xml(data, SchemaProfile(record.get("name", "QA explicit profile"), record["format"], local_path(base, record["path"])))
    require(all(pinned.get(str(Path(path).resolve())) == digest for path, digest in result.schema_resources),
            "Schema dependency not pinned or hash differs; list all schema resources")
    return {"well_formedness": result.well_formedness.value, "schema_status": result.schema_status.value,
            "schema_resources": list(result.schema_resources),
            "issues": [i.message for i in result.schema_issues]}


def run(manifest_path, predictions_path):
    manifest, predictions = load_release(manifest_path), read_json(predictions_path)
    require(isinstance(predictions, dict), "Predictions must be an object")
    require(predictions.get("contract_version") == CONTRACT_VERSION, "Unsupported prediction contract")
    converter = predictions.get("converter", {})
    require(isinstance(converter, dict), "Converter provenance must be an object")
    require(all(isinstance(converter.get(k), str) and converter[k].strip() for k in ("build_id", "commit")), "Converter build_id and commit required")
    require(isinstance(converter.get("dirty"), bool), "Converter dirty flag required")
    if converter["dirty"]:
        require(isinstance(converter.get("source_sha256"), str) and len(converter["source_sha256"]) == 64,
                "Dirty converter builds require a source fingerprint")
    entries = predictions.get("articles", [])
    require(isinstance(entries, list), "Prediction articles must be a list")
    by_id = {}
    valid_ids = {a["id"] for a in manifest["articles"]}
    for prediction in entries:
        require(isinstance(prediction, dict), "Prediction entry must be an object")
        require(prediction.get("id") in valid_ids and prediction["id"] not in by_id, "Duplicate or unknown prediction article ID")
        by_id[prediction["id"]] = prediction
    base, pred_base = Path(manifest_path).parent, Path(predictions_path).parent
    articles = []
    for article in manifest["articles"]:
        result = {"id": article["id"], "language": article.get("language", "und"),
                  "category": article.get("category", "unspecified"), "scope": article["scope"],
                  "reference_sha256": article["reference"]["sha256"], "pdf_sha256": article["pdf"]["sha256"],
                  "review": article["review"], "status": "input_error", "coverage_gate_passed": False}
        try:
            pdf = read_artifact(base, article["pdf"])
            require(pdf.startswith(b"%PDF-"), "Source artifact is not a PDF")
            reference_data = read_artifact(base, article["reference"])
            reference = adapt(reference_data, article["format"], article.get("selector"))
            result["reference_validation"] = schema_check(reference_data, article.get("schema"), base)
            if article["review"]["status"] != "approved":
                result.update(status="unreviewed", error="Reference is not approved; no accuracy calculated")
                articles.append(result)
                continue
            annotations = {}
            if "annotations" in article:
                annotations = validate_annotations(json.loads(read_artifact(base, article["annotations"])))
            prediction = by_id.get(article["id"])
            if prediction is None:
                from .models import Document
                candidate = Document(reference.format, [], {}, {}, set(), [], etree.Element(reference.tree.tag))
                result.update(evaluate(reference, candidate, annotations))
                result.update(status="missing_candidate", error="No candidate XML supplied")
            else:
                artifact(prediction.get("xml"))
                candidate_data = read_artifact(pred_base, prediction["xml"])
                candidate = adapt(candidate_data, prediction.get("format"), prediction.get("selector"))
                result["candidate_sha256"] = sha256(candidate_data)
                result["candidate_validation"] = schema_check(candidate_data, prediction.get("schema"), pred_base)
                if "alignment" in prediction:
                    alignment = validate_annotations(json.loads(read_artifact(pred_base, prediction["alignment"])), alignment=True)
                    require(alignment.get("reference_sha256") == article["reference"]["sha256"]
                            and alignment.get("candidate_sha256") == prediction["xml"]["sha256"], "Alignment hashes differ")
                    require(alignment.get("reviewer") and alignment.get("date"), "Alignment review required")
                    date.fromisoformat(alignment["date"])
                    for field in ("matches", "candidate_groups", "entities", "candidate_math_spans"):
                        if field in alignment:
                            annotations[field] = alignment[field]
                result.update(evaluate(reference, candidate, annotations))
                if "performance" in prediction:
                    result["performance"] = performance(json.loads(read_artifact(pred_base, prediction["performance"])), article, prediction, converter)
                result["status"] = "evaluated"
                fraction = result["coverage"]["evaluated_fraction"]
                result["coverage_gate_passed"] = fraction is not None and fraction >= manifest.get("coverage_threshold", .95)
                values = {"authors": result["metrics"]["affiliations"]["author_coverage"],
                          "affiliations": result["metrics"]["affiliations"]["affiliation_coverage"],
                          "reading_order": result["metrics"]["reading_order"]["coverage"]}
                result["additional_coverage_gates"] = {
                    key: {"threshold": minimum, "value": values[key],
                          "passed": values[key] is not None and values[key] >= minimum}
                    for key, minimum in manifest.get("coverage_thresholds", {}).items()}
                result["coverage_gate_passed"] &= all(v["passed"] for v in result["additional_coverage_gates"].values())
            result["coverage_threshold"] = manifest.get("coverage_threshold", .95)
        except (OSError, ValueError, KeyError, TypeError, etree.LxmlError) as exc:
            # A bad article must not stop the batch or be credited with a score.
            result = {k: v for k, v in result.items() if k not in {"metrics", "coverage", "critical_errors", "differences"}}
            result.update(status="input_error", error=str(exc), coverage_gate_passed=False)
        articles.append(result)
    report = {"contract_version": CONTRACT_VERSION, "evaluator_version": __version__, "evaluator_sha256": evaluator_hash(),
              "normalization_policy": POLICY, "corpus_id": manifest["corpus_id"], "manifest_version": manifest["manifest_version"],
              "manifest_sha256": manifest["release_sha256"], "predictions_sha256": sha256(canonical(predictions)),
              "corpus_kind": manifest["kind"], "converter": converter,
              "accuracy_claim": "Synthetic evaluator demonstration only" if manifest["kind"] == "synthetic" else "Accuracy only for the supplied approved reference scope",
              "articles": articles, "aggregate": aggregate(articles),
              "performance_note": "Only supplied external conversion measurements; evaluator runtime is not conversion time"}
    report["groups"] = {field: {value: aggregate([a for a in articles if a[field] == value])
                                for value in sorted({a[field] for a in articles})} for field in ("language", "category")}
    report["run_id"] = sha256(canonical(report))
    return report
