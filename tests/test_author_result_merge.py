from pdf_to_jats.core.author_linker import AuthorLinker
from pdf_to_jats.gui.main_window import MainWindow
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.models.document import Document
import pytest


@pytest.mark.parametrize('separate_blocks', [False, True])
def test_semicolon_wrapped_name_does_not_create_extra_author_group(separate_blocks):
    lines = [
        'Roosevelt Fajardo, MD, FACS1; Luis Felipe Cabrera, MD, FACS1;',
        'Maria Diaz2; Juan Manuel Calero2; Maria Valentina Garcia2; Karen',
        'Liceth Melo2; Santiago Melo2; Laura Moncada2',
    ]
    expected = [
        ('Roosevelt', 'Fajardo', '1'), ('Luis Felipe', 'Cabrera', '1'),
        ('Maria', 'Diaz', '2'), ('Juan Manuel', 'Calero', '2'),
        ('Maria Valentina', 'Garcia', '2'), ('Karen Liceth', 'Melo', '2'),
        ('Santiago', 'Melo', '2'), ('Laura', 'Moncada', '2'),
    ]
    linker = AuthorLinker()
    fallback = linker.link_from_texts(
        lines if separate_blocks else ['\n'.join(lines)],
        ['1 Fundacion Santa Fe de Bogota', '2 Universidad de los Andes'],
    )
    assert [(a.given_names, a.surname, a.affiliation_ids) for a in fallback.authors] == [
        (given, surname, [marker]) for given, surname, marker in expected
    ]
    primary = linker.link_from_llm_response({
        'authors': [{'given_names': given, 'surname': surname, 'affiliations': [marker]}
                    for given, surname, marker in expected],
        'affiliations': [{'marker': '1', 'text': 'Fundacion Santa Fe de Bogota'},
                         {'marker': '2', 'text': 'Universidad de los Andes'}],
    })
    merged = MainWindow._merge_author_affiliation_results(primary, fallback)
    assert len(merged.authors) == 8
    groups = JATSGenerator()._author_groups(
        Document(authors=merged.authors, affiliations=merged.affiliations))
    assert [len(authors) for _, authors in groups] == [2, 6]
    assert all(affiliation is not None for affiliation, _ in groups)


def test_complete_authors_in_separate_blocks_remain_separate():
    linked = AuthorLinker().link_from_texts(
        ['Maria Diaz2; Karen Smith1', 'Liceth Melo2; Santiago Melo2'],
        ['1 Alpha University', '2 Beta University'],
    )
    assert [a.display_name for a in linked.authors] == [
        'Maria Diaz', 'Karen Smith', 'Liceth Melo', 'Santiago Melo',
    ]


def test_soft_hyphen_wrapped_surnames_do_not_add_duplicate_authors():
    linker = AuthorLinker()
    expected = [
        ("Jane", "Doe", "J.", ["1"]),
        ("Carolina", "Nebot", "C.", ["6"]),
        ("Fatjon", "Hoxha", "F.", ["10"]),
        ("Andreia", "Freitas", "A.", ["1"]),
    ]
    fallback = linker.link_from_texts(
        ["Jane Doe1, Carolina\n\u00adNebot6, Fatjon\n\u00adHoxha10, Andreia Freitas1"],
        ["1 Alpha University", "6 Beta University", "10 Gamma University"],
    )
    assert [(a.given_names, a.surname, a.initials, a.markers)
            for a in fallback.authors] == expected
    assert [a.affiliation_ids for a in fallback.authors] == [["1"], ["6"], ["10"], ["1"]]

    primary = linker.link_from_llm_response({
        "authors": [
            {"given_names": given, "surname": surname, "initials": initials,
             "affiliations": markers}
            for given, surname, initials, markers in expected
        ],
        "affiliations": [
            {"marker": marker, "text": text}
            for marker, text in [("1", "Alpha University"), ("6", "Beta University"),
                                 ("10", "Gamma University")]
        ],
    })
    merged = MainWindow._merge_author_affiliation_results(primary, fallback)
    assert [(a.given_names, a.surname, a.initials) for a in merged.authors] == [
        (given, surname, initials) for given, surname, initials, _ in expected
    ]
    assert all(len(a.affiliation_ids) == 1 for a in merged.authors)


def test_combined_model_author_is_replaced_by_two_source_authors():
    linker = AuthorLinker()
    primary = linker.link_from_llm_response({
        "authors": [{"given_names": "Kate, Sara", "surname": "Strodtbeck",
                     "initials": "K., S.", "affiliations": ["1"]}],
        "affiliations": [{"marker": "1", "text": "Liverpool University Hospitals Foundation Trust, United Kingdom"}],
    })
    primary.corresponding_author = primary.authors[0]
    fallback = linker.link_from_texts(
        ["Kate Rowlandson, Sara Strodtbeck"],
        ["Liverpool University Hospitals Foundation Trust, United Kingdom"],
    )
    merged = MainWindow._merge_author_affiliation_results(primary, fallback)
    assert [(a.given_names, a.surname, a.initials) for a in merged.authors] == [
        ("Kate", "Rowlandson", "K."), ("Sara", "Strodtbeck", "S."),
    ]
    assert all(a.affiliation_ids == [merged.affiliations[0].id] for a in merged.authors)
    assert merged.corresponding_author is None or any(
        merged.corresponding_author is a for a in merged.authors
    )


def test_comma_in_given_names_is_not_removed_without_separate_source_evidence():
    linker = AuthorLinker()
    primary = linker.link_from_llm_response({
        "authors": [{"given_names": "Kate, Sara", "surname": "Strodtbeck", "initials": "K., S."}],
    })
    fallback = linker.link_from_texts(["Sara Strodtbeck"], [])
    merged = MainWindow._merge_author_affiliation_results(primary, fallback)
    assert primary.authors[0] in merged.authors
