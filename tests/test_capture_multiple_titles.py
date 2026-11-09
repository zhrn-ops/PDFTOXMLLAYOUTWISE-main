from pathlib import Path

from lxml import etree

from pdf_to_jats.core.author_linker import AuthorLinker
from pdf_to_jats.core.xml_correction import XmlDocumentSession
from pdf_to_jats.core.jats_generator import JATSGenerator
from pdf_to_jats.core.language import detect_language_code
from pdf_to_jats.gui.main_window import MainWindow
from pdf_to_jats.models.block import TextBlock
from pdf_to_jats.models.document import Document, DocumentTitle


ANI_NS = JATSGenerator.ANI_NS
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
PERSIAN_TITLE = "مراقبت مدرن و چالش‌های اخلاقی؛ نیازها و ملاحظات جدید"
ENGLISH_TITLE = "Modern Care and Ethical Challenges: Emerging Needs and Considerations"


def _block(text: str, block_id: str, page: int, order: int) -> TextBlock:
    return TextBlock(
        id=block_id,
        page=page,
        text=text,
        bbox=[10.0, 20.0, 280.0, 40.0],
        x=10.0,
        y=20.0,
        width=270.0,
        height=20.0,
        role="title",
        metadata={"reading_order": order},
    )


def test_detects_title_language_from_script():
    assert detect_language_code(PERSIAN_TITLE) == "FAS"
    assert detect_language_code(ENGLISH_TITLE) == "ENG"
    assert detect_language_code("الرعاية الحديثة") == "ARA"
    assert detect_language_code("12345") == "UND"


def test_generator_writes_primary_and_translated_titles():
    document = Document(
        title=PERSIAN_TITLE,
        alternate_titles=[DocumentTitle(ENGLISH_TITLE, "ENG")],
        metadata={"title_language": "FAS", "abstract_number": "S100"},
    )

    root = etree.fromstring(JATSGenerator().to_bytes(document))
    titles = root.findall(f".//{{{ANI_NS}}}titletext")

    assert [title.text for title in titles] == [PERSIAN_TITLE, ENGLISH_TITLE]
    assert [title.get(XML_LANG) for title in titles] == ["FAS", "ENG"]
    assert [title.get("original") for title in titles] == ["y", "n"]


def test_capture_exports_the_page_four_title_as_a_translation():
    persian = _block(PERSIAN_TITLE, "block_001_014", page=1, order=1)
    english = _block(ENGLISH_TITLE, "block_004_259", page=4, order=2)
    source = Document(
        blocks=[persian, english],
        raw_blocks=[persian, english],
        metadata={"abstract_number": "S100"},
    )
    window = MainWindow.__new__(MainWindow)
    window.document = source
    window.linker = AuthorLinker()

    segment = {
        "index": 1,
        "abstract_number": "S100",
        "start_page": 1,
        "end_page": 4,
    }
    exported = window._document_for_segment(segment)

    assert exported.title == PERSIAN_TITLE
    assert [title.text for title in exported.alternate_titles] == [ENGLISH_TITLE]
    assert [title.language for title in exported.alternate_titles] == ["ENG"]
    assert exported.metadata["title_language"] == "FAS"

    xml_text = JATSGenerator().to_string(exported)
    root = etree.fromstring(xml_text.encode())
    titles = root.findall(f".//{{{ANI_NS}}}titletext")
    assert [title.text for title in titles] == [PERSIAN_TITLE, ENGLISH_TITLE]
    assert [title.get(XML_LANG) for title in titles] == ["FAS", "ENG"]

    # The correction workspace must see the translated title without the user
    # having to paste it in by hand.
    session = XmlDocumentSession.from_text(xml_text, Path("article.xml"))
    assert [title["text"] for title in session.titles()] == [
        PERSIAN_TITLE,
        ENGLISH_TITLE,
    ]
    assert [title["language"] for title in session.titles()] == ["FAS", "ENG"]
