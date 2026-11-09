import pytest

from pdf_to_jats.core.author_linker import AuthorLinker


@pytest.mark.parametrize('separate_blocks', [True, False])
def test_long_marked_byline_rejoins_multiline_names(separate_blocks):
    lines = [
        'Ahmed Abdelhak1, Aleksandra Maleska Maceski2,3, Sabine',
        'Schaidelin2,3,4, Eline Willemse2,3,4, Johanna Oechtering2,3, Anna-',
        'Zadic2,3, Juan Francisco Vilchez Gomez2,3, Lester Melie-',
        'Garcia2,3,4, Alessandro Cagol2,3,5,6, Edoardo',
        'Galli2,3, Lutz',
        'Achtnichts7, Claire',
        'Bride18, Chiara',
        'Zecca15,16, Perrine Marine',
        'Charlotte Janiaud2,3, Özgür Yaldizli2,3,5, David',
        'Conen26, Michael',
        'Khalil28, Pascal',
        'Benkert2,3, Jens Kuhle2,3',
    ]
    linked = AuthorLinker().link_from_texts(lines if separate_blocks else ['\n'.join(lines)], [])
    assert [author.display_name for author in linked.authors] == [
        'Ahmed Abdelhak', 'Aleksandra Maleska Maceski', 'Sabine Schaidelin',
        'Eline Willemse', 'Johanna Oechtering', 'Anna-Zadic',
        'Juan Francisco Vilchez Gomez', 'Lester Melie-Garcia', 'Alessandro Cagol',
        'Edoardo Galli', 'Lutz Achtnichts', 'Claire Bride', 'Chiara Zecca',
        'Perrine Marine Charlotte Janiaud', 'Özgür Yaldizli', 'David Conen',
        'Michael Khalil', 'Pascal Benkert', 'Jens Kuhle',
    ]
    assert linked.authors[7].surname == 'Melie-Garcia'
    assert linked.authors[7].markers == ['2', '3', '4']
    assert linked.authors[13].given_names == 'Perrine Marine Charlotte'
    assert linked.authors[13].surname == 'Janiaud'
    assert linked.authors[13].markers == ['2', '3']


def test_unicode_multitoken_continuation_and_complete_rows():
    linked = AuthorLinker().link_from_texts(
        ['Jane Doe1, Élodie Marie', 'García2,3, Anna Smith1', 'John Jones2'], [])
    assert [author.display_name for author in linked.authors] == [
        'Jane Doe', 'Élodie Marie García', 'Anna Smith', 'John Jones']


def test_independent_unmarked_names_are_not_joined():
    linked = AuthorLinker().link_from_texts(['Jane Doe', 'John Smith2'], [])
    assert [author.display_name for author in linked.authors] == ['Jane Doe', 'John Smith']


@pytest.mark.parametrize('separate_blocks', [True, False])
def test_actual_pdf_missing_comma_in_wrapped_surname_markers(separate_blocks):
    # Verbatim extracted rows from INNCECP_133187817_0001.pdf.
    lines = ['Zadic2,3, Juan Francisco Vilchez Gomez2,3, Lester Melie-',
             'Garcia2 3,4, Alessandro Cagol2,3,5,6, Riccardo Galbusera2,3,5, ']
    linked = AuthorLinker().link_from_texts(
        lines if separate_blocks else ['\n'.join(lines)],
        [f'{i} University {i}' for i in range(1, 7)],
    )
    assert [a.display_name for a in linked.authors] == [
        'Zadic', 'Juan Francisco Vilchez Gomez', 'Lester Melie-Garcia',
        'Alessandro Cagol', 'Riccardo Galbusera',
    ]
    author = linked.authors[2]
    assert author.given_names == 'Lester'
    assert author.surname == 'Melie-Garcia'
    assert author.markers == ['2', '3', '4']
    assert author.affiliation_ids == ['2', '3', '4']
