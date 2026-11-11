import pytest

from pdf_to_jats.core.language_codes import LANGUAGES, UNDETERMINED, is_language_code, language_code
from pdf_to_jats.core.xml_correction import XmlDocumentSession

JATS = (
    '<article xmlns="urn:j"><front><article-meta><title-group>'
    '<article-title xml:lang="eng">English title</article-title>'
    '</title-group></article-meta></front></article>'
)


def _session(tmp_path):
    return XmlDocumentSession.from_text(JATS, tmp_path / 'draft.xml')


@pytest.mark.parametrize('value,expected', [
    ('Persian', 'PER'), ('persian', 'PER'), ('fa', 'PER'), ('FAS', 'PER'),
    ('French', 'FRE'), ('FRA', 'FRE'), ('ger', 'GER'), ('Chinese', 'CHI'),
    ('ZHO', 'CHI'), ('Kirghiz', 'KIR'), ('Moldovan', 'RUM'), ('BYEL', 'BEL'),
])
def test_names_and_terminology_codes_resolve(value, expected):
    assert language_code(value) == expected


def test_table_matches_language_codes_pdf():
    assert len(LANGUAGES) == 70
    assert len({row['alpha3'] for row in LANGUAGES}) == 70
    for row in LANGUAGES:
        for value in (row['name'], *row.get('aliases', []), row['alpha3'], row['alpha2'], row['alpha4']):
            if value:
                assert language_code(value) == row['alpha3']


@pytest.mark.parametrize('value', ['Klingon', 'EN-GBX', ''])
def test_unknown_languages_are_not_guessed(value):
    assert language_code(value) == ''
    assert not is_language_code(value)


def test_undetermined_is_allowed_as_a_title_language():
    assert is_language_code('UND')
    assert is_language_code('und')


def test_language_pickers_offer_every_appendix_code(qapp, tmp_path):
    from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow

    window = XmlCorrectionWindow()
    try:
        window.load_xml_text(JATS, tmp_path / 'draft.xml')
        combo = window.title_language
        assert [combo.itemData(i) for i in range(combo.count())] == (
            sorted(row['alpha3'] for row in LANGUAGES) + [UNDETERMINED]
        )
        assert combo.itemText(0) == 'AFR — Afrikaans'
        # A lowercase code in the XML selects its entry without changing the value.
        assert combo.currentData() == 'ENG'
        assert window.session.title_language() == 'eng'
    finally:
        window.deleteLater()


def test_title_language_write_rejects_unknown_code(tmp_path):
    session = _session(tmp_path)
    with pytest.raises(ValueError, match='language code'):
        session.set_title_language('KLINGON')
    assert session.titles()[0]['language'] == 'eng'


def test_added_title_rejects_unknown_code(tmp_path):
    session = _session(tmp_path)
    with pytest.raises(ValueError, match='language code'):
        session.add_title('Titulo', 'KLINGON')
    assert len(session.titles()) == 1


def test_known_terminology_code_is_written_verbatim(tmp_path):
    session = _session(tmp_path)
    session.set_title_language('FAS')
    assert session.titles()[0]['language'] == 'FAS'
