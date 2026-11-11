"""Contracts, provenance, aggregate arithmetic, CLI, and run comparisons."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from pdf_to_jats.qa.corpus import freeze_manifest, load_release
from pdf_to_jats.qa.readers import sha256, canonical
from pdf_to_jats.qa.evaluator import run, performance
from pdf_to_jats.qa.reporting import aggregate, write_report
from pdf_to_jats.qa.comparison import compare
from pdf_to_jats.qa.cli import main


def put(path, data):
    if not isinstance(data, bytes):
        data = canonical(data)
    path.write_bytes(data)
    return {"path": path.name, "sha256": sha256(data)}


@pytest.fixture
def corpus(tmp_path):
    pdf = put(tmp_path / "synthetic.pdf", b"%PDF-1.4\n% synthetic contract fixture only\n")
    reference = put(tmp_path / "reference.xml", b"<article><article-title>Scientific title</article-title><body><p>H<sub>2</sub>O</p></body></article>")
    candidate = put(tmp_path / "candidate.xml", (tmp_path / "reference.xml").read_bytes())
    annotations = put(tmp_path / "annotations.json", {"xml_order_reviewed": True})
    manifest = {"contract_version": 1, "corpus_id": "synthetic-tests", "manifest_version": "1",
                "kind": "synthetic", "coverage_threshold": .95, "articles": [
        {"id": "a", "pdf": pdf, "reference": reference, "format": "JATS", "annotations": annotations,
         "scope": "Synthetic title and body", "review": {"status": "approved", "reviewer": "synthetic-test",
         "date": "2026-11-11", "reference_version": "1", "reference_sha256": reference["sha256"], "ambiguities": []}}]}
    source, release = tmp_path / "draft.json", tmp_path / "release.json"
    put(source, manifest)
    freeze_manifest(source, release)
    predictions = {"contract_version": 1, "converter": {"build_id": "synthetic-1", "commit": "synthetic-fixture", "dirty": False},
                   "articles": [{"id": "a", "xml": candidate, "format": "JATS"}]}
    prediction_path = tmp_path / "predictions.json"
    put(prediction_path, predictions)
    return source, release, prediction_path, manifest, predictions


def test_freeze_is_exclusive_and_detects_tampering(corpus):
    source, release, _, manifest, _ = corpus
    with pytest.raises(FileExistsError):
        freeze_manifest(source, release)
    changed = json.loads(release.read_bytes())
    changed["coverage_threshold"] = 0
    put(release, changed)
    with pytest.raises(ValueError, match="modified"):
        load_release(release)


@pytest.mark.parametrize("change", ["hash", "reviewer", "date", "ambiguity", "duplicate", "threshold"])
def test_contract_rejects_invalid_reviews_and_inputs(corpus, change):
    source, release, _, manifest, _ = corpus
    review = manifest["articles"][0]["review"]
    if change == "hash": review["reference_sha256"] = "0" * 64
    if change == "reviewer": review["reviewer"] = ""
    if change == "date": review["date"] = "yesterday"
    if change == "ambiguity": review["ambiguities"] = [{"question": "unclear"}]
    if change == "duplicate": manifest["articles"].append(deepcopy(manifest["articles"][0]))
    if change == "threshold": manifest["coverage_threshold"] = 2
    put(source, manifest)
    with pytest.raises(ValueError):
        freeze_manifest(source, release.parent / "new.json")


def test_deterministic_run_and_report_files(corpus, tmp_path):
    _, release, predictions, _, _ = corpus
    a, b = run(release, predictions), run(release, predictions)
    assert a == b
    assert a["aggregate"]["coverage_gate_passed"]
    assert a["articles"][0]["candidate_validation"]["schema_status"] == "SCHEMA_UNAVAILABLE"
    assert "Synthetic" in a["accuracy_claim"]
    output = tmp_path / "report"
    write_report(a, output)
    assert {p.name for p in output.iterdir()} == {"report.json", "articles.csv", "aggregate.csv", "differences.csv"}
    with pytest.raises(FileExistsError):
        write_report(a, output)


def test_missing_candidates_are_failures_not_excluded(corpus):
    _, release, path, _, predictions = corpus
    predictions["articles"] = []
    put(path, predictions)
    report = run(release, path)
    assert report["aggregate"]["failed_articles"] == 1
    assert report["articles"][0]["metrics"]["characters"]["error_rate"] == 1
    assert report["aggregate"]["coverage"]["evaluated_fraction"] == 0


def test_hash_mismatch_is_per_article_error(corpus):
    _, release, path, _, _ = corpus
    (path.parent / "candidate.xml").write_text("<article/>")
    report = run(release, path)
    assert report["articles"][0]["status"] == "input_error"
    assert report["aggregate"]["coverage"]["articles_with_unknown_denominator"] == 1
    assert not report["aggregate"]["coverage_gate_passed"]


def test_unreviewed_reference_has_no_accuracy(corpus):
    source, _, path, manifest, _ = corpus
    manifest["articles"][0]["review"]["status"] = "in_review"
    manifest["manifest_version"] = "2"
    put(source, manifest)
    release = path.parent / "unreviewed.json"
    freeze_manifest(source, release)
    article = run(release, path)["articles"][0]
    assert article["status"] == "unreviewed" and "metrics" not in article


def test_micro_macro_aggregation_and_failed_gate(corpus):
    _, release, path, _, _ = corpus
    a = run(release, path)["articles"][0]
    b = deepcopy(a)
    a["metrics"]["characters"].update(errors=1, reference_count=10, error_rate=.1)
    b["metrics"]["characters"].update(errors=0, reference_count=90, error_rate=0)
    result = aggregate([a, b])
    assert result["metrics"]["characters"]["error_rate"] == .01
    assert result["metrics"]["characters"]["macro_error_rate"] == .05
    assert result["metrics"]["scripts"]["tp"] == 2
    assert result["metrics"]["roles"]["title"]["tp"] == 2
    assert result["metrics"]["exact_units"]["accuracy"] == 1
    assert result["metrics"]["xml_structure"]["difference_count"] == 0
    assert not aggregate([a, {"status": "input_error"}])["coverage_gate_passed"]
    assert aggregate([])["coverage"]["evaluated_fraction"] is None


def test_compare_detects_script_regression_and_improvement(corpus):
    _, release, path, _, predictions = corpus
    before = run(release, path)
    predictions["converter"]["build_id"] = "synthetic-2"
    predictions["articles"][0]["xml"] = put(path.parent / "candidate.xml", b"<article><article-title>Scientific title</article-title><body><p>H2O</p></body></article>")
    put(path, predictions)
    after = run(release, path)
    result = compare(before, after)
    assert result["regression_detected"]
    assert any(c["metric"] == "critical_errors.lost_script" and c["change"] == "regressed" for c in result["articles"][0]["changes"])
    assert not compare(after, before)["regression_detected"]
    assert not compare(before, before)["regression_detected"]


def test_comparison_rejects_incompatible_and_tampered_reports(corpus):
    _, release, path, _, _ = corpus
    report = run(release, path)
    other = deepcopy(report)
    other["manifest_version"] = "different"
    with pytest.raises(ValueError, match="integrity"):
        compare(report, other)
    other.pop("run_id")
    other["run_id"] = sha256(canonical(other))
    with pytest.raises(ValueError, match="Incompatible"):
        compare(report, other)


def test_performance_provenance_and_units(corpus):
    _, _, _, manifest, predictions = corpus
    article, prediction = manifest["articles"][0], predictions["articles"][0]
    record = {"source": "external_conversion_benchmark", "pdf_sha256": article["pdf"]["sha256"],
              "candidate_sha256": prediction["xml"]["sha256"], "converter": predictions["converter"],
              "measurement_method": "isolated process RSS sampled every 10 ms", "conversion_seconds": 1.5, "peak_rss_bytes": 1024}
    assert performance(record, article, prediction, predictions["converter"])["peak_rss_bytes"] == 1024
    for field, value in (("source", "evaluator"), ("peak_rss_bytes", -1), ("conversion_seconds", float("nan")), ("candidate_sha256", "bad")):
        changed = dict(record, **{field: value})
        with pytest.raises(ValueError):
            performance(changed, article, prediction, predictions["converter"])


def test_cli_evaluate_compare_and_overwrite_error(corpus, tmp_path):
    _, release, predictions, _, _ = corpus
    output = tmp_path / "cli"
    args = ["evaluate", "--manifest", str(release), "--predictions", str(predictions), "--output", str(output)]
    assert main(args) == 0
    assert main(args) == 2
    assert main(["compare", str(output / "report.json"), str(output / "report.json"), "--output", str(tmp_path / "comparison")]) == 0


def test_coverage_threshold_failure_is_not_accuracy_success(corpus):
    _, release, path, _, predictions = corpus
    predictions["articles"][0]["xml"] = put(path.parent / "candidate.xml", b"<article><article-title>Scientific title</article-title></article>")
    put(path, predictions)
    report = run(release, path)
    assert report["articles"][0]["status"] == "evaluated"
    assert not report["aggregate"]["coverage_gate_passed"]


def test_published_version_cannot_be_reused(corpus):
    source, release, _, manifest, _ = corpus
    manifest["coverage_threshold"] = .1
    put(source, manifest)
    with pytest.raises(ValueError, match="already published"):
        freeze_manifest(source, release.parent / "different-name.json")


def test_additional_coverage_gates_fail_when_metric_unavailable(corpus):
    source, _, path, manifest, _ = corpus
    manifest.update(manifest_version="2", coverage_thresholds={"authors": .9})
    put(source, manifest)
    release = path.parent / "v2.json"
    freeze_manifest(source, release)
    report = run(release, path)
    assert not report["aggregate"]["coverage_gate_passed"]
    assert report["articles"][0]["additional_coverage_gates"]["authors"]["value"] is None


def test_schema_validation_independent_of_semantic_accuracy(tmp_path):
    from pdf_to_jats.qa.evaluator import schema_check
    xsd = b'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="article"><xs:complexType><xs:sequence><xs:any minOccurs="0" maxOccurs="unbounded" processContents="skip"/></xs:sequence></xs:complexType></xs:element></xs:schema>'''
    record = {**put(tmp_path / "test.xsd", xsd), "format": "JATS"}
    result = schema_check(b'<article><p>Incorrect text can still be schema valid</p></article>', record, tmp_path)
    assert result["schema_status"] == "SCHEMA_VALID"
    assert "accuracy" not in result


def test_batch_continues_after_bad_article(corpus):
    source, _, path, manifest, predictions = corpus
    second = deepcopy(manifest["articles"][0]); second["id"] = "b"
    manifest["articles"].append(second); manifest["manifest_version"] = "2"
    put(source, manifest)
    release = path.parent / "v2.json"; freeze_manifest(source, release)
    prediction = deepcopy(predictions["articles"][0]); prediction["id"] = "b"
    predictions["articles"][0]["xml"]["sha256"] = "0" * 64
    predictions["articles"].append(prediction); put(path, predictions)
    result = run(release, path)
    assert [a["status"] for a in result["articles"]] == ["input_error", "evaluated"]


def test_performance_artifact_is_reported_separately(corpus):
    _, release, path, manifest, predictions = corpus
    article, prediction = manifest["articles"][0], predictions["articles"][0]
    perf = {"source": "external_conversion_benchmark", "pdf_sha256": article["pdf"]["sha256"],
            "candidate_sha256": prediction["xml"]["sha256"], "converter": predictions["converter"],
            "measurement_method": "external test fixture", "conversion_seconds": 2, "peak_rss_bytes": 4096}
    prediction["performance"] = put(path.parent / "performance.json", perf); put(path, predictions)
    report = run(release, path)
    assert report["articles"][0]["performance"]["conversion_seconds"] == 2
    assert "performance" not in report["articles"][0]["metrics"]


def test_comparison_failed_article_is_regression(corpus):
    _, release, path, _, predictions = corpus
    before = run(release, path)
    predictions["articles"] = []; put(path, predictions)
    assert compare(before, run(release, path))["regression_detected"]


def test_csv_formula_content_is_escaped(tmp_path):
    from pdf_to_jats.qa.reporting import write_csv
    path = tmp_path / "text.csv"
    write_csv(path, [{"text": "=1+1"}])
    assert "'=1+1" in path.read_text()


def test_synthetic_example_reports_detect_known_critical_errors():
    root = Path(__file__).resolve().parents[1] / "fixtures/qa"
    report = run(root / "synthetic.v1.json", root / "predictions.bad.json")
    assert report["aggregate"]["critical_errors"] == {
        "missing_scientific_content": 7, "incorrect_author_affiliation": 2,
        "corrupted_math_symbol": 2, "lost_script": 2, "missing_section": 1}
    good = run(root / "synthetic.v1.json", root / "predictions.good.json")
    assert good["aggregate"]["coverage_gate_passed"]
    assert all(v == 0 for v in good["aggregate"]["critical_errors"].values())
    assert not compare(report, good)["regression_detected"]


@pytest.mark.parametrize("value,alignment", [([], False), ({"matches": [["one"]]}, True),
    ({"xml_order_reviewed": "yes"}, False), ({"reference_groups": ["invalid"]}, False),
    ({"math_spans": [{"unit": "p", "start": "zero", "end": 2}]}, False),
    ({"entities": {"authors": [["one"]]}}, True), ({"unknown": 1}, False)])
def test_malformed_annotations_rejected(value, alignment):
    from pdf_to_jats.qa.evaluator import validate_annotations
    with pytest.raises(ValueError):
        validate_annotations(value, alignment)


@pytest.mark.parametrize("key,before,after,change", [
    ("characters.error_rate", .1, .2, "regressed"), ("scripts.f1", .5, .7, "improved"),
    ("critical_errors.lost_script", 1, 0, "improved"), ("xml_structure.difference_count", 0, 1, "regressed"),
    ("characters.error_rate", None, .2, "not_comparable"), ("count", 10, 20, "changed")])
def test_metric_delta_directions(key, before, after, change):
    from pdf_to_jats.qa.comparison import deltas
    assert deltas({key: before}, {key: after})[0]["change"] == change


def test_performance_regression_is_separate(corpus):
    _, release, path, _, _ = corpus
    a = run(release, path)
    b = deepcopy(a)
    for report, seconds in ((a, 1), (b, 2)):
        report["articles"][0]["performance"] = {"measurement_method": "external fixture", "conversion_seconds": seconds, "peak_rss_bytes": 100}
        report.pop("run_id")
        report["run_id"] = sha256(canonical(report))
    result = compare(a, b)
    assert result["performance_regression_detected"]
    assert not result["regression_detected"]


def test_schema_dependency_requires_pinned_hash(tmp_path):
    from pdf_to_jats.qa.evaluator import schema_check
    child = b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="article" type="xs:string"/></xs:schema>'
    put(tmp_path / "child.xsd", child)
    record = {**put(tmp_path / "entry.xsd", b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include schemaLocation="child.xsd"/></xs:schema>'), "format": "JATS"}
    with pytest.raises(ValueError, match="not pinned"):
        schema_check(b'<article/>', record, tmp_path)
    record["resources"] = [{"path": "child.xsd", "sha256": sha256(child)}]
    assert schema_check(b'<article/>', record, tmp_path)["schema_status"] == "SCHEMA_VALID"
