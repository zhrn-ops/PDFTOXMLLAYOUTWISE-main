from pathlib import Path

import pytest

from pdf_to_jats.core.xml_correction import XmlDocumentSession


JATS = b'''<?xml version="1.0" encoding="UTF-8"?>
<article xmlns="urn:j"><front><article-meta>
<title-group><article-title>Old title</article-title></title-group>
<contrib-group><contrib contrib-type="author"><name><surname>Smith</surname></name></contrib></contrib-group>
<abstract><p>Abstract text</p></abstract><kwd-group><kwd>one</kwd></kwd-group>
<aff id="a1">University</aff><custom flag="keep">Unknown</custom>
</article-meta></front></article>'''


def session_for(tmp_path: Path) -> tuple[Path, XmlDocumentSession]:
    source = tmp_path / "source.xml"
    source.write_bytes(JATS)
    return source, XmlDocumentSession.open(source)


def test_reads_and_updates_namespaced_jats_fields(tmp_path):
    _, session = session_for(tmp_path)
    assert session.profile == "JATS"
    assert session.title() == "Old title"
    assert session.abstract() == "Abstract text"
    assert session.affiliations() == ["University"]
    session.set_title("New title")
    session.set_author_name(0, "Jones")
    assert session.title() == "New title"
    assert session.author_name(session.authors()[0]) == "Jones"


def test_malformed_raw_xml_keeps_last_valid_tree(tmp_path):
    _, session = session_for(tmp_path)
    ok, error, line, column = session.commit_raw("<broken>")
    assert not ok and error and line == 1 and column
    assert session.title() == "Old title"


def test_save_copy_preserves_source_and_unknown_nodes(tmp_path):
    source, session = session_for(tmp_path)
    session.set_title("Corrected")
    destination = tmp_path / "corrected.xml"
    assert not any(issue.severity == "error" for issue in session.validate())
    session.save_copy(destination)
    assert b"Old title" in source.read_bytes()
    assert b"Corrected" in destination.read_bytes()
    assert b'custom flag="keep"' in destination.read_bytes()
    with pytest.raises(ValueError, match="cannot overwrite"):
        session.save_copy(source)


@pytest.mark.parametrize("name_xml", [
    '<name><surname>Smith</surname><given-names>Jane</given-names></name>',
    '<surname>Smith</surname><given-name>Jane</given-name>',
])
def test_author_edit_preserves_given_names_and_references(tmp_path, name_xml):
    session = XmlDocumentSession.from_text(
        '<article xmlns="urn:j"><contrib-group><contrib contrib-type="author">'
        + name_xml
        + '<xref ref-type="aff" rid="a1">1</xref></contrib></contrib-group></article>',
        tmp_path / "draft.xml",
    )

    assert len(session.authors()) == 1
    assert session.author_name(session.authors()[0]) == "Smith Jane"
    session.set_author_name(0, "Jones")

    assert session.author_name(session.authors()[0]) == "Jones Jane"
    assert session.authors()[0].find("{urn:j}xref").get("rid") == "a1"


def test_save_copy_requires_validation_after_each_edit(tmp_path):
    _, session = session_for(tmp_path)
    destination = tmp_path / "corrected.xml"
    with pytest.raises(ValueError, match="Validate the current XML"):
        session.save_copy(destination)
    assert not destination.exists()

    session.validate()
    session.set_author_name(0, "Jones")
    with pytest.raises(ValueError, match="Validate the current XML"):
        session.save_copy(destination)
    assert not destination.exists()

    session.validate()
    session.save_copy(destination)
    assert b"Jones" in destination.read_bytes()


def test_author_groups_use_structural_membership(tmp_path):
    session = XmlDocumentSession.from_text(
        '<root><author-group><author><surname>Smith</surname></author>'
        '<affiliation>University A</affiliation></author-group>'
        '<author-group><author><surname>Jones</surname></author>'
        '<affiliation>University B</affiliation></author-group></root>', tmp_path / 'draft.xml'
    )
    assert session.author_affiliation_groups() == [('University A', [0]), ('University B', [1])]


def test_jats_groups_follow_explicit_references(tmp_path):
    session = XmlDocumentSession.from_text(
        '<article><contrib><name><surname>Smith</surname></name>'
        '<xref ref-type="aff" rid="b a"/></contrib>'
        '<contrib><name><surname>Jones</surname></name></contrib>'
        '<aff id="a">University A</aff><aff id="b">University B</aff></article>',
        tmp_path / 'draft.xml'
    )
    assert session.author_affiliation_groups() == [
        ('University A', [0]), ('University B', [0]), ('No affiliation linked', [1])
    ]


def test_parser_does_not_resolve_external_entities(tmp_path):
    source = tmp_path / "entity.xml"
    source.write_text('<!DOCTYPE article [<!ENTITY x SYSTEM "file:///private/sentinel">]><article>&x;</article>')
    session = XmlDocumentSession.open(source)
    assert session.tree.getroot().text is None
