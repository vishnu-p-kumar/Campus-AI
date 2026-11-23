import io
from pathlib import Path
import re
import zipfile

import pymupdf as fitz
from docx import Document as DocxDocument


def extract_pages(path: Path, *, enable_ocr: bool = False, ocr_languages: str = "eng", ocr_dpi: int = 200,
                  max_pages: int = 500, max_chars: int = 5_000_000) -> list[tuple[int | None, str]]:
    if max_pages < 1 or max_chars < 1:
        raise ValueError("Extraction limits must be positive")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with fitz.open(path) as pdf:
            if len(pdf) > max_pages:
                raise ValueError(f"Document exceeds the {max_pages}-page extraction limit")
            pages = []
            extracted_chars = 0
            for index, page in enumerate(pdf):
                text = page.get_text("text").strip()
                if not text and enable_ocr:
                    try:
                        text = page.get_textpage_ocr(language=ocr_languages, dpi=ocr_dpi).extract_text().strip()
                    except (RuntimeError, OSError) as exc:
                        raise ValueError(
                            "OCR failed. Install Tesseract and the configured language data, or upload a text-based document."
                        ) from exc
                if text:
                    extracted_chars += len(text)
                    if extracted_chars > max_chars:
                        raise ValueError(f"Document exceeds the {max_chars}-character extraction limit")
                    pages.append((index + 1, text))
            return pages
    if suffix == ".docx":
        doc = DocxDocument(path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        paragraphs.extend(" | ".join(cell.text.strip() for cell in row.cells) for table in doc.tables for row in table.rows)
        text = "\n".join(paragraphs)
        if len(text) > max_chars:
            raise ValueError(f"Document exceeds the {max_chars}-character extraction limit")
        return [(None, text)]
    if suffix == ".txt":
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            raise ValueError(f"Document exceeds the {max_chars}-character extraction limit")
        return [(None, text)]
    raise ValueError("Only PDF, DOCX and TXT files are supported")


def chunk_pages(pages: list[tuple[int | None, str]], max_chars: int = 1400, overlap: int = 180) -> list[dict]:
    """Build bounded paragraph/sentence chunks and retain recognizable section headings.

    This is structure-aware chunking, not an embedding-based semantic segmenter.
    Long unpunctuated text is split on whitespace with a bounded character fallback.
    """
    if max_chars < 1 or overlap < 0 or overlap >= max_chars:
        raise ValueError("max_chars must be positive and overlap must be between zero and max_chars")
    chunks: list[dict] = []
    heading_pattern = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?\s+.{2,}|[A-Z][A-Z\s/&-]{2,})$")

    def split_long_sentence(sentence: str) -> list[str]:
        parts = []
        remaining = sentence.strip()
        while len(remaining) > max_chars:
            boundary = remaining.rfind(" ", 0, max_chars + 1)
            if boundary < max_chars // 2:
                boundary = max_chars
            parts.append(remaining[:boundary].strip())
            remaining = remaining[boundary:].strip()
        if remaining:
            parts.append(remaining)
        return parts

    for page, text in pages:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        section_name: str | None = None
        pending_heading: str | None = None
        for paragraph in paragraphs:
            lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
            if not lines:
                continue
            if len(lines[0]) <= 120 and heading_pattern.fullmatch(lines[0]):
                section_name = lines[0][:240]
                pending_heading = lines[0]
                lines = lines[1:]
            normalized = re.sub(r"\s+", " ", " ".join(lines)).strip()
            if not normalized:
                continue
            if pending_heading:
                normalized = f"{pending_heading}: {normalized}"
                pending_heading = None
            sentences = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+", normalized) if piece.strip()]
            units = [part for sentence in sentences for part in split_long_sentence(sentence)]
            current: list[str] = []
            current_length = 0
            prior_overlap: list[str] = []
            for unit in units:
                extra = len(unit) + (1 if current else 0)
                if current and current_length + extra > max_chars:
                    chunk_text = " ".join(current).strip()
                    if chunk_text:
                        chunks.append({"page_number": page, "section": section_name, "text": chunk_text})
                    overlap_units: list[str] = []
                    overlap_length = 0
                    for previous in reversed(current):
                        if overlap_length + len(previous) + (1 if overlap_units else 0) > overlap:
                            break
                        overlap_units.insert(0, previous)
                        overlap_length += len(previous) + (1 if len(overlap_units) > 1 else 0)
                    prior_overlap = overlap_units
                    current = list(prior_overlap)
                    current_length = sum(len(value) for value in current) + max(0, len(current) - 1)
                    extra = len(unit) + (1 if current else 0)
                    if current_length + extra > max_chars:
                        current = []
                        current_length = 0
                current.append(unit)
                current_length += len(unit) + (1 if len(current) > 1 else 0)
            if current:
                chunks.append({"page_number": page, "section": section_name, "text": " ".join(current).strip()})
    return chunks


def validate_document(filename: str, content: bytes, max_bytes: int) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".docx", ".txt"}:
        raise ValueError("Supported document formats are PDF, DOCX and TXT")
    if not content or len(content) > max_bytes:
        raise ValueError(f"Document must be non-empty and no larger than {max_bytes // 1_000_000} MB")
    if ext == ".pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF")
    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                names = {entry.filename for entry in entries}
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise ValueError("The uploaded file is not a valid DOCX package")
                if len(names) != len(entries):
                    raise ValueError("The DOCX archive contains duplicate file paths")
                if len(entries) > 2048:
                    raise ValueError("The DOCX archive contains too many files")
                expanded_limit = max_bytes * 10
                expanded_size = 0
                for entry in entries:
                    if entry.flag_bits & 0x1:
                        raise ValueError("Encrypted DOCX archives are not supported")
                    if entry.file_size > expanded_limit:
                        raise ValueError("The DOCX archive expands beyond the allowed size")
                    expanded_size += entry.file_size
                    if expanded_size > expanded_limit:
                        raise ValueError("The DOCX archive expands beyond the allowed size")
        except zipfile.BadZipFile as exc:
            raise ValueError("The uploaded file is not a valid DOCX archive") from exc
    if ext == ".txt":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text documents must use UTF-8 encoding") from exc
    return ext
