import io
import zipfile

import pytest

from app.documents.ingest import chunk_pages, extract_pages, validate_document


def test_text_validation_and_chunking():
    assert validate_document("policy.txt", b"Placement rules are approved.", 1000) == ".txt"
    chunks = chunk_pages([(1, "Placement rules are approved. " * 120)], max_chars=100, overlap=10)
    assert len(chunks) > 1
    assert all(chunk["page_number"] == 1 for chunk in chunks)
    assert all(chunk["text"] for chunk in chunks)


def test_text_extraction_enforces_character_limit(tmp_path):
    path = tmp_path / "large.txt"
    path.write_text("placement rules", encoding="utf-8")

    with pytest.raises(ValueError, match="character extraction limit"):
        extract_pages(path, max_chars=5)


def test_chunking_preserves_heading_page_and_sentence_boundaries():
    chunks = chunk_pages([
        (2, "ELIGIBILITY RULES\nMinimum CGPA is 7.5. Eligible branches include CSE and ECE.\n\n"
            "Applicants may have no active backlogs. Historical backlogs are reviewed separately.")
    ], max_chars=65, overlap=0)
    assert len(chunks) >= 2
    assert all(chunk["page_number"] == 2 for chunk in chunks)
    assert all(chunk["section"] == "ELIGIBILITY RULES" for chunk in chunks)
    assert all(len(chunk["text"]) <= 65 for chunk in chunks)
    assert any("Minimum CGPA is 7.5." in chunk["text"] for chunk in chunks)


def test_chunking_rejects_invalid_size_and_bounds_long_unpunctuated_text():
    import pytest
    with pytest.raises(ValueError, match="max_chars"):
        chunk_pages([(1, "words")], max_chars=10, overlap=10)
    chunks = chunk_pages([(1, "placement " * 30)], max_chars=45, overlap=5)
    assert chunks and all(len(chunk["text"]) <= 45 for chunk in chunks)


def test_pdf_extension_requires_pdf_signature():
    try:
        validate_document("fake.pdf", b"not a pdf", 100)
        assert False, "invalid PDF should be rejected"
    except ValueError as exc:
        assert "valid PDF" in str(exc)


def test_docx_requires_word_package_parts():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("not-a-docx.txt", "renamed zip")

    with pytest.raises(ValueError, match="valid DOCX package"):
        validate_document("misleading.docx", output.getvalue(), 1000)


def test_valid_docx_package_is_accepted():
    from docx import Document

    output = io.BytesIO()
    document = Document()
    document.add_paragraph("Approved placement rules")
    document.save(output)

    assert validate_document("policy.docx", output.getvalue(), 1_000_000) == ".docx"


def test_docx_expanded_content_is_bounded_before_parsing():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "x")
        archive.writestr("word/document.xml", "x" * 5121)

    with pytest.raises(ValueError, match="expands beyond the allowed size"):
        validate_document("oversized.docx", output.getvalue(), 512)


def test_scanned_pdf_uses_optional_tesseract_ocr(monkeypatch, tmp_path):
    import pymupdf as fitz

    class TextPage:
        def extract_text(self):
            return "OCR extracted placement requirements"

    class Page:
        def get_text(self, _kind):
            return ""

        def get_textpage_ocr(self, *, language, dpi):
            assert language == "eng+hin"
            assert dpi == 240
            return TextPage()

    class Pdf:
        def __enter__(self):
            return [Page()]

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(fitz, "open", lambda _path: Pdf())
    path = tmp_path / "scan.pdf"
    path.touch()
    assert extract_pages(path, enable_ocr=True, ocr_languages="eng+hin", ocr_dpi=240) == [
        (1, "OCR extracted placement requirements")
    ]


def test_scanned_pdf_skips_ocr_when_disabled(monkeypatch, tmp_path):
    import pymupdf as fitz

    class Page:
        def get_text(self, _kind):
            return ""

        def get_textpage_ocr(self, **_kwargs):
            raise AssertionError("OCR must remain opt-in")

    class Pdf:
        def __enter__(self):
            return [Page()]

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(fitz, "open", lambda _path: Pdf())
    path = tmp_path / "scan.pdf"
    path.touch()
    assert extract_pages(path) == []


def test_scanned_pdf_reports_missing_tesseract_without_saving_empty_content(monkeypatch, tmp_path):
    import pymupdf as fitz

    class Page:
        def get_text(self, _kind):
            return ""

        def get_textpage_ocr(self, **_kwargs):
            raise RuntimeError("Tesseract is not installed")

    class Pdf:
        def __enter__(self):
            return [Page()]

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(fitz, "open", lambda _path: Pdf())
    path = tmp_path / "scanned-without-tesseract.pdf"
    path.touch()
    with pytest.raises(ValueError, match="Install Tesseract"):
        extract_pages(path, enable_ocr=True)


def test_pdf_extraction_enforces_page_limit(monkeypatch, tmp_path):
    import pymupdf as fitz

    class Pdf:
        def __len__(self):
            return 2

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def __iter__(self):
            return iter(())

    monkeypatch.setattr(fitz, "open", lambda _path: Pdf())
    path = tmp_path / "many-pages.pdf"
    path.touch()

    with pytest.raises(ValueError, match="page extraction limit"):
        extract_pages(path, max_pages=1)
