from pathlib import Path

from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.gui.xml_correction_window import XmlCorrectionWindow


ANI_XML = '''<units xmlns="http://www.elsevier.com/xml/ani/ani"
 xmlns:ce="http://www.elsevier.com/xml/ani/common">
<unit><unit-content><bibrecord><head>
<citation-title><titletext xml:lang="ENG" original="y">English title</titletext></citation-title>
</head></bibrecord></unit-content></unit></units>'''


def test_adds_translated_ani_title_with_language(tmp_path):
    session = XmlDocumentSession.from_text(ANI_XML, tmp_path / 'draft.xml')

    session.add_title('عنوان فارسی', 'FAS')

    titles = session.titles()
    assert [title['text'] for title in titles] == ['English title', 'عنوان فارسی']
    assert titles[1]['language'] == 'FAS'
    assert titles[1]['original'] == 'n'
    xml = session.xml_text()
    assert xml.count('<titletext') == 2
    assert 'xml:lang="FAS"' in xml and 'original="n"' in xml


def test_primary_title_language_and_removal(tmp_path):
    session = XmlDocumentSession.from_text(ANI_XML, tmp_path / 'draft.xml')
    session.add_title('Titulo traducido', 'SPA')

    session.set_title_language('ENG')
    assert session.titles()[0]['language'] == 'ENG'
    assert session.titles()[1]['language'] == 'SPA'
    session.set_title_language('ARA', 1)
    assert session.titles()[1]['language'] == 'ARA'

    session.remove_title(1)
    assert [title['text'] for title in session.titles()] == ['English title']

    try:
        session.remove_title(0)
    except ValueError as error:
        assert 'At least one article title must remain' in str(error)
    else:
        raise AssertionError('removing the only title should fail')


def test_adds_translated_jats_title(tmp_path):
    session = XmlDocumentSession.from_text(
        '<article xmlns="urn:j"><front><article-meta><title-group>'
        '<article-title xml:lang="eng">English title</article-title>'
        '</title-group></article-meta></front></article>',
        tmp_path / 'draft.xml',
    )

    session.add_title('عنوان فارسی', 'fas')

    titles = session.titles()
    assert [title['text'] for title in titles] == ['English title', 'عنوان فارسی']
    assert [title['language'] for title in titles] == ['eng', 'fas']
    xml = session.xml_text()
    assert xml.count('<article-title') == 1
    assert xml.count('<trans-title-group') == 1
    assert 'xml:lang="fas"' in xml


def test_title_tab_captures_second_title(qapp):
    window = XmlCorrectionWindow()
    try:
        assert window.load_xml_text(ANI_XML, Path('multi-title.xml'))
        assert window.title_edit.toPlainText() == 'English title'
        assert window.title_language.currentText() == 'ENG'
        assert window.other_title_list.count() == 0

        window.session.add_title('عنوان فارسی', 'FAS')
        window._refresh()

        assert window.other_title_list.count() == 1
        assert 'FAS' in window.other_title_list.item(0).text()
        assert 'عنوان فارسی' in window.other_title_list.item(0).text()

        window.title_language.setCurrentText('ENG')
        window._title_language_changed()
        window.other_title_list.setCurrentRow(0)
        window.remove_other_title()
        assert window.other_title_list.count() == 0
        assert [title['text'] for title in window.session.titles()] == ['English title']
    finally:
        window.deleteLater()
