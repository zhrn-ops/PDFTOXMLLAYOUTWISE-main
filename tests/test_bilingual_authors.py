from lxml import etree

from pdf_to_jats.core.author_linker import AuthorLinker
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.models.block import TextBlock
from pdf_to_jats.models.document import Document


def _block(block_id: str, text: str, order: int, role: str = "author", page: int = 1) -> TextBlock:
    return TextBlock(
        id=block_id,
        page=page,
        text=text,
        bbox=[10.0, 20.0, 280.0, 40.0],
        x=10.0,
        y=20.0,
        width=270.0,
        height=20.0,
        role=role,
        metadata={"reading_order": order},
    )


def test_native_script_names_are_parsed_as_authors():
    linked = AuthorLinker().link_from_texts(
        ["علی رضایی1", "سارا محمدی2"],
        ["1 Alpha University; 2 Beta University"],
    )

    assert [author.display_name for author in linked.authors] == ["علی رضایی", "سارا محمدی"]
    assert [author.surname for author in linked.authors] == ["رضایی", "محمدی"]
    assert [author.affiliation_ids for author in linked.authors] == [["1"], ["2"]]


def test_manually_assigned_native_names_export_with_the_selected_author():
    persian_first = _block("p1", "علی رضایی1", 1, page=1)
    persian_second = _block("p2", "سارا محمدی2", 2, page=1)
    english_first = _block("e1", "Ali Rezaei1", 3, page=4)
    english_second = _block("e2", "Sara Mohammadi2", 4, page=4)
    affiliation = _block(
        "a1", "1 Alpha University; 2 Beta University", 5, role="affiliation"
    )

    persian_first.metadata['alternate_name_target'] = 'Ali Rezaei'
    persian_second.metadata['alternate_name_target'] = 'Sara Mohammadi'

    linked = AuthorLinker().link_from_blocks(
        [persian_first, persian_second, english_first, english_second],
        [affiliation],
    )

    assert [author.display_name for author in linked.authors] == [
        "Ali Rezaei",
        "Sara Mohammadi",
    ]
    assert [author.affiliation_ids for author in linked.authors] == [["1"], ["2"]]
    assert [
        [name.text for name in author.alternate_names]
        for author in linked.authors
    ] == [[persian_first.text], [persian_second.text]]

    document = Document(
        title="Modern Care",
        authors=linked.authors,
        affiliations=linked.affiliations,
        metadata={"abstract_number": "S100"},
    )
    root = etree.fromstring(JATSGenerator().to_bytes(document))
    authors = root.findall(f".//{{{JATSGenerator.ANI_NS}}}author")

    # ANI still gets one exported author per person; the native form is
    # exported beside the English name as ce:alt-name.
    assert len(authors) == 2
    assert [
        author.findtext(f"{{{JATSGenerator.CE_NS}}}alt-name") for author in authors
    ] == [persian_first.text, persian_second.text]
    assert not any(
        isinstance(node.tag, str) and node.tag.rsplit('}', 1)[-1] == 'name-script'
        for node in root.iter()
    )


def test_disjoint_markers_do_not_merge_different_bylines():
    persian_first = _block("p1", "علی رضایی3", 1, page=1)
    persian_second = _block("p2", "سارا محمدی4", 2, page=1)
    english_first = _block("e1", "Ali Rezaei1", 3, page=4)
    english_second = _block("e2", "Sara Mohammadi2", 4, page=4)
    affiliation = _block(
        "a1",
        "1 Alpha University; 2 Beta University; 3 Gamma University; 4 Delta University",
        5,
        role="affiliation",
    )

    linked = AuthorLinker().link_from_blocks(
        [persian_first, persian_second, english_first, english_second],
        [affiliation],
    )

    # Native captures are pending user assignment, never separate authors.
    assert len(linked.authors) == 2
    assert all(not author.alternate_names for author in linked.authors)
    assert sum("Unassigned alternate name" in issue.message for issue in linked.issues) == 2
