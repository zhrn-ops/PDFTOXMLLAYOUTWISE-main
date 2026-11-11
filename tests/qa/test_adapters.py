import pytest
from lxml import etree
from pdf_to_jats.qa.adapters import adapt
from pdf_to_jats.qa.adapters.base import ANI, CE
from pdf_to_jats.qa.readers import parse_xml, local_path, read_json


def test_jats_roles_scripts_entities_and_unknown_text():
    xml = b'''<article><front><article-meta><title-group><article-title>H<sub>2</sub>O</article-title></title-group>
    <contrib-group><contrib id="a"><name><surname>Lovelace</surname><given-names>Ada</given-names></name>
    <xref ref-type="aff" rid="f"/></contrib></contrib-group><aff id="f">Institute</aff>
    <abstract><p>Summary</p></abstract></article-meta></front><body><sec><title>Methods</title><p>Result</p></sec></body>
    <custom>Unsupported</custom></article>'''
    doc = adapt(xml, "JATS")
    assert [u.role for u in doc.units] == ["title", "abstract", "section", "body"]
    assert doc.units[0].scripts == [(1, 2, "sub")]
    assert doc.authors == {"a": "Ada Lovelace"}
    assert doc.edges == {("a", "f")}
    assert doc.unsupported == [{"path": "/article/custom", "text": "Unsupported"}]


def test_ani_repeated_authors_and_common_scripts():
    xml = f'''<units xmlns="{ANI}" xmlns:ce="{CE}"><unit><head><citation-title><titletext>A<ce:inf>2</ce:inf></titletext></citation-title>
    <author-group><author seq="1"><ce:given-name>Ada</ce:given-name><ce:surname>Lovelace</ce:surname></author><affiliation><ce:source-text>Institute A</ce:source-text></affiliation></author-group>
    <author-group><author seq="1"><ce:given-name>Ada</ce:given-name><ce:surname>Lovelace</ce:surname></author><affiliation><ce:source-text>Institute B</ce:source-text></affiliation></author-group>
    <abstracts><abstract><ce:para>Summary</ce:para></abstract></abstracts></head></unit></units>'''.encode()
    doc = adapt(xml, "ANI")
    assert len(doc.authors) == 1 and len(doc.edges) == 2
    assert doc.units[0].scripts == [(1, 2, "sub")]
    assert doc.units[1].role == "abstract"


def test_namespace_spoofing_is_unsupported():
    doc = adapt(b'<article xmlns:x="untrusted"><x:p>unknown</x:p><p>x<x:sup>2</x:sup></p></article>', "JATS")
    assert doc.unsupported[0]["text"] == "unknown"
    assert doc.units[0].scripts == []


def test_mathml_offsets_and_comments():
    doc = adapt(b'<article><body><p>A<!--ignore--> <inline-formula><m:math xmlns:m="http://www.w3.org/1998/Math/MathML"><m:mi>x</m:mi></m:math></inline-formula> B</p></body></article>', "JATS")
    assert doc.units[0].text == "A x B"
    assert (2, 3) in doc.units[0].math


@pytest.mark.parametrize("data", [b'<!DOCTYPE article [<!ENTITY x "bad">]><article>&x;</article>',
    b'<!DOCTYPE article SYSTEM "https://invalid.example/x"><article/>', b'<broken>'])
def test_unsafe_or_malformed_xml_rejected(data):
    with pytest.raises((ValueError, etree.XMLSyntaxError)):
        parse_xml(data)


@pytest.mark.parametrize("path", ["../escape", "C:/private", "https://example.com/x"])
def test_path_escape_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        local_path(tmp_path, path)


def test_duplicate_json_rejected(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"id":1,"id":2}')
    with pytest.raises(ValueError, match="Duplicate"):
        read_json(path)


def test_multiple_ani_articles_require_explicit_selector():
    data = f'<units xmlns="{ANI}"><unit/><unit/></units>'.encode()
    with pytest.raises(ValueError, match="Select one"):
        adapt(data, "ANI")
    assert adapt(data, "ANI", "//ani:unit[1]").format == "ANI"


def test_duplicate_author_identity_rejected():
    with pytest.raises(ValueError, match="Duplicate author"):
        adapt(b'<article><contrib id="a"/><contrib id="a"/></article>', "JATS")


@pytest.mark.parametrize("family,xml", [("JATS", b'<article xmlns="http://jats.nlm.nih.gov"><body><p>Text</p></body></article>'),
    ("ANI", f'<units xmlns="{ANI}" xmlns:ce="{CE}"><unit><body><ce:para>Text</ce:para></body></unit></units>'.encode())])
def test_namespaced_adapters(family, xml):
    assert adapt(xml, family).units[0].text == "Text"


def test_wrong_family_and_wrong_selector_rejected():
    with pytest.raises(ValueError):
        adapt(b'<article/>', "ANI")
    with pytest.raises(ValueError):
        adapt(b'<article/>', "JATS", "//missing")


def test_reader_size_limit(tmp_path):
    from pdf_to_jats.qa.readers import read_bytes
    p = tmp_path / "large"
    p.write_bytes(b"12345")
    with pytest.raises(ValueError, match="size limit"):
        read_bytes(p, limit=4)


def test_jats_affiliation_marker_and_inline_affiliation():
    doc = adapt(b'<article><contrib id="a"><name><given-names>Ada</given-names><surname>Example</surname></name><aff id="f"><label>1</label>Institute <italic>A</italic> Campus</aff></contrib></article>', "JATS")
    assert doc.affiliations == {"f": "Institute A Campus"}
    assert doc.edges == {("a", "f")}


def test_namespaced_section_hierarchy():
    doc = adapt(b'<article xmlns="http://jats.nlm.nih.gov"><body><sec><title>Methods</title><p>Details</p></sec></body></article>', "JATS")
    assert doc.units[-1].section == ("Methods",)
