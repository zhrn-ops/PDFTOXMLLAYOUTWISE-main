"""Synthetic arithmetic checks, not claims about real PDF accuracy."""
import pytest
from lxml import etree
from pdf_to_jats.qa.models import Unit, Document, prf
from pdf_to_jats.qa.metrics import (text_metric, reading_order, affiliation_metric,
                                  script_metric, structural_diff, evaluate)
from pdf_to_jats.qa.alignment import align, edits
from pdf_to_jats.qa.normalization import normalized


def document(units, **kwargs):
    return Document("JATS", units, kwargs.get("authors", {}), kwargs.get("affiliations", {}),
                    kwargs.get("edges", set()), kwargs.get("unsupported", []), etree.XML("<article/>"))


@pytest.mark.parametrize("a,b,s,d,i", [("abc", "abc", 0, 0, 0), ("abc", "axc", 1, 0, 0),
    ("abc", "ac", 0, 1, 0), ("abc", "abbc", 0, 0, 1), ("", "x", 0, 0, 1),
    ("x", "", 0, 1, 0), ("kitten", "sitting", 2, 0, 1)])
def test_edit_arithmetic(a, b, s, d, i):
    metric, _ = text_metric(a, b)
    assert (metric["substitutions"], metric["deletions"], metric["insertions"]) == (s, d, i)
    assert metric["error_rate"] == ((s+d+i)/len(a) if a else None)


def test_edit_bound_and_tie_break_are_deterministic(monkeypatch):
    assert edits("ab", "ba") == [("replace", 0, 0), ("replace", 1, 1)]
    monkeypatch.setattr("pdf_to_jats.qa.alignment.MAX_EDIT_CELLS", 1)
    with pytest.raises(ValueError, match="cell limit"):
        edits("ab", "ac")


def test_normalization_retains_scientific_distinctions():
    assert normalized("e\u0301  x\n") == "é x"
    assert normalized("− μ ²") != normalized("- u 2")


def test_role_blind_alignment_detects_reordering_and_wrong_roles():
    r = [Unit("a", "title", "Unique title"), Unit("b", "body", "Paragraph text")]
    c = [Unit("x", "abstract", "Paragraph text"), Unit("y", "body", "Unique title")]
    assert align(r, c) == ([(0, 1), (1, 0)], [], [])
    result = evaluate(document(r), document(c), {"xml_order_reviewed": True})
    assert result["metrics"]["reading_order"]["accuracy"] == 0
    assert result["metrics"]["roles"]["title"]["fn"] == 1
    assert result["metrics"]["roles"]["abstract"]["fp"] == 1


def test_ambiguous_duplicates_are_not_credited():
    units = [Unit("a", "body", "same"), Unit("b", "body", "same")]
    assert align(units, units) == ([], [0, 1], [0, 1])
    assert align(units, units, [["a", "a"], ["b", "b"]])[0] == [(0, 0), (1, 1)]
    with pytest.raises(ValueError, match="one-to-one"):
        align(units, units, [["a", "a"], ["a", "b"]])


def test_order_coverage_does_not_hide_missing_units():
    value = reading_order([(0, 0), (2, 1)], [(0, 1), (0, 2), (1, 2)])
    assert value["accuracy"] == 1
    assert value["coverage"] == pytest.approx(1/3)
    assert reading_order([])["accuracy"] is None


@pytest.mark.parametrize("candidate_scripts,tp,fp,fn", [([(1, 2, "sub")], 1, 0, 0),
    ([], 0, 0, 1), ([(1, 2, "sup")], 0, 1, 1), ([(0, 1, "sub")], 0, 1, 1)])
def test_script_precision_recall(candidate_scripts, tp, fp, fn):
    r = Unit("r", "body", "H2O", [(1, 2, "sub")])
    c = Unit("c", "body", "H2O", candidate_scripts)
    result = script_metric(r, c, edits(r.text, c.text))
    assert {k: result[k] for k in prf(tp, fp, fn)} == prf(tp, fp, fn)


def test_scripts_follow_character_alignment_after_insertion():
    r = Unit("r", "body", "H2O", [(1, 2, "sub")])
    c = Unit("c", "body", "aH2O", [(2, 3, "sub")])
    assert script_metric(r, c, edits(r.text, c.text))["tp"] == 1


def test_author_mapping_uses_entities_not_local_ids():
    r = document([], authors={"a": "Ada Lovelace"}, affiliations={"f": "Institute"}, edges={("a", "f")})
    c = document([], authors={"z": "Ada Lovelace"}, affiliations={"q": "Institute"}, edges={("z", "q")})
    assert affiliation_metric(r, c)["f1"] == 1
    c.edges = {("z", "wrong")}
    assert affiliation_metric(r, c)["fp"] == 1
    assert affiliation_metric(r, c)["fn"] == 1
    c.authors["duplicate"] = "Ada Lovelace"
    assert affiliation_metric(r, c)["author_coverage"] == 0


@pytest.mark.parametrize("before,after", [("x − y", "x - y"), ("a × b", "a x b"), ("μ = 2", "u = 2")])
def test_math_corruption(before, after):
    result = evaluate(document([Unit("r", "body", before)]), document([Unit("c", "body", after)]))
    assert result["critical_errors"]["corrupted_math_symbol"] == 1
    assert any(d["kind"] == "math_symbol" for d in result["differences"])


def test_missing_added_content_and_unsupported_coverage():
    r = document([Unit("a", "title", "Reference title"), Unit("b", "body", "Lost content")],
                 unsupported=[{"path": "/custom", "text": "unknown"}])
    c = document([Unit("a", "title", "Reference title"), Unit("z", "body", "ZZZZZZZZZZZZ")])
    result = evaluate(r, c)
    assert result["coverage"]["evaluated_fraction"] == len("Reference title") / (len("Reference titleLost contentunknown"))
    assert result["critical_errors"]["missing_scientific_content"] > 0
    assert {d["kind"] for d in result["differences"]} >= {"missing_unit", "added_unit"}
    assert result["metrics"]["reading_order"]["accuracy"] is None


def test_missing_section_and_zero_denominators():
    result = evaluate(document([Unit("s", "section", "Methods")]), document([]))
    assert result["critical_errors"]["missing_section"] == 1
    assert result["metrics"]["characters"]["error_rate"] == 1
    assert prf(0, 0, 0)["f1"] is None


@pytest.mark.parametrize("xml,kind", [("<p a='1'>x</p>", "attributes"), ("<p>y</p>", "text"),
    ("<q>x</q>", "element"), ("<p>x<b/></p>", "added_node")])
def test_xml_differences(xml, kind):
    assert kind in {d["kind"] for d in structural_diff(etree.XML("<p>x</p>"), etree.XML(xml))}


def test_xml_prefixes_do_not_matter_but_inline_spaces_do():
    assert structural_diff(etree.XML('<a:p xmlns:a="u">x</a:p>'), etree.XML('<b:p xmlns:b="u">x</b:p>')) == []
    assert structural_diff(etree.XML('<p><i>x</i> y</p>'), etree.XML('<p><i>x</i>y</p>'))[0]["kind"] == "tail"


def test_cross_format_structure_is_not_scored():
    r, c = document([]), document([])
    c.format = "ANI"
    assert evaluate(r, c)["xml_structure"]["comparable"] is False


def test_reviewed_split_merge_keeps_offsets():
    r = document([Unit("r", "body", "H2O flows", [(1, 2, "sub")])])
    c = document([Unit("c1", "body", "H2O", [(1, 2, "sub")]), Unit("c2", "body", "flows")])
    result = evaluate(r, c, {"candidate_groups": [{"key": "joined", "units": ["c1", "c2"]}]})
    assert result["metrics"]["characters"]["error_rate"] == 0
    assert result["metrics"]["scripts"]["characters"]["f1"] == 1
    assert result["coverage"]["evaluated_fraction"] == 1


@pytest.mark.parametrize("group", [
    {"key": "g", "units": ["b", "a"]}, {"key": "g", "units": ["a", "c"]},
    {"key": "a", "units": ["a"]}, {"key": "g", "units": ["a"], "separator": "wrong"}])
def test_invalid_groups_fail(group):
    from pdf_to_jats.qa.alignment import group_units
    with pytest.raises(ValueError):
        group_units([Unit(k, "body", k) for k in "abc"], [group])


@pytest.mark.parametrize("pairs", [[["a", "a"]], [["a", "b"], ["b", "a"]], [["a", "b"], ["a", "b"]]])
def test_bad_reading_order_constraints_fail(pairs):
    d = document([Unit("a", "title", "title"), Unit("b", "body", "body")])
    with pytest.raises(ValueError):
        evaluate(d, d, {"order_pairs": pairs})


def test_reviewed_entity_mapping_resolves_duplicate_names():
    from pdf_to_jats.qa.metrics import entity_map
    assert entity_map({"a": "Same", "b": "Same"}, {"x": "Same", "y": "Same"}, [["a", "y"], ["b", "x"]]) == {"a": "y", "b": "x"}
    with pytest.raises(ValueError):
        entity_map({"a": "Same", "b": "Same"}, {"x": "Same"}, [["a", "x"], ["b", "x"]])


def test_structural_comments_and_pi_targets_are_deterministic():
    a = etree.XML('<p><!--a--><?first x?></p>')
    b = etree.XML('<p><!--b--><?second x?></p>')
    result = structural_diff(a, b)
    assert any(d["candidate"] == "#pi:second" for d in result if d["kind"] == "element")
    assert result == structural_diff(a, b)


def test_reviewed_math_spans_measure_letters_without_mutating_document():
    r, c = document([Unit("r", "body", "x = 2")]), document([Unit("c", "body", "y = 2")])
    annotations = {"math_spans": [{"unit": "r", "start": 0, "end": 5}]}
    result = evaluate(r, c, annotations)
    assert result["critical_errors"]["corrupted_math_symbol"] == 1
    assert r.units[0].math == []
    with pytest.raises(ValueError):
        evaluate(r, c, {"math_spans": [{"unit": "r", "start": 0, "end": 100}]})
